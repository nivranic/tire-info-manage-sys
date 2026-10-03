"""Private synthetic producer lifecycle, ownership, unknown outcomes and drafts."""
import asyncio
from copy import deepcopy

from tire_api.ai_gateway import GatewayError, OpenAIConfig
from test_ai_stream_parser import PACK, TEXT


class Store:
    def __init__(self):
        self.started = set()
        self.events = []
        self.finishes = []

    def start_execution(self, database, request_id, token):
        if request_id in self.started or token != 'owner':
            return False
        self.started.add(request_id)
        return True

    def append_event(self, database, request_id, token, kind, payload):
        self.events.append((kind, deepcopy(payload)))
        return True

    def finish_execution(self, database, request_id, token, **result):
        if self.finishes:
            return False
        self.finishes.append(deepcopy(result))
        return True


class HeldProvider:
    def __init__(self, *, failure=None):
        self.ready, self.release = asyncio.Event(), asyncio.Event()
        self.calls = self.closed = 0
        self.failure = failure

    async def stream(self, config, body, on_text):
        self.calls += 1
        try:
            split = TEXT.index('],"uncertainty"')
            await on_text(TEXT[:split])
            self.ready.set()
            await self.release.wait()
            if self.failure:
                raise GatewayError(self.failure)
            await on_text(TEXT[split:])
            return {'text': TEXT, 'error': None, 'usage': {'input_tokens': 10, 'output_tokens': 20, 'total_tokens': 30},
                    'provider_response_id': 'resp_synthetic'}
        finally:
            self.closed += 1


def test_detached_producer_emits_real_draft_before_terminal_and_starts_only_once():
    from tire_api.ai_streaming import AIStreamSupervisor

    async def scenario():
        store, provider = Store(), HeldProvider()
        supervisor = AIStreamSupervisor(object(), provider, store=store)
        assert supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        assert not supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        task = supervisor._tasks['run']
        await provider.ready.wait()
        assert store.events[0][0] == 'claim_draft'
        assert store.events[0][1]['claim']['text'] == '宽度 245 mm'
        assert not store.finishes and not task.done()
        provider.release.set()
        await task
        assert provider.calls == provider.closed == 1
        assert store.finishes[0]['state'] == 'completed'
        assert store.finishes[0]['answer']['claims'][0]['text'] == '宽度 245 mm'
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_two_supervisors_cannot_dispatch_same_durable_execution_twice():
    from tire_api.ai_streaming import AIStreamSupervisor

    async def scenario():
        store, provider = Store(), HeldProvider()
        first, other = AIStreamSupervisor(object(), provider, store=store), AIStreamSupervisor(object(), provider, store=store)
        first.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        await provider.ready.wait()
        other.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        await asyncio.gather(*list(other._tasks.values()))
        assert provider.calls == 1 and not store.finishes
        provider.release.set()
        await asyncio.gather(*list(first._tasks.values()))
        await first.shutdown()
        await other.shutdown()

    asyncio.run(scenario())


def test_provider_eof_records_unknown_and_never_accepts_partial_draft_as_answer():
    from tire_api.ai_streaming import AIStreamSupervisor

    async def scenario():
        store, provider = Store(), HeldProvider(failure='ai_stream_interrupted')
        supervisor = AIStreamSupervisor(object(), provider, store=store)
        supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        task = supervisor._tasks['run']
        await provider.ready.wait()
        provider.release.set()
        await task
        final = store.finishes[0]
        assert final['state'] == 'outcome_unknown' and final['answer'] is None and final['usage'] is None
        assert final['error_code'] == 'ai_stream_interrupted'
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_shutdown_closes_producer_and_records_unknown_without_retry():
    from tire_api.ai_streaming import AIStreamSupervisor

    async def scenario():
        store, provider = Store(), HeldProvider()
        supervisor = AIStreamSupervisor(object(), provider, store=store)
        supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        await provider.ready.wait()
        await supervisor.shutdown()
        assert provider.calls == provider.closed == 1
        assert store.finishes[0]['state'] == 'outcome_unknown'
        assert store.finishes[0]['answer'] is None
        assert not supervisor.start('other', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)

    asyncio.run(scenario())


def test_whole_producer_deadline_closes_network_and_preserves_unknown_usage(monkeypatch):
    from tire_api import ai_streaming

    async def scenario():
        store, provider = Store(), HeldProvider()
        supervisor = ai_streaming.AIStreamSupervisor(object(), provider, store=store)
        supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        await asyncio.gather(*list(supervisor._tasks.values()))
        assert provider.closed == 1 and store.finishes[0]['state'] == 'outcome_unknown'
        assert store.finishes[0]['usage'] is None and store.finishes[0]['answer'] is None
        await supervisor.shutdown()

    monkeypatch.setattr(ai_streaming, 'PRODUCER_SECONDS', .03)
    asyncio.run(scenario())


def test_rejected_late_completion_retries_only_owned_unknown_finalization():
    from tire_api.ai_streaming import AIStreamSupervisor

    class LateStore(Store):
        def __init__(self):
            super().__init__()
            self.states = []

        def finish_execution(self, database, request_id, token, **result):
            self.states.append(result['state'])
            if result['state'] == 'completed':
                return False
            return super().finish_execution(database, request_id, token, **result)

    async def scenario():
        store, provider = LateStore(), HeldProvider()
        supervisor = AIStreamSupervisor(object(), provider, store=store)
        supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        task = supervisor._tasks['run']
        await provider.ready.wait()
        provider.release.set()
        await task
        assert store.states == ['completed', 'outcome_unknown']
        assert provider.calls == 1 and store.finishes[0]['answer'] is None and store.finishes[0]['usage'] is None
        await supervisor.shutdown()

    asyncio.run(scenario())


def test_final_database_failure_keeps_drafts_without_claiming_completion_or_retrying():
    from tire_api.ai_streaming import AIStreamSupervisor

    class FailedStore(Store):
        def finish_execution(self, *args, **kwargs):
            raise RuntimeError('private database detail must not escape')

    async def scenario():
        store, provider = FailedStore(), HeldProvider()
        supervisor = AIStreamSupervisor(object(), provider, store=store)
        supervisor.start('run', 'owner', OpenAIConfig('synthetic', 'fixture'), {}, PACK)
        task = supervisor._tasks['run']
        await provider.ready.wait()
        provider.release.set()
        await task
        assert store.events and not store.finishes and provider.calls == 1
        await supervisor.shutdown()

    asyncio.run(scenario())

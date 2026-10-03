"""One bounded, detached producer per durably accepted Responses stream."""
import asyncio
from copy import deepcopy

from .ai_gateway import GatewayError, safe_error, safe_usage
from .ai_stream_parser import StructuredDraftProjector

PRODUCER_SECONDS = 60
UNKNOWN_ERRORS = {'ai_stream_interrupted', 'ai_provider_timeout', 'ai_provider_network_error'}


class AIStreamSupervisor:
    def __init__(self, database, adapter, *, store=None):
        if store is None:
            from . import ai_stream_store as store
        self.database, self.adapter, self.store = database, adapter, store
        self._tasks = {}
        self._closed = False

    def start(self, request_id, owner_token, config, body, pack):
        """Only the accepting route calls this; reads/subscriptions never do."""
        if self._closed or request_id in self._tasks:
            return False
        task = asyncio.create_task(self._run(request_id, owner_token, config, deepcopy(body), deepcopy(pack)),
                                   name='ai-stream-producer')
        self._tasks[request_id] = task

        def finished(done):
            if self._tasks.get(request_id) is done:
                self._tasks.pop(request_id, None)
            # The durable ledger is the status surface. Never print provider/DB exception text.
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        return True

    async def _call(self, method, *args, finishing=False, **kwargs):
        operation = asyncio.create_task(asyncio.to_thread(getattr(self.store, method), self.database, *args, **kwargs))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            # A synchronous DB transaction already dispatched to a thread must finish
            # before shutdown closes the database or a second terminal write starts.
            result = await asyncio.shield(operation)
            if finishing:
                return result
            raise

    async def _run(self, request_id, owner_token, config, body, pack):
        from .telemetry import observe, record_ai_usage
        receipt = {}
        answer = None
        state, error = 'outcome_unknown', 'ai_stream_interrupted'
        started = False
        with observe('ai.response', component='ai') as operation:
            try:
                async with asyncio.timeout(PRODUCER_SECONDS):
                    started = await self._call('start_execution', request_id, owner_token)
                    if not started:
                        operation.finish('not_started')
                        return
                    projector = StructuredDraftProjector(pack)

                    async def on_text(delta):
                        for event in projector.feed(delta):
                            if not await self._call('append_event', request_id, owner_token,
                                                    event['type'], event['payload']):
                                raise GatewayError('ai_stream_interrupted')

                    receipt = await self.adapter.stream(config, body, on_text)
                    if not isinstance(receipt, dict):
                        raise GatewayError('ai_response_invalid')
                    if receipt.get('error'):
                        error = safe_error(receipt['error'])
                        state = 'outcome_unknown' if error in UNKNOWN_ERRORS else 'failed'
                    else:
                        if receipt.get('text') != projector.text:
                            raise GatewayError('ai_stream_protocol_error')
                        answer = projector.finish()
                        state, error = 'completed', None
            except asyncio.CancelledError:
                state, error, answer = 'outcome_unknown', 'ai_stream_interrupted', None
            except (TimeoutError, asyncio.TimeoutError):
                state, error, answer = 'outcome_unknown', 'ai_provider_timeout', None
            except GatewayError as cause:
                error = safe_error(str(cause))
                state, answer = ('outcome_unknown' if error in UNKNOWN_ERRORS else 'failed'), None
            except (ValueError, TypeError, KeyError, RecursionError):
                state, error, answer = 'failed', 'ai_grounding_validation_failed', None
            except Exception:
                state, error, answer = 'outcome_unknown', 'ai_stream_interrupted', None
            # Even cancellation during the initial DB claim can have committed a
            # started event; owner-fenced finalization safely handles that window.
            if not isinstance(receipt, dict):
                receipt = {}
            usage = safe_usage(receipt.get('usage')) if state != 'outcome_unknown' else None
            try:
                committed = await self._call('finish_execution', request_id, owner_token, finishing=True,
                    state=state, error_code=error, answer=answer, usage=usage,
                    provider_response_id=receipt.get('provider_response_id'))
                if not committed and state != 'outcome_unknown':
                    # A late admission fence can reject a complete/failed write.
                    # Fresh owner-fenced unknown finalization never calls the provider.
                    state, error, answer, usage = 'outcome_unknown', 'ai_stream_interrupted', None, None
                    committed = await self._call('finish_execution', request_id, owner_token, finishing=True,
                        state=state, error_code=error, answer=None, usage=None,
                        provider_response_id=receipt.get('provider_response_id'))
            except Exception:
                # No completion receipt means unknown. Never retry a provider or
                # report success after a failed final DB transaction.
                operation.finish('outcome_unknown')
                return
            if committed:
                record_ai_usage('openai_responses', usage)
            operation.finish(state if committed else 'outcome_unknown')

    async def shutdown(self):
        self._closed = True
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

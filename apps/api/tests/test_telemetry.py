"""Actual SDK export, privacy, cardinality and context/lifecycle regression."""
import asyncio
from io import StringIO
import json

import pytest
from opentelemetry import baggage, context, trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from prometheus_client.parser import text_string_to_metric_families

from tire_api.telemetry import (
    MAX_RECENT_SPANS, TelemetryRuntime, observe, record_ai_usage,
)


def samples(runtime, name):
    return [sample for family in text_string_to_metric_families(runtime.metrics())
            for sample in family.samples if sample.name == name]


def test_sdk_span_metric_and_json_log_share_safe_identity():
    log = StringIO()
    runtime = TelemetryRuntime(log_output=log)
    runtime.set_routes(['/v1/sources/{source_id}/live-query'])
    try:
        with runtime.scope():
            with observe('api.request', component='api') as request:
                with observe('source.query', component='crawler', source='michelin-us') as source:
                    source.finish('consent_required', token='SECRET', body='SECRET')
                request.finish('success', http_status=200, route='/v1/sources/{source_id}/live-query')
        child, parent = runtime.finished_spans()
        assert child['trace_id'] == parent['trace_id']
        assert child['parent_span_id'] == parent['span_id']
        assert parent['parent_span_id'] is None
        assert child['attributes']['outcome'] == 'consent_required'
        logs = [json.loads(line) for line in log.getvalue().splitlines()]
        assert logs[0]['trace_id'] == child['trace_id']
        assert logs[1]['span_id'] == parent['span_id']
        counters = samples(runtime, 'tire_operations_total')
        assert len(counters) == 2 and all(row.value == 1 for row in counters)
        assert samples(runtime, 'tire_operation_duration_seconds_count')
        assert 'SECRET' not in json.dumps(runtime.status()) + runtime.metrics() + log.getvalue()
    finally:
        runtime.shutdown()


def test_business_exception_is_preserved_without_exception_content():
    log = StringIO()
    runtime = TelemetryRuntime(log_output=log)
    failure = RuntimeError('PRIVATE-URL?key=SECRET-BODY-SQL')
    try:
        with pytest.raises(RuntimeError) as caught, runtime.scope():
            with observe('source.http', component='crawler', source='nhtsa'):
                raise failure
        assert caught.value is failure
        span, = runtime.finished_spans()
        assert span['status'] == 'ERROR' and span['attributes']['outcome'] == 'error'
        assert span['attributes']['source'] == 'nhtsa-us-recalls'
        assert 'SECRET' not in json.dumps(runtime.status()) + runtime.metrics() + log.getvalue()
        assert not trace.get_current_span().get_span_context().is_valid
    finally:
        runtime.shutdown()


def test_resource_environment_and_existing_context_are_not_inherited(monkeypatch):
    # Exercise the private in-memory exporters independently of the host's
    # observability switch; monkeypatch restores its disabled state afterwards.
    monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', '1')
    monkeypatch.setenv('TI_OBSERVABILITY_LOGS', '0')
    monkeypatch.setenv('OTEL_SERVICE_NAME', 'SECRET-SERVICE')
    monkeypatch.setenv('OTEL_RESOURCE_ATTRIBUTES', 'secret=SECRET-RESOURCE')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_ENDPOINT', 'https://SECRET.invalid')
    monkeypatch.setenv('OTEL_EXPORTER_OTLP_HEADERS', 'authorization=SECRET')
    monkeypatch.setenv('OTEL_TRACES_EXPORTER', 'otlp')
    monkeypatch.setenv('OTEL_METRICS_EXPORTER', 'otlp')
    monkeypatch.setenv('OTEL_PROPAGATORS', 'baggage')
    runtime = TelemetryRuntime.from_env('tire-api')
    outer = SpanContext(trace_id=123, span_id=456, is_remote=True, trace_flags=TraceFlags(1))
    external = baggage.set_baggage('secret', 'SECRET-BAGGAGE', trace.set_span_in_context(NonRecordingSpan(outer)))
    token = context.attach(external)
    try:
        with runtime.scope():
            assert baggage.get_baggage('secret') is None
            with observe('api.request', component='api'):
                pass
        assert trace.get_current_span().get_span_context() == outer
        row, = runtime.finished_spans()
        assert row['parent_span_id'] is None and row['trace_id'] != format(123, '032x')
        assert runtime._traces.resource.attributes == {'service.name': 'tire-api'}
        assert runtime._meters._sdk_config.resource.attributes == {'service.name': 'tire-api'}
        assert 'SECRET' not in json.dumps(runtime.status()) + runtime.metrics()
    finally:
        context.detach(token)
        runtime.shutdown()


def test_unknown_labels_bounded_retention_and_metric_overflow(monkeypatch):
    import tire_api.telemetry as module
    monkeypatch.setattr(module, 'MAX_METRIC_SERIES', 4)
    runtime = TelemetryRuntime(logs_enabled=False)
    runtime.set_routes([f'/fixed/{i}' for i in range(10)])
    try:
        with runtime.scope():
            for index in range(MAX_RECENT_SPANS + 30):
                with observe('api.request', component='api', source=f'SECRET-{index}') as op:
                    op.finish('SECRET-OUTCOME', route=f'/user/SECRET-{index}', http_status=200)
            for index in range(10):
                with observe('api.request', component='api') as op:
                    op.finish('success', route=f'/fixed/{index}', http_status=200)
        assert len(runtime.finished_spans()) == MAX_RECENT_SPANS
        assert len(samples(runtime, 'tire_operations_total')) == 5
        assert any(row.labels['operation'] == 'overflow' for row in samples(runtime, 'tire_operations_total'))
        assert 'SECRET' not in runtime.metrics() + json.dumps(runtime.finished_spans())
        assert len(runtime._series) == 4
    finally:
        runtime.shutdown()


def test_independent_runtimes_and_disabled_noop(monkeypatch):
    first = TelemetryRuntime(logs_enabled=False)
    second = TelemetryRuntime('tire-worker', logs_enabled=False)
    disabled = TelemetryRuntime(enabled=False)
    try:
        with first.scope(), observe('api.request', component='api'):
            with second.scope(), observe('worker.cycle', component='worker'):
                pass
        assert first.finished_spans()[0]['parent_span_id'] is None
        assert second.finished_spans()[0]['parent_span_id'] is None
        first.shutdown()
        first.shutdown()
        with second.scope(), observe('worker.job', component='worker'):
            pass
        assert len(second.finished_spans()) == 2
        assert 'api.request' not in second.metrics()
        with disabled.scope(), observe('api.request', component='api'):
            record_ai_usage('openai_responses', {'input_tokens': 12})
        assert disabled.finished_spans() == []
        assert not list(text_string_to_metric_families(disabled.metrics()))
        monkeypatch.setenv('TI_OBSERVABILITY_ENABLED', 'SECRET')
        with pytest.raises(ValueError, match='TI_OBSERVABILITY_ENABLED must be 0 or 1'):
            TelemetryRuntime.from_env('tire-api')
    finally:
        first.shutdown()
        second.shutdown()
        disabled.shutdown()


def test_async_concurrency_thread_context_and_cancellation():
    runtime = TelemetryRuntime(logs_enabled=False)

    async def task(cancel=False):
        with runtime.scope(), observe('api.request', component='api'):
            def work():
                with observe('source.query', component='crawler', source='michelin-cn'):
                    return 7
            assert await asyncio.to_thread(work) == 7
            await asyncio.sleep(0)
            if cancel:
                raise asyncio.CancelledError('SECRET-CANCEL')

    async def run():
        results = await asyncio.gather(task(), task(), task(True), return_exceptions=True)
        assert isinstance(results[-1], asyncio.CancelledError)

    try:
        asyncio.run(run())
        parents = [row for row in runtime.finished_spans() if row['parent_span_id'] is None]
        assert len(parents) == 3 and len({row['trace_id'] for row in parents}) == 3
        assert {row['attributes']['outcome'] for row in parents} == {'success', 'cancelled'}
        for parent in parents:
            child, = [row for row in runtime.finished_spans() if row['parent_span_id'] == parent['span_id']]
            assert child['trace_id'] == parent['trace_id']
        assert not trace.get_current_span().get_span_context().is_valid
    finally:
        runtime.shutdown()


def test_usage_unknown_is_not_zero_and_telemetry_failure_cannot_replace_business(monkeypatch):
    runtime = TelemetryRuntime(logs_enabled=False)
    try:
        with runtime.scope():
            record_ai_usage('openai_responses', None)
            record_ai_usage('openai_responses', {'input_tokens': None, 'output_tokens': True})
        assert not samples(runtime, 'tire_ai_tokens_total')
        with runtime.scope():
            record_ai_usage('openai_responses', {'input_tokens': 12, 'output_tokens': 0, 'secret': 'SECRET'})
        tokens = samples(runtime, 'tire_ai_tokens_total')
        assert {row.labels['kind']: row.value for row in tokens} == {'input_tokens': 12, 'output_tokens': 0}

        def broken(*args, **kwargs):
            raise RuntimeError('SECRET-EXPORTER')
        monkeypatch.setattr(runtime, '_record', broken)
        with runtime.scope(), observe('worker.job', component='worker'):
            result = 'business-result'
        assert result == 'business-result'
        with pytest.raises(ValueError, match='business-failure'), runtime.scope():
            with observe('worker.job', component='worker'):
                raise ValueError('business-failure')
        assert len(runtime.finished_spans()) == 2
        assert 'SECRET' not in json.dumps(runtime.status())
    finally:
        runtime.shutdown()


def test_failed_log_sink_and_span_storage_do_not_print_business_exception(capsys, caplog):
    class BrokenSink:
        def write(self, value):
            raise OSError('SECRET-SINK')

        def flush(self):
            pass

    class BrokenRows:
        def append(self, value):
            raise OSError('SECRET-EXPORT')

    runtime = TelemetryRuntime(log_output=BrokenSink())
    runtime._exporter.rows = BrokenRows()
    failure = ValueError('SECRET-BUSINESS-BODY')
    try:
        with pytest.raises(ValueError) as caught, runtime.scope():
            with observe('source.query', component='crawler'):
                raise failure
        assert caught.value is failure
        captured = capsys.readouterr()
        assert 'SECRET' not in captured.out + captured.err + caplog.text
        assert samples(runtime, 'tire_operations_total')[0].value == 1
    finally:
        runtime.shutdown()


def test_sdk_internal_metrics_cannot_use_host_global_provider(monkeypatch):
    from opentelemetry import metrics
    import opentelemetry.sdk.trace.export as export_module
    monkeypatch.setenv('OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED', 'true')

    def forbidden():
        raise AssertionError('global metric provider must not be consulted')
    monkeypatch.setattr(metrics, 'get_meter_provider', forbidden)
    monkeypatch.setattr(export_module, 'get_meter_provider', forbidden)
    runtime = TelemetryRuntime(logs_enabled=False)
    try:
        with runtime.scope(), observe('api.request', component='api'):
            pass
        assert len(runtime.finished_spans()) == 1
        assert samples(runtime, 'tire_operations_total')[0].value == 1
    finally:
        runtime.shutdown()


def test_one_provider_shutdown_failure_still_closes_remaining_resources(monkeypatch):
    runtime = TelemetryRuntime(logs_enabled=False)
    closed = []

    def failed():
        raise RuntimeError('PRIVATE-shutdown-message')
    monkeypatch.setattr(runtime._traces, 'shutdown', failed)
    original = runtime._meters.shutdown

    def close_metrics():
        original()
        closed.append('metrics')
    monkeypatch.setattr(runtime._meters, 'shutdown', close_metrics)
    runtime.shutdown()
    runtime.shutdown()
    assert closed == ['metrics']
    assert runtime.closed


def test_sdk_ambient_limits_and_malformed_flags_do_not_leak(monkeypatch, capsys, caplog):
    monkeypatch.setenv('OTEL_SPAN_ATTRIBUTE_VALUE_LENGTH_LIMIT', 'SECRET-LIMIT')
    monkeypatch.setenv('OTEL_METRICS_EXEMPLAR_FILTER', 'SECRET-EXEMPLAR')
    runtime = TelemetryRuntime(logs_enabled=False)
    try:
        with runtime.scope(), observe('worker.cycle', component='worker'):
            pass
        assert len(runtime.finished_spans()) == 1
    finally:
        runtime.shutdown()
    monkeypatch.setenv('OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED', 'SECRET-FLAG')
    with pytest.raises(ValueError) as error:
        TelemetryRuntime(logs_enabled=False)
    assert 'SECRET' not in str(error.value)
    captured = capsys.readouterr()
    assert 'SECRET' not in captured.out + captured.err + caplog.text


def test_sdk_disable_is_explicit_and_does_not_emit_misleading_metrics(monkeypatch):
    monkeypatch.setenv('OTEL_SDK_DISABLED', 'true')
    runtime = TelemetryRuntime(logs_enabled=False)
    try:
        with runtime.scope(), observe('api.request', component='api'):
            pass
        assert runtime.status()['sdk_disabled'] and not runtime.status()['enabled']
        assert not runtime.finished_spans()
        assert not list(text_string_to_metric_families(runtime.metrics()))
    finally:
        runtime.shutdown()


def test_explicit_worker_http_export_is_loopback_guarded_and_closes():
    import http.client
    import socket
    runtime = TelemetryRuntime('tire-worker', logs_enabled=False)
    assert runtime._http_server is None
    listener = runtime.start_metrics_server(0)
    assert listener['address'] == '127.0.0.1'
    port = listener['port']

    def request(path, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    try:
        with runtime.scope(), observe('worker.job', component='worker') as item:
            item.finish('live', queue_lag_seconds=37)
        assert request(listener['metrics_path'])[0] == 200
        assert 'tire_worker_queue_lag_seconds' in request(listener['metrics_path'])[1]
        assert request('/v1/observability', {'Origin': 'https://private.invalid'})[0] == 403
        assert request('/v1/observability', {'Host': 'private.invalid'})[0] == 400
        assert request('/v1/observability', {'Sec-Fetch-Site': 'cross-site'})[0] == 403
        assert request('/private?secret')[0] == 404
        status, body = request('/v1/observability')
        assert status == 200 and json.loads(body)['worker_presence'] == 'this_process'
        assert len(runtime.finished_spans()) == 1
        with pytest.raises(RuntimeError):
            runtime.start_metrics_server(0)
    finally:
        runtime.shutdown()
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1', port)) != 0

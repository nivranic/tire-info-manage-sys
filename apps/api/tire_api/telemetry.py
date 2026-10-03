"""Process-local OpenTelemetry with bounded, explicitly selected public metadata.

No automatic instrumentation, global provider, resource detection, remote exporter,
or incoming trace/baggage extraction. Business payloads never enter this module.
"""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
import math
import os
import re
from threading import RLock, Thread
import time
from typing import TextIO

from opentelemetry import context as otel_context
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.metrics import NoOpMeterProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics import AlwaysOffExemplarFilter
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import StatusCode
from prometheus_client import CollectorRegistry, generate_latest

OPERATIONS = {
    'api.request': 'api', 'source.query': 'crawler', 'source.http': 'crawler',
    'ai.response': 'ai', 'ai.embedding': 'ai', 'worker.cycle': 'worker',
    'worker.job': 'worker', 'db.ingestion_lock': 'database',
}
SOURCES = frozenset({'michelin-us', 'michelin-cn', 'michelin-uk', 'michelin-fr',
    'michelin-de', 'toyo-us', 'hankook-us', 'pirelli-us', 'xiaomi-cn-vehicles', 'nhtsa-us-recalls'})
OUTCOMES = frozenset({'success', 'error', 'cancelled', 'unknown', 'completed', 'failed',
    'live', 'live_verified_304', 'local_snapshot', 'consent_required', 'source_unavailable',
    'unavailable', 'not_modified', 'worker_error', 'lease_lost', 'idle', 'rejected',
    'blocked', 'skipped', 'finalized', 'stale'})
ERROR_OUTCOMES = frozenset({'error', 'failed', 'source_unavailable', 'unavailable',
    'worker_error', 'lease_lost'})
PROVIDERS = frozenset({'openai_responses', 'openai_embeddings'})
MAX_RECENT_SPANS = 256
MAX_ROUTES = 512
MAX_METRIC_SERIES = 1024
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1, 2, 3, 5, 8, 10, 30, 60)
_current: ContextVar[TelemetryRuntime | None] = ContextVar('tire_telemetry_runtime', default=None)


def _member(value, allowed: frozenset | dict, fallback='unknown') -> str:
    return value if type(value) is str and value in allowed else fallback


def _flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    if raw not in {'0', '1'}:
        raise ValueError(f'{name} must be 0 or 1')
    return raw == '1'


def _sdk_flag(name: str, default=False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized not in {'true', 'false'}:
        # SDK otherwise echoes malformed values in warnings. Never include the value.
        raise ValueError(f'{name} must be true or false')
    return normalized == 'true'


class _LocalSpans(SpanExporter):
    def __init__(self):
        self.rows: deque[dict] = deque(maxlen=MAX_RECENT_SPANS)
        self.lock = RLock()

    def export(self, spans) -> SpanExportResult:
        try:
            with self.lock:
                for span in spans:
                    self.rows.append({
                        'name': span.name,
                        'trace_id': format(span.context.trace_id, '032x'),
                        'span_id': format(span.context.span_id, '016x'),
                        'parent_span_id': format(span.parent.span_id, '016x') if span.parent else None,
                        'attributes': dict(span.attributes or {}),
                        'status': span.status.status_code.name,
                        'duration_ms': round(max(0, (span.end_time - span.start_time) / 1_000_000), 3),
                    })
            return SpanExportResult.SUCCESS
        except Exception:
            # SDK exporter errors otherwise log exception chains, which could
            # include an active business exception even though we never read it.
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        pass

    def snapshot(self) -> list[dict]:
        with self.lock:
            return [{**row, 'attributes': dict(row['attributes'])} for row in self.rows]


class _SafeStreamHandler(logging.StreamHandler):
    def handleError(self, record) -> None:
        # logging's default handler prints a traceback and active exception
        # chain to stderr when a sink fails. That chain may contain private data.
        pass


class TelemetryRuntime:
    """One API/Worker process runtime; independent instances also work in tests."""

    def __init__(self, service_name: str = 'tire-api', *, enabled: bool = True,
                 logs_enabled: bool = True, log_output: TextIO | None = None):
        self.service_name = _member(service_name, frozenset({'tire-api', 'tire-worker', 'tire-test'}), 'tire-test')
        self.sdk_disabled = _sdk_flag('OTEL_SDK_DISABLED')
        _sdk_flag('OTEL_PYTHON_SDK_INTERNAL_METRICS_ENABLED')
        self.enabled = bool(enabled) and not self.sdk_disabled
        self.closed = False
        self._routes: frozenset[str] = frozenset()
        self._lock = RLock()
        self._series: set[tuple] = set()
        self._http_server = self._http_thread = None
        self._exporter = _LocalSpans()
        self._registry = CollectorRegistry(auto_describe=False)
        self._logger = logging.Logger('tire.telemetry', logging.INFO)
        self._logger.propagate = False
        if self.enabled and logs_enabled:
            handler = _SafeStreamHandler(log_output)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._logger.addHandler(handler)
        self._traces = self._meters = None
        if self.enabled:
            try:
                self._initialize_sdk()
            except Exception:
                self.shutdown()
                raise ValueError('Telemetry SDK initialization failed') from None

    def _initialize_sdk(self):
        # Resource.create() performs environment/default resource detection.
        # Explicit Resource avoids inheriting host metadata or OTEL_* secrets.
        resource = Resource({'service.name': self.service_name})
        internal_metrics = NoOpMeterProvider()
        self._traces = TracerProvider(resource=resource, sampler=ALWAYS_ON,
            span_limits=SpanLimits(max_attributes=12, max_events=0, max_links=0,
                max_attribute_length=180, max_span_attribute_length=180, max_span_attributes=12,
                max_event_attributes=0, max_link_attributes=0), shutdown_on_exit=False,
            meter_provider=internal_metrics)
        self._traces.add_span_processor(SimpleSpanProcessor(self._exporter, meter_provider=internal_metrics))
        self._tracer = self._traces.get_tracer('tire.observability', '1')
        reader = PrometheusMetricReader(registry=self._registry, disable_target_info=True,
                                      scope_info_enabled=False)
        self._meters = MeterProvider(resource=resource, metric_readers=[reader],
            views=[View(instrument_name='tire.operation.duration',
                aggregation=ExplicitBucketHistogramAggregation(LATENCY_BUCKETS))],
            exemplar_filter=AlwaysOffExemplarFilter(), shutdown_on_exit=False)
        meter = self._meters.get_meter('tire.observability', '1')
        self._operations = meter.create_counter('tire.operations', description='Completed observed operations')
        self._duration = meter.create_histogram('tire.operation.duration', unit='s',
            description='Elapsed operation time, including failures and local results')
        self._tokens = meter.create_counter('tire.ai.tokens', description='Explicitly reported provider tokens')
        self._queue_lag = meter.create_histogram('tire.worker.queue.lag', unit='s',
            description='Observed delay from due time to claimed job execution')

    @classmethod
    def from_env(cls, service_name: str) -> TelemetryRuntime:
        return cls(service_name, enabled=_flag('TI_OBSERVABILITY_ENABLED'),
                   logs_enabled=_flag('TI_OBSERVABILITY_LOGS'))

    def set_routes(self, routes) -> None:
        self._routes = frozenset(sorted({route for route in routes if type(route) is str
            and len(route) <= 180 and re.fullmatch(r'/[A-Za-z0-9_/{},:.\-]*', route)})[:MAX_ROUTES])

    @contextmanager
    def scope(self):
        token = _current.set(self)
        # Start an independent root. Do not inherit external SDK/global baggage.
        context_token = otel_context.attach(otel_context.Context())
        try:
            yield self
        finally:
            otel_context.detach(context_token)
            _current.reset(token)

    def finished_spans(self) -> list[dict]:
        return self._exporter.snapshot()

    def status(self) -> dict:
        return {'enabled': self.enabled, 'closed': self.closed, 'service_name': self.service_name,
            'sdk_disabled': self.sdk_disabled,
            'scope': 'current_process_only', 'external_export': False,
            'retention': {'kind': 'memory', 'max_recent_spans': MAX_RECENT_SPANS},
            'max_operation_attribute_sets': MAX_METRIC_SERIES + 1,
            'metric_cardinality_scope': 'operation label sets; histogram buckets and token kinds add series',
            'recent_spans': self.finished_spans(),
            'worker_presence': 'not_observed_here' if self.service_name != 'tire-worker' else 'this_process',
            'cost_tracking': 'not_configured'}

    def metrics(self) -> str:
        with self._lock:
            if not self.enabled or self.closed:
                return '# tire telemetry disabled or closed\n'
            return generate_latest(self._registry).decode('utf-8')

    def start_metrics_server(self, port: int) -> dict:
        """Explicit Worker-only loopback listener, never started by a library import."""
        if type(port) is not int or not 0 <= port <= 65535:
            raise ValueError('Invalid local metrics port')
        runtime = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(2)

            def log_message(self, *_args):
                # BaseHTTPRequestHandler otherwise logs raw paths and headers.
                pass

            def reply(self, code, body, content_type='application/json'):
                data = body.encode('utf-8')
                self.send_response(code)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Connection', 'close')
                self.end_headers()
                self.close_connection = True
                self.wfile.write(data)

            def do_GET(self):
                port_value = self.server.server_port
                hosts = {f'127.0.0.1:{port_value}', f'localhost:{port_value}'}
                origins = {'http://' + host for host in hosts}
                if self.headers.get('Host') not in hosts:
                    self.reply(400, '{"error":"invalid_host"}')
                elif (self.headers.get('Origin') not in origins | {None}
                      or self.headers.get('Sec-Fetch-Site') == 'cross-site'):
                    self.reply(403, '{"error":"invalid_origin"}')
                elif self.path == '/v1/observability/metrics':
                    self.reply(200, runtime.metrics(), 'text/plain; version=0.0.4; charset=utf-8')
                elif self.path == '/v1/observability':
                    self.reply(200, json.dumps(runtime.status()))
                else:
                    self.reply(404, '{"error":"not_found"}')

            def do_POST(self):
                self.reply(405, '{"error":"method_not_allowed"}')

        class QuietServer(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, *_args):
                # Disconnected clients/sinks must not dump exception chains.
                pass

        with self._lock:
            if self.closed or self._http_server is not None:
                raise RuntimeError('Metrics listener cannot be started in this state')
            server = QuietServer(('127.0.0.1', port), Handler)
            thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.1},
                            name='tire-local-metrics', daemon=True)
            try:
                thread.start()
            except Exception:
                server.server_close()
                raise RuntimeError('Local metrics listener failed to start') from None
            self._http_server, self._http_thread = server, thread
            return {'address': '127.0.0.1', 'port': server.server_port,
                    'metrics_path': '/v1/observability/metrics'}

    def shutdown(self) -> None:
        with self._lock:
            if self.closed:
                return
            self.closed = True
            server, thread = self._http_server, self._http_thread
        # Do not hold the metrics lock while waiting for an active scrape to exit.
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        with self._lock:
            for provider in (self._traces, self._meters):
                if provider:
                    try:
                        provider.shutdown()
                    except Exception:
                        # No remote flush; one local provider cannot prevent the
                        # remaining resources from closing or print exception data.
                        pass
            for handler in self._logger.handlers[:]:
                self._logger.removeHandler(handler)
                handler.close()

    def _record(self, attributes: dict, elapsed: float, span, queue_lag: float | None) -> None:
        with self._lock:
            if self.closed:
                return
            key = tuple(sorted(attributes.items()))
            if key not in self._series and len(self._series) >= MAX_METRIC_SERIES:
                labels = {'component': 'unknown', 'operation': 'overflow', 'outcome': 'unknown'}
            else:
                self._series.add(key)
                labels = attributes
            self._operations.add(1, labels)
            self._duration.record(elapsed, labels)
            if queue_lag is not None:
                self._queue_lag.record(queue_lag, {'component': 'worker'})
            if self._logger.handlers:
                context = span.get_span_context()
                record = {'event': 'operation_finished', 'service': self.service_name,
                    'trace_id': format(context.trace_id, '032x'),
                    'span_id': format(context.span_id, '016x'),
                    'duration_ms': round(elapsed * 1000, 3), **attributes}
                self._logger.info(json.dumps(record, ensure_ascii=True, separators=(',', ':')))


class Observation:
    def __init__(self, operation: str, *, component: str, source: str | None = None):
        self.runtime = _current.get()
        self.operation = _member(operation, OPERATIONS)
        self.attributes = {'operation': self.operation,
            'component': OPERATIONS.get(self.operation, 'unknown'), 'outcome': 'success'}
        # A mismatched component cannot create a new label or operation series.
        if component != self.attributes['component']:
            self.attributes = {'operation': 'unknown', 'component': 'unknown', 'outcome': 'unknown'}
        if source is not None:
            source = {'xiaomi-su7': 'xiaomi-cn-vehicles', 'nhtsa': 'nhtsa-us-recalls'}.get(source, source) if type(source) is str else source
            self.attributes['source'] = _member(source, SOURCES)
        self.queue_lag = None
        self._context = self._span = None
        self._started = time.perf_counter()

    def __enter__(self):
        runtime = self.runtime
        if runtime and runtime.enabled and not runtime.closed:
            try:
                self._context = runtime._tracer.start_as_current_span(self.attributes['operation'],
                    record_exception=False, set_status_on_exception=False)
                self._span = self._context.__enter__()
            except Exception:
                self._context = self._span = None
        return self

    def finish(self, outcome: str = 'success', **fields) -> None:
        self.attributes['outcome'] = _member(outcome, OUTCOMES)
        code = fields.get('http_status')
        if type(code) is int and 100 <= code <= 599:
            self.attributes['http_status'] = code
        route = fields.get('route')
        if route is not None:
            self.attributes['route'] = route if (type(route) is str and self.runtime
                and route in self.runtime._routes) else 'unknown'
        lag = fields.get('queue_lag_seconds')
        if type(lag) in {int, float} and math.isfinite(lag) and 0 <= lag <= 31_536_000:
            self.queue_lag = float(lag)

    def __exit__(self, exc_type, exc, traceback):
        if exc_type is not None:
            self.attributes['outcome'] = 'cancelled' if issubclass(exc_type, asyncio.CancelledError) else 'error'
        if self._span is not None:
            try:
                self._span.set_attributes(self.attributes)
                self._span.set_status(StatusCode.ERROR if self.attributes['outcome'] in ERROR_OUTCOMES
                                      or self.attributes['outcome'] == 'cancelled' else StatusCode.UNSET)
                self.runtime._record(self.attributes, max(0, time.perf_counter() - self._started),
                                     self._span, self.queue_lag)
            except Exception:
                # Observability failure must not change a committed business result.
                pass
            finally:
                try:
                    # Never pass a business exception to SDK exception recording.
                    self._context.__exit__(None, None, None)
                except Exception:
                    pass
        return False


def observe(operation: str, *, component: str, source: str | None = None) -> Observation:
    return Observation(operation, component=component, source=source)


def record_ai_usage(provider: str, usage: dict | None) -> None:
    runtime = _current.get()
    if not runtime or not runtime.enabled or runtime.closed or type(usage) is not dict:
        return
    provider = _member(provider, PROVIDERS)
    # Missing values are not zero. Total and cached tokens are distinct reported
    # kinds; dashboards must not sum total/input/output/cached together.
    try:
        with runtime._lock:
            if runtime.closed:
                return
            for kind in ('input_tokens', 'output_tokens', 'cached_tokens', 'total_tokens'):
                value = usage.get(kind)
                if type(value) is int and 0 <= value <= 100_000_000:
                    runtime._tokens.add(value, {'provider': provider, 'kind': kind})
    except Exception:
        pass

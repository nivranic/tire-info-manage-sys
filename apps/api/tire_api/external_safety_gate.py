"""Licensed source-native alert pages, authorized inside one fresh reader lock."""
import re

from fastapi import HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.exc import DBAPIError

from .db import QueryRun, utc
from .domain import digest, stable_json
from .external_api import SAFE_HEADERS, _cursor, decode_cursor, encode_cursor, fail, unauthorized
from .external_fact_governance import GovernanceError
from .external_fact_page import PageOutcome
from .external_fact_page_budget import PageCapacityError, PageReadBudget
from .external_fact_policy import evaluate_applicability
from .external_fact_reader import ERROR_CODES, OwnedFactReader, ReaderError, _fail, _identifier
from .safety_gate import SafetyGateSnapshot, SafetyGateVerification, checked_snapshot
from .service import timestamp

SOURCE = 'eu-safety-gate'
ROUTE = 'safety-gate-report-alerts'
MAX_PAGE_BYTES = 2 * 1024 * 1024
REQUIRED_FIELDS = frozenset({
    'identity.report_id', 'identity.report_reference', 'identity.alert_id', 'identity.case_number',
    'evidence.report_published_date', 'evidence.alert_published_date', 'evidence.alert_source_url',
    'evidence.source_id', 'evidence.snapshot_id', 'evidence.raw_hash', 'evidence.parser_version',
    'evidence.source_url', 'evidence.observed_at', 'evidence.verified_at',
})
FACT_FIELDS = {
    'category': 'category', 'product': 'product', 'brand': 'brand', 'name': 'name',
    'model_number': 'type_numberOfModel', 'batch_number': 'batchNumber', 'barcode': 'barcode',
    'risk_type': 'riskType', 'danger': 'danger', 'measures': 'measures', 'recall_url': 'URLrecall',
    'description': 'description', 'notifying_country': 'notifyingCountry', 'country_of_origin': 'countryOfOrigin',
    'type': 'type', 'level': 'level', 'online_trader': 'onlineTrader',
    'company_recall_code': 'companyRecallCode', 'production_dates': 'productionDates',
}
ALL_FIELDS = REQUIRED_FIELDS | frozenset('facts.' + name for name in FACT_FIELDS)
_REPORT = re.compile(r'[1-9][0-9]{0,11}', re.ASCII)


class SafetyGateReadBudget(PageReadBudget):
    # One XML plus its validated parsed document, license chain and ownership.
    MAX_STORAGE_BYTES = 32 * 1024 * 1024


def _params(report_id, pairs):
    if type(report_id) is not str or _REPORT.fullmatch(report_id) is None or type(pairs) not in (list, tuple):
        _fail('reader_query_invalid')
    values = {}
    for pair in pairs:
        if (type(pair) not in (list, tuple) or len(pair) != 2 or type(pair[0]) is not str
                or type(pair[1]) is not str or pair[0] not in {'query_id', 'mode', 'limit', 'cursor'}
                or pair[0] in values):
            _fail('reader_query_invalid')
        values[pair[0]] = pair[1]
    if (values.get('mode') != 'history' or not _identifier(values.get('query_id'))
            or re.fullmatch(r'(?:[1-9]|1[0-9]|20)', values.get('limit', '20')) is None
            or 'cursor' in values and not 1 <= len(values['cursor']) <= 2048):
        _fail('reader_query_invalid')
    return values, int(values.get('limit', '20'))


class SafetyGateReader:
    def __init__(self, engine, grant_id=None, *, clock=None):
        self._auth = OwnedFactReader(engine, {} if grant_id is None else {SOURCE: grant_id}, None, clock=clock)
        self._store = self._auth._store
        self._grant = grant_id

    def capture_credential(self, headers):
        return self._auth.capture_credential(headers)

    @staticmethod
    def _formal(db, budget, query_id, report_id, now, cache):
        run = budget.get(db, QueryRun, query_id, limits={'query': 65536, 'selection_filters': 65536})
        verifications = budget.load(db, SafetyGateVerification, SafetyGateVerification.query_id == query_id,
                                    limits={'parser_identity': 16384})
        if (run is None or len(verifications) != 1 or run.source_id != SOURCE or run.state != 'live'
                or type(run.query) is not dict or run.query.get('operation') != 'report'
                or run.query.get('report_id') != report_id or digest(run.query) != run.query_key):
            _fail('reader_not_available')
        verification = verifications[0]
        if (verification.status not in {'ok', 'not_modified'} or verification.query_key != run.query_key
                or not _identifier(verification.snapshot_id)
                or not utc(run.created_at) <= utc(verification.verified_at) <= now):
            _fail('reader_binding_invalid')
        if verification.snapshot_id not in cache:
            snapshot = budget.get(db, SafetyGateSnapshot, verification.snapshot_id, limits={
                'body': 8 * 1024 * 1024, 'document': 8 * 1024 * 1024, 'parser_identity': 16384,
                'query': 65536, 'license_basis': 16384, 'source_url': 2048, 'attribution': 2048})
            if snapshot is None:
                _fail('reader_binding_invalid')
            try:
                checked_snapshot(snapshot)
            except HTTPException:
                _fail('reader_binding_invalid')
            cache[snapshot.id] = snapshot
        snapshot = cache[verification.snapshot_id]
        if (snapshot.query != run.query or snapshot.query_key != run.query_key
                or verification.parser_identity != snapshot.parser_identity
                or snapshot.parser_identity is not None and type(snapshot.parser_identity) is not dict
                or not utc(snapshot.observed_at) <= utc(verification.verified_at)
                or type(snapshot.parser_version) is not str or not 1 <= len(snapshot.parser_version) <= 100):
            _fail('reader_binding_invalid')
        return run, verification, snapshot

    def read_page(self, credential, *, report_id, query_pairs):
        try:
            params, limit = _params(report_id, query_pairs)
            budget = SafetyGateReadBudget()
            with self._store._reader_transaction(budget=budget) as (db, now):
                key = self._auth._authenticate(db, credential, now, budget=budget, return_key=True,
                                              required_scope='safety-gate:read')
                owner = self._auth._owned(db, params['query_id'], key.owner_user_id, budget=budget)
                if utc(owner.captured_at) > now:
                    _fail('reader_binding_invalid')
                if self._grant is None:
                    _fail('reader_not_available')
                cache = {}
                run, verification, snapshot = self._formal(db, budget, params['query_id'], report_id, now, cache)
                rows, current = self._store._reader_load(db, self._grant, budget=budget)
                if current.policy is None or current.state != 'approved':
                    _fail('reader_not_available')
                fields = sorted(ALL_FIELDS.intersection(current.policy.latest.coverage.field_keys))
                if not REQUIRED_FIELDS.issubset(fields):
                    _fail('reader_not_available')
                observation = {'source_id': SOURCE, 'snapshot_id': snapshot.id,
                               'raw_hash': snapshot.raw_hash, 'parser_version': snapshot.parser_version}
                if evaluate_applicability(current.policy, observation, fields, now=now).status != 'applicable':
                    _fail('reader_not_available')
                bindings = [binding for binding in rows[-1].binding_receipts if binding['snapshot_id'] == snapshot.id]
                if len(bindings) != 1:
                    _fail('reader_binding_invalid')
                binding = bindings[0]
                _, approved_verification, approved_snapshot = self._formal(db, budget, binding['query_id'], report_id, now, cache)
                if (approved_snapshot.id != snapshot.id or binding['verification_id'] != approved_verification.id
                        or any(binding[name] != value for name, value in observation.items())
                        or binding['query_key'] != run.query_key
                        or binding['parser_identity_digest'] != (digest(snapshot.parser_identity) if snapshot.parser_identity is not None else None)):
                    _fail('reader_binding_invalid')
                report = {name: snapshot.document['report'][name] for name in ('report_id', 'reference', 'published_date')}
                evidence = {**observation, 'source_url': snapshot.source_url,
                            'observed_at': timestamp(snapshot.observed_at), 'verified_at': timestamp(verification.verified_at)}
                alerts = snapshot.document['alerts']
                context = {'window': digest({'evidence': evidence, 'document_hash': snapshot.document_hash,
                    'parser_identity': snapshot.parser_identity, 'verification_id': verification.id,
                    'owner_receipt': owner.record_digest, 'policy_head': current.head, 'fields': fields,
                    'query_key': run.query_key, 'report': report}), 'count': len(alerts)}
                principal = {'id': key.id, 'owner': key.owner_user_id, 'cursor_secret': key.cursor_secret}
                filters = {'report_id': report_id, 'query_id': params['query_id'], 'mode': 'history'}
                cursor, offset = None, 0
                if 'cursor' in params:
                    try:
                        cursor = decode_cursor(principal, params['cursor'], ROUTE, limit, filters)
                    except HTTPException:
                        _fail('reader_cursor_invalid')
                    if cursor['context'] != context:
                        _fail('reader_window_changed')
                    offset = cursor['after']
                    if type(offset) is not int or not 0 < offset < len(alerts) or offset % limit:
                        _fail('reader_cursor_invalid')
                selected = alerts[offset:offset + limit]
                items = [{**{name: alert[name] for name in ('alert_id', 'case_number', 'published_date', 'source_url', 'applicability')},
                          'facts': {name: alert['fields'][original] for name, original in FACT_FIELDS.items()
                                    if 'facts.' + name in fields}} for alert in selected]
                next_cursor = None
                if offset + limit < len(alerts):
                    payload = _cursor(principal, ROUTE, limit, filters, context, offset + limit)
                    if cursor is not None:
                        payload['expires'] = cursor['expires']
                    next_cursor = encode_cursor(principal, payload)
                result = {'schema': 'external-safety-gate-alert-page@1', 'data_state': 'local_snapshot',
                    'source_refresh_performed': False, 'query_id': run.id, 'report': report,
                    'observation': evidence, 'items': items, 'limit': limit, 'next_cursor': next_cursor}
                budget.json(result)
                body = stable_json(result).encode('utf-8')
                if len(body) > MAX_PAGE_BYTES:
                    _fail('reader_capacity')
                outcome = PageOutcome(body, budget.actual_rows, budget.charged_rows)
            return outcome
        except ReaderError:
            raise
        except PageCapacityError:
            raise ReaderError('reader_capacity') from None
        except GovernanceError as error:
            raise ReaderError(error.code if error.code in ERROR_CODES else 'reader_policy_invalid') from None
        except DBAPIError:
            raise ReaderError('reader_storage_unavailable') from None
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise ReaderError('reader_binding_invalid') from None


def register_external_safety_gate_routes(app, reader=None):
    @app.get('/external/v1/safety-gate-reports/{report_id}/alerts')
    def alerts(report_id: str, request: Request):
        if reader is None:
            fail('external_safety_gate_service_unavailable', 503)
        try:
            credential = reader.capture_credential(request.headers.getlist('authorization'))
            outcome = reader.read_page(credential, report_id=report_id, query_pairs=tuple(request.query_params.multi_items()))
        except ReaderError as error:
            if error.code == 'reader_unauthorized':
                unauthorized()
            if error.code == 'reader_scope_required':
                fail('external_scope_required', 403)
            if error.code in {'reader_query_invalid', 'reader_cursor_invalid'}:
                fail('external_' + error.code.removeprefix('reader_'), 422)
            if error.code == 'reader_window_changed':
                fail('external_safety_gate_window_changed', 409)
            if error.code in {'reader_backend_unsupported', 'reader_schema_required', 'reader_clock_invalid', 'reader_storage_unavailable'}:
                fail('external_safety_gate_service_unavailable', 503)
            fail('external_safety_gate_not_available', 404)
        return Response(content=outcome.body, media_type='application/json', headers=SAFE_HEADERS)

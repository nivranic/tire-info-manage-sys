"""Whole-window owned fact pagination under one fresh SQLite reader lock."""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import re

from sqlalchemy.exc import DBAPIError, StatementError

from .db import (AuditEvent, FactVersion, ManualFactRevision, Snapshot, TireVariant,
                 VariantLifecycleEvent, utc)
from .domain import VariantInput, digest, stable_json
from .curation import FIELD_CATALOG
from .external_fact_cursor import CursorError, SCHEMA, ROUTE, commitment, decode, encode
from .external_fact_governance import GovernanceError
from .external_fact_page_budget import PageCapacityError, PageReadBudget
from .external_fact_reader import ReaderError, _FACTS, _HASH, _ID, _SOURCE, _fail, _identifier
from .field_authority import canonical_field
from .identity_contract import IdentityContractError, _exact_current_binding, schema_version
from .identity_models import IdentityRevision
from .query_ownership import QueryOwnershipError
from .service import business_facts

MAX_PAGE_BYTES = 1327104
_REQUIRED = {'source_id', 'query_id', 'verification_id'}
_ALLOWED = _REQUIRED | {'limit', 'cursor'}
_FACT_COLUMNS = ('id', 'variant_id', 'source_id', 'snapshot_id', 'version', 'facts_hash', 'observed_at')
_MANUAL_COLUMNS = ('id', 'variant_id', 'source_id', 'revision', 'field', 'action', 'base_fact_id', 'created_at')
_IDENTITY_COLUMNS = ('id', 'variant_id', 'target_id', 'revision', 'action', 'created_at')
_LIFECYCLE_COLUMNS = ('id', 'variant_id', 'revision', 'action', 'before_state', 'after_state', 'created_at')


@dataclass(frozen=True, slots=True, repr=False)
class PageOutcome:
    body: bytes
    actual_sql_rows: int
    charged_sql_rows: int

    def to_dict(self):
        return json.loads(self.body)


def _stamp(value):
    if type(value) is not datetime:
        _fail('reader_binding_invalid')
    return utc(value).isoformat(timespec='microseconds')


def _columns(row, names):
    return {name: _stamp(value) if type(value := getattr(row, name)) is datetime else value for name in names}


def _hash(budget, value):
    budget.json(value)
    return digest(value)


def _params(pairs):
    if type(pairs) not in (list, tuple):
        _fail('reader_query_invalid')
    params = {}
    for pair in pairs:
        if (type(pair) not in (list, tuple) or len(pair) != 2 or type(pair[0]) is not str
                or type(pair[1]) is not str or pair[0] not in _ALLOWED or pair[0] in params):
            _fail('reader_query_invalid')
        params[pair[0]] = pair[1]
    if (not _REQUIRED.issubset(params) or not _identifier(params['source_id'], _SOURCE)
            or not all(_identifier(params[name]) for name in ('query_id', 'verification_id'))):
        _fail('reader_query_invalid')
    raw = params.get('limit', '20')
    if re.fullmatch(r'(?:[1-9]|1[0-9]|20)', raw) is None:
        _fail('reader_query_invalid')
    return params, int(raw)


def _formal_descriptor(budget, run, verification, snapshot):
    return {
        'query': _columns(run, ('id', 'source_id', 'query_key', 'state', 'created_at')) |
                 {'query': _hash(budget, run.query), 'selection_filters': _hash(budget, run.selection_filters)},
        'verification': _columns(verification, ('id', 'query_id', 'source_id', 'query_key', 'status',
                                                'snapshot_id', 'verified_at')) |
                        {'parser_identity': _hash(budget, verification.parser_identity)},
        'snapshot': _snapshot_descriptor(budget, snapshot),
    }


def _snapshot_descriptor(budget, snapshot):
    return _columns(snapshot, ('id', 'source_id', 'query_key', 'raw_hash', 'parser_version',
                               'identity_contract_version', 'observed_at')) | {
        'parser_identity': _hash(budget, snapshot.parser_identity),
        'source_url': hashlib.sha256(snapshot.source_url.encode('utf-8')).hexdigest(),
        'body_hash': hashlib.sha256(snapshot.body.encode('utf-8')).hexdigest(),
    }


def _history(db, budget, model, where, columns, order, now):
    rows = budget.load(db, model, *where, columns=columns, maximum=4096, order=(order,))
    budget.history(model, rows)
    seen_ids, seen_numbers = set(), set()
    number = 'version' if model is FactVersion else 'revision'
    for row in rows:
        value = getattr(row, number)
        if (not _identifier(row.id) or row.id in seen_ids or type(value) is not int
                or value < 1 or value in seen_numbers):
            _fail('reader_governance_invalid')
        seen_ids.add(row.id)
        seen_numbers.add(value)
        if utc(getattr(row, 'observed_at' if model is FactVersion else 'created_at')) > now:
            _fail('reader_governance_invalid')
    return rows


def _endpoint(value):
    if (type(value) is not dict or value.keys() != {'id', 'identity', 'identity_status', 'identity_contract',
                                                 'facts', 'lifecycle'}
            or not _identifier(value['id']) or type(value['identity']) is not dict
            or type(value['identity_contract']) is not dict or type(value['identity_status']) is not str
            or not 1 <= len(value['identity_status']) <= 24 or not value['identity_status'].isprintable()
            or type(value['facts']) is not list or len(value['facts']) > 256):
        _fail('reader_identity_invalid')
    for fact in value['facts']:
        if (type(fact) is not dict or fact.keys() != {'id', 'source_id', 'version', 'snapshot_id'}
                or not all(_identifier(fact[name]) for name in ('id', 'snapshot_id'))
                or not _identifier(fact['source_id'], _SOURCE)
                or type(fact['version']) is not int or fact['version'] < 1):
            _fail('reader_identity_invalid')
    state = value['lifecycle']
    if (type(state) is not dict or state.keys() != {'revision', 'state'}
            or type(state['revision']) is not int or state['revision'] < 0
            or type(state['state']) is not str or state['state'] not in {'active', 'revoked'}):
        _fail('reader_identity_invalid')


def _stored_identity(db, budget, latest, variant_id):
    stored, = budget.load(db, IdentityRevision, IdentityRevision.id == latest.id,
                         columns=('binding', 'binding_hash'), limits={'binding': 64 * 1024})
    value = stored.binding
    if (type(value) is not dict or value.keys() != {'policy_version', 'source', 'target', 'target_resolution_revision'}
            or value['policy_version'] != 'identity-resolution@2'
            or type(value['target_resolution_revision']) is not int or value['target_resolution_revision'] < 0
            or not _identifier(stored.binding_hash, _HASH) or _hash(budget, value) != stored.binding_hash):
        _fail('reader_identity_invalid')
    _endpoint(value['source'])
    if value['source']['id'] != latest.variant_id or latest.variant_id != variant_id:
        _fail('reader_identity_invalid')
    if latest.action == 'clear':
        if latest.target_id is not None or value['target'] is not None or value['target_resolution_revision'] != 0:
            _fail('reader_identity_invalid')
    else:
        _endpoint(value['target'])
        if value['target']['id'] != latest.target_id:
            _fail('reader_identity_invalid')
    return {'binding_hash': stored.binding_hash, 'binding_digest': _hash(budget, value)}


def _candidate(reader, db, budget, policy, snapshot, index, member, now, references):
    variant_id = member['id']
    variant = budget.get(db, TireVariant, variant_id, limits={'identity': 64 * 1024})
    if variant is None:
        _fail('reader_identity_invalid')
    binding = _exact_current_binding(db, variant_id, budget=budget)
    parsed = VariantInput.model_validate({key: value for key, value in member.items() if key in VariantInput.model_fields})
    identity_key, status = parsed.identity_key(snapshot.source_id, snapshot.query_key, index)
    if (identity_key != binding.canonical_key or status != binding.identity_status
            or member.get('identity_key') != identity_key or member.get('identity_status') != status
            or member.get('identity_contract_version') != schema_version()
            or stable_json(parsed.identity()) != stable_json(binding.current_identity)
            or status not in {'complete', 'source_scoped'}):
        _fail('reader_identity_invalid')
    identity = {'variant_id': variant_id, 'contract_version': schema_version(),
                'status': status, 'values': binding.current_identity}
    identities = _history(db, budget, IdentityRevision, (IdentityRevision.variant_id == variant_id,),
                          _IDENTITY_COLUMNS, IdentityRevision.revision, now)
    for row in identities:
        if (row.action not in {'correct', 'merge', 'clear'}
                or (row.action == 'clear' and row.target_id is not None)
                or (row.action != 'clear' and (not _identifier(row.target_id) or row.target_id == variant_id))):
            _fail('reader_identity_invalid')
    stored = _stored_identity(db, budget, identities[-1], variant_id) if identities else None
    lifecycle = _history(db, budget, VariantLifecycleEvent,
                         (VariantLifecycleEvent.variant_id == variant_id,), _LIFECYCLE_COLUMNS,
                         VariantLifecycleEvent.revision, now)
    for row in lifecycle:
        if (row.action, row.before_state, row.after_state) not in {
                ('revoke', 'active', 'revoked'), ('restore', 'revoked', 'active')}:
            _fail('reader_governance_invalid')
    pending_hidden = (bool(identities and identities[-1].action in {'correct', 'merge'})
                      or bool(lifecycle and lifecycle[-1].action == 'revoke'))
    facts_history = _history(db, budget, FactVersion,
        (FactVersion.variant_id == variant_id, FactVersion.source_id == snapshot.source_id),
        _FACT_COLUMNS, FactVersion.version, now)
    for row in facts_history:
        if not _identifier(row.facts_hash, _HASH) or not _identifier(row.snapshot_id):
            _fail('reader_governance_invalid')
        if row.snapshot_id not in references:
            referenced = budget.load(db, Snapshot, Snapshot.id == row.snapshot_id, columns=('id', 'source_id'))
            if len(referenced) != 1 or referenced[0].source_id != snapshot.source_id:
                _fail('reader_binding_invalid')
            references[row.snapshot_id] = {'requested_id': row.snapshot_id, 'exists': True,
                                            'id': referenced[0].id, 'source_id': referenced[0].source_id}
    facts = member.get('facts')
    if type(facts) is not dict:
        _fail('reader_binding_invalid')
    expected_hash = _hash(budget, business_facts(facts))
    version = member.get('fact_version')
    if 'fact_version' in member and (type(version) is not int or version < 1):
        _fail('reader_binding_invalid')
    selected = [row for row in facts_history if row.facts_hash == expected_hash and
                (row.version == version if 'fact_version' in member else utc(row.observed_at) <= utc(snapshot.observed_at))]
    if not selected:
        _fail('reader_governance_invalid')
    selected_fact = budget.get(db, FactVersion, selected[-1].id, limits={'facts': 64 * 1024})
    if (_hash(budget, selected_fact.facts) != selected_fact.facts_hash
            or utc(selected_fact.observed_at) > utc(snapshot.observed_at)):
        _fail('reader_governance_invalid')
    current_id = facts_history[-1].id
    manual = _history(db, budget, ManualFactRevision,
        (ManualFactRevision.variant_id == variant_id, ManualFactRevision.source_id == snapshot.source_id),
        _MANUAL_COLUMNS, ManualFactRevision.revision, now)
    fact_ids = {row.id for row in facts_history}
    for row in manual:
        if (type(row.field) is not str or row.field not in FIELD_CATALOG
                or not 1 <= len(row.field) <= 80 or not row.field.isprintable()
                or row.action not in {'clear_override', 'manual_override', 'revoke'}
                or not _identifier(row.base_fact_id) or row.base_fact_id not in fact_ids):
            _fail('reader_governance_invalid')
    latest, suppressed, manual_state = set(), set(), []
    for row in reversed(manual):
        if row.field in latest:
            continue
        latest.add(row.field)
        state = ('cleared' if row.action == 'clear_override' else 'needs_review'
                 if row.base_fact_id != current_id else 'revoked' if row.action == 'revoke' else 'manual_override')
        field = canonical_field(row.field)
        manual_state.append({'field': row.field, 'canonical': field, 'status': state})
        if state != 'cleared' and field in _FACTS:
            suppressed.add(field)
    observation = {'source_id': snapshot.source_id, 'snapshot_id': snapshot.id,
                   'raw_hash': snapshot.raw_hash, 'parser_version': snapshot.parser_version}
    result = reader._project(policy, observation, identity, facts, suppressed, now,
                             budget=budget, allow_empty=True).to_dict()
    item = result['item']
    if result['status'] == 'projected':
        budget.item(item)
    hidden = pending_hidden or result['status'] == 'not_applicable'
    descriptor = {
        'variant': _columns(variant, ('id', 'identity_key', 'identity_status')) | {'identity': _hash(budget, variant.identity)},
        'binding': {column.key: _stamp(value) if type(value := getattr(binding, column.key)) is datetime else value
                    for column in binding.__table__.columns},
        'identity_history': [_columns(row, _IDENTITY_COLUMNS) for row in identities], 'stored_identity': stored,
        'lifecycle_history': [_columns(row, _LIFECYCLE_COLUMNS) for row in lifecycle],
        'fact_history': [_columns(row, _FACT_COLUMNS) for row in facts_history],
        'selected_fact': {'id': selected_fact.id, 'facts_digest': _hash(budget, selected_fact.facts)},
        'current_fact_id': current_id, 'manual_history': [_columns(row, _MANUAL_COLUMNS) for row in manual],
        'manual_state': sorted(manual_state, key=lambda value: value['field']),
        'outcome': 'hidden_governance' if pending_hidden else result['reason'],
        'projected_digest': _hash(budget, item),
    }
    return None if hidden else item, descriptor


def read_page(reader, credential, *, query_pairs):
    budget, verified = PageReadBudget(), False
    try:
        with reader._store._reader_transaction(budget=budget) as (db, now):
            key = reader._authenticate(db, credential, now, budget=budget, return_key=True)
            params, limit = _params(query_pairs)
            source, query, verification_id = (params[name] for name in ('source_id', 'query_id', 'verification_id'))
            owner = commitment(key.cursor_secret, 'external-fact-page-owner@1', key.owner_user_id)
            token = None
            if 'cursor' in params:
                try:
                    token = decode(params['cursor'], secret=key.cursor_secret, key_id=key.id, owner=owner,
                                   source_id=source, query_id=query, verification_id=verification_id, limit=limit, now=now)
                except CursorError as error:
                    _fail('reader_cursor_expired' if error.code == 'expired' else 'reader_cursor_invalid')
                verified = True
            receipt = reader._owned(db, query, key.owner_user_id, budget=budget)
            if utc(receipt.captured_at) > now:
                _fail('reader_binding_invalid')
            cache = {'snapshots': {}, 'body_bytes': 0}
            run, verification, snapshot = reader._formal(db, source, query, verification_id, now, cache, budget=budget)
            if snapshot.identity_contract_version != schema_version():
                _fail('reader_identity_invalid')
            grant = reader._routing.get(source)
            if grant is None:
                _fail('reader_route_unconfigured')
            grants, current = reader._store._reader_load(db, grant, budget=budget)
            if current.policy is None or current.state != 'approved' or current.policy.latest.source_id != source:
                _fail('reader_not_available')
            formal = [_formal_descriptor(budget, run, verification, snapshot)]
            for binding in grants[-1].binding_receipts:
                bound_run, bound_verification, bound_snapshot = reader._formal(db, source, binding['query_id'],
                    binding['verification_id'], now, cache, budget=budget)
                if (bound_snapshot.id != binding['snapshot_id'] or bound_snapshot.raw_hash != binding['raw_hash']
                        or bound_snapshot.parser_version != binding['parser_version']
                        or bound_run.query_key != binding['query_key']
                        or _hash(budget, bound_snapshot.parser_identity) != binding['parser_identity_digest']
                        and bound_snapshot.parser_identity is not None
                        or bound_snapshot.parser_identity is None and binding['parser_identity_digest'] is not None):
                    _fail('reader_binding_invalid')
                formal.append(_formal_descriptor(budget, bound_run, bound_verification, bound_snapshot))
            members, seen = [], set()
            for index, member in enumerate(snapshot.parsed_variants):
                if type(member) is not dict or not _identifier(member.get('id')) or member['id'] in seen:
                    _fail('reader_binding_invalid')
                seen.add(member['id'])
                members.append((member['id'], index, member))
            members.sort(key=lambda row: row[0])
            visible, candidates, references = [], [], {}
            for variant_id, index, member in members:
                item, descriptor = _candidate(reader, db, budget, current.policy, snapshot, index, member, now, references)
                candidates.append({'id': variant_id, 'index': index, 'descriptor': descriptor})
                if item is not None:
                    visible.append((variant_id, item))
            owner_audit = budget.get(db, AuditEvent, receipt.audit_event_id, limits={'detail': 16 * 1024})
            ledger = []
            for revision in grants:
                audit = budget.get(db, AuditEvent, revision.audit_event_id, limits={'detail': 16 * 1024})
                ledger.append(_columns(revision, ('id', 'revision', 'record_digest', 'event_digest', 'evidence_sha256')) |
                    {'record': _hash(budget, revision.record), 'binding_receipts': _hash(budget, revision.binding_receipts),
                     'audit': {'id': audit.id, 'detail': _hash(budget, audit.detail), 'created': _stamp(audit.created_at)}})
            descriptor = {
                'schema': 'external-fact-page-context@1',
                'budgets': {name: getattr(PageReadBudget, name) for name in vars(PageReadBudget) if name.startswith('MAX_')},
                'routing': dict(sorted(reader._routing.items())),
                'key': _columns(key, ('id', 'owner_user_id', 'scopes', 'created_at', 'expires_at', 'fingerprint')),
                'user_exists': True, 'owner': _columns(receipt, tuple(column.key for column in receipt.__table__.columns)),
                'owner_audit': {'id': owner_audit.id, 'detail': _hash(budget, owner_audit.detail), 'created': _stamp(owner_audit.created_at)},
                'formal': formal, 'ledger': ledger, 'head': current.head,
                'candidates': candidates, 'references': [references[name] for name in sorted(references)],
            }
            universe = [[variant_id, index] for variant_id, index, _ in members]
            window_input = {'source_id': source, 'query_id': query, 'verification_id': verification_id,
                'selected_snapshot_descriptor': _snapshot_descriptor(budget, snapshot), 'U': universe,
                'selected_parsed_digest': _hash(budget, snapshot.parsed_variants)}
            budget.json(window_input)
            window = commitment(key.cursor_secret, 'external-fact-page-window@1', window_input)
            context_input = {'window': window, 'closure_descriptor': descriptor}
            budget.json(context_input)
            context = commitment(key.cursor_secret, 'external-fact-page-context@1', context_input)
            start = 0
            if token is not None:
                ids = [variant_id for variant_id, _ in visible]
                if token['window'] != window or token['context'] != context or token['after'] not in ids:
                    _fail('reader_window_changed')
                start = ids.index(token['after']) + 1
                if start >= len(visible):
                    _fail('reader_window_changed')
            selected = visible[start:start + limit + 1]
            if not selected:
                _fail('reader_not_available')
            next_cursor = None
            if len(selected) > limit:
                issued = token['issued'] if token is not None else int(now.timestamp())
                expires = token['expires'] if token is not None else issued + 900
                next_cursor = encode({'schema': SCHEMA, 'key_id': key.id, 'owner': owner, 'route': ROUTE,
                    'source_id': source, 'query_id': query, 'verification_id': verification_id, 'limit': limit,
                    'issued': issued, 'expires': expires, 'window': window, 'context': context,
                    'after': selected[limit - 1][0]}, secret=key.cursor_secret)
            page = {'schema': 'external-tire-fact-page@1', 'items': [item for _, item in selected[:limit]],
                    'next_cursor': next_cursor, 'limit': limit, 'data_state': 'local_snapshot',
                    'source_refresh_performed': False}
            budget.json(page, maximum_depth=6, maximum_nodes=5472)
            body = stable_json(page).encode('utf-8')
            if len(body) > MAX_PAGE_BYTES:
                raise PageCapacityError('page_response_capacity')
            outcome = PageOutcome(body, budget.actual_rows, budget.charged_rows)
        return outcome
    except ReaderError as error:
        if error.code in {'reader_unauthorized', 'reader_scope_required', 'reader_query_invalid',
                          'reader_cursor_invalid', 'reader_cursor_expired', 'reader_window_changed',
                          'reader_backend_unsupported', 'reader_schema_required', 'reader_clock_invalid'}:
            raise
        raise ReaderError('reader_window_changed' if verified else 'reader_not_available') from None
    except DBAPIError:
        raise ReaderError('reader_storage_unavailable') from None
    except StatementError as error:
        if isinstance(error.orig, (ValueError, TypeError, UnicodeError)):
            raise ReaderError('reader_window_changed' if verified else 'reader_not_available') from None
        raise
    except (PageCapacityError, GovernanceError, IdentityContractError, QueryOwnershipError,
            ValueError, OverflowError, UnicodeError):
        raise ReaderError('reader_window_changed' if verified else 'reader_not_available') from None

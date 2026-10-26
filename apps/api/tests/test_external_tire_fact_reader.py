"""Synthetic private SQLite: real service adoption, key issuance and grant store.

No main, Database.initialize, HTTP client, Parser, network or normal database.
The controlled synchronous registry does not exercise the raw capture journal.
Direct FastAPI endpoint calls exercise its real mutation dependency explicitly.
Corruption vectors use Core SQL on their own private fixture only.
"""
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import threading
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import FastAPI
from sqlalchemy import create_engine, event, func, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tire_api.auth import hash_password
from tire_api.db import (AlertRule, AlertRuleRevision, AuditEvent, Base, ChangeEvent,
    FactVersion, FallbackConsent, ManualFactRevision, MonitorJob, QueryRun, Snapshot,
    SourceQuarantine, TireVariant, User, UserSession,
    VariantLifecycleEvent, Verification, utc, utcnow)
from tire_api.domain import LiveQueryRequest
from tire_api.external_api import KeyCreate, register_external_api_routes, revoke_account_keys
from tire_api.external_api_models import ApiKey, ApiKeyMinute, ApiKeyOperation, ApiKeyRevocation
from tire_api.external_fact_governance import GovernanceError, GovernanceStore
from tire_api.external_fact_models import (ExternalFactGrantRevision as Grant,
    ExternalFactLicenseEvidence as License, install_schema as install_grants)
from tire_api.external_fact_reader import OwnedFactReader, ReaderError
from tire_api.fitment_relation_models import FitmentRelation, FitmentRelationRevision
from tire_api.identity_contract_models import VariantIdentityBinding, VariantIdentityMigrationApplication
from tire_api.identity_models import IdentityRevision
from tire_api.interest_applicability_models import TireCurationApplicabilityEvent
from tire_api.interest_catalog_models import TireCatalogRevision
from tire_api.interest_models import Interest, InterestEvent, InterestRevision
from tire_api.query_owner_models import QueryRunOwnerReceipt, install_schema as install_owners
from tire_api.query_ownership import capture_query_actor
from tire_api.service import QueryService
from tire_api.source_page_models import SourcePageChange, SourcePageNotification
from tire_api.source_page_url_models import SourcePageUrlMove, SourcePageUrlMoveNotification
from tire_api.source_setting_models import SourceSettingRevision
from tire_api.vehicles import VehicleManufacturer, VehicleModel
from tire_api.webhook_delivery import seal

TEST_ROOT = Path(__file__).resolve().parents[3] / '.artifacts/fact-reader-verification-20261021/t'
PASSWORD = 'Synthetic-reader-password-2026'
SOURCE = 'synthetic-reader-source'
QUERY = {'model': 'Synthetic Reader Tire'}
TERMS = b'Synthetic review statement; not a real redistribution permission.\n'
REQUIRED = [
    'evidence.source_id', 'evidence.snapshot_id', 'evidence.raw_hash', 'evidence.parser_version',
    'identity.variant_id', 'identity.identity_status', 'identity.identity_contract_version',
    'identity.brand', 'identity.model', 'identity.region', 'identity.manufacturer_product_code',
    'identity.product_code_type', 'identity.size', 'identity.load_index', 'identity.speed_rating',
    'identity.xl', 'identity.hl', 'identity.run_flat', 'identity.oe_mark',
    'identity.acoustic_technology', 'identity.gtin', 'identity.technology_features', 'identity.eprel_id',
]
FACT_FIELDS = ['facts.utqg_treadwear', 'facts.weight_kg', 'facts.eu_wet_grip']
VARIANT = {
    'brand': 'Synthetic Reader Brand', 'model': 'Synthetic Reader Tire',
    'manufacturer_product_code': 'SYN-READ-001', 'region': 'US', 'size': '265/40ZR20',
    'load_index': '104', 'speed_rating': 'Y', 'xl': True, 'hl': False, 'oe_mark': '',
    'acoustic_technology': '', 'run_flat': False, 'source_variant_name': 'synthetic only',
    'facts': {'product_code_type': 'MSPN', 'utqg_treadwear': 0, 'weight_kg': None,
              'eu_wet_grip': 'A', 'evidence_spans': {'utqg_treadwear': '/synthetic/treadwear',
                 'weight_kg': '/synthetic/weight', 'eu_wet_grip': '/synthetic/wet'}},
}


def independent_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def synchronous(coroutine):
    try:
        coroutine.send(None)
    except StopIteration as complete:
        return complete.value
    finally:
        coroutine.close()
    raise AssertionError('controlled_coroutine_suspended')


class Registry:
    supports_parser_deployments = False

    def __init__(self):
        self.calls = 0
        self.result = self.success()

    def sources(self):
        return [{'id': SOURCE, 'name': 'Synthetic reader fixture', 'region': 'US',
                 'source_class': 'test_fixture', 'status': 'ready'}]

    @staticmethod
    def success(*, body='Synthetic accepted reader fixture', variants=None):
        return {'status': 'ok', 'url': 'https://fixture.example/tires/product', 'body': body,
                'content_type': 'text/html', 'parser_version': 'fixture@1', 'parser_identity': None,
                'etag': '"fixture-etag"', 'variants': deepcopy(variants if variants is not None else [VARIANT])}

    async def fetch(self, source_id, query, cached=None, *, on_observation=None):
        if source_id != SOURCE or query.get('model') != QUERY['model']:
            raise AssertionError('unexpected_controlled_fetch')
        self.calls += 1
        return deepcopy(self.result)


class OwnedFactReaderTests(unittest.TestCase):
    def setUp(self):
        self.directory = TEST_ROOT / uuid4().hex
        self.directory.mkdir(parents=True, exist_ok=False)
        self.addCleanup(lambda: shutil.rmtree(self.directory) if self.directory.exists() else None)
        self.engine = create_engine('sqlite:///' + (self.directory / 'reader.sqlite').as_posix(),
            connect_args={'timeout': 5, 'check_same_thread': False}, poolclass=NullPool)

        @event.listens_for(self.engine, 'connect')
        def configure(connection, _record):
            connection.execute('PRAGMA foreign_keys=ON').close()
            connection.execute('PRAGMA busy_timeout=5000').close()

        self.addCleanup(self.engine.dispose)
        # Explicit service/reader tables plus FK closure. No broad metadata.create_all.
        models = (User, UserSession, QueryRun, Snapshot, Verification, AuditEvent,
            SourceQuarantine, SourcePageChange, SourcePageNotification,
            SourcePageUrlMove, SourcePageUrlMoveNotification,
            TireVariant, FactVersion, ChangeEvent, SourceSettingRevision,
            VariantIdentityBinding, VariantIdentityMigrationApplication, IdentityRevision,
            VariantLifecycleEvent, ManualFactRevision, MonitorJob, AlertRule, AlertRuleRevision,
            Interest, InterestRevision, InterestEvent, TireCatalogRevision,
            TireCurationApplicabilityEvent, FitmentRelationRevision, FitmentRelation,
            VehicleModel, VehicleManufacturer, ApiKey, ApiKeyRevocation, ApiKeyOperation,
            ApiKeyMinute, FallbackConsent)
        Base.metadata.create_all(self.engine, tables=[model.__table__ for model in models])
        with self.engine.begin() as connection:
            install_grants(connection)
            install_owners(connection)
            connection.execute(text('CREATE TABLE tire_schema_versions(version VARCHAR(80) PRIMARY KEY)'))
            for version in ('025_external_fact_governance', '026_query_ownership'):
                connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:v)'), {'v': version})
        self.now = datetime.now(UTC) + timedelta(seconds=1)
        password_hash = hash_password(PASSWORD)
        with Session(self.engine) as db:
            db.add_all([User(id=owner, username=owner.replace('-', '_'), display_name='Synthetic reader',
                password_hash=password_hash, is_admin=owner == 'admin')
                for owner in ('owner-a', 'owner-b', 'admin')])
            db.add_all([UserSession(id=session, user_id=owner,
                expires_at=self.now + timedelta(days=30)) for session, owner in (
                    ('session-a', 'owner-a'), ('session-b', 'owner-b'),
                    ('session-admin', 'admin'), ('session-anonymous', None))])
            db.commit()
        self.registry = Registry()
        self.app = FastAPI()
        register_external_api_routes(self.app)
        self.create_route = next(route for route in self.app.routes
            if getattr(route, 'path', None) == '/v1/api-keys' and 'POST' in getattr(route, 'methods', ()))
        self.mutation = next(dependency.call for dependency in self.create_route.dependant.dependencies
            if dependency.call.__name__ == 'mutation')
        self.issued = self.issue(['facts:read'])
        self.selected = self.adopt()
        self.store = GovernanceStore(self.engine, clock=lambda: self.now)
        self.actor = self.store.authenticate('admin', PASSWORD)
        self.grant_id = 'synthetic-reader-grant'
        self.approve(self.selected)
        self.reader = self.new_reader()
        self.credential = self.reader.capture_credential(['Bearer ' + self.issued['token']])

    def new_reader(self, *, routing=None, clock=None):
        return OwnedFactReader(self.engine, {SOURCE: self.grant_id} if routing is None else routing,
            self.registry, clock=clock or (lambda: self.now))

    def issue(self, scopes, *, session_id='session-a'):
        request = SimpleNamespace(state=SimpleNamespace(session_id=session_id), method='POST',
                                  url=SimpleNamespace(path='/v1/api-keys'))
        with Session(self.engine) as db:
            owner = self.mutation(request, db)
            return self.create_route.endpoint(payload=KeyCreate(name='Synthetic reader key', scopes=scopes,
                expires_in_days=30, acknowledged=True), request=request, owner=owner,
                idempotency_key=str(uuid4()), db=db)

    def adopt(self, *, session='session-a', result=None, anonymous=False, query=None):
        if result is not None:
            self.registry.result = deepcopy(result)
        with Session(self.engine) as db:
            actor = None if anonymous else capture_query_actor(db, session)
            response = synchronous(QueryService(db, self.registry).execute(SOURCE,
                LiveQueryRequest(query=QUERY if query is None else query, fallback_policy='ask'), session, owner_actor=actor))
            self.assertIn(response['data_state'], ('live', 'live_verified_304'))
            run = db.get(QueryRun, response['query_id'])
            verification = db.scalar(select(Verification).where(Verification.query_id == run.id))
            snapshot = db.get(Snapshot, verification.snapshot_id)
            selected = {'source_id': SOURCE, 'query_id': run.id, 'verification_id': verification.id,
                'snapshot_id': snapshot.id, 'raw_hash': snapshot.raw_hash,
                'parser_version': snapshot.parser_version, 'variant_id': snapshot.parsed_variants[0]['id'],
                'observed_at': utc(snapshot.observed_at), 'verified_at': utc(verification.verified_at)}
        self.now = max(self.now, datetime.now(UTC) + timedelta(seconds=1))
        return selected

    def submit(self, request):
        terms = TERMS if request['action'] == 'approve' else None
        preview = self.store.preview(self.actor, request, terms=terms)
        return self.store.append(self.actor, request, terms=terms,
            expected_revision=preview['expected_revision'], expected_head=preview['expected_head'],
            expected_preview_fingerprint=preview['fingerprint'], idempotency_key=str(uuid4()))

    def approve(self, selected, *, grant=None, fields=None):
        return self.submit({'schema': 'external-fact-governance-request@1', 'action': 'approve',
            'grant_id': grant or self.grant_id, 'reason': 'Synthetic reviewed fixture only',
            'source_id': SOURCE, 'coverage': {'observations': [{key: selected[key] for key in (
                'snapshot_id', 'raw_hash', 'parser_version')}], 'field_keys': REQUIRED + (FACT_FIELDS if fields is None else fields)},
            'rights': {'holder': 'Synthetic holder', 'basis': 'Synthetic fixture only'},
            'validity': {'not_before': (self.now - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                         'not_after': (self.now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')},
            'license_reference': 'https://fixture.example/license', 'rights_reviewed': True})

    def stop(self, action='withdraw', *, grant=None):
        return self.submit({'schema': 'external-fact-governance-request@1', 'action': action,
            'grant_id': grant or self.grant_id, 'reason': 'Stop synthetic fixture permission'})

    def read(self, selected=None, *, reader=None, credential=None):
        target = self.selected if selected is None else selected
        reader = self.reader if reader is None else reader
        credential = self.credential if credential is None else credential
        return reader.read_one(credential, **{key: target[key]
            for key in ('source_id', 'query_id', 'verification_id', 'variant_id')})

    def projected(self, selected=None, **kwargs):
        outcome = self.read(selected, **kwargs)
        value = outcome.to_dict()
        self.assertEqual(set(value), {'status', 'reason', 'item'})
        self.assertEqual(value['status'], 'projected')
        self.assertEqual(value['reason'], 'projected')
        item = value['item']
        self.assertEqual(set(item), {'schema', 'data_state', 'source_refresh_performed',
            'observation', 'identity', 'facts', 'conflicted_fields'})
        self.assertEqual(item['data_state'], 'local_snapshot')
        self.assertIs(item['source_refresh_performed'], False)
        self.assertNotIn('verification_id', json.dumps(value))
        for marker in ('Synthetic reviewed fixture', 'Synthetic-reader-password', self.issued['token']):
            self.assertNotIn(marker, json.dumps(value))
        return item

    def code(self, expected, call):
        with self.assertRaises(ReaderError) as caught:
            call()
        self.assertEqual(caught.exception.code, expected)
        self.assertEqual(str(caught.exception), expected)

    def mutate(self, model, identifier, **changes):
        with self.engine.begin() as connection:
            connection.execute(update(model).where(model.id == identifier).values(**changes))

    def saved(self, model, identifier, *columns):
        with Session(self.engine) as db:
            row = db.get(model, identifier)
            return {column: deepcopy(getattr(row, column)) for column in columns}

    def manual(self, field, action, *, base=None):
        with Session(self.engine) as db:
            fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == self.selected['variant_id'],
                FactVersion.source_id == SOURCE).order_by(FactVersion.version.desc()).limit(1))
            revision = (db.scalar(select(func.max(ManualFactRevision.revision)).where(
                ManualFactRevision.variant_id == fact.variant_id, ManualFactRevision.source_id == SOURCE)) or 0) + 1
            db.add(ManualFactRevision(id=uuid4().hex, variant_id=fact.variant_id, source_id=SOURCE,
                base_fact_id=base or fact.id, revision=revision, field=field, action=action,
                operator_session_id='session-admin', operator='Synthetic private operator',
                reason='SENTINEL_PRIVATE_MANUAL_REASON', before={'present': True, 'value': 0},
                after={'present': action != 'revoke', 'value': 4777},
                source_before={'present': True, 'value': 0}, evidence=[], created_at=self.now))
            db.commit()

    def test_01_real_service_and_real_facts_only_all_three_key_issuance(self):
        item = self.projected()
        self.assertEqual(item['facts'], {'utqg_treadwear': 0, 'weight_kg': None, 'eu_wet_grip': 'A'})
        self.assertEqual(item['identity']['status'], 'complete')
        self.assertIs(item['identity']['values']['run_flat'], False)
        all_three = self.issue(['webhooks:read', 'facts:read', 'sources:read'])
        self.assertEqual(all_three['key']['scopes'], ['facts:read', 'sources:read', 'webhooks:read'])
        self.projected(credential=self.reader.capture_credential(['Bearer ' + all_three['token']]))
        with Session(self.engine) as db:
            row = db.get(ApiKey, all_three['key']['id'])
            self.assertEqual(row.bearer_sha256, hashlib.sha256(all_three['token'].encode('ascii')).hexdigest())
            self.assertEqual(db.scalar(select(func.count()).select_from(ApiKeyOperation)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(InterestEvent)), 2)
            self.assertEqual(db.scalar(select(func.count()).select_from(QueryRunOwnerReceipt)), 1)

    def test_02_current_source_scoped_keeps_unknowns_false_zero(self):
        variant = deepcopy(VARIANT)
        variant['manufacturer_product_code'] = None
        variant['facts'].pop('product_code_type')
        selected = self.adopt(result=Registry.success(body='Synthetic source scoped', variants=[variant]),
            query={**QUERY, 'size': '265/40R20'})
        self.approve(selected, grant='source-scoped-grant')
        reader = self.new_reader(routing={SOURCE: 'source-scoped-grant'})
        credential = reader.capture_credential(['Bearer ' + self.issued['token']])
        item = self.projected(selected, reader=reader, credential=credential)
        self.assertEqual(item['identity']['status'], 'source_scoped')
        self.assertIsNone(item['identity']['values']['manufacturer_product_code'])
        self.assertIsNone(item['identity']['values']['product_code_type'])
        self.assertIs(item['identity']['values']['hl'], False)
        self.assertEqual(item['facts']['utqg_treadwear'], 0)
        self.assertIsNone(item['facts']['weight_kg'])

    def test_03_approved_old_anchor_and_new_owned_verification_share_snapshot(self):
        other = self.adopt(session='session-b')
        self.assertEqual(other['snapshot_id'], self.selected['snapshot_id'])
        self.assertNotEqual(other['verification_id'], self.selected['verification_id'])
        issued = self.issue(['facts:read'], session_id='session-b')
        credential = self.reader.capture_credential(['Bearer ' + issued['token']])
        self.projected(other, credential=credential)
        self.mutate(Verification, other['verification_id'], status='unavailable')
        self.code('reader_binding_invalid', lambda: self.read(other, credential=credential))
        self.projected()  # Other owner's newer bad V must not replace the exact owned V.

    def test_04_real_304_reuses_snapshot_and_new_owned_query(self):
        selected = self.adopt(result={'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
            'etag': '"fixture-etag"', 'parser_identity': None})
        self.assertEqual(selected['snapshot_id'], self.selected['snapshot_id'])
        self.assertEqual(selected['observed_at'], self.selected['observed_at'])
        self.assertGreaterEqual(selected['verified_at'], self.selected['verified_at'])
        self.assertNotEqual(selected['query_id'], self.selected['query_id'])
        self.projected(selected)

    def test_05_new_snapshot_may_reuse_older_fact_version(self):
        selected = self.adopt(result=Registry.success(body='Synthetic changed page same business facts'))
        self.assertNotEqual(selected['snapshot_id'], self.selected['snapshot_id'])
        self.approve(selected, grant='new-page-grant')
        reader = self.new_reader(routing={SOURCE: 'new-page-grant'})
        self.projected(selected, reader=reader,
            credential=reader.capture_credential(['Bearer ' + self.issued['token']]))
        with Session(self.engine) as db:
            fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == selected['variant_id']))
            self.assertEqual(fact.snapshot_id, self.selected['snapshot_id'])
            self.assertNotEqual(fact.snapshot_id, selected['snapshot_id'])

    def test_06_credential_shape_issuer_and_bearer_binding(self):
        bad_headers = ([], ['Bearer nope'], ['Bearer ' + self.issued['token']] * 2,
            ['bearer ' + self.issued['token']], ['Bearer ' + self.issued['token'] + '\n'])
        for headers in bad_headers:
            with self.subTest(kind='headers'):
                self.code('reader_unauthorized', lambda: self.reader.capture_credential(headers))
        for value in ({'owner': 'owner-a', 'scopes': ['facts:read']}, SimpleNamespace(owner='owner-a')):
            with self.subTest(kind='untrusted_context'):
                self.code('reader_unauthorized', lambda: self.read(credential=value))
        other_reader = self.new_reader()
        self.code('reader_unauthorized', lambda: self.read(reader=other_reader))
        token = self.issued['token'][:-1] + ('0' if self.issued['token'][-1] != '0' else '1')
        credential = self.reader.capture_credential(['Bearer ' + token])
        self.code('reader_unauthorized', lambda: self.read(credential=credential))
        self.assertNotIn(self.issued['token'], repr(self.credential))

    def test_07_old_scopes_do_not_upgrade_and_bad_key_seal_fails(self):
        for scopes in (['sources:read'], ['webhooks:read']):
            with self.subTest(kind='old_scope'):
                issued = self.issue(scopes)
                credential = self.reader.capture_credential(['Bearer ' + issued['token']])
                self.code('reader_scope_required', lambda: self.read(credential=credential))
        token_id = uuid4().hex
        token = 'ti_' + token_id + '.' + 'a' * 64
        with Session(self.engine) as db:
            db.add(ApiKey(id=token_id, owner_user_id='owner-a', name='Synthetic bad seal', scopes=['facts:read'],
                bearer_sha256=hashlib.sha256(token.encode('ascii')).hexdigest(), cursor_secret='b' * 64,
                created_at=self.now, expires_at=self.now + timedelta(days=1), fingerprint='0' * 64))
            db.commit()
        self.code('reader_unauthorized', lambda: self.read(
            credential=self.reader.capture_credential(['Bearer ' + token])))

    def test_08_microsecond_expiry_and_clock_validation(self):
        with Session(self.engine) as db:
            expiry = utc(db.get(ApiKey, self.issued['key']['id']).expires_at)
        self.now = expiry - timedelta(microseconds=1)
        # Key itself passes just before expiry; grant is intentionally expired then.
        self.code('reader_not_available', self.read)
        for offset in (0, 1):
            with self.subTest(kind='expiry'):
                self.now = expiry + timedelta(microseconds=offset)
                self.code('reader_unauthorized', self.read)
        reader = self.new_reader(clock=lambda: datetime(2026, 10, 21))
        credential = reader.capture_credential(['Bearer ' + self.issued['token']])
        self.code('reader_clock_invalid', lambda: self.read(reader=reader, credential=credential))

    def test_09_capture_then_real_revoke_or_delete_same_name_cannot_inherit(self):
        with Session(self.engine) as db:
            QueryService(db, None).lock_ingestion()
            revoke_account_keys(db, 'owner-a', 'password_reset')
            db.commit()
        self.code('reader_unauthorized', self.read)
        issued = self.issue(['facts:read'], session_id='session-b')
        credential = self.reader.capture_credential(['Bearer ' + issued['token']])
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM users WHERE id='owner-b'"))
        self.code('reader_unauthorized', lambda: self.read(credential=credential))
        with Session(self.engine) as db:
            db.add(User(id='new-owner-b', username='owner_b', display_name='Synthetic same name',
                password_hash=hash_password(PASSWORD), is_admin=False))
            db.commit()
        self.code('reader_unauthorized', lambda: self.read(credential=credential))

    def test_10_routing_is_copied_explicit_and_never_uses_another_grant(self):
        routing = {SOURCE: self.grant_id}
        reader = self.new_reader(routing=routing)
        credential = reader.capture_credential(['Bearer ' + self.issued['token']])
        routing[SOURCE] = 'nonexistent-grant'
        self.projected(reader=reader, credential=credential)
        missing = self.new_reader(routing={})
        self.code('reader_route_unconfigured', lambda: self.read(reader=missing,
            credential=missing.capture_credential(['Bearer ' + self.issued['token']])))
        self.approve(self.selected, grant='another-approved-grant')
        self.stop()
        self.code('reader_not_available', self.read)

    def test_11_current_policy_field_restriction_expiry_and_broken_chain(self):
        self.approve(self.selected, fields=['facts.weight_kg'])
        self.assertEqual(self.projected()['facts'], {'weight_kg': None})
        self.now += timedelta(days=2)
        self.code('reader_not_available', self.read)
        self.now -= timedelta(days=2)
        with Session(self.engine) as db:
            row = db.scalar(select(Grant).where(Grant.grant_id == self.grant_id)
                .order_by(Grant.revision.desc()).limit(1))
            copied = {column.name: deepcopy(getattr(row, column.name)) for column in Grant.__table__.columns}
        copied.update(id=uuid4().hex, revision=3, previous_digest='0' * 64,
            audit_event_id=uuid4().hex, idempotency_key=str(uuid4()))
        with self.engine.begin() as connection:
            connection.execute(AuditEvent.__table__.insert(), {'id': copied['audit_event_id'],
                'session_id': 'synthetic-fixture', 'action': 'synthetic_broken_chain', 'detail': {}, 'created_at': self.now})
            connection.execute(Grant.__table__.insert(), copied)
        self.code('reader_policy_invalid', self.read)

    def test_12_original_approval_anchor_cannot_be_replaced_by_latest(self):
        newer = self.adopt()
        self.projected(newer)
        self.mutate(Verification, self.selected['verification_id'], status='unavailable')
        self.code('reader_binding_invalid', lambda: self.read(newer))

    def test_13_exact_owner_receipt_and_selected_verification(self):
        other = self.adopt(session='session-b')
        self.code('reader_not_available', lambda: self.read(other))
        anonymous = self.adopt(session='session-anonymous', anonymous=True)
        self.code('reader_not_available', lambda: self.read(anonymous))
        mixed = {**self.selected, 'verification_id': other['verification_id']}
        self.code('reader_binding_invalid', lambda: self.read(mixed))
        self.mutate(QueryRun, self.selected['query_id'], query={'model': 'SENTINEL_PRIVATE_QUERY'})
        self.code('reader_binding_invalid', self.read)

    def test_14_formal_query_verification_and_snapshot_corruption(self):
        changes = (
            (QueryRun, self.selected['query_id'], 'state', 'local_snapshot'),
            (QueryRun, self.selected['query_id'], 'source_id', 'foreign-source'),
            (Verification, self.selected['verification_id'], 'query_key', '0' * 64),
            (Verification, self.selected['verification_id'], 'parser_identity', {'unexpected': 'private'}),
            (Snapshot, self.selected['snapshot_id'], 'body', 'SENTINEL_CORRUPT_BODY'),
            (Snapshot, self.selected['snapshot_id'], 'parser_version', 'foreign@1'),
        )
        for model, identifier, field, invalid in changes:
            before = self.saved(model, identifier, field)
            with self.subTest(kind='formal_binding'):
                self.mutate(model, identifier, **{field: invalid})
                with self.assertRaises(ReaderError) as caught:
                    self.read()
                self.assertIn(caught.exception.code, ('reader_binding_invalid', 'reader_not_available'))
            self.mutate(model, identifier, **before)
        self.projected()

    def test_15_member_identity_fact_integrity_and_no_cross_id_substitution(self):
        saved = self.saved(Snapshot, self.selected['snapshot_id'], 'parsed_variants', 'identity_contract_version')
        original = saved['parsed_variants']
        variants = ([], original + deepcopy(original),
            [{**deepcopy(original[0]), 'id': 'foreign-variant'}],
            [{**deepcopy(original[0]), 'region': 'CN'}],
            [{**deepcopy(original[0]), 'identity_key': '0' * 64}],
            [{**deepcopy(original[0]), 'fact_version': 999}])
        for members in variants:
            with self.subTest(kind='member'):
                self.mutate(Snapshot, self.selected['snapshot_id'], parsed_variants=members)
                with self.assertRaises(ReaderError) as caught:
                    self.read()
                self.assertIn(caught.exception.code, ('reader_binding_invalid', 'reader_identity_invalid',
                    'reader_governance_invalid', 'reader_not_available'))
        self.mutate(Snapshot, self.selected['snapshot_id'], **saved)
        with Session(self.engine) as db:
            fact_id = db.scalar(select(FactVersion.id).where(FactVersion.variant_id == self.selected['variant_id']))
        self.mutate(FactVersion, fact_id, facts_hash='0' * 64)
        self.code('reader_governance_invalid', self.read)

    def test_16_lifecycle_and_identity_current_governance(self):
        with Session(self.engine) as db:
            binding_id = db.scalar(select(VariantIdentityBinding.id).where(
                VariantIdentityBinding.variant_id == self.selected['variant_id']))
        original = self.saved(VariantIdentityBinding, binding_id, 'fingerprint')
        self.mutate(VariantIdentityBinding, binding_id, fingerprint='0' * 64)
        self.code('reader_identity_invalid', self.read)
        self.mutate(VariantIdentityBinding, binding_id, **original)
        with Session(self.engine) as db:
            db.add(VariantLifecycleEvent(id=uuid4().hex, variant_id=self.selected['variant_id'], revision=1,
                action='revoke', before_state='active', after_state='revoked', operator_session_id='session-admin',
                operator='Synthetic', reason='SENTINEL_PRIVATE_LIFECYCLE', evidence=[], created_at=self.now))
            db.commit()
        self.code('reader_governance_invalid', self.read)
        with Session(self.engine) as db:
            db.add(VariantLifecycleEvent(id=uuid4().hex, variant_id=self.selected['variant_id'], revision=2,
                action='restore', before_state='revoked', after_state='active', operator_session_id='session-admin',
                operator='Synthetic', reason='Synthetic restore', evidence=[], created_at=self.now))
            db.commit()
        self.projected()
        target_variant = deepcopy(VARIANT)
        target_variant['manufacturer_product_code'] = 'SYN-READ-002'
        target = self.adopt(result=Registry.success(body='Synthetic correction target', variants=[target_variant]),
            query={**QUERY, 'size': '265/40R20'})
        with Session(self.engine) as db:
            db.add(IdentityRevision(id=uuid4().hex, variant_id=self.selected['variant_id'], target_id=target['variant_id'],
                revision=1, action='correct', binding={}, binding_hash=independent_digest({}), differences=[], field_reasons={},
                acknowledged_unknowns=True, evidence=[], operator='Synthetic', reason='SENTINEL_IDENTITY',
                actor_session_id='session-admin', idempotency_key=str(uuid4()), request_hash='0' * 64,
                created_at=self.now))
            db.commit()
        self.code('reader_identity_invalid', self.read)
        with Session(self.engine) as db:
            db.add(IdentityRevision(id=uuid4().hex, variant_id=self.selected['variant_id'], target_id=None,
                revision=2, action='clear', binding={}, binding_hash=independent_digest({}), differences=[], field_reasons={},
                acknowledged_unknowns=True, evidence=[], operator='Synthetic', reason='Synthetic clear correction',
                actor_session_id='session-admin', idempotency_key=str(uuid4()), request_hash='0' * 64,
                created_at=self.now))
            db.commit()
        self.projected()

    def test_17_manual_alias_union_clear_and_source_values_only(self):
        self.manual('utqg_treadwear', 'manual_override')
        self.manual('treadwear', 'revoke')
        self.manual('utqg_treadwear', 'clear_override')
        item = self.projected()
        self.assertNotIn('utqg_treadwear', item['facts'])
        self.assertNotIn('utqg_treadwear', item['conflicted_fields'])
        self.manual('treadwear', 'clear_override')
        restored = self.projected()
        self.assertEqual(restored['facts']['utqg_treadwear'], 0)
        self.assertNotIn('4777', json.dumps(restored))
        self.assertNotIn('SENTINEL_PRIVATE_MANUAL_REASON', json.dumps(restored))

    def test_18_manual_needs_review_never_revives_old_source_value(self):
        self.manual('utqg_treadwear', 'revoke')
        variant = deepcopy(VARIANT)
        variant['facts']['eu_wet_grip'] = 'B'
        changed = self.adopt(result=Registry.success(body='Synthetic new fact after manual revoke', variants=[variant]))
        self.approve(changed, grant='needs-review-grant')
        reader = self.new_reader(routing={SOURCE: 'needs-review-grant'})
        credential = reader.capture_credential(['Bearer ' + self.issued['token']])
        item = self.projected(changed, reader=reader, credential=credential)
        self.assertNotIn('utqg_treadwear', item['facts'])
        self.assertEqual(item['facts']['eu_wet_grip'], 'B')

    def test_19_conflict_alias_null_and_permission_do_not_leak_values(self):
        variant = deepcopy(VARIANT)
        variant['facts'].update(treadwear=4333, source_field_conflicts=[
            {'field': 'facts.eu_wet_grip', 'values': [{'value': 'B'}, {'value': 'C'}]}])
        chosen = self.adopt(result=Registry.success(body='Synthetic source conflict', variants=[variant]))
        self.approve(chosen, grant='conflict-grant', fields=['facts.utqg_treadwear', 'facts.weight_kg'])
        reader = self.new_reader(routing={SOURCE: 'conflict-grant'})
        item = self.projected(chosen, reader=reader,
            credential=reader.capture_credential(['Bearer ' + self.issued['token']]))
        self.assertEqual(item['facts'], {'weight_kg': None})
        self.assertEqual(item['conflicted_fields'], ['utqg_treadwear'])
        self.assertNotIn('4333', json.dumps(item))
        self.assertNotIn('eu_wet_grip', json.dumps(item))

    def test_20_source_pause_keeps_history_and_reader_transaction_is_read_only(self):
        setting = SourceSettingRevision(id=uuid4().hex, source_id=SOURCE, revision=1,
            action='pause', state='paused', notes='', access_generation=1, before={}, after={},
            catalog_fingerprint='a' * 64, preview_fingerprint='b' * 64, fingerprint='', operator='Synthetic',
            reason='Synthetic pause', actor_session_id='session-admin', idempotency_key='synthetic-pause',
            request_hash='c' * 64)
        setting.fingerprint = independent_digest({key: getattr(setting, key) for key in (
            'id', 'source_id', 'revision', 'action', 'state', 'notes', 'access_generation', 'before', 'after',
            'catalog_fingerprint', 'preview_fingerprint', 'operator', 'reason', 'actor_session_id',
            'idempotency_key', 'request_hash')})
        with Session(self.engine) as db:
            db.add(setting)
            db.commit()
        statements, commits, checkouts = [], [], []
        def capture(_c, _cu, statement, _p, _co, _m):
            statements.append(statement.lower())
        def committed(_c):
            commits.append(True)
        def checked_out(_c, _r, _p):
            checkouts.append(True)
        event.listen(self.engine, 'before_cursor_execute', capture)
        event.listen(self.engine, 'commit', committed)
        event.listen(self.engine, 'checkout', checked_out)
        calls = self.registry.calls
        try:
            outcome = self.read()
            item = outcome.to_dict()['item']
            item['facts']['utqg_treadwear'] = 999
            self.assertEqual(outcome.to_dict()['item']['facts']['utqg_treadwear'], 0)
        finally:
            event.remove(self.engine, 'before_cursor_execute', capture)
            event.remove(self.engine, 'commit', committed)
            event.remove(self.engine, 'checkout', checked_out)
        self.assertEqual(self.registry.calls, calls)
        self.assertEqual(checkouts, [True])
        self.assertEqual(commits, [True])
        self.assertEqual(sum(s.strip() == 'begin immediate' for s in statements), 1)
        self.assertFalse(any(s.lstrip().startswith(('insert ', 'update ', 'delete ', 'replace ')) for s in statements))

    def test_21_body_capacity_is_utf8_sql_preflight_and_legitimate_boundary(self):
        for size, query in ((8 * 1024 * 1024 - 1, QUERY),
                            (8 * 1024 * 1024, {**QUERY, 'size': '265/40R20'})):
            with self.subTest(kind='accepted_body_boundary'):
                chosen = self.adopt(result=Registry.success(body='x' * size), query=query)
                grant = 'body-grant-' + str(size)
                self.approve(chosen, grant=grant)
                reader = self.new_reader(routing={SOURCE: grant})
                self.projected(chosen, reader=reader,
                    credential=reader.capture_credential(['Bearer ' + self.issued['token']]))
        before = self.saved(Snapshot, self.selected['snapshot_id'], 'body')
        for body in ('x' * (8 * 1024 * 1024 + 1), '\0' + 'x' * (8 * 1024 * 1024),
                     '汉' * (8 * 1024 * 1024 // 3 + 1)):
            with self.subTest(kind='rejected_body_bytes'):
                self.mutate(Snapshot, self.selected['snapshot_id'], body=body)
                statements = []
                def capture(_c, _cu, statement, _p, _co, _m):
                    statements.append(statement.lower())
                event.listen(self.engine, 'before_cursor_execute', capture)
                try:
                    self.code('reader_capacity', self.read)
                finally:
                    event.remove(self.engine, 'before_cursor_execute', capture)
                self.assertTrue(any('length(' in s and 'snapshots.body' in s and 'blob' in s for s in statements))
                self.assertFalse(any('snapshots.body' in s and 'length(' not in s for s in statements))
        self.mutate(Snapshot, self.selected['snapshot_id'], **before)

    def test_22_json_audit_fact_and_manual_history_preflight_capacity(self):
        with Session(self.engine) as db:
            receipt = db.get(QueryRunOwnerReceipt, self.selected['query_id'])
            fact_id = db.scalar(select(FactVersion.id).where(FactVersion.variant_id == self.selected['variant_id']))
            binding_id = db.scalar(select(VariantIdentityBinding.id).where(
                VariantIdentityBinding.variant_id == self.selected['variant_id']))
        cases = ((Snapshot, self.selected['snapshot_id'], 'parsed_variants', [{'padding': 'x' * (2 * 1024 * 1024)}]),
            (QueryRun, self.selected['query_id'], 'query', {'padding': 'x' * 65536}),
            (AuditEvent, receipt.audit_event_id, 'detail', {'padding': 'x' * 16384}),
            (FactVersion, fact_id, 'facts', {'padding': 'x' * 65536}),
            (VariantIdentityBinding, binding_id, 'proof', {'padding': 'x' * 65536}))
        for model, identifier, field, oversized in cases:
            before = self.saved(model, identifier, field)
            with self.subTest(kind='json_preflight'):
                self.mutate(model, identifier, **{field: oversized})
                self.code('reader_capacity', self.read)
            self.mutate(model, identifier, **before)
        with self.engine.begin() as connection:
            connection.execute(ManualFactRevision.__table__.insert(), [dict(id=uuid4().hex,
                variant_id=self.selected['variant_id'], source_id=SOURCE, base_fact_id=fact_id,
                revision=index, field='weight_kg', action='clear_override', operator_session_id='session-admin',
                operator='Synthetic', reason='Synthetic capacity', before={}, after={}, source_before={},
                evidence=[], created_at=self.now) for index in range(1, 4097)])
        self.projected()
        self.manual('weight_kg', 'clear_override')
        self.code('reader_capacity', self.read)

    def race(self, writer_action):
        attempted, finished = threading.Event(), threading.Event()
        failures, threads = [], []
        def observe(_c, _cu, statement, _p, _co, _m):
            if threading.current_thread().name == 'synthetic-reader-writer' and statement.strip().upper() == 'BEGIN IMMEDIATE':
                attempted.set()
        def writer():
            try:
                writer_action()
            except BaseException as error:
                failures.append(type(error).__name__)
            finally:
                finished.set()
        def clock():
            thread = threading.Thread(target=writer, name='synthetic-reader-writer')
            threads.append(thread)
            thread.start()
            self.assertTrue(attempted.wait(3), 'writer_never_attempted_lock')
            self.assertFalse(finished.wait(0.05), 'writer_did_not_wait_for_reader')
            return self.now
        reader = self.new_reader(clock=clock)
        credential = reader.capture_credential(['Bearer ' + self.issued['token']])
        event.listen(self.engine, 'before_cursor_execute', observe)
        try:
            self.projected(reader=reader, credential=credential)
        finally:
            event.remove(self.engine, 'before_cursor_execute', observe)
            for thread in threads:
                thread.join(6)
        self.assertTrue(finished.is_set())
        self.assertFalse(failures)

    def test_23_real_sqlite_lock_serializes_key_revocation(self):
        def revoke():
            with Session(self.engine) as db:
                QueryService(db, None).lock_ingestion()
                revoke_account_keys(db, 'owner-a', 'password_reset')
                db.commit()
        self.race(revoke)
        self.code('reader_unauthorized', self.read)

    def test_24_real_sqlite_lock_serializes_grant_withdrawal(self):
        self.race(self.stop)
        self.code('reader_not_available', self.read)

    def test_25_backend_schema_gates_and_single_locked_clock(self):
        calls = []
        def clock():
            calls.append(True)
            return self.now
        reader = self.new_reader(clock=clock)
        self.projected(reader=reader, credential=reader.capture_credential(['Bearer ' + self.issued['token']]))
        self.assertEqual(calls, [True])
        with Session(self.engine) as db:
            audit_before = db.scalar(select(func.count()).select_from(AuditEvent))
        for action in ('session_commit', 'session_rollback', 'pending_flush', 'core_insert',
                       'core_insert_scalar', 'core_insert_scalars',
                       'connection_commit_reopen', 'connection_rollback_reopen'):
            with self.subTest(kind='owned_transaction_guard'):
                with self.assertRaises(GovernanceError) as caught:
                    with self.store._reader_transaction() as (db, _now):
                        if action == 'session_commit':
                            db.commit()
                        elif action == 'session_rollback':
                            db.rollback()
                        elif action == 'pending_flush':
                            db.add(AuditEvent(session_id='synthetic', action='forbidden_reader_write', detail={}))
                            db.flush()
                        elif action.startswith('core_insert'):
                            statement = AuditEvent.__table__.insert().values(id=uuid4().hex,
                                session_id='synthetic', action='forbidden_reader_write', detail={}, created_at=self.now)
                            if action == 'core_insert_scalar':
                                db.scalar(statement)
                            elif action == 'core_insert_scalars':
                                db.scalars(statement)
                            else:
                                db.execute(statement)
                        else:
                            connection = db.connection()
                            if action == 'connection_commit_reopen':
                                connection.commit()
                            else:
                                connection.rollback()
                            connection.exec_driver_sql('BEGIN IMMEDIATE')
                            connection.exec_driver_sql('SELECT 1')
                self.assertEqual(caught.exception.code, 'reader_governance_invalid')
        with Session(self.engine) as db:
            self.assertEqual(db.scalar(select(func.count()).select_from(AuditEvent)), audit_before)
        original = self.engine.dialect.name
        try:
            self.engine.dialect.name = 'postgresql'  # Dialect stub only; no PG connection or acceptance.
            self.code('reader_backend_unsupported', self.read)
        finally:
            self.engine.dialect.name = original
        with self.engine.begin() as connection:
            connection.execute(text("DELETE FROM tire_schema_versions WHERE version='026_query_ownership'"))
        self.code('reader_schema_required', self.read)

"""Opt-in PG45 recall research/consent concurrency and exact restore acceptance.

Run only through the PG45 wrapper on loopback port 55445. All observations and
model output are synthetic. Round45 adds no tables or migrations.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints
import monitor_tasks_postgres_acceptance as previous

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_recall_research_private_postgresql_no_ddl', 'checks': []}
STEP = 'isolation'
PORT = 55445
PREFIX = 'round45-recall-knowledge-PG-'
VERSIONS = {'001_verification_validators', '002_monitor_rule_conditions', '003_parser_release_provenance',
    '004_query_selection_filters', '005_variant_identity_contract', '006_source_settings',
    '007_monitor_tasks', '008_recall_discovery_monitoring', '009_ai_streaming'}
ENUM_CHECKS = (
    ('monitor_task_attempts', 'kind', ('tire', 'recall')),
    ('monitor_task_events', 'kind', ('tire', 'recall')),
    ('monitor_task_events', 'phase', ('claimed', 'running', 'finished')),
    ('monitor_task_events', 'state', ('running', 'succeeded', 'failed', 'blocked', 'interrupted')),
    ('ai_stream_events', 'type', ('accepted', 'started', 'claim_draft', 'uncertainty_draft', 'completed', 'failed', 'outcome_unknown')),
    ('recall_discovery_runs', 'coverage', ('complete', 'incomplete')),
    ('recall_discovery_task_events', 'phase', ('claimed', 'running', 'finished')),
    ('recall_discovery_task_events', 'state', ('running', 'succeeded', 'failed', 'blocked', 'interrupted')),
    ('source_setting_revisions', 'action', ('enable', 'pause', 'archive', 'restore', 'edit_notes')),
    ('source_setting_revisions', 'state', ('enabled', 'paused', 'archived')),
)
save_atomic, safe_failure, wait_gate = previous.save_atomic, previous.safe_failure, previous.wait_gate


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert root.parent == (ROOT / '.artifacts/runtime').resolve() and root.name.startswith(PREFIX)
    assert (root / '.round45-recall-knowledge-owned').read_text(encoding='utf-8') == root.name
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == root / 'data'
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == root / 'report.json'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == PORT
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    assert os.environ['TI_OBSERVABILITY_ENABLED'] == '0' and os.environ.get('TI_DISABLED_SOURCES', '') == ''
    assert os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    assert Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve() == root / 'objects'
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == root / 'bundles'
    import_guard = 'sqlite:///' + (root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == import_guard
    assert Path(os.environ['TIRE_PG_BIN']).resolve() == Path('E:/PostgreSQL/18/bin').resolve()
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    return root


def config():
    from tire_api.ai_gateway import OpenAIConfig
    return OpenAIConfig(model='synthetic-pg45-recall', api_key='synthetic-never-live',
                        daily_token_limit=2_000_000, daily_request_limit=100, allow_private=True)


class SyntheticRecall:
    supports_parser_deployments = False

    def __init__(self, mode='baseline'):
        self.mode, self.calls, self.observations = mode, 0, 0

    async def fetch(self, query, cached=None, *, on_observation=None):
        from test_recalls import IDENTITY, record as row
        from tire_api.recalls import campaign_url
        self.calls += 1
        if self.mode == 'offline':
            return {'status': 'unavailable', 'reason': 'synthetic_pg45_outage'}
        a, b = row('PG45 ALPHA'), row('PG45 BETA')
        a.update(make='PG45 BRAND A', summary='Synthetic announcement A; not physical safety evidence.')
        b.update(make='PG45 BRAND B', summary='Synthetic announcement B; independent product record.')
        if self.mode == 'changed':
            a['remedy'] = 'Synthetic revised remedy, no physical applicability claim.'
        rows = [] if self.mode == 'empty' else [a, b, deepcopy(a)]
        value = {'status': 'ok', 'url': campaign_url(query['campaign_number']), 'content_type': 'application/json',
            'parser_version': 'synthetic-pg45-recall@1', 'parser_identity': deepcopy(IDENTITY),
            'etag': '"synthetic-pg45"', 'last_modified': None, 'records': rows,
            'body': json.dumps({'synthetic_only': True, 'raw_nonce': 1 if self.mode == 'new_raw' else 0,
                                'records': rows}, ensure_ascii=False)}
        assert callable(on_observation)
        on_observation(value)
        self.observations += 1
        return value


class SyntheticModel:
    def __init__(self):
        self.mode, self.sync_calls, self.stream_calls = 'facts', 0, 0

    def output(self, body):
        assert body['store'] is False and body['background'] is False and body['tools'] == []
        payload = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        assert payload['purpose'] == 'recall_research' and payload['recall_boundary']['applicability'] == 'not_assessed'
        assert body['text']['format']['name'] == 'recall_evidence_answer'
        facts = [item for item in payload['facts'] if item.get('scope') == 'record' and item['field_code'] == 'recall.remedy']
        selected = facts[:1] or payload['facts'][:1]
        claim = {'type': 'fact', 'text': '', 'fact_ids': [item['id'] for item in selected],
                 'evidence_ids': [selected[0]['evidence_id']]}
        if self.mode == 'inference':
            claim.update(type='inference', text='UNSAFE SYNTHETIC SAFETY CONCLUSION')
        if self.mode == 'cross_record':
            claim['fact_ids'] = [item['id'] for item in facts]
        uncertainty = 'UNSAFE SYNTHETIC UNCERTAINTY' if self.mode == 'uncertainty' else ''
        return {'uncertainty': uncertainty, 'claims': [claim]}

    def receipt(self, text):
        return {'text': text, 'error': None, 'usage': {'input_tokens': 100, 'output_tokens': 20, 'total_tokens': 120},
                'provider_response_id': 'resp_synthetic_pg45'}

    async def generate(self, _config, body):
        self.sync_calls += 1
        return self.receipt(json.dumps(self.output(body)))

    async def stream(self, _config, body, on_text):
        self.stream_calls += 1
        raw = json.dumps(self.output(body))
        # Actual production projector sees the forbidden uncertainty first.
        for offset in range(0, len(raw), 13):
            await on_text(raw[offset:offset + 13])
            await asyncio.sleep(0)
        return self.receipt(raw)


def schema_snapshot(database):
    from sqlalchemy import inspect
    inspector = inspect(database.engine)
    result = {}
    for name in sorted(inspector.get_table_names()):
        result[name] = {'columns': inspector.get_columns(name), 'checks': inspector.get_check_constraints(name),
            'indexes': inspector.get_indexes(name), 'unique': inspector.get_unique_constraints(name),
            'foreign': inspector.get_foreign_keys(name), 'primary': inspector.get_pk_constraint(name)}
        for key in ('checks', 'indexes', 'unique', 'foreign'):
            result[name][key] = sorted(result[name][key], key=lambda row: json.dumps(row, sort_keys=True, default=str))
    return json.loads(json.dumps(result, sort_keys=True, default=str))


def enum_expressions(column, values):
    array = ', '.join("'" + value + "'::character varying" for value in values)
    elements = ', '.join("'" + value + "'::character varying::text" for value in values)
    return (column + '::text = ANY (ARRAY[' + array + ']::text[])',
            column + '::text = ANY (ARRAY[' + elements + '])')


def normalized_schema(schema):
    """Only ten individually observed PG18 cast deparse equivalences, no others."""
    result = deepcopy(schema)
    for table, column, values in ENUM_CHECKS:
        original, restored = enum_expressions(column, values)
        name = table + '_' + column + '_check'
        for constraint in result[table]['checks']:
            if constraint['name'] == name and constraint['sqltext'] == original:
                constraint['sqltext'] = restored
    return result


def evaluate_enum_checks(database, schema):
    """Run every allowed value, two invalid values and NULL against exact SQL."""
    from sqlalchemy import text
    evidence = []
    with database.engine.connect() as connection:
        for table, column, values in ENUM_CHECKS:
            name = table + '_' + column + '_check'
            expression = next(item['sqltext'] for item in schema[table]['checks'] if item['name'] == name)
            assert expression in enum_expressions(column, values), 'unknown_enum_schema_expression'
            cases = list(values) + ['__pg45_invalid__', '', None]
            actual = [connection.execute(text('SELECT (' + expression + ') FROM '
                '(SELECT CAST(:value AS VARCHAR) AS "' + column + '") AS synthetic'), {'value': value}).scalar_one()
                for value in cases]
            assert actual == [True] * len(values) + [False, False, None]
            evidence.append({'table': table, 'constraint': name, 'values': cases, 'results': actual})
    return evidence


def check_restored_stream_constraint(database):
    """A real invalid UPDATE must be rejected; the complete transaction rolls back."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from tire_api.ai_stream_models import AIStreamEvent
    with database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            event_id = connection.execute(select(AIStreamEvent.id).limit(1)).scalar_one()
            try:
                connection.execute(AIStreamEvent.__table__.update().where(AIStreamEvent.id == event_id).values(type='invalid'))
            except IntegrityError as error:
                assert error.orig.sqlstate == '23514'
                assert error.orig.diag.constraint_name == 'ai_stream_events_type_check'
                return {'table': 'ai_stream_events', 'constraint': error.orig.diag.constraint_name,
                        'sqlstate': error.orig.sqlstate, 'invalid_update_rejected': True, 'rolled_back': True}
            raise AssertionError('restored_stream_check_accepted_invalid_value')
        finally:
            transaction.rollback()


def writer(name):
    root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((root / f'{name}.request.json').read_text(encoding='utf-8'))
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', request['group'])
    from fastapi.testclient import TestClient
    from sqlalchemy import event
    from sqlalchemy.engine import make_url
    from tire_api.main import SESSION_COOKIE, create_app
    from test_recalls import NoTireSource
    url = os.environ['TIRE_PG_APP_URL']
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == PORT
    assert parsed.database.startswith('recall_knowledge_')
    app = create_app(url, NoTireSource())
    source = SyntheticRecall('offline')
    app.state.recall_adapter = source
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'action': 'consume_once_consent', 'status': 'running'}
    code, statements = 0, []

    def track(_connection, _cursor, statement, _parameters, _context, _many):
        statements.append(statement.lower())

    try:
        with TestClient(app, cookies={SESSION_COOKIE: request['actor']}) as client:
            with app.state.database.sessions() as db:
                outcome['backend_pid'] = db.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
                db.commit()
            event.listen(app.state.database.engine, 'before_cursor_execute', track)
            save_atomic(root / f'{name}.ready.json', {'pid': os.getpid(), 'backend_pid': outcome['backend_pid']})
            wait_gate(root / (request['group'] + '.go'))
            response = client.post('/v1/ai/evidence-packs', json=request['body'])
            outcome.update(status='finished', response_status=response.status_code, source_calls=source.calls)
            if response.status_code == 200:
                pack = response.json()['pack']
                claimed = next(index for index, sql in enumerate(statements) if sql.startswith('update fallback_consents'))
                read = next(index for index, sql in enumerate(statements) if 'recall_snapshots.records' in sql)
                assert claimed < read
                outcome.update(pack_id=pack['id'], data_state=pack['data_state'],
                    verification_id=pack['evidence'][0]['verification_id'], claim_before_history_read=True)
            else:
                assert response.status_code == 409
                assert not any('recall_snapshots.records' in sql for sql in statements)
                outcome['history_read'] = False
            assert source.calls == 0
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        app.state.database.close()
        save_atomic(root / f'{name}.result.json', outcome)
    return code


class Writers(previous.Writers):
    def launch(self, group, request):
        names = []
        for index in range(2):
            name = f'{group}-{index}'
            names.append(name)
            save_atomic(self.root / f'{name}.request.json', {'group': group, **request})
            env = {**os.environ, 'TIRE_PG_APP_URL': self.url}
            env.pop('TIRE_PG_TEST_PASSWORD', None)
            self.logs[name] = (self.root / f'{name}.log').open('wb')
            self.children[name] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', name],
                env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=self.logs[name], stderr=subprocess.STDOUT)
        ready = self.collect(names, 'ready')
        assert len({item['pid'] for item in ready}) == len({item['backend_pid'] for item in ready}) == 2
        assert all(item['pid'] != os.getpid() for item in ready)
        self.evidence.extend({'scenario': group, 'launcher_pid': self.children[name].pid, **item}
                             for name, item in zip(names, ready, strict=True))
        (self.root / f'{group}.go').write_text('begin', encoding='utf-8')
        for name in names:
            assert self.children[name].wait(timeout=45) == 0, 'private_writer_failed'
        return self.collect(names, 'result')


def run():
    global STEP
    root = guards()
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.engine import URL
    from tire_api import ai_analysis, ai_stream_store as store, reports
    from tire_api.ai_models import AIRequest, AICompletion
    from tire_api.ai_stream_models import AIStreamEvent
    from tire_api.captures import checked_capture_bytes
    from tire_api.db import Base, Database, FallbackConsent, RawCapture
    from tire_api.domain import digest
    from tire_api.main import SESSION_COOKIE, create_app
    from tire_api.recall_models import RecallRevision, RecallSnapshot
    from tire_api.report_models import ResearchReport
    from tire_api.recall_evidence import recall_boundary_descriptor
    from ai_stream_postgres_acceptance import seed_pack
    from test_ai import analyze
    from test_ai_stream_api import accept, until
    from test_recalls import CAMPAIGN, NoTireSource, grant, live
    from test_recall_knowledge_ai import current_pack, history_pack, search
    from test_reports import save, export
    admin = psycopg.connect(host='127.0.0.1', port=PORT, user='tire_recall_knowledge_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = writers = None
    previous.REPORT = REPORT
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == root / 'data'
        assert admin.execute('SHOW listen_addresses').fetchone()[0] == '127.0.0.1'
        REPORT.update(postgres_version=admin.execute('SHOW server_version').fetchone()[0], parent_pid=os.getpid(),
                      postmaster_pid=int((root / 'data/postmaster.pid').read_text().splitlines()[0]))
        assert REPORT['postgres_version'].split('.')[0] == '18'
        role, password = 'recall_knowledge_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password, host='127.0.0.1', port=PORT,
                              database=name).render_as_string(hide_password=False)

        name = 'recall_knowledge_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert connection.exec_driver_sql('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user').scalar_one() is False
            assert not inspect(connection).get_table_names()
        database.initialize()
        initial_schema = schema_snapshot(database)
        initial_values = fingerprints(database, Base.metadata)
        database.initialize()
        assert schema_snapshot(database) == initial_schema and fingerprints(database, Base.metadata) == initial_values
        with database.engine.connect() as connection:
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
        assert versions == VERSIONS
        save_atomic(root / 'schema-initialized.json', initial_schema)
        record('private_loopback_non_superuser_all_existing_009_schema_repeat_initialize_no_changes')

        STEP = 'formal_recall_knowledge_and_double_binding'
        actor = str(uuid4())
        legacy_pack_id = seed_pack(database, actor)
        source, model = SyntheticRecall(), SyntheticModel()
        app = create_app(url, NoTireSource())
        app.state.recall_adapter, app.state.ai_adapter = source, model
        with patch.object(ai_analysis, 'configured_model', config), TestClient(app, cookies={SESSION_COOKIE: actor}) as client:
            legacy = save(client, {'id': legacy_pack_id}).json()
            assert legacy['body_hash'] == digest(legacy['body']) and 'recall_policy' not in legacy['body']
            first_response = current_pack(client)
            assert first_response.status_code == 200
            first = first_response.json()['pack']
            first_source = first['evidence'][0]
            assert first['data_state'] == 'live' and first_source['record_count'] == 3
            assert len(first['facts']) == 46 and len({row['record_key'] for row in first_source['record_scopes']}) == 3
            source.mode = 'new_raw'
            second_observation = live(client).json()
            second_response = history_pack(client, second_observation['analysis_reference'])
            assert second_response.status_code == 200
            selected = second_response.json()['pack']
            chosen = selected['evidence'][0]
            assert chosen['snapshot_id'] != first_source['snapshot_id']
            assert chosen['recall_revision_id'] == first_source['recall_revision_id']
            assert chosen['revision_snapshot_id'] == first_source['snapshot_id']
            assert chosen['raw_hash'] != first_source['raw_hash'] and chosen['records_hash'] == first_source['records_hash']
            found = search(client, campaign_number=CAMPAIGN).json()
            assert found['total'] == 3 and len(found['items']) == 3
            assert search(client, campaign_number=CAMPAIGN, brand='PG45 BRAND A', model='PG45 BETA').json()['total'] == 0
            assert search(client, campaign_number=CAMPAIGN, brand='PG45 BRAND A', model='PG45 ALPHA').json()['total'] == 2
            assert len({item['id'] for item in found['items']}) == 3
            with database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(RecallRevision)) == 1
                assert db.scalar(select(func.count()).select_from(RecallSnapshot)) == 2
            REPORT['recall_binding'] = {key: chosen[key] for key in ('snapshot_id', 'recall_revision_id',
                'revision_snapshot_id', 'record_count', 'records_hash', 'verification_id')}
            record('three_formal_records_duplicate_multiset_new_raw_original_revision_and_per_record_knowledge')

            STEP = 'independent_once_consent_race'
            source.mode = 'offline'
            unavailable = current_pack(client).json()
            assert unavailable['pack'] is None and unavailable['query_result']['data_state'] == 'consent_required'
            consent_id = grant(client, unavailable['query_result']['query_id'])
            writers = Writers(root, url)
            outcomes = writers.launch('once-consent', {'actor': actor, 'body': {'mode': 'current',
                'query_kind': 'recall_by_campaign', 'source_id': 'nhtsa-us-recalls',
                'query': {'campaign_number': CAMPAIGN}, 'consent_id': consent_id}})
            assert sorted(item['response_status'] for item in outcomes) == [200, 409]
            winner = next(item for item in outcomes if item['response_status'] == 200)
            assert winner['data_state'] == 'local_snapshot' and winner['verification_id'] == chosen['verification_id']
            assert sum(item['source_calls'] for item in outcomes) == 0
            with database.sessions() as db:
                assert db.get(FallbackConsent, consent_id).used_at is not None
            REPORT['once_consent_outcomes'] = outcomes
            writers.close()
            record('two_real_writer_processes_one_once_consent_claim_before_history_read_and_no_refetch')

            STEP = 'synchronous_stream_safety_and_frozen_report'
            success = analyze(client, selected).json()
            assert success['state'] == 'completed' and success['answer']['recall_boundary'] == recall_boundary_descriptor()
            assert success['request_contract']['prompt_version'] == 'recall-grounding@1'
            report_response = save(client, selected, success['id'])
            assert report_response.status_code == 201
            saved = report_response.json()
            assert saved['body']['evidence'][0]['verification_id'] == chosen['verification_id']
            for mode in ('inference', 'cross_record', 'uncertainty'):
                model.mode = mode
                rejected = analyze(client, selected).json()
                assert rejected['state'] == 'failed' and rejected['answer'] is None
                assert rejected['error_code'] == 'ai_grounding_validation_failed'
                assert save(client, selected, rejected['id']).status_code == 409
            model.mode = 'uncertainty'
            response = accept(client, selected)
            assert response.status_code == 202
            stream_id = response.json()['analysis']['id']
            terminal = until(client, stream_id, lambda row: row['execution']['terminal'])
            assert terminal['analysis']['state'] == 'failed' and terminal['analysis']['answer'] is None
            assert terminal['draft_claims'] == [] and terminal['draft_uncertainty'] is None
            assert save(client, selected, stream_id).status_code == 409
            with database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(AIStreamEvent).where(
                    AIStreamEvent.request_id == stream_id, AIStreamEvent.type.in_(('claim_draft', 'uncertainty_draft')))) == 0
                assert db.get(AICompletion, stream_id).state == 'failed'
            record('postgres_sync_inference_cross_record_uncertainty_and_uncertainty_first_stream_rejected')

            STEP = 'later_revision_empty_and_old_reports'
            source.mode = 'changed'
            assert live(client).json()['revision'] == 2
            source.mode = 'empty'
            empty = live(client).json()
            assert empty['records'] == [] and empty['analysis_reference']['recall_revision_id'] is None
            empty_pack = history_pack(client, empty['analysis_reference']).json()['pack']
            assert len(empty_pack['facts']) == 4 and empty_pack['evidence'][0]['record_count'] == 0
            empty_saved = save(client, empty_pack)
            assert empty_saved.status_code == 201
            after_empty = search(client, campaign_number=CAMPAIGN).json()
            assert after_empty['total'] == 4
            for expected in (legacy, saved):
                fetched = client.get('/v1/reports/' + expected['id'] + '?mode=history').json()
                assert fetched['body'] == expected['body'] and fetched['body_hash'] == expected['body_hash']
            before_exports = source.calls, model.sync_calls, model.stream_calls
            for format in ('markdown', 'html', 'pdf'):
                export(client, saved, format)
            assert before_exports == (source.calls, model.sync_calls, model.stream_calls)
            REPORT.update(synthetic_source_calls=source.calls, synthetic_source_observations=source.observations,
                          synthetic_sync_calls=model.sync_calls, synthetic_stream_calls=model.stream_calls,
                          recall_report_id=saved['id'], legacy_report_id=legacy['id'], rejected_stream_id=stream_id)
            record('new_revision_and_empty_observation_preserve_both_frozen_reports_and_offline_three_format_exports')

        STEP = 'final_schema_and_object_evidence'
        final_schema = schema_snapshot(database)
        assert final_schema == initial_schema, 'round45_schema_changed'
        enum_before = evaluate_enum_checks(database, final_schema)
        save_atomic(root / 'enum-checks-before-dump.json', enum_before)
        with database.sessions() as db:
            captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
            assert len(captures) == source.observations == 4
            for capture_id, expected in captures:
                raw, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(raw).hexdigest() == expected
            expected_reports = {row.id: {'body': deepcopy(row.body), 'hash': row.body_hash}
                                for row in db.scalars(select(ResearchReport))}
            expected_stream = previous.strip_clock(store.detail(db, stream_id, actor))
        frozen = fingerprints(database, Base.metadata)
        save_atomic(root / 'fingerprints-frozen.json', public_fingerprints(frozen))
        save_atomic(root / 'schema-frozen.json', final_schema)
        database.initialize()
        assert fingerprints(database, Base.metadata) == frozen and schema_snapshot(database) == final_schema
        record('all_registered_values_and_full_schema_unchanged_by_repeat_initialize_no_round45_ddl')

        STEP = 'four_stage_exact_dump_restore'
        restored_name = 'restored_recall_knowledge_' + uuid4().hex[:10]
        restored_url = new_database(restored_name)
        archive = root / 'recall-knowledge.dump'
        env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': str(PORT), 'PGUSER': role, 'PGPASSWORD': password}
        env.pop('TIRE_PG_TEST_PASSWORD', None)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        pre_dump = fingerprints(database, Base.metadata)
        save_atomic(root / 'fingerprints-pre-dump.json', public_fingerprints(pre_dump))
        save_atomic(root / 'schema-pre-dump.json', schema_snapshot(database))
        assert pre_dump == frozen
        for command in ([str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password', '--dbname', name, '--file', str(archive)],
                        [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password', '--dbname', restored_name, str(archive)]):
            assert subprocess.run(command, env=env, capture_output=True, timeout=60).returncode == 0, 'private_dump_restore_failed'
        objects = file_hashes(root / 'objects')
        destination = root / 'restored-objects'
        assert objects and not destination.exists()
        shutil.copytree(root / 'objects', destination)
        assert file_hashes(destination) == objects
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        pre_initialize = fingerprints(restored, Base.metadata)
        restored_schema_before = schema_snapshot(restored)
        save_atomic(root / 'fingerprints-restored-pre-initialize.json', public_fingerprints(pre_initialize))
        save_atomic(root / 'schema-restored-pre-initialize.json', restored_schema_before)
        assert pre_initialize == frozen
        assert normalized_schema(restored_schema_before) == normalized_schema(final_schema), 'restore_schema_changed'
        enum_restored = evaluate_enum_checks(restored, restored_schema_before)
        assert enum_restored == enum_before
        rejected_update = check_restored_stream_constraint(restored)
        save_atomic(root / 'enum-checks-restored.json', {'evaluations': enum_restored, 'invalid_update': rejected_update})
        restored.initialize()
        post_initialize = fingerprints(restored, Base.metadata)
        restored_schema_after = schema_snapshot(restored)
        save_atomic(root / 'fingerprints-restored-post-initialize.json', public_fingerprints(post_initialize))
        save_atomic(root / 'schema-restored-post-initialize.json', restored_schema_after)
        assert post_initialize == frozen
        assert restored_schema_after == restored_schema_before
        with restored.sessions() as db:
            assert set(db.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == versions
            for report_id, expected in expected_reports.items():
                row = db.get(ResearchReport, report_id)
                assert row.body == expected['body'] and row.body_hash == expected['hash']
                assert reports.detail(db, row)['body'] == expected['body']
            assert previous.strip_clock(store.detail(db, stream_id, actor)) == expected_stream
            for capture_id, expected in captures:
                raw, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(raw).hexdigest() == expected
        assert fingerprints(restored, Base.metadata) == frozen
        assert not (root / 'import-guard.sqlite').exists()
        record('four_stage_all_values_full_schema_objects_frozen_reports_and_stream_state_exact_restore')
        nonempty = [name for name, value in frozen.items() if value['rows']]
        REPORT.update(status='passed', migration=None, actual_added_tables=[], actual_removed_tables=[],
            table_rebuilds=0, all_registered_schema_unchanged=True,
            tables_checked=len(frozen), columns_checked=sum(len(item['columns']) for item in frozen.values()),
            schema_tables_checked=len(final_schema), nonempty_table_count=len(nonempty), nonempty_tables=sorted(nonempty),
            empty_table_count=len(frozen) - len(nonempty), schema_versions=sorted(versions),
            table_fingerprints=public_fingerprints(frozen), restored_table_fingerprints=public_fingerprints(post_initialize),
            fingerprint_artifacts=['fingerprints-frozen.json', 'fingerprints-pre-dump.json',
                'fingerprints-restored-pre-initialize.json', 'fingerprints-restored-post-initialize.json'],
            schema_artifacts=['schema-frozen.json', 'schema-pre-dump.json',
                'schema-restored-pre-initialize.json', 'schema-restored-post-initialize.json'],
            schema_normalization='Only ten explicitly named PG18 enum ARRAY cast deparse equivalents; all other schema content exact',
            enum_check_contracts=len(enum_before), enum_cases_per_stage=sum(len(item['values']) for item in enum_before),
            enum_original_restored_results_identical=True, restored_invalid_stream_update=rejected_update,
            four_stage_exact_values=True, pre_dump_values_unchanged=True, restored_before_initialize_values_unchanged=True,
            object_hashes=objects, restored_object_hashes=file_hashes(destination), capture_count=len(captures),
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), archive_bytes=archive.stat().st_size,
            real_source_calls=0, real_model_calls=0, real_parser_children=0, normal_database_used=False,
            fingerprint_scope='All registered columns and values; all public table columns/constraints/indexes; schema versions and object bytes; no production role/ACL/cross-host recovery claim')
    finally:
        if writers is not None:
            writers.close()
        if database is not None:
            database.close()
        if restored is not None:
            restored.close()
        admin.close()


def guarded(action):
    guards()
    from tire_api.adapters.transport import SafeHttpClient
    from tire_api import parser_runtime
    from tire_api.ai_gateway import OpenAIResponsesAdapter
    with patch.object(SafeHttpClient, '_request', side_effect=AssertionError('real_source_forbidden')) as source, \
         patch.object(parser_runtime, '_run_sync', side_effect=AssertionError('real_parser_forbidden')) as parser, \
         patch.object(OpenAIResponsesAdapter, 'stream', side_effect=AssertionError('real_model_forbidden')) as stream, \
         patch.object(OpenAIResponsesAdapter, 'generate', side_effect=AssertionError('real_model_forbidden')) as generate:
        value = action()
        assert source.call_count == parser.call_count == stream.call_count == generate.call_count == 0
        return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--run-private-postgres', action='store_true')
    mode.add_argument('--writer')
    args = parser.parse_args()
    if args.writer:
        try:
            return guarded(lambda: writer(args.writer))
        except Exception as error:
            print(json.dumps({'status': 'failed', **safe_failure(error)}), flush=True)
            return 1
    code = 0
    try:
        guarded(run)
    except Exception as error:
        code = 1
        REPORT.update(status='failed', failure_step=STEP, **safe_failure(error))
    path = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert path.parent.parent == (ROOT / '.artifacts/runtime').resolve() and path.parent.name.startswith(PREFIX)
    save_atomic(path, REPORT)
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

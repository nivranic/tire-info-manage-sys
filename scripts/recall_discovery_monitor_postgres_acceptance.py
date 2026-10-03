"""Opt-in PG43 additive discovery acceptance; isolated synthetic evidence only.

Prepared without execution. Run through round43-verify-discovery-postgres.ps1
only after the coordinator grants the exclusive private PostgreSQL window.
The legacy baseline is created directly in a fresh database; existing task
tables are never removed, rebuilt, renamed or altered by this harness.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints
import monitor_tasks_postgres_acceptance as previous

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_discovery_additive_private_postgresql', 'checks': []}
STEP = 'isolation'
NEW_TABLES = {'recall_discovery_jobs', 'recall_discovery_rules', 'recall_discovery_rule_revisions',
    'recall_discovery_runs', 'recall_discovery_pages', 'recall_discovery_candidates',
    'recall_discovery_notifications', 'recall_discovery_task_attempts', 'recall_discovery_task_events'}
OLD_VERSIONS = {'001_verification_validators', '002_monitor_rule_conditions', '003_parser_release_provenance',
    '004_query_selection_filters', '005_variant_identity_contract', '006_source_settings', '007_monitor_tasks'}
MIGRATION = '008_recall_discovery_monitoring'
save_atomic, safe_failure = previous.save_atomic, previous.safe_failure
wait_gate, strip_clock, stream_rows = previous.wait_gate, previous.strip_clock, previous.stream_rows


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert root.parent == (ROOT / '.artifacts/runtime').resolve()
    assert root.name.startswith('round43-discovery-PG-')
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == root / 'data'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == 55443
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == root / 'report.json'
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    assert os.environ.get('TI_DISABLED_SOURCES', '') == ''
    assert os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    assert Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve() == root / 'objects'
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == root / 'bundles'
    import_guard = 'sqlite:///' + (root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == import_guard
    assert Path(os.environ['TIRE_PG_BIN']).resolve() == Path('E:/PostgreSQL/18/bin').resolve()
    sys.path[:0] = [str(ROOT / 'apps/api'), str(ROOT / 'apps/api/tests')]
    return root


def worker_module():
    spec = importlib.util.spec_from_file_location('pg43_worker', ROOT / 'apps/worker/monitor.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def search_adapter(mode):
    from test_recall_discovery import SearchFixture, product
    adapter = SearchFixture()
    adapter.products = [product(index, campaign=False) for index in range(1, 12)]
    adapter.products[-1] = product(11)
    if mode in {'new', 'later'}:
        row = deepcopy(adapter.products[-1]['campaigns'][0])
        row['campaign_number'] = '26T009000'
        adapter.products[-1]['campaigns'].append(row)
    if mode == 'later':
        row = deepcopy(adapter.products[-1]['campaigns'][0])
        row['campaign_number'] = '26T010000'
        adapter.products[-1]['campaigns'].append(row)
    adapter.products[-1]['recalls_count'] = len(adapter.products[-1]['campaigns'])
    return adapter


def writer(name):
    root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((root / f'{name}.request.json').read_text(encoding='utf-8'))
    group, kind = request['group'], request['kind']
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', group)
    assert kind in {'recall', 'recall_discovery'} and request['mode'] in {'baseline', 'new', 'later'}
    from sqlalchemy.engine import make_url
    from tire_api import recall_monitoring, recall_discovery_monitoring
    from tire_api.db import Database
    from tire_api.recall_models import RecallLiveRequest
    from tire_api.recalls import RecallService
    from test_recalls import RecallFixture
    url = os.environ['TIRE_PG_APP_URL']
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == 55443
    assert parsed.database.startswith('discovery_')
    database, worker = Database(url), worker_module()
    queue = recall_monitoring if kind == 'recall' else recall_discovery_monitoring
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'kind': kind, 'status': 'running'}
    code = 0
    try:
        with database.sessions() as db:
            outcome['backend_pid'] = db.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            db.commit()
        save_atomic(root / f'{name}.ready.json', {'pid': os.getpid(), 'backend_pid': outcome['backend_pid']})
        wait_gate(root / f'{group}.go')
        claim = queue.claim_job(database)
        if claim is None:
            outcome['status'] = 'idle'
            save_atomic(root / f'{name}.claim.json', outcome)
        else:
            worker.begin_attempt(database, claim, queue.guard_claim)
            outcome.update(status='claimed', job_id=claim['id'], attempt_id=claim['attempt_id'])
            save_atomic(root / f'{name}.claim.json', outcome)
            result = None
            adapter = search_adapter(request['mode']) if kind == 'recall_discovery' else None
            if kind == 'recall_discovery' and request.get('scan_before_finish'):
                result = asyncio.run(queue.execute_scan(database, claim, adapter))
                save_atomic(root / f'{name}.scanned.json', {'state': result['state'], 'page_queries': len(adapter.calls)})
            wait_gate(root / f'{name}.finish.go')
            if kind == 'recall_discovery':
                result = result or asyncio.run(queue.execute_scan(database, claim, adapter))
                finalized = queue.finish_job(database, claim, result['state'], result.get('reason'), usage=result['usage'])
                outcome.update(page_queries=len(adapter.calls), result_state=result['state'])
            else:
                with database.sessions() as db:
                    result = asyncio.run(RecallService(db, RecallFixture(), ingestion_guard=lambda session: queue.guard_claim(session, claim)).execute(
                        RecallLiveRequest(query=claim['query'], fallback_policy='never'), claim['session_id']))
                assert result['data_state'] == 'live'
                finalized = queue.finish_job(database, claim, result['data_state'], result.get('reason'), query_id=result['query_id'])
                outcome.update(result_state=result['data_state'], query_id=result['query_id'])
            outcome.update(status='finished', finalized=finalized)
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        database.close()
        save_atomic(root / f'{name}.result.json', outcome)
    return code


class Writers(previous.Writers):
    def start(self, group, kinds, *, mode='baseline', scan_before_finish=False):
        child_env = {**os.environ, 'TIRE_PG_APP_URL': self.url}
        child_env.pop('TIRE_PG_TEST_PASSWORD', None)
        names = [f'{group}-{index}' for index in range(len(kinds))]
        for name, kind in zip(names, kinds, strict=True):
            save_atomic(self.root / f'{name}.request.json', {'group': group, 'kind': kind, 'mode': mode,
                'scan_before_finish': scan_before_finish})
            log = (self.root / f'{name}.log').open('wb')
            self.logs[name] = log
            self.children[name] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', name],
                env=child_env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        ready = self.collect(names, 'ready')
        assert len({row['pid'] for row in ready}) == len({row['backend_pid'] for row in ready}) == len(names)
        assert all(row['pid'] != os.getpid() for row in ready)
        self.evidence.extend({'scenario': group, 'kind': kind, 'launcher_pid': self.children[name].pid, **row}
            for name, kind, row in zip(names, kinds, ready, strict=True))
        (self.root / f'{group}.go').write_text('begin', encoding='utf-8')
        outcomes = self.collect(names, 'claim')
        assert sum(row['status'] == 'claimed' for row in outcomes) == 1, 'cross_queue_did_not_have_one_winner'
        assert sum(row['status'] == 'idle' for row in outcomes) == len(names) - 1
        for name, row in zip(names, outcomes, strict=True):
            if row['status'] == 'idle':
                assert self.children[name].wait(timeout=10) == 0
        selected = next((name, row) for name, row in zip(names, outcomes, strict=True) if row['status'] == 'claimed')
        return selected


def journal_schema(database):
    from sqlalchemy import inspect
    inspector = inspect(database.engine)
    result = {}
    for name in ('monitor_task_attempts', 'monitor_task_events'):
        result[name] = {
            'columns': [{key: str(value) for key, value in row.items()} for row in inspector.get_columns(name)],
            'checks': inspector.get_check_constraints(name), 'indexes': inspector.get_indexes(name),
            'unique': inspector.get_unique_constraints(name), 'foreign': inspector.get_foreign_keys(name),
            'primary': inspector.get_pk_constraint(name),
        }
    return json.loads(json.dumps(result, sort_keys=True, default=str))


def restored_journal_schema(schema):
    """Canonicalize only four observed PG18 array-cast deparse equivalents."""
    result = deepcopy(schema)
    known = (
        ('monitor_task_attempts', 'kind', ('tire', 'recall')),
        ('monitor_task_events', 'kind', ('tire', 'recall')),
        ('monitor_task_events', 'phase', ('claimed', 'running', 'finished')),
        ('monitor_task_events', 'state', ('running', 'succeeded', 'failed', 'blocked', 'interrupted')),
    )
    for table, column, values in known:
        name = table + '_' + column + '_check'
        array_values = ', '.join("'" + value + "'::character varying" for value in values)
        element_values = ', '.join("'" + value + "'::character varying::text" for value in values)
        array_cast = column + '::text = ANY (ARRAY[' + array_values + ']::text[])'
        element_cast = column + '::text = ANY (ARRAY[' + element_values + '])'
        for check in result.get(table, {}).get('checks', []):
            if check.get('name') == name and check.get('sqltext') == array_cast:
                check['sqltext'] = element_cast
    return result


def verify_restored_journal_checks(database):
    """Use valid restored rows and roll back each targeted rejected update."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError
    from tire_api.db import Base
    cases = (
        ('monitor_task_attempts', 'kind', {'kind': 'invalid'}),
        ('monitor_task_events', 'kind', {'kind': 'invalid'}),
        ('monitor_task_events', 'phase', {'phase': 'invalid', 'state': 'running'}),
        ('monitor_task_events', 'state', {'state': 'invalid'}),
    )
    evidence = []
    with database.engine.connect() as connection:
        transaction = connection.begin()
        try:
            for table_name, column, changes in cases:
                table = Base.metadata.tables[table_name]
                query = select(table.c.id).limit(1)
                if table_name == 'monitor_task_events':
                    query = query.where(table.c.phase == 'finished')
                row_id = connection.execute(query).scalar_one()
                checkpoint = connection.begin_nested()
                try:
                    connection.execute(table.update().where(table.c.id == row_id).values(**changes))
                except IntegrityError as error:
                    checkpoint.rollback()
                    expected_constraint = table_name + '_' + column + '_check'
                    assert error.orig.sqlstate == '23514'
                    assert error.orig.diag.constraint_name == expected_constraint
                    evidence.append({'table': table_name, 'column': column,
                        'sqlstate': error.orig.sqlstate, 'constraint': expected_constraint,
                        'invalid_value_rejected': True})
                else:
                    checkpoint.rollback()
                    raise AssertionError('restored_enum_check_did_not_reject_invalid_value')
        finally:
            transaction.rollback()
    return evidence


def seed_legacy(database):
    """Synthetic pre-008 rows inserted once into freshly created old tables."""
    from tire_api.db import AlertRule, AlertRuleRevision, MonitorJob, MonitorRun, UserSession, uid, utcnow
    from tire_api.recall_models import RecallMonitorJob, RecallMonitorRule, RecallMonitorRun, RecallRuleRevision
    from tire_api.monitor_task_models import MonitorTaskAttempt, MonitorTaskEvent
    from test_core import QUERY
    from test_recalls import CAMPAIGN
    owner, other = str(uuid4()), str(uuid4())
    jobs = {'tire': 'a' * 64, 'recall': 'b' * 64}
    old = utcnow() - timedelta(days=1)
    with database.sessions() as db:
        for session in (owner, other):
            db.add(UserSession(id=session, expires_at=utcnow() + timedelta(hours=4)))
        db.flush()
        db.add(MonitorJob(id=jobs['tire'], source_id='fixture', query=QUERY['query'], next_due_at=old, last_finished_at=old))
        db.add(RecallMonitorJob(id=jobs['recall'], session_id=owner, campaign_number=CAMPAIGN, next_due_at=old, last_finished_at=old))
        db.flush()
        tire_rule, recall_rule = uid(), uid()
        db.add(AlertRule(id=tire_rule, job_id=jobs['tire']))
        db.add(RecallMonitorRule(id=recall_rule, session_id=owner, job_id=jobs['recall']))
        db.flush()
        db.add(AlertRuleRevision(rule_id=tire_rule, revision=1, name='Synthetic old tire rule', enabled=False,
            archived=False, interval_seconds=21600, kinds=['facts_changed'], fields=[], conditions={}, actor_session_id=owner))
        db.add(RecallRuleRevision(rule_id=recall_rule, revision=1, name='Synthetic old campaign rule', enabled=True,
            archived=False, interval_seconds=21600))
        for kind, run_model, query, source in (
            ('tire', MonitorRun, QUERY['query'], 'fixture'),
            ('recall', RecallMonitorRun, {'campaign_number': CAMPAIGN}, 'nhtsa-us-recalls'),
        ):
            attempt_id, run_id = uid(), uid()
            db.add(run_model(id=run_id, job_id=jobs[kind], lease_token='synthetic-pre008-' + kind,
                state='live', reason=None, started_at=old, finished_at=old + timedelta(seconds=2)))
            db.add(MonitorTaskAttempt(id=attempt_id, kind=kind, job_id=jobs[kind], source_id=source,
                query=query, lease_token_hash=hashlib.sha256(('synthetic-pre008-' + kind).encode()).hexdigest(),
                source_access_generation=0, started_at=old))
            db.flush()
            for sequence, phase in enumerate(('claimed', 'running', 'finished'), 1):
                db.add(MonitorTaskEvent(id=uid(), attempt_id=attempt_id, kind=kind, job_id=jobs[kind],
                    sequence=sequence, phase=phase, state='succeeded' if phase == 'finished' else 'running',
                    result_state='live' if phase == 'finished' else None,
                    run_id=run_id if phase == 'finished' else None, created_at=old + timedelta(seconds=sequence)))
        db.commit()
    return owner, other, jobs


def run():
    global STEP
    root = guards()
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.engine import URL
    from tire_api.db import Base, Database, RawCapture, QueryRun, utcnow
    from tire_api.main import SESSION_COOKIE, create_app
    from tire_api.monitor_tasks import task_detail, event_page
    from tire_api.recall_models import RecallMonitorJob
    from tire_api.recall_discovery_monitor_models import RecallDiscoveryJob, RecallDiscoveryRun, RecallDiscoveryPage, RecallDiscoveryCandidate, RecallDiscoveryNotification
    from tire_api.recall_discovery import RecallSearchVerification
    from tire_api.captures import checked_capture_bytes
    from test_source_access import RecordingRegistry
    admin = psycopg.connect(host='127.0.0.1', port=55443, user='tire_discovery_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = writers = None
    previous.REPORT = REPORT
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == root / 'data'
        REPORT.update(postgres_version=admin.execute('SHOW server_version').fetchone()[0], parent_pid=os.getpid(),
            admin_backend_pid=admin.execute('SELECT pg_backend_pid()').fetchone()[0],
            postmaster_pid=int((root / 'data/postmaster.pid').read_text().splitlines()[0]))
        role, password = 'discovery_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                host='127.0.0.1', port=55443, database=name).render_as_string(hide_password=False)

        name = 'discovery_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        with database.engine.connect() as connection:
            assert connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user')).scalar_one() is False
            assert not inspect(connection).get_table_names()
        record('owned_loopback_cluster_and_application_role_without_admin_privileges')

        STEP = 'fresh_legacy_subset_then_additive_initialize'
        # Register all current models, then create only pre-008 tables directly.
        # No existing table is removed to synthesize an old database.
        from tire_api import parser_release_models, identity_models, identity_contract_models, fitment_relation_models, golden_models, source_setting_models, monitor_task_models, vehicles  # noqa: F401
        legacy_tables = [table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES]
        registered_before = set(Base.metadata.tables)
        assert NEW_TABLES <= set(Base.metadata.tables)
        with database.engine.begin() as connection:
            Base.metadata.create_all(connection, tables=legacy_tables)
            connection.exec_driver_sql('CREATE TABLE tire_schema_versions (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            for version in sorted(OLD_VERSIONS):
                connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:version)'), {'version': version})
            actual_tables_before = set(inspect(connection).get_table_names())
            assert not NEW_TABLES.intersection(actual_tables_before)
        owner, other, jobs = seed_legacy(database)
        old_rows = fingerprints(database, SimpleNamespace(sorted_tables=legacy_tables))
        old_schema = journal_schema(database)
        old_cursors, old_pages = {}, {}
        with database.sessions() as db:
            for kind in ('tire', 'recall'):
                initial = event_page(db, kind, jobs[kind], owner)
                old_cursors[kind] = initial['items'][0]['cursor']
                old_pages[kind] = strip_clock(event_page(db, kind, jobs[kind], owner, cursor=old_cursors[kind]))
                assert task_detail(db, kind, jobs[kind], owner)['task']['state'] == 'succeeded'
        database.initialize()
        database.initialize()
        assert set(Base.metadata.tables) == registered_before, 'startup_registered_unexpected_table'
        assert journal_schema(database) == old_schema
        initialized = fingerprints(database, Base.metadata)
        assert {key: initialized[key] for key in old_rows} == old_rows
        assert all(initialized[name]['rows'] == 0 for name in NEW_TABLES)
        with database.engine.connect() as connection:
            actual_tables_after = set(inspect(connection).get_table_names())
            assert actual_tables_after - actual_tables_before == NEW_TABLES
            assert not actual_tables_before - actual_tables_after
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            assert versions == OLD_VERSIONS | {MIGRATION}
        with database.sessions() as db:
            for kind in old_cursors:
                assert strip_clock(event_page(db, kind, jobs[kind], owner, cursor=old_cursors[kind])) == old_pages[kind]
        record('fresh_legacy_subset_adds_nine_tables_twice_preserving_old_schema_rows_ids_and_cursors')
        database.close()
        database = None

        STEP = 'api_scope_and_cross_queue_process_race'
        app, stranger_app = create_app(url, RecordingRegistry()), create_app(url, RecordingRegistry())
        expected_details, expected_events, cursors = {}, {}, dict(old_cursors)
        with TestClient(app, cookies={SESSION_COOKIE: owner}) as client, TestClient(stranger_app, cookies={SESSION_COOKIE: other}) as stranger:
            database = app.state.database
            payload = {'query': {'search': 'SYNTHETIC PG DISCOVERY'}, 'name': 'Synthetic PG discovery', 'enabled': True, 'interval_seconds': 21600}
            created = client.post('/v1/recall-discovery-rules', json=payload, headers={'Idempotency-Key': str(uuid4())})
            assert created.status_code == 201
            rule = created.json()
            jobs['recall_discovery'] = rule['job']['id']
            path = '/v1/monitor-tasks/recall_discovery/' + rule['job']['id']
            assert stranger.get('/v1/recall-discovery-rules/' + rule['id'] + '?mode=history').status_code == 404
            for suffix in ('', '/events', '/events/stream'):
                assert stranger.get(path + suffix).status_code == 404
            assert stranger.get('/v1/recall-discovery-notifications').json()['total'] == 0
            record('discovery_rule_task_and_notifications_are_session_private')

            def assert_discovery_state(expected):
                detail_state = client.get(path).json()['task']['state']
                assert detail_state == expected
                rows = []
                for wanted in ('running', 'result_unknown', 'succeeded', 'failed', 'interrupted'):
                    response = client.get('/v1/monitor-tasks', params={'kind': 'recall_discovery',
                        'rule_id': rule['id'], 'state': wanted})
                    assert response.status_code == 200
                    page = response.json()
                    assert page['total'] == (1 if wanted == expected else 0)
                    assert all(row['job_id'] == jobs['recall_discovery'] and row['state'] == wanted for row in page['items'])
                    rows.append({'filter': wanted, 'total': page['total']})
                REPORT.setdefault('discovery_state_filter_checks', []).append({'projection': expected, 'filters': rows})

            writers = Writers(root, url)
            winner, claim = writers.start('cross-lane', ['recall', 'recall_discovery'])
            REPORT['cross_queue_winner'] = claim['kind']
            assert client.get('/v1/monitor-tasks/' + claim['kind'] + '/' + claim['job_id']).json()['task']['state'] == 'running'
            assert writers.finish(winner)['finalized'] is True
            time.sleep(2.2)
            remaining = 'recall_discovery' if claim['kind'] == 'recall' else 'recall'
            next_writer, _ = writers.start('remaining-lane', [remaining])
            assert writers.finish(next_writer)['finalized'] is True
            with database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(RecallDiscoveryCandidate)) == 1
                assert db.scalar(select(func.count()).select_from(RecallDiscoveryNotification)) == 0
            record('two_independent_processes_exclude_campaign_and_discovery_claims_on_one_source')

            def due_discovery():
                time.sleep(2.2)
                with database.sessions() as db:
                    db.get(RecallDiscoveryJob, jobs['recall_discovery']).next_due_at = utcnow() - timedelta(seconds=1)
                    db.commit()

            STEP = 'complete_new_candidate_receipts'
            due_discovery()
            name_new, new_claim = writers.start('new-candidate', ['recall_discovery'], mode='new')
            cursors['recall_discovery'] = client.get(path).json()['cursor']
            assert_discovery_state('running')
            completed = writers.finish(name_new)
            assert completed['finalized'] is True and completed['page_queries'] == 4
            assert_discovery_state('succeeded')
            notices = client.get('/v1/recall-discovery-notifications').json()
            assert notices['total'] == 1 and notices['items'][0]['candidate']['campaign_number'] == '26T009000'
            runs = client.get('/v1/recall-discovery-runs', params={'job_id': jobs['recall_discovery'], 'mode': 'history'}).json()
            assert runs['items'][0]['coverage']['status'] == 'complete'
            run_id = runs['items'][0]['id']
            detail = client.get('/v1/recall-discovery-runs/' + run_id, params={'mode': 'history', 'page_limit': 2}).json()
            second = client.get('/v1/recall-discovery-runs/' + run_id, params={'mode': 'history', 'page_offset': 2, 'page_limit': 2}).json()
            assert detail['pages_total'] == 4 and len(detail['pages']) == len(second['pages']) == 2
            assert {row['pass_number'] for row in detail['pages']} == {1}
            assert {row['pass_number'] for row in second['pages']} == {2}
            with database.sessions() as db:
                for page in db.scalars(select(RecallDiscoveryPage).where(RecallDiscoveryPage.attempt_id == new_claim['attempt_id'])):
                    query = db.get(QueryRun, page.query_id)
                    verification = db.get(RecallSearchVerification, page.verification_id)
                    assert query.fallback_policy == 'never' and query.query['offset'] == str(page.offset)
                    assert verification.query_id == query.id and verification.snapshot_id == page.snapshot_id
            assert stranger.get('/v1/recall-discovery-runs/' + run_id + '?mode=history').status_code == 404
            record('double_pass_receipts_query_snapshot_verification_and_page_two_new_candidate_notification')

            STEP = 'old_worker_late_completion'
            due_discovery()
            old_writer, old_claim = writers.start('old-late', ['recall_discovery'], mode='later', scan_before_finish=True)
            scanned, = writers.collect([old_writer], 'scanned')
            assert scanned['state'] == 'discovery_complete' and scanned['page_queries'] == 4
            with database.sessions() as db:
                # Simulate a legacy process changing an opaque active lease.
                # The SQL filter must detect the hash mismatch in the new lane.
                db.get(RecallDiscoveryJob, jobs['recall_discovery']).lease_token = str(uuid4())
                db.commit()
            before_unknown_reads = fingerprints(database, Base.metadata)
            assert_discovery_state('result_unknown')
            assert fingerprints(database, Base.metadata) == before_unknown_reads
            record('new_journal_pg_lease_hash_state_filters_match_pure_read_projection')
            with database.sessions() as db:
                job = db.get(RecallDiscoveryJob, jobs['recall_discovery'])
                job.lease_until = utcnow() - timedelta(seconds=1)
                job.next_due_at = utcnow() - timedelta(seconds=1)
                db.commit()
            replacement, replacement_claim = writers.start('replacement', ['recall_discovery'], mode='new')
            assert replacement_claim['attempt_id'] != old_claim['attempt_id']
            with database.sessions() as db:
                replacement_token = db.get(RecallDiscoveryJob, jobs['recall_discovery']).lease_token
                counts_before = [db.scalar(select(func.count()).select_from(model)) for model in (RecallDiscoveryRun, RecallDiscoveryCandidate, RecallDiscoveryNotification)]
            assert writers.finish(old_writer)['finalized'] is False
            with database.sessions() as db:
                assert db.get(RecallDiscoveryJob, jobs['recall_discovery']).lease_token == replacement_token
                assert [db.scalar(select(func.count()).select_from(model)) for model in (RecallDiscoveryRun, RecallDiscoveryCandidate, RecallDiscoveryNotification)] == counts_before
            assert writers.finish(replacement)['finalized'] is True
            with database.sessions() as db:
                assert set(db.scalars(select(RecallDiscoveryCandidate.campaign_number))) == {'26T008000', '26T009000'}
                assert db.scalar(select(func.count()).select_from(RecallDiscoveryNotification)) == 1
            record('old_process_with_complete_page_evidence_cannot_commit_after_lease_replacement')
            writers.close()
            for kind in ('tire', 'recall', 'recall_discovery'):
                task_path = '/v1/monitor-tasks/' + kind + '/' + jobs[kind]
                expected_details[kind] = strip_clock(client.get(task_path).json())
                expected_events[kind] = strip_clock(client.get(task_path + '/events', params={'cursor': cursors[kind]}).json())
                assert stream_rows(client, task_path, cursors[kind]) == expected_events[kind]['items']
                assert stranger.get(task_path).status_code == (200 if kind == 'tire' else 404)
            with database.sessions() as db:
                for table in ('ai_requests', 'embedding_requests', 'fallback_consents'):
                    assert db.execute(text('SELECT count(*) FROM ' + table)).scalar_one() == 0
                captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
                assert captures
                for capture_id, raw_hash in captures:
                    body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                    assert location == 'object_store' and hashlib.sha256(body).hexdigest() == raw_hash
            frozen_rows = fingerprints(database, Base.metadata)
        database = None

        STEP = 'all_values_and_objects_dump_restore'
        save_atomic(root / 'frozen-row-hashes.json', frozen_rows)
        save_atomic(root / 'legacy-journal-schema-before.json', old_schema)
        dump_source = Database(url)
        try:
            save_atomic(root / 'pre-dump-row-hashes.json', fingerprints(dump_source, Base.metadata))
        finally:
            dump_source.close()
        restored_name = 'restored_discovery_' + uuid4().hex[:10]
        restored_url = new_database(restored_name)
        archive = root / 'discovery.dump'
        child_env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55443', 'PGUSER': role, 'PGPASSWORD': password}
        child_env.pop('TIRE_PG_TEST_PASSWORD', None)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        for command in ([str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password', '--dbname', name, '--file', str(archive)],
                        [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password', '--dbname', restored_name, str(archive)]):
            assert subprocess.run(command, env=child_env, capture_output=True, timeout=60).returncode == 0, 'private_dump_restore_failed'
        object_hashes = file_hashes(root / 'objects')
        destination = root / 'restored-objects'
        assert object_hashes and not destination.exists()
        shutil.copytree(root / 'objects', destination)
        assert file_hashes(destination) == object_hashes
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        save_atomic(root / 'restored-pre-initialize-row-hashes.json', fingerprints(restored, Base.metadata))
        restored.initialize()
        restored_rows = fingerprints(restored, Base.metadata)
        restored_schema = journal_schema(restored)
        save_atomic(root / 'restored-row-hashes.json', restored_rows)
        save_atomic(root / 'legacy-journal-schema-restored.json', restored_schema)
        changed_tables = sorted(name for name in frozen_rows.keys() | restored_rows.keys()
            if frozen_rows.get(name) != restored_rows.get(name))
        REPORT['dump_restore_comparison'] = {
            'all_column_values_match': restored_rows == frozen_rows,
            'legacy_journal_schema_raw_match': restored_schema == old_schema,
            'legacy_journal_schema_match': restored_journal_schema(restored_schema) == restored_journal_schema(old_schema),
            'schema_normalization': 'Only four exact PG18 enum ARRAY varchar-to-text cast equivalents',
            'changed_tables': changed_tables,
            'before': public_fingerprints({name: frozen_rows[name] for name in changed_tables if name in frozen_rows}),
            'after': public_fingerprints({name: restored_rows[name] for name in changed_tables if name in restored_rows}),
        }
        if restored_schema != old_schema:
            REPORT['dump_restore_comparison'].update(legacy_schema_before=old_schema,
                legacy_schema_after=restored_schema)
        assert restored_rows == frozen_rows, 'restored_registered_column_values_changed'
        assert restored_journal_schema(restored_schema) == restored_journal_schema(old_schema), 'restored_legacy_journal_schema_changed'
        REPORT['restored_enum_constraint_checks'] = verify_restored_journal_checks(restored)
        assert fingerprints(restored, Base.metadata) == frozen_rows
        record('restored_old_journal_rejects_invalid_enums_by_original_check_names_and_sqlstate')
        with restored.sessions() as db:
            assert set(db.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == versions
            for capture_id, raw_hash in captures:
                body, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(body).hexdigest() == raw_hash
        restored.close()
        restored = None
        record('dump_restore_all_registered_values_schema_versions_object_bytes_and_old_journal_schema')
        with TestClient(create_app(restored_url, RecordingRegistry()), cookies={SESSION_COOKIE: owner}) as client, \
             TestClient(create_app(restored_url, RecordingRegistry()), cookies={SESSION_COOKIE: other}) as stranger:
            for kind in ('tire', 'recall', 'recall_discovery'):
                task_path = '/v1/monitor-tasks/' + kind + '/' + jobs[kind]
                assert strip_clock(client.get(task_path).json()) == expected_details[kind]
                replay = client.get(task_path + '/events', params={'cursor': cursors[kind]}).json()
                assert strip_clock(replay) == expected_events[kind]
                assert stream_rows(client, task_path, cursors[kind]) == expected_events[kind]['items']
                assert stranger.get(task_path).status_code == (200 if kind == 'tire' else 404)
            assert client.get('/v1/recall-discovery-notifications').json()['total'] == 1
            assert stranger.get('/v1/recall-discovery-notifications').json()['total'] == 0
        record('old_and_new_opaque_cursors_resume_original_events_after_restore_with_session_scope')
        assert not (root / 'import-guard.sqlite').exists()
        REPORT.update(status='passed', migration=MIGRATION, additive_tables=sorted(NEW_TABLES),
            actual_added_tables=sorted(actual_tables_after - actual_tables_before),
            actual_removed_tables=sorted(actual_tables_before - actual_tables_after),
            registered_metadata_table_names=sorted(registered_before),
            legacy_journal_schema_unchanged=True, table_rebuilds=0, tables_checked=len(frozen_rows),
            columns_checked=sum(len(value['columns']) for value in frozen_rows.values()),
            schema_versions=sorted(versions), table_fingerprints=public_fingerprints(frozen_rows),
            restored_table_fingerprints=public_fingerprints(restored_rows), capture_count=len(captures),
            object_file_count=len(object_hashes), object_hashes=object_hashes,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), archive_bytes=archive.stat().st_size,
            real_source_calls=0, real_parser_children=0, real_ai_calls=0, real_embedding_calls=0,
            normal_database_used=False, sse_test_window_seconds=0.06,
            fingerprint_scope='All Base.metadata columns and row values plus schema versions and object hashes; not roles, ACL or cross-host recovery')
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
    with patch.object(SafeHttpClient, '_request', side_effect=AssertionError('real_source_transport_forbidden')) as transport, \
         patch.object(parser_runtime, '_run_sync', side_effect=AssertionError('real_parser_execution_forbidden')) as parser:
        result = action()
        assert transport.call_count == parser.call_count == 0
        return result


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
    report = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert report.parent.parent == (ROOT / '.artifacts/runtime').resolve() and report.parent.name.startswith('round43-discovery-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

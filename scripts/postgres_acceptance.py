"""Real PostgreSQL persistence/backup validation using explicitly synthetic inputs.

Only runs against the fresh loopback cluster created by verify-postgres.ps1.
Never prints connection credentials or accepts an arbitrary production DB URL.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import subprocess
import shutil
import sys
from threading import Barrier
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql
from sqlalchemy import select, text
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from test_core import FixtureRegistry, QUERY, VARIANT, grant, live, success
from test_vehicles import FixtureVehicleAdapter
from tire_api.db import Base, Database, FactVersion, FallbackConsent, QueryRun, RawCapture, UserSession, utcnow
from tire_api.captures import before_parse_recorder
from tire_api.domain import LiveQueryRequest
from tire_api.curation import RevisionRequest, append_revision
from tire_api.lifecycle import LifecycleRequest, append_lifecycle_event
from tire_api.main import create_app
from tire_api.service import QueryService
from tire_api.vehicles import register_vehicle_routes
from tire_api.adapters import xiaomi

REPORT: dict = {"checks": [], "data": "synthetic fixtures in isolated real PostgreSQL"}
STEP = "environment_guard"


def record(name: str):
    REPORT['checks'].append(name)
    print(json.dumps({"check": name, "status": "passed"}), flush=True)


def assert_status(response, expected=200):
    assert response.status_code == expected, f"Unexpected HTTP status: {response.status_code}"
    return response.json()


def database_fingerprint(database: Database) -> dict:
    """Hash every persisted row, including evidence bodies and all audit tables."""
    result = {}
    with database.engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            rows = [dict(row) for row in connection.execute(table.select()).mappings()]
            serialized = sorted(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) for row in rows)
            result[table.name] = {"rows": len(rows), "sha256": hashlib.sha256('\n'.join(serialized).encode()).hexdigest()}
        versions = list(connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars())
        result['schema_versions'] = versions
    return result


def run():
    global STEP
    expected_data = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    root = (ROOT / '.artifacts/postgres').resolve()
    assert expected_data.is_relative_to(root) and expected_data.name == 'data'
    assert expected_data.parent.name.startswith('pgverify-')
    port = int(os.environ['TIRE_PG_TEST_PORT'])
    password = os.environ['TIRE_PG_TEST_PASSWORD']
    admin = psycopg.connect(host='127.0.0.1', port=port, user='tire_verify_admin', password=password,
                           dbname='postgres', autocommit=True, connect_timeout=5)
    assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected_data
    REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
    REPORT['vector_available'] = bool(admin.execute("SELECT 1 FROM pg_available_extensions WHERE name='vector'").fetchone())
    role = 'tire_app_' + uuid4().hex[:12]
    app_password = secrets.token_hex(32)
    admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(role), sql.Literal(app_password)))
    name = 'tire_verify_' + uuid4().hex[:12]

    def new_database(dbname):
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(dbname), sql.Identifier(role)))
        return URL.create('postgresql+psycopg', username=role, password=app_password, host='127.0.0.1', port=port, database=dbname).render_as_string(hide_password=False)

    url = new_database(name)
    record('isolated_cluster_and_non_superuser_application_role')
    STEP = 'concurrent_empty_database_startup'
    barrier = Barrier(4)

    def initialize(_):
        database = Database(url)
        try:
            barrier.wait(timeout=10)
            database.initialize()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialize, range(4)))
    record(STEP)

    STEP = 'api_evidence_curation_and_fallback'
    registry = FixtureRegistry()
    app = create_app(url, registry)
    vehicle_adapter = FixtureVehicleAdapter()
    register_vehicle_routes(app, vehicle_adapter)
    with TestClient(app) as client:
        assert client.get('/health').json()['database'] == 'postgresql'
        result = assert_status(live(client))
        assert result['data_state'] == 'live'
        vid = result['variants'][0]['id']
        snapshot_id = result['provenance'][0]['snapshot_id']
        evidence = assert_status(client.get(f'/v1/evidence/{snapshot_id}'))
        assert hashlib.sha256(evidence['body'].encode()).hexdigest() == evidence['raw_hash']
        assert_status(client.post('/v1/watchlists', json={'variant_id': vid}), 201)
        view = assert_status(client.get(f'/v1/tire-variants/{vid}/fact-review', params={'source_id': 'fixture', 'mode': 'history'}))
        edit = {'source_id': 'fixture', 'base_fact_id': view['base_fact_id'], 'expected_revision': 0,
                'field': 'utqg_treadwear', 'action': 'manual_override', 'value': 420,
                'operator': 'PostgreSQL verification', 'reason': 'Synthetic manual correction for persistence test',
                'evidence': [{'snapshot_id': snapshot_id, 'locator': 'synthetic fixture UTQG'}]}
        changed = assert_status(client.post(f'/v1/tire-variants/{vid}/fact-revisions', json=edit), 201)
        assert changed['source_facts']['utqg_treadwear'] == 300 and changed['effective_facts']['utqg_treadwear'] == 420
        compare = assert_status(client.post('/v1/compare', json={'variant_ids': [vid], 'include_manual': True}))
        assert compare['variants'][0]['effective_facts']['utqg_treadwear'] == 420
        registry.result = {'status': 'unavailable', 'reason': 'pg_test_outage'}
        pending = assert_status(live(client))
        assert pending['data_state'] == 'consent_required' and not pending['variants']
        approval = assert_status(grant(client, pending['query_id']), 201)
        approved = {**QUERY, 'consent_id': approval['id']}
        local = assert_status(live(client, approved))
        assert local['data_state'] == 'local_snapshot' and local['variants'] == result['variants']
        assert live(client, approved).status_code == 409
        record(STEP)

        STEP = 'concurrent_single_use_consent'
        pending = assert_status(live(client))
        approval = assert_status(grant(client, pending['query_id']), 201)
        with app.state.database.sessions() as db:
            actor = db.get(FallbackConsent, approval['id']).session_id
        claim_gate = Barrier(2)

        def claim(_):
            with app.state.database.sessions() as db:
                claim_gate.wait(timeout=10)
                try:
                    answer = asyncio.run(QueryService(db, registry).execute('fixture', LiveQueryRequest.model_validate({**QUERY, 'consent_id': approval['id']}), actor))
                    assert answer['data_state'] == 'local_snapshot'
                    return 200
                except HTTPException as error:
                    return error.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(claim, range(2))) == [200, 409]
        record(STEP)

        STEP = 'quality_quarantine_and_304_cache'
        broken = deepcopy(VARIANT)
        broken['facts'] = {}
        for field in ('load_index', 'speed_rating', 'xl', 'hl', 'oe_mark', 'acoustic_technology', 'run_flat'):
            broken[field] = None
        registry.result = success('synthetic broken parser', variants=[broken], parser_version='fixture@broken')
        rejected = assert_status(live(client))
        assert rejected['reason'] == 'source_quality_quarantined' and not rejected['variants']
        registry.result = {'status': 'not_modified', 'url': evidence['source_url'], 'parser_version': 'fixture@1', 'etag': '"fixture-etag"'}
        verified = assert_status(live(client))
        assert verified['data_state'] == 'live_verified_304' and verified['variants'] == result['variants']
        assert verified['snapshot_observed_at'] == result['snapshot_observed_at']
        record(STEP)

        STEP = 'rejected_response_binary_evidence'
        rejected_body = '合成解析失败原文\x00<script>not executable</script>'
        registry.result = {'status': 'unavailable', 'reason': 'parser_schema_changed', 'rejected_observation': {
            'url': evidence['source_url'], 'body': rejected_body, 'content_type': 'text/html', 'parser_version': 'fixture@bad'}}
        failed_parse = assert_status(live(client))
        assert not failed_parse['variants'] and not failed_parse['provenance']
        capture = client.get('/v1/quarantines').json()['items'][0]
        assert capture['kind'] == 'response_rejected' and capture['metrics'] is None
        raw = client.get(capture['evidence_path']).json()
        assert raw['body'] == rejected_body and raw['raw_hash'] == hashlib.sha256(rejected_body.encode()).hexdigest()
        assert registry.calls[-1][2]['body'] == 'fixture-body-v1'
        record(STEP)

        STEP = 'vehicle_persistence_and_consent'
        vehicle_url = f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments'
        vehicle = assert_status(client.post(vehicle_url, json={'fallback_policy': 'ask'}))
        assert vehicle['data_state'] == 'live' and vehicle['fitments']
        vehicle_adapter.result = {'status': 'unavailable', 'reason': 'pg_vehicle_test_outage'}
        failed = assert_status(client.post(vehicle_url, json={'fallback_policy': 'ask'}))
        allowed = assert_status(grant(client, failed['query_id']), 201)
        fallback = assert_status(client.post(vehicle_url, json={'fallback_policy': 'ask', 'consent_id': allowed['id']}))
        assert fallback['fitments'] == vehicle['fitments'] and fallback['snapshot_observed_at'] == vehicle['snapshot_observed_at']
        record(STEP)
        cookies = dict(client.cookies)

        STEP = 'garage_records_fitment_copy_and_restore'
        from test_garage import PROFILE
        car = assert_status(client.post('/v1/garage', json=PROFILE), 201)
        garage_id = car['id']
        assigned = assert_status(client.post(f'/v1/garage/{garage_id}/tires', json={
            'expected_revision': 1, 'axle': 'rear', 'variant_id': vid}))
        assert assigned['current_tires']['rear']['id'] == vid and assigned['revision'] == 2
        edited_car = assert_status(client.put(f'/v1/garage/{garage_id}', json={
            'expected_revision': 2, 'profile': {**assigned['profile'], 'nickname': 'PG 合成车库记录'}}))
        assert edited_car['revision'] == 3
        assert_status(client.post(f'/v1/garage/{garage_id}/state', json={'expected_revision': 3, 'action': 'archive'}))
        assert client.get('/v1/garage').json()['items'] == []
        restored_car = assert_status(client.post(f'/v1/garage/{garage_id}/state', json={'expected_revision': 4, 'action': 'restore'}))
        assert restored_car['revision'] == 5 and not restored_car['archived']
        assert len(client.get(f'/v1/garage/{garage_id}?mode=history').json()['history']) == 5
        fitment = next(row for row in vehicle['fitments'] if row['availability'] == 'standard')
        copied = assert_status(client.post('/v1/garage/from-fitment', json={
            'snapshot_id': vehicle['provenance'][0]['snapshot_id'], 'fitment_id': fitment['id'], 'nickname': 'PG 合成配置复制'}), 201)
        assert copied['profile']['model_year'] is None and copied['current_tires']['front'] is None
        assert copied['fitment_reference']['raw_hash'] == vehicle['provenance'][0]['raw_hash']
        record(STEP)

        STEP = 'frozen_comparison_and_metadata_history'
        compared = assert_status(client.post('/v1/compare', json={'variant_ids': [vid], 'include_manual': True}))
        saved_comparison = assert_status(client.post('/v1/saved-comparisons', json={
            'variant_ids': [vid], 'include_manual': True, 'expected_fingerprint': compared['fingerprint'],
            'title': 'PG 合成保存比较', 'notes': '真实 PostgreSQL、合成事实数据'}), 201)
        saved_id = saved_comparison['id']
        assert_status(client.put(f'/v1/saved-comparisons/{saved_id}', json={
            'expected_revision': 1, 'title': 'PG 修改记录说明', 'notes': '固定事实不改动'}))
        for revision, action in [(2, 'archive'), (3, 'restore')]:
            assert_status(client.post(f'/v1/saved-comparisons/{saved_id}/state', json={'expected_revision': revision, 'action': action}))
        saved_detail = assert_status(client.get(f'/v1/saved-comparisons/{saved_id}?mode=history'))
        assert saved_detail['comparison'] == compared and len(saved_detail['history']) == 4
        record(STEP)

        STEP = 'personal_preferences_do_not_rewrite_facts'
        weights = {'dry': 20, 'wet': 25, 'quiet': 20, 'comfort': 10, 'wear': 15, 'energy': 5, 'appearance': 5}
        preferences = assert_status(client.put('/v1/driving-preferences', json={'expected_revision': 0, 'weights': weights}))
        assert preferences['revision'] == 1 and preferences['weights'] == weights
        assert client.post('/v1/compare', json={'variant_ids': [vid], 'include_manual': True}).json() == compared
        cleared = assert_status(client.post('/v1/driving-preferences/clear', json={'expected_revision': 1}))
        assert cleared['weights'] is None and cleared['history'][1]['weights'] == weights
        record(STEP)

        STEP = 'pre_parser_receipt_survives_downstream_rollback'
        with app.state.database.sessions() as db:
            parent_run = db.get(QueryRun, failed_parse['query_id'])
            run = QueryRun(session_id=parent_run.session_id, source_id='fixture', query_key='pg-receipt',
                           query={'model': 'Fixture Tire'}, fallback_policy='never')
            db.add(run)
            db.commit()
            before_parse_recorder(db, run)({'url': evidence['source_url'], 'body': rejected_body,
                'content_type': 'text/html', 'parser_version': 'fixture@receipt'})
            with app.state.database.sessions() as independently_visible:
                saved = independently_visible.scalar(select(RawCapture).where(RawCapture.query_id == run.id))
                assert saved.raw_body == rejected_body.encode() and saved.byte_count == len(rejected_body.encode())
                receipt_id = saved.id
            run.state = 'live'
            db.flush()
            db.rollback()
        journal = assert_status(client.get('/v1/captures?mode=history&pending_only=true'))
        assert any(row['id'] == receipt_id and row['processing_unconfirmed'] for row in journal['items'])
        detail = assert_status(client.get(f'/v1/captures/{receipt_id}?mode=history'))
        assert detail['body'] == rejected_body and detail['query_state'] == 'pending'
        record(STEP)

    STEP = 'legacy_migration_preserves_existing_data'
    with TestClient(create_app(url, registry)) as legacy_client:
        legacy_rule = assert_status(legacy_client.post('/v1/alert-rules', json={
            'name': '合成旧版无技术条件规则', 'source_id': 'fixture',
            'query': {'model': 'Fixture Tire'}, 'enabled': False}), 201)
    database = Database(url)
    with database.engine.begin() as connection:
        connection.exec_driver_sql('ALTER TABLE verifications DROP COLUMN etag, DROP COLUMN last_modified')
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version = '001_verification_validators'")
        connection.exec_driver_sql('ALTER TABLE alert_rule_revisions DROP COLUMN conditions')
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version = '002_monitor_rule_conditions'")
        for table in ('snapshots', 'verifications', 'raw_captures', 'rejected_observations',
                      'source_quarantines', 'vehicle_snapshots', 'vehicle_verifications', 'vehicle_quarantines'):
            connection.exec_driver_sql(f'ALTER TABLE {table} DROP COLUMN parser_identity')
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version = '003_parser_release_provenance'")
        connection.exec_driver_sql('ALTER TABLE query_runs DROP COLUMN selection_filters')
        connection.exec_driver_sql("DELETE FROM tire_schema_versions WHERE version = '004_query_selection_filters'")
    database.close()
    migrated = create_app(url, registry)
    with TestClient(migrated, cookies=cookies) as client:
        restored_evidence = assert_status(client.get(f'/v1/evidence/{snapshot_id}'))
        assert restored_evidence['body'] == evidence['body'] and restored_evidence['raw_hash'] == evidence['raw_hash']
        assert len(client.get('/v1/watchlists').json()['items']) == 1
        review = client.get(f'/v1/tire-variants/{vid}/fact-review', params={'source_id': 'fixture', 'mode': 'history'}).json()
        assert review['revision'] == 1 and review['effective_facts']['utqg_treadwear'] == 420
        with migrated.state.database.engine.connect() as connection:
            assert connection.execute(text('SELECT count(*) FROM verifications WHERE etag IS NOT NULL')).scalar() == 0
            assert connection.execute(text('SELECT count(*) FROM verifications WHERE parser_identity IS NOT NULL')).scalar() == 0
            assert connection.execute(text('SELECT count(*) FROM query_runs WHERE selection_filters IS NOT NULL')).scalar() == 0
            assert connection.execute(text('SELECT conditions FROM alert_rule_revisions WHERE rule_id=:id'),
                                      {'id': legacy_rule['id']}).scalar() is None
        migrated_rule = assert_status(client.get('/v1/alert-rules/' + legacy_rule['id'] + '?mode=history'))
        assert migrated_rule['conditions'] == {} and migrated_rule['name'] == legacy_rule['name']
        assert not migrated_rule['enabled'] and migrated_rule['history'][0]['conditions'] == {}
        migrated.state.database.initialize()
    record(STEP)

    STEP = 'api_worker_concurrent_ingestion'
    database = Database(url)
    database.initialize()
    ingestion_gate = Barrier(2)
    variant = deepcopy(VARIANT)
    variant.update(size='225/45R18', manufacturer_product_code='PG-CONCURRENT')

    class ConcurrentRegistry(FixtureRegistry):
        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            await asyncio.to_thread(ingestion_gate.wait, timeout=10)
            return success('concurrent fixture', variants=[variant])

    with database.sessions() as db:
        for actor_id in ('pg-api', 'pg-worker'):
            db.add(UserSession(id=actor_id, expires_at=utcnow() + timedelta(hours=1)))
        db.commit()

    def ingest(actor_id):
        with database.sessions() as db:
            return asyncio.run(QueryService(db, ConcurrentRegistry()).execute('fixture', LiveQueryRequest(query={'model': 'Fixture Tire', 'size': '225/45R18'}, fallback_policy='never'), actor_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = list(pool.map(ingest, ['pg-api', 'pg-worker']))
    assert all(answer['data_state'] == 'live' for answer in answers)
    assert answers[0]['variants'][0]['id'] == answers[1]['variants'][0]['id']
    race_id = answers[0]['variants'][0]['id']
    with database.sessions() as db:
        assert len(db.scalars(select(FactVersion).where(FactVersion.variant_id == race_id)).all()) == 1
    record(STEP)

    STEP = 'concurrent_manual_revision'
    edit_gate = Barrier(2)

    def revise(value):
        with database.sessions() as db:
            edit_gate.wait(timeout=10)
            try:
                state = append_revision(db, vid, RevisionRequest(**{**edit, 'expected_revision': 1, 'value': value}), 'pg-api')
                return state['revision']
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(revise, [440, 460])) == [2, 409]
    record(STEP)

    lifecycle_gate = Barrier(2)
    lifecycle_payload = {'action': 'revoke', 'expected_revision': 0, 'operator': 'PG 合成验收',
        'reason': '临时数据库模拟整实体撤销，不对真实产品作判断',
        'evidence': [{'snapshot_id': snapshot_id, 'locator': 'FIX-001 合成规格记录'}]}

    def change_lifecycle(_):
        with database.sessions() as db:
            lifecycle_gate.wait(timeout=10)
            try:
                return append_lifecycle_event(db, vid, LifecycleRequest(**lifecycle_payload), 'pg-api')['lifecycle']['revision']
            except HTTPException as error:
                return error.status_code

    STEP = 'concurrent_entity_withdrawal_and_restore'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(change_lifecycle, [1, 2])) == [1, 409]
    with database.sessions() as db:
        history = QueryService(db, registry).historical_variant(vid)
        assert history['lifecycle']['state'] == 'revoked' and history['facts']
        db.rollback()
        restored = append_lifecycle_event(db, vid, LifecycleRequest(**{
            **lifecycle_payload, 'action': 'restore', 'expected_revision': 1}), 'pg-api')
        assert restored['lifecycle']['state'] == 'active' and len(restored['history']) == 2
    record(STEP)

    STEP = 'worker_cycle_on_postgres'
    worker_spec = importlib.util.spec_from_file_location('pg_verification_worker', ROOT / 'apps/worker/monitor.py')
    worker = importlib.util.module_from_spec(worker_spec)
    worker_spec.loader.exec_module(worker)
    worker.registry = FixtureRegistry()
    cycle = asyncio.run(worker.run_cycle(database))
    assert cycle['jobs'] == 1 and cycle['results'][0]['state'] == 'live'
    record(STEP)

    STEP = 'transaction_rollback'
    from tire_api.monitoring import claim_job, finish_job
    from tire_api.db import MonitorJob
    monitor_registry = FixtureRegistry()
    with TestClient(create_app(url, monitor_registry)) as monitor_client:
        live(monitor_client)
        rule_payload = {'name': 'PG synthetic rule', 'source_id': 'fixture', 'query': QUERY['query'], 'enabled': True}
        for index in range(2):
            assert_status(monitor_client.post('/v1/alert-rules', json={**rule_payload, 'name': f'PG synthetic rule {index}'}), 201)
        monitor_registry.result = success('monitor change', [{**VARIANT, 'facts': {'utqg_treadwear': 501}}])
        live(monitor_client)
        live(monitor_client)
        notices = assert_status(monitor_client.get('/v1/notifications'))
        assert notices['total'] == 2 and all(item['previous_snapshot_id'] for item in notices['items'])
        assert_status(monitor_client.put('/v1/notifications/' + notices['items'][0]['id'] + '/read', json={'read': True}))
        assert assert_status(monitor_client.get('/v1/notifications?unread=true'))['total'] == 1
        record('transactional_monitor_rules_alerts_and_read_receipts')
        claim_barrier = Barrier(2)
        def concurrent_claim(_):
            claim_barrier.wait(timeout=10)
            return claim_job(database)
        with ThreadPoolExecutor(max_workers=2) as pool:
            claimed = list(pool.map(concurrent_claim, range(2)))
        assert sum(item is not None for item in claimed) == 1
        first_claim = next(item for item in claimed if item)
        with database.sessions() as db:
            db.get(MonitorJob, first_claim['id']).lease_until = utcnow() - timedelta(seconds=1)
            db.commit()
        second_claim = claim_job(database)
        assert second_claim and not finish_job(database, first_claim, 'live')
        assert finish_job(database, second_claim, 'live')
        assert_status(monitor_client.post('/v1/alert-rules', json={**rule_payload, 'source_id': 'fixture-two'}), 201)
        worker.registry = monitor_registry
        scheduled = asyncio.run(worker.run_scheduled_cycle(database, max_jobs=1))
        assert scheduled['jobs'] == 1 and scheduled['results'][0]['state'] == 'live' and scheduled['results'][0]['finalized']
        record('concurrent_scheduler_claim_recovery_fencing_and_worker')

    STEP = 'vehicle_quality_quarantine_and_authorized_baseline'
    quality_adapter = FixtureVehicleAdapter()
    quality_app = create_app(url, FixtureRegistry())
    register_vehicle_routes(quality_app, quality_adapter)
    with TestClient(quality_app) as quality_client:
        accepted = assert_status(quality_client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'never'}))
        assert accepted['data_state'] == 'live'
        dropped = quality_adapter.result['payload']['trims'].pop()
        quality_adapter.result['payload']['fitments'] = [row for row in quality_adapter.result['payload']['fitments'] if row['trim_id'] != dropped['id']]
        quality_adapter.result['body'] = json.dumps(quality_adapter.result['payload'], ensure_ascii=False)
        rejected = assert_status(quality_client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'ask'}))
        assert rejected['reason'] == 'source_quality_quarantined' and not rejected['fitments']
        quarantines = assert_status(quality_client.get('/v1/quarantines?source_id=' + xiaomi.SOURCE_ID))
        entry = next(row for row in quarantines['items'] if row['kind'] == 'field_loss')
        detail = assert_status(quality_client.get(entry['evidence_path']))
        assert detail['quality']['groups']['trims']['row_loss_ratio'] == .5
        consent = assert_status(grant(quality_client, rejected['query_id']), 201)
        offline = assert_status(quality_client.post(f'/v1/vehicles/{xiaomi.CURRENT_ID}/live-fitments', json={'fallback_policy': 'ask', 'consent_id': consent['id']}))
        assert offline['fitments'] == accepted['fitments'] and offline['provenance'] == accepted['provenance']
        source = next(row for row in assert_status(quality_client.get('/v1/source-health'))['sources'] if row['source_id'] == xiaomi.SOURCE_ID)
        assert source['status'] == 'quarantined' and source['last_success_at']
    record(STEP)

    STEP = 'transaction_rollback'
    with database.sessions() as db:
        db.add(UserSession(id='must-roll-back', expires_at=utcnow() + timedelta(hours=1)))
        db.flush()
        db.rollback()
    with database.sessions() as db:
        assert db.get(UserSession, 'must-roll-back') is None
    record(STEP)

    STEP = 'concurrent_quarantine_review_and_online_application'
    from test_quarantine_review import verify_concurrent_review
    verify_concurrent_review(url)
    record(STEP)

    STEP = 'test_event_history_restart_and_concurrent_revision'
    from test_test_events import verify_event_persistence
    verify_event_persistence(url)
    record(STEP)

    STEP = 'ai_evidence_ledger_concurrent_idempotency_restart'
    from unittest.mock import patch
    from test_ai import verify_ai_persistence
    with patch.dict(os.environ, {'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-model',
            'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
            'TI_AI_DAILY_TOKEN_LIMIT': '100000', 'TI_AI_DAILY_REQUEST_LIMIT': '20'}):
        verify_ai_persistence(url)
    record(STEP)

    STEP = 'binary_document_object_store_roundtrip'
    from test_object_store import PDF, upload as upload_document
    from tire_api.db import EvidenceObject
    from tire_api.object_store import FileObjectStore
    with TestClient(create_app(url, FixtureRegistry())) as document_client:
        document = assert_status(upload_document(document_client), 201)
        downloaded = document_client.get('/v1/documents/' + document['id'] + '/content?mode=history')
        assert downloaded.status_code == 200 and downloaded.content == PDF
        assert downloaded.headers['x-evidence-sha256'] == hashlib.sha256(PDF).hexdigest()
    record(STEP)

    STEP = 'knowledge_structured_fts_and_restart'
    from test_knowledge import verify_knowledge_persistence
    knowledge_checkpoint = verify_knowledge_persistence(url)
    record(STEP)

    STEP = 'monitor_identity_conditions_revisions_and_restart'
    from test_monitor_conditions import verify_monitor_conditions_persistence
    verify_monitor_conditions_persistence(url)
    record(STEP)

    STEP = 'monitor_ai_evidence_draft_idempotent_apply_and_restart'
    from test_ai_rule_drafts import assert_monitor_ai_checkpoint, verify_monitor_ai_persistence
    with patch.dict(os.environ, {'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-model',
            'TI_OPENAI_API_KEY': 'synthetic-key-never-live', 'TI_AI_ALLOW_PRIVATE': '1',
            'TI_AI_DAILY_TOKEN_LIMIT': '1000000', 'TI_AI_DAILY_REQUEST_LIMIT': '100'}):
        monitor_checkpoint = verify_monitor_ai_persistence(url)
    record(STEP)

    STEP = 'frozen_reports_revisions_exports_and_restart'
    from test_reports import assert_report_checkpoint, verify_report_persistence
    report_checkpoint = verify_report_persistence(url)
    record(STEP)

    STEP = 'historical_reparse_review_and_restart'
    from test_reparse import assert_reparse_checkpoint, verify_reparse_persistence
    reparse_checkpoint = verify_reparse_persistence(url)
    record(STEP)

    STEP = 'actual_parser_release_approval_a_b_a_and_restart'
    from test_parser_releases import assert_parser_release_checkpoint, verify_parser_release_persistence
    parser_checkpoint = verify_parser_release_persistence(url, expected_data.parent / 'parser-acceptance')
    parser_backup = expected_data.parent / 'parser-bundles.backup'
    shutil.copytree(parser_checkpoint['bundle_root'], parser_backup)
    record(STEP)

    STEP = 'recall_campaign_discovery_concurrent_consent_rules_leases_and_restart'
    from recall_acceptance import assert_recall_checkpoint, verify_recall_persistence
    recall_checkpoint = verify_recall_persistence(url)
    record(STEP)

    STEP = 'recall_historical_replay_signed_code_upgrade_rollback_and_restart'
    from test_recall_parser_releases import (assert_recall_parser_checkpoint,
                                            verify_recall_parser_persistence)
    recall_parser_checkpoint = verify_recall_parser_persistence(url, expected_data.parent / 'recall-parser-acceptance')
    # Restore the entire application against ONE archive root. Independent test
    # installs may share A's content hash; never overwrite an existing archive.
    recall_parser_root = Path(recall_parser_checkpoint['bundle_root'])
    for bundle_id in recall_parser_checkpoint['bundle_ids']:
        original = recall_parser_root / 'sha256' / bundle_id
        target = parser_backup / 'sha256' / bundle_id
        if target.exists():
            assert (target / 'manifest.json').read_bytes() == (original / 'manifest.json').read_bytes()
        else:
            shutil.copytree(original, target)
    record(STEP)

    STEP = 'query_filters_frozen_scope_full_snapshot_consent_and_restart'
    from query_filter_acceptance import assert_query_filter_checkpoint, verify_query_filter_persistence
    query_filter_checkpoint = verify_query_filter_persistence(url)
    record(STEP)

    # Identity acceptance freezes all source tables, including the shared raw
    # receipt journal. Complete both recall acceptance flows before freezing it.
    STEP = 'identity_decision_concurrent_cas_uuid_withdrawal_and_restart'
    from identity_acceptance import assert_identity_checkpoint, verify_identity_persistence
    identity_checkpoint = verify_identity_persistence(url)
    record(STEP)

    STEP = 'dump_restore_all_evidence_and_audit_tables'
    before = database_fingerprint(database)
    assert before['identity_revisions']['rows'] >= 3
    from tire_api.report_models import ReportExport
    with database.sessions() as db:
        object_manifest = [(row.raw_hash, row.byte_count) for row in db.scalars(select(EvidenceObject))]
        report_object_manifest = [(row.sha256, row.byte_count) for row in db.scalars(select(ReportExport))]
    object_backup = expected_data.parent / 'objects.backup'
    shutil.copytree(database.object_store.root, object_backup)
    database.close()
    archive = expected_data.parent / 'verification.backup'
    restore_name = 'tire_restore_' + uuid4().hex[:12]
    restored_url = new_database(restore_name)
    environment = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': str(port), 'PGUSER': role, 'PGPASSWORD': app_password}
    pg_bin = Path(os.environ['TIRE_PG_BIN'])
    for command in ([str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password', '--dbname', name, '--file', str(archive)],
                    [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password', '--dbname', restore_name, str(archive)]):
        completed = subprocess.run(command, env=environment, capture_output=True, timeout=60)
        assert completed.returncode == 0, 'PostgreSQL dump/restore command failed'
    restored = Database(restored_url)
    restored.initialize()
    STEP = 'restored_database_fingerprint'
    assert database_fingerprint(restored) == before
    STEP = 'restored_identity_checkpoint'
    assert_identity_checkpoint(restored_url, identity_checkpoint)
    STEP = 'restored_monitor_ai_checkpoint'
    assert_monitor_ai_checkpoint(restored_url, monitor_checkpoint)
    # Exercise report content downloads against the restored object copy, not
    # the original live directory which would conceal an incomplete backup.
    with patch.dict(os.environ, {'TI_OBJECT_STORE_ROOT': str(object_backup)}):
        STEP = 'restored_query_filter_checkpoint'
        assert_query_filter_checkpoint(restored_url, query_filter_checkpoint)
        STEP = 'restored_report_checkpoint'
        assert_report_checkpoint(restored_url, report_checkpoint)
        STEP = 'restored_reparse_checkpoint'
        assert_reparse_checkpoint(restored_url, reparse_checkpoint)
        STEP = 'restored_recall_checkpoint'
        assert_recall_checkpoint(restored_url, recall_checkpoint)
        with patch.dict(os.environ, {'TI_PARSER_BUNDLE_ROOT': str(parser_backup)}):
            STEP = 'restored_parser_release_checkpoint'
            assert_parser_release_checkpoint(restored_url, parser_checkpoint)
            STEP = 'restored_recall_parser_release_checkpoint'
            assert_recall_parser_checkpoint(restored_url, recall_parser_checkpoint)
    STEP = 'restored_knowledge_checkpoint'
    with TestClient(create_app(restored_url, FixtureRegistry())) as knowledge_client:
        restored_search = assert_status(knowledge_client.post('/v1/knowledge/search', json=knowledge_checkpoint['request']))
        assert all(reference in [item['reference'] for item in restored_search['items']]
                   for reference in knowledge_checkpoint['references'])
        assert 'postgres' in restored_search['index']['engine']
        assert any(stage['name'] == 'fts' and stage['state'] == 'succeeded' for stage in restored_search['stages'])
    backup_store = FileObjectStore(object_backup)
    STEP = 'restored_object_manifest'
    with restored.sessions() as db:
        for digest, size in object_manifest:
            assert db.get(EvidenceObject, digest).byte_count == size
            backup_store.get(digest, size)
        for digest, size in report_object_manifest:
            backup_store.get(digest, size)
    REPORT['object_backup_count'] = len(object_manifest)
    REPORT['object_backup_bytes'] = sum(size for _, size in object_manifest)
    REPORT['report_export_object_count'] = len(set(report_object_manifest))
    REPORT['report_export_object_bytes'] = sum(size for _, size in set(report_object_manifest))
    REPORT['parser_bundle_ids'] = sorted(set(parser_checkpoint['bundle_ids'] + recall_parser_checkpoint['bundle_ids']))
    REPORT['parser_bundle_backup_bytes'] = sum(path.stat().st_size for path in parser_backup.rglob('*') if path.is_file())
    REPORT['recall_parser_bundle_ids'] = recall_parser_checkpoint['bundle_ids']
    REPORT['recall_parser_bundle_backup_bytes'] = sum(
        path.stat().st_size for bundle_id in recall_parser_checkpoint['bundle_ids']
        for path in (parser_backup / 'sha256' / bundle_id).rglob('*') if path.is_file())
    REPORT['identity_revisions'] = before['identity_revisions']
    REPORT['recall_revisions'] = before['recall_revisions']
    REPORT['recall_search_snapshots'] = before['recall_search_snapshots']
    restored.close()
    REPORT['backup_bytes'] = archive.stat().st_size
    REPORT['tables_checked'] = len(Base.metadata.tables)
    record('dump_restore_all_evidence_and_audit_tables')
    record('restored_object_files_match_database_references')
    record('restored_postgres_full_text_query_preserves_references')
    record('restored_monitor_draft_origin_and_change_evidence')
    record('restored_report_exports_use_backup_object_directory')
    record('restored_reparse_lineage_review_and_original_object')
    record('restored_parser_approval_revision_and_actual_old_code_from_backup')
    record('restored_identity_relationship_evidence_history_and_original_uuid_events')
    record('restored_recall_campaign_discovery_raw_objects_rules_and_private_notifications')
    record('restored_recall_reparse_reviews_signed_upgrade_rollback_and_archived_code')
    record('restored_query_filters_full_snapshot_and_unconsumed_consent_scope')
    admin.close()
    REPORT['status'] = 'passed'


if __name__ == '__main__':
    status = 0
    try:
        run()
    except Exception as error:
        status = 1
        REPORT.update(status='failed', failure_step=STEP, error_type=type(error).__name__,
                      sqlstate=getattr(getattr(error, 'orig', error), 'sqlstate', None))
        import traceback
        REPORT['failure_frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__)
            if Path(frame.filename).resolve().is_relative_to(ROOT)]
    report_path = os.environ.get('TIRE_PG_TEST_REPORT')
    if report_path:
        Path(report_path).write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(REPORT, ensure_ascii=False, indent=2))
    sys.exit(status)

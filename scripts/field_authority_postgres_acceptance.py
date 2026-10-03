"""Private PG39 field-policy acceptance. All source responses are synthetic."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_field_policy_private_postgresql', 'checks': []}
STEP = 'isolation'


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def run():
    global STEP
    runtime = (ROOT / '.artifacts/runtime').resolve()
    run_root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    expected = Path(os.environ['TIRE_PG_TEST_DATA']).resolve()
    assert run_root.parent == runtime and run_root.name.startswith('round39-field-PG-')
    assert expected == run_root / 'data' and int(os.environ['TIRE_PG_TEST_PORT']) == 55439
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == run_root / 'report.json'
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    object_root = Path(os.environ['TI_OBJECT_STORE_ROOT']).resolve()
    assert object_root == run_root / 'objects' and os.environ['TI_OBJECT_STORE_BACKEND'] == 'filesystem'
    assert Path(os.environ['TI_PARSER_BUNDLE_ROOT']).resolve() == run_root / 'bundles'
    guard = 'sqlite:///' + (run_root / 'import-guard.sqlite').as_posix()
    assert os.environ['TIRE_DATABASE_URL'] == os.environ['DATABASE_URL'] == guard
    pg_bin = Path(os.environ['TIRE_PG_BIN']).resolve()
    assert pg_bin == Path('E:/PostgreSQL/18/bin').resolve()

    sys.path.insert(0, str(ROOT / 'apps/api'))
    sys.path.insert(0, str(ROOT / 'apps/api/tests'))
    import psycopg
    from psycopg import sql
    from sqlalchemy import event, func, select, text
    from sqlalchemy.engine import URL
    from fastapi.testclient import TestClient
    from tire_api.db import Base, Database, FactVersion, RawCapture, Snapshot
    from tire_api.ai_models import AIRequest
    from tire_api.embedding_models import EmbeddingRequest
    from tire_api.captures import checked_capture_bytes
    from tire_api.field_authority import policy_descriptor
    from tire_api.main import create_app
    from tire_api.db import utcnow
    from test_core import FixtureRegistry, success
    from test_field_evidence import known_variant
    from test_identity_resolution import decision, post

    class Registry(FixtureRegistry):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def sources(self):
            rows = [{**row, 'source_class': 'manufacturer_official' if row['id'] == 'fixture' else 'regulatory'}
                    for row in super().sources()]
            return rows + [{**rows[0], 'id': 'fixture-three', 'name': 'Synthetic second official source'}]

        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            self.calls += 1
            result = deepcopy(self.result)
            if result['status'] == 'ok':
                on_observation(result)
            return result

    def field_map(value):
        return {row['field']: row for row in value['fields']}

    def variant(code, model, **facts):
        return {**known_variant(**facts), 'manufacturer_product_code': code, 'model': model}

    admin = psycopg.connect(host='127.0.0.1', port=55439, user='tire_field_verify_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = None
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == expected
        REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
        assert REPORT['postgres_version'].split('.')[0] == '18'
        role, password = 'field_app_' + uuid4().hex[:12], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))

        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password,
                host='127.0.0.1', port=55439, database=name).render_as_string(hide_password=False)

        name = 'fields_' + uuid4().hex[:12]
        url = new_database(name)
        registry = Registry()
        app = create_app(url, registry)
        initial_policy = policy_descriptor()
        base_time = utcnow() - timedelta(hours=4)
        with TestClient(app) as client:
            database = app.state.database
            with database.engine.connect() as connection:
                assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
                assert connection.execute(text('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication '
                    'FROM pg_roles WHERE rolname = current_user')).scalar_one() is False
                versions = list(connection.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars())
            initial_tables = set(Base.metadata.tables)
            record('fresh_pg18_non_superuser_role_no_new_schema_migration')

            def observe(source, model, rows, body, at, *, query=None):
                registry.result = success(body, rows, etag='"field-etag"')
                with patch('tire_api.service.utcnow', return_value=at):
                    response = client.post(f'/v1/sources/{source}/live-query',
                        json={'query': query or {'model': model}, 'fallback_policy': 'never'})
                assert response.status_code == 200 and response.json()['data_state'] == 'live'
                return response.json()

            def resolution(variant_id):
                response = client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history')
                assert response.status_code == 200
                return response.json()

            STEP = 'mixed_field_authority'
            preference_model = 'Synthetic Field Preference'
            maker = variant('PG-PREFERENCE', preference_model)
            regulator = variant('PG-PREFERENCE', preference_model, utqg_treadwear=500, eu_wet_grip='B')
            maker_response = observe('fixture', preference_model, [maker], 'synthetic PG maker preference', base_time)
            regulatory_response = observe('fixture-two', preference_model, [regulator], 'synthetic PG regulator preference', base_time + timedelta(hours=1))
            preference_id = maker_response['variants'][0]['id']
            assert preference_id == regulatory_response['variants'][0]['id']
            preference = field_map(resolution(preference_id))
            assert preference['utqg_treadwear']['default_value'] == 300
            assert preference['eu_wet_grip']['default_value'] == 'B'
            assert all(preference[name]['state'] == 'conflict_preferred' for name in ('utqg_treadwear', 'eu_wet_grip'))
            record('same_exact_sku_uses_manufacturer_utqg_and_regulatory_eu_without_overwriting_sources')

            STEP = 'tie_and_missing'
            tie_model = 'Synthetic Field Tie'
            tie = observe('fixture', tie_model, [variant('PG-TIE', tie_model)], 'synthetic PG equal time left', base_time)
            observe('fixture-three', tie_model, [variant('PG-TIE', tie_model, utqg_treadwear=400)],
                'synthetic PG equal time right', base_time)
            tie_id = tie['variants'][0]['id']
            tied = field_map(resolution(tie_id))['utqg_treadwear']
            assert tied['state'] == 'conflict_tied' and tied['has_default'] is False
            missing_model = 'Synthetic Field Missing'
            absent = variant('PG-MISSING', missing_model)
            absent['facts'].pop('utqg_treadwear')
            missing = observe('fixture', missing_model, [absent], 'synthetic PG missing field', base_time)
            observe('fixture-two', missing_model, [variant('PG-MISSING', missing_model, utqg_treadwear=None)],
                'synthetic PG explicit null field', base_time)
            missing_id = missing['variants'][0]['id']
            unknown = field_map(resolution(missing_id))['utqg_treadwear']
            assert unknown['state'] == 'unknown'
            assert {(row['present'], row['value']) for row in unknown['candidates']} == {(False, None), (True, None)}
            observe('fixture-three', missing_model, [variant('PG-MISSING', missing_model, utqg_treadwear=0)],
                'synthetic PG known zero field', base_time)
            known = field_map(resolution(missing_id))['utqg_treadwear']
            assert known['state'] == 'uncontested' and known['default_value'] == 0
            assert len(known['candidates']) == 3
            record('equal_rank_disagreement_has_no_default_missing_null_and_zero_stay_distinct')

            STEP = 'same_source_active_query_heads'
            multi_model = 'Synthetic Multiple Active Queries'
            first_query = observe('fixture', multi_model, [variant('PG-MULTI-QUERY', multi_model)],
                'synthetic PG older query body', base_time)
            second_query = observe('fixture', multi_model, [variant('PG-MULTI-QUERY', multi_model, utqg_treadwear=400)],
                'synthetic PG newer query body', base_time + timedelta(hours=1),
                query={'model': multi_model, 'size': '265/40R20'})
            multi_id = first_query['variants'][0]['id']
            assert multi_id == second_query['variants'][0]['id']
            registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                'etag': '"field-etag"', 'parser_version': 'fixture@1'}
            with patch('tire_api.service.utcnow', return_value=base_time + timedelta(hours=2)):
                response = client.post('/v1/sources/fixture/live-query',
                    json={'query': {'model': multi_model}, 'fallback_policy': 'never'})
            assert response.status_code == 200 and response.json()['data_state'] == 'live_verified_304'
            multi = field_map(resolution(multi_id))['utqg_treadwear']
            assert len(multi['candidates']) == 2 and multi['default_value'] == 400
            assert multi['state'] == 'conflict_preferred'
            record('older_query_304_does_not_drop_other_active_snapshot_or_win_content_recency')

            STEP = 'explicit_merge_and_correction'
            merge_model = 'Synthetic Field Merge'
            left = {**variant('PG-MERGE', merge_model), 'hl': None}
            right = {**variant('PG-MERGE', merge_model, utqg_treadwear=500), 'hl': None}
            a = observe('fixture', merge_model, [left], 'synthetic PG merge original', base_time)
            b = observe('fixture-two', merge_model, [right], 'synthetic PG merge target', base_time)
            origin_id, target_id = a['variants'][0]['id'], b['variants'][0]['id']
            assert origin_id != target_id
            evidence = [a['provenance'][0]['snapshot_id'], b['provenance'][0]['snapshot_id']]
            merged = post(client, origin_id, decision(client, origin_id, target_id, evidence, 'merge'))
            assert merged.status_code == 201
            merge_event = merged.json()['event']['id']
            merge_selection = {'variant_ids': [origin_id, target_id], 'resolve_identities': True}
            merged_compare = client.post('/v1/compare', json=merge_selection)
            assert merged_compare.status_code == 200
            merged_row, = merged_compare.json()['variants']
            merged_wear = field_map(merged_row['field_resolution'])['utqg_treadwear']
            assert merged_wear['default_value'] == 300 and merged_row['facts']['utqg_treadwear'] == 500
            assert {row['variant_id'] for row in merged_wear['candidates']} == {origin_id, target_id}
            assert next(row for row in merged_wear['candidates'] if row['variant_id'] == origin_id)['equivalence_event_id'] == merge_event
            target_only = client.post('/v1/compare', json={'variant_ids': [target_id], 'resolve_identities': True}).json()
            assert {row['variant_id'] for row in field_map(target_only['variants'][0]['field_resolution'])['utqg_treadwear']['candidates']} == {target_id}
            correct_model = 'Synthetic Field Correct'
            corrected = observe('fixture', correct_model, [variant('PG-CORRECT-A', correct_model),
                variant('PG-CORRECT-B', correct_model, utqg_treadwear=700)], 'synthetic PG correction pair', base_time)
            ca, cb = [row['id'] for row in corrected['variants']]
            accepted = post(client, ca, decision(client, ca, cb, [corrected['provenance'][0]['snapshot_id']], 'correct'))
            assert accepted.status_code == 201
            correction_selection = {'variant_ids': [ca, cb], 'resolve_identities': True}
            corrected_compare = client.post('/v1/compare', json=correction_selection).json()
            assert {row['variant_id'] for row in field_map(corrected_compare['variants'][0]['field_resolution'])['utqg_treadwear']['candidates']} == {cb}
            record('explicit_valid_merge_keeps_selected_originals_correct_and_unselected_ancestors_do_not_join')

            STEP = 'read_only_projection'
            before_reads = fingerprints(database, Base.metadata)
            statements = []
            def trace(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement.lower())
            event.listen(database.engine, 'before_cursor_execute', trace)
            try:
                assert client.get('/v1/field-policies').status_code == 200
                listing = client.get('/v1/field-conflicts?mode=history&field=utqg_treadwear&source_id=fixture&limit=1').json()
                assert listing['total'] >= 2 and len(listing['items']) == 1
                for variant_id in (preference_id, tie_id, missing_id):
                    assert resolution(variant_id)['policy'] == initial_policy
            finally:
                event.remove(database.engine, 'before_cursor_execute', trace)
            assert fingerprints(database, Base.metadata) == before_reads
            assert not any(statement.lstrip().startswith(('insert ', 'update ', 'delete ', 'create ', 'alter '))
                           for statement in statements)
            assert not any('knowledge_fts' in statement or 'knowledge_documents' in statement for statement in statements)
            record('field_projection_reads_no_fts_and_writes_no_rows_or_schema')

            STEP = 'frozen_save_and_new_verifications'
            selection = {'variant_ids': [preference_id]}
            compared = client.post('/v1/compare', json=selection).json()
            saved = client.post('/v1/saved-comparisons', json={**selection, 'expected_fingerprint': compared['fingerprint'],
                'title': 'Synthetic PG field authority freeze', 'notes': 'private synthetic acceptance only'})
            assert saved.status_code == 201
            saved_id = saved.json()['id']
            with database.sessions() as db:
                fact_count = db.scalar(select(func.count()).select_from(FactVersion))
                original_fact = db.scalar(select(FactVersion).where(FactVersion.variant_id == preference_id,
                    FactVersion.source_id == 'fixture').order_by(FactVersion.version.desc()))
                original_fact_id, original_snapshot_id = original_fact.id, original_fact.snapshot_id
            metadata = deepcopy(maker)
            metadata['facts']['evidence_spans']['facts.utqg_treadwear'] = '$.newLayout.sku.utqg'
            updated = observe('fixture', preference_model, [metadata], 'synthetic PG metadata-only new raw', base_time + timedelta(hours=2))
            current_snapshot_id = updated['provenance'][0]['snapshot_id']
            assert current_snapshot_id != original_snapshot_id
            candidate, = field_map(updated['variants'][0]['field_resolution'])['utqg_treadwear']['candidates']
            assert candidate['snapshot_id'] == current_snapshot_id and candidate['fact_version_id'] == original_fact_id
            registry.result = {'status': 'not_modified', 'url': 'https://fixture.example/tires/product',
                'etag': '"field-etag"', 'parser_version': 'fixture@1'}
            with patch('tire_api.service.utcnow', return_value=base_time + timedelta(hours=3)):
                result = client.post('/v1/sources/fixture/live-query',
                    json={'query': {'model': preference_model}, 'fallback_policy': 'never'})
            assert result.status_code == 200 and result.json()['data_state'] == 'live_verified_304'
            assert result.json()['provenance'][0]['snapshot_id'] == current_snapshot_id
            with database.sessions() as db:
                assert db.scalar(select(func.count()).select_from(FactVersion)) == fact_count
            new_comparison = client.post('/v1/compare', json=selection).json()
            assert new_comparison['fingerprint'] != compared['fingerprint']
            current_fields = field_map(new_comparison['variants'][0]['field_resolution'])
            assert current_fields['utqg_treadwear']['default_value'] == 300 and current_fields['eu_wet_grip']['default_value'] == 'B'
            frozen = client.get(f'/v1/saved-comparisons/{saved_id}?mode=history').json()
            assert frozen['comparison'] == compared
            stale = client.post('/v1/saved-comparisons', json={**selection, 'expected_fingerprint': compared['fingerprint'],
                'title': 'Must reject stale field snapshot', 'notes': ''})
            assert stale.status_code == 409
            record('saved_policy_and_candidates_remain_frozen_after_metadata_only_200_and_304')

            ids = {'preference': preference_id, 'tie': tie_id, 'missing': missing_id, 'multi_query': multi_id}
            expected_resolutions = {label: resolution(variant_id) for label, variant_id in ids.items()}
            expected_merge = client.post('/v1/compare', json=merge_selection).json()
            expected_correction = client.post('/v1/compare', json=correction_selection).json()
            with database.sessions() as db:
                for model in (AIRequest, EmbeddingRequest):
                    assert db.scalar(select(func.count()).select_from(model)) == 0
                captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
                for capture_id, raw_hash in captures:
                    data, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                    assert hashlib.sha256(data).hexdigest() == raw_hash and location == 'object_store'
                assert list(db.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars()) == versions
            assert policy_descriptor() == initial_policy and set(Base.metadata.tables) == initial_tables
            frozen_rows = fingerprints(database, Base.metadata)

        database = None  # The app lifespan has closed this engine.
        STEP = 'dump_restore'
        restore_name = 'restored_fields_' + uuid4().hex[:12]
        restored_url = new_database(restore_name)
        archive = run_root / 'fields.dump'
        child_env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55439', 'PGUSER': role, 'PGPASSWORD': password}
        commands = [
            [str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password',
                '--dbname', name, '--file', str(archive)],
            [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password',
                '--dbname', restore_name, str(archive)],
        ]
        for command in commands:
            result = subprocess.run(command, env=child_env, capture_output=True, timeout=60)
            assert result.returncode == 0, 'private_pg_dump_or_restore_failed'
        destination = run_root / 'restored-objects'
        assert object_root.parent == destination.parent == run_root and not destination.exists()
        object_hashes = file_hashes(object_root)
        assert object_hashes
        shutil.copytree(object_root, destination)
        assert file_hashes(destination) == object_hashes
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        restored.initialize()
        restored_rows = fingerprints(restored, Base.metadata)
        assert frozen_rows == restored_rows
        with restored.sessions() as db:
            assert list(db.execute(text('SELECT version FROM tire_schema_versions ORDER BY version')).scalars()) == versions
            for capture_id, raw_hash in captures:
                data, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert hashlib.sha256(data).hexdigest() == raw_hash and location == 'object_store'
        restored.close()
        restored = None
        record('dump_restore_all_base_columns_schema_versions_and_object_copy_hashes')

        STEP = 'restored_api_semantics'
        with TestClient(create_app(restored_url, Registry())) as restored_client:
            for label, variant_id in ids.items():
                response = restored_client.get(f'/v1/tire-variants/{variant_id}/field-resolution?mode=history')
                assert response.status_code == 200 and response.json() == expected_resolutions[label]
            assert restored_client.post('/v1/compare', json=merge_selection).json() == expected_merge
            assert restored_client.post('/v1/compare', json=correction_selection).json() == expected_correction
            restored_saved = restored_client.get(f'/v1/saved-comparisons/{saved_id}?mode=history')
            assert restored_saved.status_code == 200 and restored_saved.json()['comparison'] == compared
        record('restored_policy_reasoning_original_candidates_defaults_and_old_saved_payload_are_identical')
        REPORT.update(status='passed', tables_checked=len(frozen_rows), columns_checked=sum(
            len(value['columns']) for value in frozen_rows.values()), schema_migrations_added=0,
            policy=initial_policy, schema_versions=versions, source_fact_count=fact_count,
            read_projection_unchanged=True, fts_projection_writes=0,
            preserved_saved_fingerprint=compared['fingerprint'], current_comparison_fingerprint=new_comparison['fingerprint'],
            original_candidate_ids_preserved=True, merge_event_preserved=True,
            table_fingerprints=public_fingerprints(frozen_rows), restore_table_fingerprints=public_fingerprints(restored_rows),
            object_file_count=len(object_hashes), object_hashes=object_hashes, copied_object_hashes=file_hashes(destination),
            capture_count=len(captures), archive_bytes=archive.stat().st_size,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
            synthetic_source_observations=registry.calls, real_source_calls=0, real_parser_children=0,
            real_ai_calls=0, real_embedding_calls=0, normal_database_used=False,
            fingerprint_scope='All Base.metadata registered columns and values, schema versions and copied object files; '
                'not database roles, ACL or cross-host recovery')
    finally:
        if database is not None:
            database.close()
        if restored is not None:
            restored.close()
        admin.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-private-postgres', action='store_true', required=True)
    parser.parse_args()
    code = 0
    try:
        run()
    except Exception as error:
        import traceback
        code = 1
        REPORT.update(status='failed', failure_step=STEP, error_type=type(error).__name__)
        REPORT['frames'] = [{'file': Path(frame.filename).name, 'line': frame.lineno}
            for frame in traceback.extract_tb(error.__traceback__) if Path(frame.filename).resolve().is_relative_to(ROOT)]
    report = Path(os.environ['TIRE_PG_TEST_REPORT']).resolve()
    assert report.name == 'report.json' and report.parent.parent == (ROOT / '.artifacts/runtime').resolve()
    assert report.parent.name.startswith('round39-field-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

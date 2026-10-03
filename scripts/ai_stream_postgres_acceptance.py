"""Opt-in PG44 stream-ledger concurrency and additive restore acceptance.

Run only in the coordinator-owned temporary cluster on loopback port 55444.
Providers and the one source observation are synthetic; no live model or Parser.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from datetime import timedelta
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
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from identity_contract_postgres_acceptance import file_hashes, fingerprints, public_fingerprints
import monitor_tasks_postgres_acceptance as previous

ROOT = Path(__file__).resolve().parents[1]
REPORT = {'status': 'running', 'scope': 'synthetic_ai_stream_additive_private_postgresql', 'checks': []}
STEP = 'isolation'
NEW_TABLES = {'ai_stream_executions', 'ai_stream_events'}
OLD_AI_SCHEMA_TABLES = ('ai_requests', 'ai_completions')
OLD_VERSIONS = {'001_verification_validators', '002_monitor_rule_conditions', '003_parser_release_provenance',
    '004_query_selection_filters', '005_variant_identity_contract', '006_source_settings',
    '007_monitor_tasks', '008_recall_discovery_monitoring'}
save_atomic, safe_failure, wait_gate = previous.save_atomic, previous.safe_failure, previous.wait_gate


def record(name):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def guards():
    root = Path(os.environ['TIRE_PG_RUN_ROOT']).resolve()
    assert root.parent == (ROOT / '.artifacts/runtime').resolve() and root.name.startswith('round44-ai-stream-PG-')
    assert Path(os.environ['TIRE_PG_TEST_DATA']).resolve() == root / 'data'
    assert Path(os.environ['TIRE_PG_TEST_REPORT']).resolve() == root / 'report.json'
    assert int(os.environ['TIRE_PG_TEST_PORT']) == 55444
    assert os.environ['TI_AI_ENABLED'] == os.environ['TI_EMBEDDINGS_ENABLED'] == '0'
    assert os.environ['TI_OBSERVABILITY_ENABLED'] == '0'
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
    return OpenAIConfig(model='synthetic-pg-stream', api_key='synthetic-not-a-real-provider-key',
                        daily_token_limit=1_000_000, daily_request_limit=100, allow_private=True)


def output(payload):
    fact = payload['facts'][0]
    return {'claims': [{'type': 'fact', 'text': '', 'fact_ids': [fact['id']], 'evidence_ids': [fact['evidence_id']]}],
            'uncertainty': 'Synthetic database concurrency evidence, not live AI.'}


class SyntheticModel:
    def __init__(self, gate):
        self.gate, self.calls = gate, 0

    async def stream(self, _config, body, on_text):
        assert body['stream'] is True and body['store'] is False and body['background'] is False and body['tools'] == []
        self.calls += 1
        payload = json.loads(body['input'][1]['content'])['untrusted_evidence_pack']
        answer = output(payload)
        prefix = '{"claims":' + json.dumps(answer['claims'])
        suffix = ',"uncertainty":' + json.dumps(answer['uncertainty']) + '}'
        await on_text(prefix)
        while not self.gate.is_file():
            await asyncio.sleep(0.02)
        await on_text(suffix)
        return {'text': prefix + suffix, 'error': None,
                'usage': {'input_tokens': 120, 'output_tokens': 30, 'total_tokens': 150},
                'provider_response_id': 'synthetic_pg_stream'}


def observation_fixture_registry():
    from test_core import FixtureRegistry

    class ObservationFixtureRegistry(FixtureRegistry):
        def __init__(self):
            super().__init__()
            self.observation_count = 0

        async def fetch(self, source_id, query, cached=None, *, on_observation=None):
            result = await super().fetch(source_id, query, cached=cached)
            assert result['status'] == 'ok' and callable(on_observation)
            # Exercise the real pre-parser receipt callback before accepting the
            # synthetic parsed result; the base FixtureRegistry omits this step.
            on_observation({key: result[key] for key in ('url', 'body', 'content_type', 'parser_version')})
            self.observation_count += 1
            return result

    return ObservationFixtureRegistry()


def writer(name):
    root = guards()
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', name)
    request = json.loads((root / f'{name}.request.json').read_text(encoding='utf-8'))
    assert re.fullmatch(r'[a-z][a-z0-9-]{0,79}', request['group'])
    from fastapi.testclient import TestClient
    from sqlalchemy.engine import make_url
    from tire_api import ai_analysis, ai_stream_routes, ai_stream_store as store
    from tire_api.ai_models import AIEvidencePack, AIRequest
    from tire_api.db import Database
    from tire_api.main import SESSION_COOKIE, create_app
    from test_core import FixtureRegistry
    url = os.environ['TIRE_PG_APP_URL']
    parsed = make_url(url)
    assert parsed.get_backend_name() == 'postgresql' and parsed.host == '127.0.0.1' and parsed.port == 55444
    assert parsed.database.startswith('ai_stream_')
    token = os.environ['TIRE_PG_AI_OWNER']
    database = Database(url)
    outcome = {'pid': os.getpid(), 'parent_pid': os.getppid(), 'action': request['action'], 'status': 'running'}
    code = 0
    try:
        with database.sessions() as db:
            outcome['backend_pid'] = db.connection().exec_driver_sql('SELECT pg_backend_pid()').scalar_one()
            db.commit()
        save_atomic(root / f'{name}.ready.json', {'pid': os.getpid(), 'backend_pid': outcome['backend_pid']})
        wait_gate(root / (request['group'] + '.go'))
        if request['action'] == 'accept':
            model = SyntheticModel(root / f'{name}.finish.go')
            app = create_app(url, FixtureRegistry())
            app.state.ai_adapter = model
            with patch.object(ai_analysis, 'configured_model', config), patch.object(ai_stream_routes, 'uid', lambda: token), \
                 TestClient(app, cookies={SESSION_COOKIE: request['actor']}) as client:
                response = client.post('/v1/ai/analysis-streams', json=request['body'],
                                       headers={'Idempotency-Key': request['key']})
                assert response.status_code == 202
                value = response.json()
                request_id = value['analysis']['id']
                outcome.update(request_id=request_id, replayed=value['replayed'])
                if value['replayed']:
                    outcome.update(status='idle', provider_calls=model.calls)
                    save_atomic(root / f'{name}.claim.json', outcome)
                else:
                    deadline = time.monotonic() + 15
                    while True:
                        value = client.get('/v1/ai/analysis-streams/' + request_id + '?mode=history').json()
                        if value['draft_claims']:
                            break
                        assert time.monotonic() < deadline, 'synthetic_draft_not_observed'
                        time.sleep(0.02)
                    outcome.update(status='claimed', provider_calls=model.calls)
                    save_atomic(root / f'{name}.claim.json', outcome)
                    wait_gate(root / f'{name}.finish.go')
                    deadline = time.monotonic() + 15
                    while True:
                        value = client.get('/v1/ai/analysis-streams/' + request_id + '?mode=history').json()
                        if value['execution']['terminal']:
                            break
                        assert time.monotonic() < deadline, 'synthetic_completion_not_observed'
                        time.sleep(0.02)
                    assert value['analysis']['state'] == 'completed'
                    outcome.update(status='finished', provider_calls=model.calls)
        else:
            request_id = request['request_id']
            with database.sessions() as db:
                row = db.get(AIRequest, request_id)
                pack = db.get(AIEvidencePack, row.pack_id)
                answer = ai_analysis.grounded_answer(json.dumps(output(pack.payload)), pack)
            if request['action'] == 'wrong_owner':
                outcome['started'] = store.start_execution(database, request_id, token)
                outcome['drafted'] = store.append_event(database, request_id, token, 'claim_draft',
                                                        {'index': 0, 'claim': answer['claims'][0]})
                outcome['finished'] = store.finish_execution(database, request_id, token, state='completed', answer=answer)
            elif request['action'] == 'draft':
                outcome['written'] = store.append_event(database, request_id, token, 'claim_draft',
                                                        {'index': 0, 'claim': answer['claims'][0]})
            elif request['action'] in {'complete', 'late_complete'}:
                outcome['written'] = store.finish_execution(database, request_id, token, state='completed', answer=answer,
                    usage={'input_tokens': 80, 'output_tokens': 20, 'total_tokens': 100})
            else:
                raise ValueError('invalid_synthetic_action')
            outcome['status'] = 'finished'
    except Exception as error:
        code = 1
        outcome.update(status='failed', **safe_failure(error))
    finally:
        database.close()
        save_atomic(root / f'{name}.result.json', outcome)
    return code


class Writers(previous.Writers):
    def launch(self, group, requests, token):
        names = []
        for index, request in enumerate(requests):
            name = f'{group}-{index}'
            names.append(name)
            save_atomic(self.root / f'{name}.request.json', {'group': group, **request})
            env = {**os.environ, 'TIRE_PG_APP_URL': self.url, 'TIRE_PG_AI_OWNER': token}
            env.pop('TIRE_PG_TEST_PASSWORD', None)
            log = (self.root / f'{name}.log').open('wb')
            self.logs[name] = log
            self.children[name] = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--writer', name],
                env=env, cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
        ready = self.collect(names, 'ready')
        assert len({row['pid'] for row in ready}) == len({row['backend_pid'] for row in ready}) == len(names)
        self.evidence.extend({'scenario': group, **row} for row in ready)
        (self.root / f'{group}.go').write_text('begin', encoding='utf-8')
        return names

    def results(self, names):
        for name in names:
            assert self.children[name].wait(timeout=45) == 0, 'private_writer_failed'
        return self.collect(names, 'result')


def old_ai_schema(database):
    from sqlalchemy import inspect
    inspector = inspect(database.engine)
    result = {}
    for name in OLD_AI_SCHEMA_TABLES:
        result[name] = {'columns': inspector.get_columns(name), 'checks': inspector.get_check_constraints(name),
            'indexes': inspector.get_indexes(name), 'unique': inspector.get_unique_constraints(name),
            'foreign': inspector.get_foreign_keys(name), 'primary': inspector.get_pk_constraint(name)}
    return json.loads(json.dumps(result, sort_keys=True, default=str))


def seed_pack(database, actor):
    from tire_api.ai_models import AIEvidencePack
    from tire_api.db import UserSession, utcnow
    from tire_api.domain import digest
    from tire_api.field_authority import policy_descriptor
    content = {'retrieval': 'exact_structured_lookup', 'evidence': [{'id': 'e1', 'kind': 'regulatory',
        'label': 'Synthetic database fixture', 'source_url': 'https://fixture.example/evidence'}],
        'facts': [{'id': 'f1', 'evidence_id': 'e1', 'field': 'Synthetic value', 'field_code': 'synthetic.value',
                   'value': 1, 'text': 'Synthetic database fixture：Synthetic value = 1'}],
        'field_policy': policy_descriptor(), 'field_resolutions': [], 'conflicts': [], 'source_state': 'snapshot'}
    with database.sessions() as db:
        db.add(UserSession(id=actor, expires_at=utcnow() + timedelta(hours=4)))
        pack = AIEvidencePack(actor_session_id=actor, mode='history', data_state='local_snapshot',
            privacy_class='public', payload=content, fingerprint=digest(content), expires_at=utcnow() + timedelta(minutes=30))
        db.add(pack)
        db.commit()
        return pack.id


def manual_reservation(database, actor, pack_id, token, *, ttl=90):
    from tire_api.ai_execution import reserve_response
    from tire_api.ai_gateway import request_body
    from tire_api.ai_models import AIEvidencePack
    from tire_api import ai_stream_store as store
    from tire_api.db import utcnow
    from tire_api.service import QueryService
    with database.sessions() as db:
        QueryService(db, None).lock_ingestion()
        pack = db.get(AIEvidencePack, pack_id)
        body, reserve = request_body(config(), 'Synthetic database fencing', {**pack.payload, 'data_state': pack.data_state}, stream=True)
        row = reserve_response(db, config=config(), pack=pack, session_id=actor, key=str(uuid4()), request_hash='f' * 64,
            question='Synthetic database fencing', reserve=reserve, body=body,
            contract={'purpose': 'analysis', 'delivery_mode': 'stream'}, before_commit=lambda session, request:
                store.create_execution_locked(session, request, token, utcnow() + timedelta(seconds=ttl)))
        return row.id


def run():
    global STEP
    root = guards()
    import psycopg
    from psycopg import sql
    from fastapi.testclient import TestClient
    from sqlalchemy import func, inspect, select, text
    from sqlalchemy.engine import URL
    from tire_api import ai_stream_store as store
    from tire_api.ai_models import AICompletion, AIRequest
    from tire_api.ai_stream_models import AIStreamEvent
    from tire_api.captures import checked_capture_bytes
    from tire_api.db import Base, Database, RawCapture, uid
    from tire_api.knowledge_models import initialize_search
    from tire_api.main import SESSION_COOKIE, create_app
    from test_core import FixtureRegistry, live
    admin = psycopg.connect(host='127.0.0.1', port=55444, user='tire_ai_stream_admin',
        password=os.environ['TIRE_PG_TEST_PASSWORD'], dbname='postgres', autocommit=True, connect_timeout=5)
    database = restored = writers = None
    previous.REPORT = REPORT
    try:
        assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == root / 'data'
        REPORT.update(postgres_version=admin.execute('SHOW server_version').fetchone()[0],
                      parent_pid=os.getpid(), postmaster_pid=int((root / 'data/postmaster.pid').read_text().splitlines()[0]))
        role, password = 'ai_stream_app_' + uuid4().hex[:10], secrets.token_hex(32)
        admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION').format(
            sql.Identifier(role), sql.Literal(password)))
        def new_database(name):
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
            return URL.create('postgresql+psycopg', username=role, password=password, host='127.0.0.1', port=55444,
                              database=name).render_as_string(hide_password=False)
        name = 'ai_stream_' + uuid4().hex[:10]
        url = new_database(name)
        database = Database(url)
        with database.engine.connect() as connection:
            assert connection.exec_driver_sql('SELECT current_user').scalar_one() == role
            assert connection.exec_driver_sql('SELECT rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication FROM pg_roles WHERE rolname=current_user').scalar_one() is False
            assert not inspect(connection).get_table_names()
        record('private_loopback_cluster_non_superuser_application_role')

        STEP = 'purely_additive_migration'
        registered = set(Base.metadata.tables)
        assert NEW_TABLES <= registered
        old_tables = [table for table in Base.metadata.sorted_tables if table.name not in NEW_TABLES]
        with database.engine.begin() as connection:
            Base.metadata.create_all(connection, tables=old_tables)
            connection.exec_driver_sql('CREATE TABLE tire_schema_versions (version VARCHAR(80) PRIMARY KEY, applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            for version in sorted(OLD_VERSIONS):
                connection.execute(text('INSERT INTO tire_schema_versions(version) VALUES (:version)'), {'version': version})
            initialize_search(connection)
        actor, other = str(uuid4()), str(uuid4())
        pack_id = seed_pack(database, actor)
        seed_pack(database, other)
        with database.sessions() as db:
            old = AIRequest(actor_session_id=actor, idempotency_key=uid(), request_hash='a' * 64,
                pack_id=pack_id, question='Synthetic pre009 record', provider='openai_responses', model='synthetic-old',
                request_contract={'purpose': 'analysis'}, reserved_tokens=1000)
            db.add(old)
            db.flush()
            db.add(AICompletion(request_id=old.id, state='completed', answer={'legacy': 'preserved'},
                usage={'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}))
            db.commit()
        old_rows, old_schema = fingerprints(database, SimpleNamespace(sorted_tables=old_tables)), old_ai_schema(database)
        before_names = set(inspect(database.engine).get_table_names())
        database.initialize()
        database.initialize()
        after_names = set(inspect(database.engine).get_table_names())
        assert set(Base.metadata.tables) == registered and after_names - before_names == NEW_TABLES and not before_names - after_names
        assert old_ai_schema(database) == old_schema
        assert {key: value for key, value in fingerprints(database, Base.metadata).items() if key in old_rows} == old_rows
        with database.engine.connect() as connection:
            versions = set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars())
            assert versions == OLD_VERSIONS | {'009_ai_streaming'}
        record('only_two_new_tables_009_and_all_old_values_ai_schema_unchanged_after_repeat_initialize')

        STEP = 'independent_same_uuid_acceptance'
        writers = Writers(root, url)
        token, key = uid(), str(uuid4())
        request = {'action': 'accept', 'actor': actor, 'key': key,
                   'body': {'pack_id': pack_id, 'question': 'Explain synthetic historical evidence', 'allow_external_processing': True}}
        names = writers.launch('same-uuid', [request, request], token)
        claims = writers.collect(names, 'claim')
        assert len({row['request_id'] for row in claims}) == 1
        assert sorted(row['replayed'] for row in claims) == [False, True]
        assert sum(row['provider_calls'] for row in claims) == 1
        request_id = claims[0]['request_id']
        winner = next(worker for worker, value in zip(names, claims, strict=True) if not value['replayed'])
        with database.sessions() as db:
            page = store.event_page(db, request_id, actor)
            assert [row['type'] for row in page['items']] == ['accepted', 'started', 'claim_draft']
            cursor = page['items'][1]['cursor']
            assert db.get(AICompletion, request_id) is None
        (root / f'{winner}.finish.go').write_text('finish', encoding='utf-8')
        assert sum(row['provider_calls'] for row in writers.results(names)) == 1
        with database.sessions() as db:
            assert db.scalar(select(func.count()).select_from(AIRequest).where(AIRequest.idempotency_key == key)) == 1
            assert db.scalar(select(func.count()).select_from(AIStreamEvent).where(AIStreamEvent.request_id == request_id,
                AIStreamEvent.type == 'started')) == 1
            assert db.get(AICompletion, request_id).state == 'completed'
        record('two_real_processes_same_uuid_one_budget_request_started_provider_and_completion')

        STEP = 'owner_and_terminal_races'
        race_token = uid()
        race_id = manual_reservation(database, actor, pack_id, race_token)
        wrong = writers.launch('wrong-owner', [{'action': 'wrong_owner', 'request_id': race_id}], uid())
        wrong_result, = writers.results(wrong)
        assert wrong_result['started'] is wrong_result['drafted'] is wrong_result['finished'] is False
        assert store.start_execution(database, race_id, race_token)
        names = writers.launch('draft-terminal', [{'action': action, 'request_id': race_id} for action in ('draft', 'complete')], race_token)
        outcomes = writers.results(names)
        assert outcomes[1]['written'] is True
        with database.sessions() as db:
            page = store.event_page(db, race_id, actor)
            assert page['items'][-1]['type'] == 'completed'
            assert sum(item['type'] == 'completed' for item in page['items']) == 1
            assert db.get(AICompletion, race_id).state == 'completed'
        record('wrong_owner_rejected_and_independent_draft_terminal_race_has_no_post_terminal_draft')

        STEP = 'late_writer_fence'
        late_token = uid()
        late_id = manual_reservation(database, actor, pack_id, late_token, ttl=2)
        assert store.start_execution(database, late_id, late_token)
        time.sleep(2.1)
        names = writers.launch('late-writer', [{'action': 'late_complete', 'request_id': late_id}], late_token)
        result, = writers.results(names)
        assert result['written'] is False
        with database.sessions() as db:
            assert db.get(AICompletion, late_id) is None
            projected = store.detail(db, late_id, actor)
            assert projected['execution']['projection_only'] and projected['analysis']['state'] == 'outcome_unknown'
        assert store.finish_execution(database, late_id, late_token, state='outcome_unknown', error_code='ai_stream_owner_expired')
        with database.sessions() as db:
            assert db.get(AICompletion, late_id).usage is None
            from tire_api.embedding_budget import budget_usage
            assert not budget_usage(db)['has_pending_request']
            assert budget_usage(db)['accounted_tokens'] == 15 + 150 + 100 + db.get(AIRequest, late_id).reserved_tokens
        record('expired_late_writer_cannot_complete_fresh_unknown_preserves_reserved_tokens')
        writers.close()

        STEP = 'private_scope_and_object_fixture'
        observation_registry = observation_fixture_registry()
        app = create_app(url, observation_registry)
        with TestClient(app, cookies={SESSION_COOKIE: actor}) as client, \
             TestClient(create_app(url, FixtureRegistry()), cookies={SESSION_COOKIE: other}) as stranger:
            observation_response = live(client)
            assert observation_response.status_code == 200 and observation_response.json()['data_state'] == 'live'
            assert observation_registry.observation_count == len(observation_registry.calls) == 1
            path = '/v1/ai/analysis-streams/' + request_id
            assert stranger.get(path + '?mode=history').status_code == 404
            assert stranger.get(path + '/events?cursor=invalid').status_code == 404
            assert stranger.get(path + '/events/stream').status_code == 404
            assert client.get(path + '/events?cursor=invalid').status_code == 409
            expected_detail = previous.strip_clock(client.get(path + '?mode=history').json())
            expected_events = previous.strip_clock(client.get(path + '/events', params={'cursor': cursor}).json())
        with database.sessions() as db:
            captures = [(row.id, row.raw_hash) for row in db.scalars(select(RawCapture))]
            assert len(captures) == 1
            for capture_id, expected_hash in captures:
                data, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(data).hexdigest() == expected_hash
        frozen_rows = fingerprints(database, Base.metadata)
        save_atomic(root / 'fingerprints-frozen.json', public_fingerprints(frozen_rows))
        record('actor_scope_cursor_rejection_and_synthetic_original_object_hashes')

        STEP = 'dump_restore_all_values_and_cursors'
        restored_name = 'restored_ai_stream_' + uuid4().hex[:10]
        restored_url = new_database(restored_name)
        archive = root / 'ai-stream.dump'
        env = {**os.environ, 'PGHOST': '127.0.0.1', 'PGPORT': '55444', 'PGUSER': role, 'PGPASSWORD': password}
        env.pop('TIRE_PG_TEST_PASSWORD', None)
        pg_bin = Path(os.environ['TIRE_PG_BIN'])
        pre_dump_rows = fingerprints(database, Base.metadata)
        save_atomic(root / 'fingerprints-pre-dump.json', public_fingerprints(pre_dump_rows))
        assert pre_dump_rows == frozen_rows, 'pre_dump_registered_values_changed'
        for command in ([str(pg_bin / 'pg_dump.exe'), '--format=custom', '--no-owner', '--no-acl', '--no-password', '--dbname', name, '--file', str(archive)],
                        [str(pg_bin / 'pg_restore.exe'), '--exit-on-error', '--no-owner', '--no-acl', '--no-password', '--dbname', restored_name, str(archive)]):
            assert subprocess.run(command, env=env, capture_output=True, timeout=60).returncode == 0, 'private_dump_restore_failed'
        object_hashes = file_hashes(root / 'objects')
        destination = root / 'restored-objects'
        assert object_hashes and not destination.exists()
        shutil.copytree(root / 'objects', destination)
        assert file_hashes(destination) == object_hashes
        os.environ['TI_OBJECT_STORE_ROOT'] = str(destination)
        restored = Database(restored_url)
        pre_initialize_rows = fingerprints(restored, Base.metadata)
        save_atomic(root / 'fingerprints-restored-pre-initialize.json', public_fingerprints(pre_initialize_rows))
        assert pre_initialize_rows == frozen_rows, 'restored_before_initialize_registered_values_changed'
        assert old_ai_schema(restored) == old_schema, 'restored_before_initialize_legacy_ai_schema_changed'
        restored.initialize()
        restored_rows = fingerprints(restored, Base.metadata)
        save_atomic(root / 'fingerprints-restored-post-initialize.json', public_fingerprints(restored_rows))
        assert restored_rows == frozen_rows, 'restored_registered_values_changed'
        assert old_ai_schema(restored) == old_schema, 'restored_legacy_ai_schema_changed'
        with restored.sessions() as db:
            assert previous.strip_clock(store.detail(db, request_id, actor)) == expected_detail
            assert previous.strip_clock(store.event_page(db, request_id, actor, after=cursor)) == expected_events
            assert set(db.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == versions
            for capture_id, expected_hash in captures:
                data, location = checked_capture_bytes(db, db.get(RawCapture, capture_id))
                assert location == 'object_store' and hashlib.sha256(data).hexdigest() == expected_hash
        record('dump_restore_every_registered_column_value_legacy_ai_schema_objects_and_original_cursor')
        assert not (root / 'import-guard.sqlite').exists()
        REPORT.update(status='passed', migration='009_ai_streaming', actual_added_tables=sorted(after_names - before_names),
            actual_removed_tables=sorted(before_names - after_names), old_ai_schema_unchanged=True, table_rebuilds=0,
            old_ai_schema_tables=list(OLD_AI_SCHEMA_TABLES),
            tables_checked=len(frozen_rows), columns_checked=sum(len(value['columns']) for value in frozen_rows.values()),
            table_fingerprints=public_fingerprints(frozen_rows), restored_table_fingerprints=public_fingerprints(restored_rows),
            fingerprint_artifacts=['fingerprints-frozen.json', 'fingerprints-pre-dump.json',
                'fingerprints-restored-pre-initialize.json', 'fingerprints-restored-post-initialize.json'],
            pre_dump_values_unchanged=True, restored_before_initialize_values_unchanged=True,
            schema_versions=sorted(versions), object_hashes=object_hashes, capture_count=len(captures),
            synthetic_source_observations=observation_registry.observation_count,
            archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), archive_bytes=archive.stat().st_size,
            real_source_calls=0, real_model_calls=0, real_parser_children=0, normal_database_used=False,
            fingerprint_scope='All registered columns/values; ai_requests and ai_completions schema; version IDs and object bytes; no production roles/ACL/cross-host recovery claim')
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
        result = action()
        assert source.call_count == parser.call_count == stream.call_count == generate.call_count == 0
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
    assert report.parent.parent == (ROOT / '.artifacts/runtime').resolve() and report.parent.name.startswith('round44-ai-stream-PG-')
    report.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: REPORT[key] for key in ('status', 'scope', 'checks')}), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

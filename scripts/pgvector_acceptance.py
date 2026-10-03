"""Real pgvector checks in verify-pgvector.ps1's disposable, loopback cluster.

Synthetic vectors validate storage and retrieval contracts, not embedding quality.
No OpenAI key, production database URL, or external model request is used.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy.engine import URL

ROOT = Path(__file__).resolve().parents[1]
REPORT: dict = {'checks': [], 'data': 'synthetic vectors in isolated real PostgreSQL and pgvector'}
STEP = 'environment_guard'


def record(name: str):
    REPORT['checks'].append(name)
    print(json.dumps({'check': name, 'status': 'passed'}), flush=True)


def fingerprint(connection):
    rows = connection.execute('''SELECT id, namespace, state, privacy, evidence_revision,
        content_hash, embedding::text FROM evidence_vectors ORDER BY id''').fetchall()
    return {'rows': len(rows), 'sha256': hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()}


def filtered(connection, *, approximate=False):
    predicate = "namespace = 'alpha' AND state = 'accepted' AND privacy = 'public'"
    # Materialization guarantees the acceptance oracle does not silently use ANN
    # after index creation or database restore. The separate ANN query must use HNSW.
    prefix = '' if approximate else f'WITH candidates AS MATERIALIZED (SELECT * FROM evidence_vectors WHERE {predicate}) '
    source = f'evidence_vectors WHERE {predicate}' if approximate else 'candidates'
    return connection.execute(prefix + f'''SELECT id, embedding <=> %s::vector AS distance
        FROM {source} ORDER BY embedding <=> %s::vector LIMIT 2''', ('[1,0,0]', '[1,0,0]')).fetchall()


def all_table_fingerprints(connection):
    result = {}
    tables = connection.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    for (name,) in tables:
        values = connection.execute(sql.SQL('SELECT row_to_json(t)::text FROM public.{} AS t').format(sql.Identifier(name))).fetchall()
        serialized = '\n'.join(sorted(row[0] for row in values))
        result[name] = {'rows': len(values), 'sha256': hashlib.sha256(serialized.encode()).hexdigest()}
    return result


def run():
    global STEP
    data = Path(os.environ['TIRE_VECTOR_TEST_DATA']).resolve()
    artifact = (ROOT / '.artifacts/pgvector').resolve()
    assert data.is_relative_to(artifact) and data.name == 'data' and data.parent.name.startswith('vectorverify-')
    binary = Path(os.environ['TIRE_VECTOR_TEST_BIN']).resolve()
    assert binary == data.parent / 'postgres/bin'
    report_path = Path(os.environ['TIRE_VECTOR_TEST_REPORT']).resolve()
    assert report_path == data.parent / 'report.json'
    port = int(os.environ['TIRE_VECTOR_TEST_PORT'])
    password = os.environ['TIRE_VECTOR_TEST_PASSWORD']
    common = {'host': '127.0.0.1', 'port': port, 'connect_timeout': 5, 'autocommit': True}
    admin_args = common | {'user': 'tire_vector_admin', 'password': password}
    admin = psycopg.connect(**admin_args, dbname='postgres')
    assert Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() == data
    REPORT['postgres_version'] = admin.execute('SHOW server_version').fetchone()[0]
    record('workspace_cluster_and_loopback_guard')
    role = 'vector_app_' + uuid4().hex[:12]
    app_password = secrets.token_hex(32)
    dbname = 'vector_test_' + uuid4().hex[:12]
    restored_name = dbname + '_restored'
    admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(sql.Identifier(role), sql.Literal(app_password)))
    for name in (dbname, restored_name):
        admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(role)))
    owner = psycopg.connect(**admin_args, dbname=dbname)
    STEP = 'extension_creation'
    owner.execute('CREATE EXTENSION vector')
    REPORT['pgvector_version'] = owner.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
    assert REPORT['pgvector_version'] == '0.8.1'
    record('real_create_extension_vector_0_8_1')
    connection = psycopg.connect(**common, user=role, password=app_password, dbname=dbname)
    assert connection.execute('SELECT rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0] is False
    connection.execute('''CREATE TABLE evidence_vectors (
        id integer PRIMARY KEY, namespace text NOT NULL, state text NOT NULL, privacy text NOT NULL,
        evidence_revision integer NOT NULL, content_hash text NOT NULL, embedding vector(3) NOT NULL)''')
    seed = [
        (1, 'alpha', 'accepted', 'public', 1, 'revision-one', '[1,0,0]'),
        (2, 'alpha', 'accepted', 'public', 2, 'revision-two', '[0.8,0.6,0]'),
        (3, 'alpha', 'accepted', 'public', 1, 'orthogonal', '[0,1,0]'),
        (4, 'beta', 'accepted', 'public', 1, 'other-namespace', '[1,0,0]'),
        (5, 'alpha', 'quarantine', 'public', 1, 'not-accepted', '[1,0,0]'),
        (6, 'alpha', 'accepted', 'private', 1, 'not-public', '[1,0,0]'),
    ]
    # Deterministic Fibonacci sphere: unique directions rather than duplicate clusters.
    # This is an ANN benchmark, not an assertion of universal exact recall.
    for index in range(1000):
        x = 1 - 2 * (index + 0.5) / 1000
        radius = math.sqrt(1 - x * x)
        angle = index * math.pi * (3 - math.sqrt(5))
        vector = f'[{x},{radius * math.cos(angle)},{radius * math.sin(angle)}]'
        seed.append((index + 7, 'alpha', 'accepted', 'public', 1, f'fixture-{index + 7}', vector))
    with connection.cursor() as cursor:
        cursor.executemany('INSERT INTO evidence_vectors VALUES (%s,%s,%s,%s,%s,%s,%s::vector)', seed)
    assert connection.execute('SELECT vector_dims(embedding) FROM evidence_vectors LIMIT 1').fetchone()[0] == 3
    record('non_superuser_vector_column_and_1006_persisted_vectors')
    for invalid in ('[1,0]', '[NaN,0,0]', '[Infinity,0,0]'):
        try:
            connection.execute("INSERT INTO evidence_vectors VALUES (99999,'alpha','accepted','public',1,'invalid',%s::vector)", (invalid,))
        except psycopg.DataError:
            pass
        else:
            raise AssertionError('pgvector accepted invalid dimension or nonfinite vector')
    assert connection.execute('SELECT count(*) FROM evidence_vectors WHERE id=99999').fetchone()[0] == 0
    record('dimension_and_nonfinite_input_rejected')
    exact = filtered(connection)
    assert [row[0] for row in exact] == [1, 7]
    assert abs(exact[0][1]) < 1e-7 and abs(exact[1][1] - 0.001) < 1e-6
    known_distance = connection.execute("SELECT embedding <=> '[1,0,0]'::vector FROM evidence_vectors WHERE id=2").fetchone()[0]
    assert abs(known_distance - 0.2) < 1e-6
    record('cosine_distance_exact_order_and_namespace_state_privacy_filters')
    STEP = 'hnsw_index'
    connection.execute('CREATE INDEX evidence_vectors_cosine ON evidence_vectors USING hnsw (embedding vector_cosine_ops)')
    connection.execute('ANALYZE evidence_vectors')
    connection.execute('SET enable_seqscan=off')
    connection.execute("SET hnsw.iterative_scan='strict_order'")
    connection.execute('SET hnsw.ef_search=100')
    plan = connection.execute('''EXPLAIN (FORMAT JSON) SELECT id FROM evidence_vectors
        WHERE namespace='alpha' AND state='accepted' AND privacy='public'
        ORDER BY embedding <=> '[1,0,0]'::vector LIMIT 2''').fetchone()[0]
    REPORT['hnsw_plan'] = plan
    assert 'evidence_vectors_cosine' in json.dumps(plan), 'hnsw_index_not_used'
    approximate = filtered(connection, approximate=True)
    recall = len({row[0] for row in approximate} & {row[0] for row in exact}) / len(exact)
    REPORT['retrieval_observations'] = {
        'exact': exact, 'hnsw': approximate, 'recall_at_2': recall, 'ef_search': 100,
        'iterative_scan': 'strict_order', 'corpus': '1000 Fibonacci sphere vectors plus 6 filter/metric fixtures',
        'limitations': 'Measured recall for this synthetic corpus; ANN does not guarantee complete or exact retrieval.',
    }
    assert len(approximate) == 2 and all(row[0] not in {4, 5, 6} for row in approximate), 'hnsw_filter_leak'
    assert approximate[0][1] <= approximate[1][1], 'hnsw_distance_order'
    for identifier, distance in approximate:
        actual = connection.execute("SELECT embedding <=> '[1,0,0]'::vector FROM evidence_vectors WHERE id=%s", (identifier,)).fetchone()[0]
        assert abs(distance - actual) < 1e-6, 'hnsw_distance_mismatch'
    record('hnsw_cosine_index_used_with_filtered_iterative_scan')
    before = fingerprint(connection)
    connection.close()
    owner.close()
    admin.close()
    STEP = 'restart'
    # PostgreSQL must not inherit a subprocess PIPE; Windows would keep communicate()
    # waiting after pg_ctl exits. Keep server output in the isolated log across restart.
    with (data.parent / 'restart-command.log').open('wb') as restart_log:
        restart = subprocess.run([str(binary / 'pg_ctl.exe'), '-D', str(data), '-l',
                                  str(data.parent / 'postgres.log'), '-m', 'fast', '-w', '-t', '30', 'restart'],
                                 stdout=restart_log, stderr=subprocess.STDOUT, timeout=45)
    assert restart.returncode == 0, 'Isolated restart failed'
    connection = psycopg.connect(**common, user=role, password=app_password, dbname=dbname)
    assert fingerprint(connection) == before and filtered(connection) == exact
    record('vector_rows_and_cosine_results_survive_restart')
    STEP = 'backup_restore'
    backup = data.parent / 'pgvector-backup.dump'
    environment = os.environ.copy()
    environment['PGPASSWORD'] = password
    args = ['--host=127.0.0.1', f'--port={port}', '--username=tire_vector_admin', '--no-password']
    dumped = subprocess.run([str(binary / 'pg_dump.exe'), *args, '--format=custom', f'--file={backup}', dbname], env=environment, capture_output=True, timeout=120)
    assert dumped.returncode == 0 and backup.stat().st_size > 0, 'pgvector backup failed'
    restored = subprocess.run([str(binary / 'pg_restore.exe'), *args, '--exit-on-error', f'--dbname={restored_name}', str(backup)], env=environment, capture_output=True, timeout=120)
    assert restored.returncode == 0, 'pgvector restore failed'
    restored_connection = psycopg.connect(**common, user=role, password=app_password, dbname=restored_name)
    assert fingerprint(restored_connection) == before
    assert filtered(restored_connection) == exact
    index = restored_connection.execute("SELECT indexdef FROM pg_indexes WHERE indexname='evidence_vectors_cosine'").fetchone()[0]
    assert 'USING hnsw' in index and 'vector_cosine_ops' in index
    assert restored_connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0] == '0.8.1'
    REPORT['fingerprint'] = before
    REPORT['backup_bytes'] = backup.stat().st_size
    record('backup_restore_preserves_extension_vector_values_hnsw_index_and_cosine_results')
    restored_connection.close()
    connection.close()
    if os.environ.get('TIRE_VECTOR_BUSINESS_CHECKS') == '1':
        STEP = 'business_embedding_checks'
        business_name = dbname + '_business'
        with psycopg.connect(**admin_args, dbname='postgres') as admin:
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(business_name), sql.Identifier(role)))
        with psycopg.connect(**admin_args, dbname=business_name) as owner:
            owner.execute('CREATE EXTENSION vector')
        environment = os.environ.copy()
        environment['TIRE_VECTOR_BUSINESS_DATABASE_URL'] = URL.create(
            'postgresql+psycopg', username=role, password=app_password,
            host='127.0.0.1', port=port, database=business_name,
        ).render_as_string(hide_password=False)
        child = """import json, os, sys
sys.path.insert(0, 'apps/api/tests')
from test_embeddings import verify_embedding_persistence
result = verify_embedding_persistence(os.environ['TIRE_VECTOR_BUSINESS_DATABASE_URL'])
print(json.dumps({'business_result': result}, ensure_ascii=False, default=str))
"""
        result = subprocess.run([sys.executable, '-c', child], cwd=ROOT, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=180)
        # Never serialize child tracebacks: connection exceptions can include URLs.
        if result.returncode:
            frames = []
            for filename, line, function in re.findall(r'File "([^"]+)", line (\d+), in ([\w<>]+)', result.stderr):
                path = Path(filename).resolve()
                if path.is_relative_to(ROOT / 'apps/api'):
                    frames.append({'file': path.relative_to(ROOT).as_posix(), 'line': int(line), 'function': function})
            REPORT['business_failure'] = {'exit_code': result.returncode, 'frames': frames}
        assert result.returncode == 0, 'business_embedding_checks_failed'
        lines = [line for line in result.stdout.splitlines() if line.startswith('{"business_result":')]
        assert lines, 'business_embedding_result_missing'
        REPORT['business'] = json.loads(lines[-1])['business_result']
        record('business_embedding_persistence_in_separate_non_superuser_database')
        STEP = 'business_backup_restore'
        with psycopg.connect(**common, user=role, password=app_password, dbname=business_name) as connection:
            business_before = all_table_fingerprints(connection)
        assert business_before, 'business_database_has_no_tables'
        business_backup = data.parent / 'business-backup.dump'
        environment = os.environ.copy()
        environment['PGPASSWORD'] = password
        dumped = subprocess.run([str(binary / 'pg_dump.exe'), *args, '--format=custom',
                                 f'--file={business_backup}', business_name],
                                env=environment, capture_output=True, timeout=120)
        assert dumped.returncode == 0 and business_backup.stat().st_size > 0, 'business_backup_failed'
        business_restored = business_name + '_restored'
        with psycopg.connect(**admin_args, dbname='postgres') as admin:
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(business_restored), sql.Identifier(role)))
        restored = subprocess.run([str(binary / 'pg_restore.exe'), *args, '--exit-on-error',
                                   f'--dbname={business_restored}', str(business_backup)],
                                  env=environment, capture_output=True, timeout=120)
        assert restored.returncode == 0, 'business_restore_failed'
        with psycopg.connect(**common, user=role, password=app_password, dbname=business_restored) as connection:
            business_after = all_table_fingerprints(connection)
            extension = connection.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()[0]
            indexes = connection.execute("SELECT indexdef FROM pg_indexes WHERE schemaname='public' AND indexdef LIKE '%%USING hnsw%%'").fetchall()
        assert business_after == business_before and extension == '0.8.1', 'business_restore_mismatch'
        REPORT['business_backup_restore'] = {
            'tables': business_before, 'table_count': len(business_before),
            'backup_bytes': business_backup.stat().st_size, 'hnsw_index_count': len(indexes),
        }
        record('business_all_tables_and_vectors_identical_after_pg_dump_restore')
    REPORT['status'] = 'passed'


if __name__ == '__main__':
    try:
        run()
    except Exception as error:
        REPORT.update(status='failed', failed_step=STEP, error_type=type(error).__name__)
        if isinstance(error, AssertionError) and str(error) in {
            'hnsw_index_not_used', 'hnsw_filter_leak', 'hnsw_distance_order', 'hnsw_distance_mismatch',
            'business_embedding_checks_failed', 'business_embedding_result_missing',
            'business_database_has_no_tables', 'business_backup_failed', 'business_restore_failed',
            'business_restore_mismatch',
        }:
            REPORT['error_code'] = str(error)
        raise SystemExit(1) from None
    finally:
        target = Path(os.environ['TIRE_VECTOR_TEST_REPORT']).resolve()
        if target.is_relative_to((ROOT / '.artifacts/pgvector').resolve()):
            target.write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')

"""Disposable real-pgvector browser QA with synthetic source and model adapters.

Uses an already-built private PostgreSQL runtime, a fresh loopback cluster, and
fake credentials configured only in this process. POST /fixture/shutdown stops
uvicorn and then PostgreSQL. This harness never contacts OpenAI.
"""
from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
from uuid import uuid4

import psycopg
from psycopg import sql
from sqlalchemy import func, select, text
from sqlalchemy.engine import URL
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'apps/api/tests'))
from ai_acceptance import BrowserModel
from test_core import VARIANT, success
from test_embeddings import SyntheticEmbeddings
from test_knowledge import Sources, seed
from tire_api.embedding_gateway import EmbeddingError
from tire_api.embedding_models import EmbeddingCache, EmbeddingCompletion, EmbeddingRequest
from tire_api.main import create_app


class BrowserSources(Sources):
    def sources(self):
        return [{**source, 'name': '合成向量验收来源 · 非真实轮胎',
                 'description': '仅隔离浏览器验收，不代表真实厂商数据。',
                 'supported_models': ['fixturealpha', 'fixturebeta', 'fixturemissing']}
                for source in super().sources()]


class BrowserEmbeddings(SyntheticEmbeddings):
    fail_next = False

    async def embed(self, config, inputs):
        await asyncio.sleep(0.35)
        if self.fail_next:
            self.fail_next = False
            self.calls.append((config.model, config.dimensions, list(inputs)))
            raise EmbeddingError('embeddings_timeout')
        return await super().embed(config, inputs)


def available_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', port))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--postgres-runtime', required=True)
    parser.add_argument('--pg-port', type=int, default=55434)
    parser.add_argument('--api-port', type=int, default=8001)
    args = parser.parse_args()
    artifact_root = (ROOT / '.artifacts/pgvector').resolve()
    runtime = Path(args.postgres_runtime).resolve()
    if not runtime.is_relative_to(artifact_root) or runtime.name != 'postgres':
        raise ValueError('Only a private workspace pgvector runtime is accepted')
    for executable in ('initdb.exe', 'pg_ctl.exe'):
        if not (runtime / 'bin' / executable).is_file():
            raise ValueError('Private PostgreSQL runtime is incomplete')
    if not (runtime / 'lib/vector.dll').is_file():
        raise ValueError('Private runtime must already contain the built pgvector extension')
    for port in (args.pg_port, args.api_port):
        if not 1024 <= port <= 65535:
            raise ValueError('Invalid fixture port')
        available_port(port)
    run = artifact_root / ('vector-ui-' + uuid4().hex)
    run.mkdir()
    data = run / 'data'
    password_file = run / 'init-password.txt'
    admin_password = secrets.token_hex(32)
    password_file.write_text(admin_password, encoding='utf-8')
    binary = runtime / 'bin'
    started = False
    app = None
    summary = {'synthetic': True, 'runtime': str(runtime), 'run_directory': str(run),
               'process_id': os.getpid(), 'pg_port': args.pg_port, 'api_port': args.api_port,
               'server_started': False, 'server_stopped': False, 'api_state': 'initializing'}

    def save_summary():
        encoded = json.dumps(summary, ensure_ascii=False, indent=2)
        (run / 'state.json').write_text(encoded, encoding='utf-8')
        (artifact_root / 'latest-ui.json').write_text(encoded, encoding='utf-8')

    save_summary()
    try:
        with (run / 'initdb.log').open('wb') as output:
            initialized = subprocess.run([str(binary / 'initdb.exe'), '-D', str(data),
                '--username=tire_vector_ui_admin', '--auth=scram-sha-256', '--encoding=UTF8', '--locale=C',
                f'--pwfile={password_file}'], stdout=output, stderr=subprocess.STDOUT, timeout=90)
        if initialized.returncode:
            raise RuntimeError('isolated_initdb_failed')
        with (run / 'pg-control.log').open('ab') as output:
            result = subprocess.run([str(binary / 'pg_ctl.exe'), '-D', str(data), '-l', str(run / 'postgres.log'),
                '-o', f'-h 127.0.0.1 -p {args.pg_port}', '-w', '-t', '30', 'start'],
                stdout=output, stderr=subprocess.STDOUT, timeout=45)
        if result.returncode:
            raise RuntimeError('isolated_postgres_start_failed')
        started = True
        password_file.unlink()
        summary['server_started'] = True
        common = {'host': '127.0.0.1', 'port': args.pg_port, 'user': 'tire_vector_ui_admin',
                  'password': admin_password, 'autocommit': True, 'connect_timeout': 5}
        role = 'tire_vector_ui_app'
        app_password = secrets.token_hex(32)
        dbname = 'tire_vector_ui'
        with psycopg.connect(**common, dbname='postgres') as admin:
            if Path(admin.execute('SHOW data_directory').fetchone()[0]).resolve() != data:
                raise RuntimeError('isolated_cluster_identity_mismatch')
            admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE').format(
                sql.Identifier(role), sql.Literal(app_password)))
            admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(dbname), sql.Identifier(role)))
        with psycopg.connect(**common, dbname=dbname) as admin:
            admin.execute('CREATE EXTENSION vector')
        os.environ.update({
            'TI_AI_ENABLED': '1', 'TI_OPENAI_MODEL': 'synthetic-vector-browser-responses',
            'TI_EMBEDDINGS_ENABLED': '1', 'TI_OPENAI_EMBEDDING_MODEL': 'synthetic-embedding-fixture',
            'TI_OPENAI_EMBEDDING_DIMENSIONS': '3', 'TI_OPENAI_API_KEY': 'synthetic-key-never-live',
            'TI_AI_ALLOW_PRIVATE': '0', 'TI_AI_DAILY_REQUEST_LIMIT': '100',
            'TI_AI_DAILY_TOKEN_LIMIT': '1000000', 'TI_OBJECT_STORE_BACKEND': 'filesystem',
            'TI_OBJECT_STORE_ROOT': str(run / 'objects'),
            'TIRE_CORS_ORIGINS': 'http://localhost:3001,http://127.0.0.1:3001',
        })
        url = URL.create('postgresql+psycopg', username=role, password=app_password,
                         host='127.0.0.1', port=args.pg_port, database=dbname).render_as_string(hide_password=False)
        registry = BrowserSources()
        app = create_app(url, registry)
        # Seed before uvicorn starts accepting requests. Lifespan initialization
        # is idempotent and will recheck the same schema on server startup.
        app.state.database.initialize()
        model = BrowserEmbeddings()
        app.state.embedding_adapter = model
        app.state.ai_adapter = BrowserModel()
        alpha = deepcopy(VARIANT)
        alpha.update(id=str(uuid4()), model='fixturealpha', manufacturer_product_code='FIX-ALPHA')
        alpha['facts'].update(description='湿地制动 静音 合成验收 fixturealpha', technology_features=['Acoustic'])
        beta = deepcopy(VARIANT)
        beta.update(id=str(uuid4()), model='fixturebeta', manufacturer_product_code='FIX-BETA')
        beta['facts'].update(description='日常通勤 舒适 合成验收 fixturebeta')
        missing = deepcopy(VARIANT)
        missing.update(id=str(uuid4()), model='fixturemissing', manufacturer_product_code='FIX-MISSING')
        missing['facts'].update(description='湿地制动 仅全文候选 合成验收 fixturemissing <script>window.vectorCanary=1</script>')
        rows = [alpha, beta, missing]
        seed(app.state.database, rows, query='embedding-browser-qa')
        registry.result = success(variants=rows)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.api_port, log_level='info'))

        @app.get('/fixture/state')
        def fixture_state():
            with app.state.database.sessions() as db:
                counts = {name: db.scalar(select(func.count()).select_from(table)) for name, table in (
                    ('embedding_requests', EmbeddingRequest), ('embedding_completions', EmbeddingCompletion),
                    ('embedding_cache', EmbeddingCache))}
                counts['embedding_vectors'] = db.scalar(text('SELECT count(*) FROM embedding_vectors'))
            return {'synthetic': True, 'real_openai_calls': 0, 'synthetic_calls': len(model.calls),
                    'call_input_counts': [len(call[2]) for call in model.calls], **counts,
                    'run_directory': str(run), 'seed_query': '湿地制动',
                    'models': ['fixturealpha', 'fixturebeta', 'fixturemissing']}

        @app.post('/fixture/fail-next')
        def fail_next():
            model.fail_next = True
            return {'synthetic': True, 'next_embedding_call': 'embeddings_timeout'}

        @app.post('/fixture/shutdown')
        def shutdown():
            server.should_exit = True
            return {'synthetic': True, 'shutdown_requested': True}

        summary['api_state'] = 'running'
        save_summary()
        print(json.dumps({'synthetic': True, 'api': f'http://127.0.0.1:{args.api_port}',
                          'run_directory': str(run), 'pid': os.getpid(), 'seed_query': '湿地制动'}, ensure_ascii=False), flush=True)
        server.run()
        summary['api_state'] = 'stopped'
    except Exception as error:
        # Exception messages may include DB connection strings: log only the class.
        summary.update(api_state='failed', error_type=type(error).__name__)
        print(json.dumps({'synthetic': True, 'status': 'failed', 'error_type': type(error).__name__}), flush=True)
        raise SystemExit(1) from None
    finally:
        if app is not None:
            app.state.database.close()
        if password_file.exists():
            password_file.unlink()
        if started:
            with (run / 'pg-control.log').open('ab') as output:
                stopped = subprocess.run([str(binary / 'pg_ctl.exe'), '-D', str(data), '-m', 'fast', '-w', '-t', '30', 'stop'],
                                         stdout=output, stderr=subprocess.STDOUT, timeout=45)
            summary['server_stopped'] = stopped.returncode == 0
        save_summary()


if __name__ == '__main__':
    main()

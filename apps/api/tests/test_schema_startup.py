"""Atomic schema startup and recovery; PostgreSQL race is also tested by its native runner."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

from version_registry import EXPECTED_SCHEMA_VERSIONS

from tire_api import migrations
from tire_api.db import Database
from tire_api.main import create_app
from test_core import FixtureRegistry, live


def test_runtime_schema_mode_never_silently_migrates(tmp_path, monkeypatch):
    from tire_api.postgres_schema import SchemaContractError
    for mode in ('skip', '', 'VERIFY'):
        with pytest.raises(SchemaContractError):
            Database('sqlite:///:memory:', schema_mode=mode)
    with pytest.raises(SchemaContractError):
        Database('sqlite:///:memory:', schema_mode='verify', schema_contract=tmp_path / 'contract.json',
                 schema_sha256='a' * 64)
    monkeypatch.setenv('TI_DATABASE_SCHEMA_CONTRACT', str(tmp_path / 'contract.json'))
    with pytest.raises(SchemaContractError):
        Database('sqlite:///:memory:')


def test_pg_verify_dispatch_cannot_run_create_or_upgrade(tmp_path, monkeypatch):
    from tire_api import postgres_schema
    from tire_api.db import Base
    monkeypatch.setenv('TI_OBJECT_STORE_ROOT', str(tmp_path / 'objects'))
    database = Database('postgresql+psycopg://synthetic@127.0.0.1/synthetic', schema_mode='verify',
        schema_contract=tmp_path / 'contract.json', schema_sha256='a' * 64)
    calls = []
    def denied(*args, **kwargs):
        raise AssertionError('verify must never perform DDL')
    monkeypatch.setattr(Base.metadata, 'create_all', denied)
    monkeypatch.setattr(migrations, 'upgrade', denied)
    monkeypatch.setattr(postgres_schema, 'verify_schema', lambda *args: calls.append(args))
    try:
        database.initialize()
        assert calls == [(database.engine, tmp_path / 'contract.json', 'a' * 64)]
    finally:
        database.close()


def test_contract_pin_and_closed_json_are_required_before_connection(tmp_path):
    import hashlib
    from tire_api.postgres_schema import SchemaContractError, load_contract
    path = tmp_path / 'contract.json'
    for data in (b'{"schema":1,"schema":2}', b'{"value":NaN}', b'{}'):
        path.write_bytes(data)
        with pytest.raises(SchemaContractError):
            load_contract(path, hashlib.sha256(data).hexdigest())
    with pytest.raises(SchemaContractError):
        load_contract(path, '0' * 64)
    with pytest.raises(SchemaContractError):
        load_contract(path, None)


def test_reference_cli_requires_explicit_empty_target_and_hidden_input(tmp_path, monkeypatch, capsys):
    from tire_api import postgres_schema_cli as cli
    from types import SimpleNamespace
    calls = []
    monkeypatch.setattr(cli, 'postgres_engine', lambda *args: calls.append(args))
    args = ['--postgres-profile', str(tmp_path / 'profile.json'), '--output-file', str(tmp_path / 'contract.json')]
    assert cli.main(args) == 1
    assert 'request_invalid' in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    assert cli.main(args + ['--empty-reference-confirmed']) == 1
    assert 'interactive_authentication_required' in capsys.readouterr().out
    assert calls == []


def test_postgres_vehicle_maintenance_requires_explicit_target_and_offline_confirmation(tmp_path, monkeypatch, capsys):
    from tire_api import vehicle_binary_postgres_cli as cli
    from tire_api.vehicle_binary_postgres import migrate_postgres
    from tire_api.vehicle_binary_migration import VehicleBinaryMigrationError
    from types import SimpleNamespace
    with pytest.raises(VehicleBinaryMigrationError, match='offline_confirmation_required'):
        migrate_postgres(None)
    with pytest.raises(VehicleBinaryMigrationError, match='unsupported_backend'):
        migrate_postgres(SimpleNamespace(dialect=SimpleNamespace(name='sqlite')), offline_confirmed=True)
    calls = []
    monkeypatch.setattr(cli, 'postgres_engine', lambda *args: calls.append(args))
    args = ['--postgres-profile', str(tmp_path / 'profile.json'), '--pg-bin', str(tmp_path),
            '--backup-file', str(tmp_path / 'backup.dump')]
    assert cli.main(args) == 1
    assert 'request_invalid' in capsys.readouterr().out
    monkeypatch.setattr(cli.sys, 'stdin', SimpleNamespace(isatty=lambda: False))
    assert cli.main(args + ['--offline-confirmed']) == 1
    assert 'interactive_authentication_required' in capsys.readouterr().out
    assert calls == []


@pytest.mark.parametrize("attempt", range(3))
def test_concurrent_startup_creates_one_complete_schema(tmp_path, attempt):
    url = f"sqlite:///{(tmp_path / 'shared-startup.db').as_posix()}"
    gate = Barrier(4)

    def initialize(_):
        database = Database(url)
        try:
            gate.wait(timeout=10)
            database.initialize()
        finally:
            database.close()

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(initialize, range(4)))
    database = Database(url)
    try:
        assert {'snapshots', 'verifications', 'manual_fact_revisions', 'vehicle_snapshots'} <= set(inspect(database.engine).get_table_names())
        with database.engine.connect() as connection:
            assert set(connection.execute(text('SELECT version FROM tire_schema_versions')).scalars()) == set(EXPECTED_SCHEMA_VERSIONS)
    finally:
        database.close()


def test_failed_initial_upgrade_leaves_no_half_created_schema(tmp_path, monkeypatch):
    database = Database(f"sqlite:///{(tmp_path / 'failed-initialize.db').as_posix()}")
    original = migrations.upgrade

    def fail(connection):
        original(connection)
        raise RuntimeError('injected migration failure')

    monkeypatch.setattr(migrations, 'upgrade', fail)
    with pytest.raises(RuntimeError, match='injected migration failure'):
        database.initialize()
    assert inspect(database.engine).get_table_names() == []
    monkeypatch.setattr(migrations, 'upgrade', original)
    database.initialize()
    assert 'snapshots' in inspect(database.engine).get_table_names()
    database.close()


def test_failed_upgrade_rolls_back_ddl_without_losing_existing_evidence(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'existing-evidence.db').as_posix()}"
    app = create_app(url, FixtureRegistry())
    with TestClient(app) as client:
        result = live(client).json()
        snapshot_id = result['provenance'][0]['snapshot_id']
        before = client.get(f'/v1/evidence/{snapshot_id}').json()
    database = Database(url)
    original = migrations.upgrade

    def fail(connection):
        connection.exec_driver_sql('ALTER TABLE verifications ADD COLUMN rejected_migration TEXT')
        raise RuntimeError('injected migration failure')

    monkeypatch.setattr(migrations, 'upgrade', fail)
    with pytest.raises(RuntimeError, match='injected migration failure'):
        database.initialize()
    assert 'rejected_migration' not in {column['name'] for column in inspect(database.engine).get_columns('verifications')}
    database.close()
    monkeypatch.setattr(migrations, 'upgrade', original)
    with TestClient(create_app(url, FixtureRegistry())) as client:
        assert client.get(f'/v1/evidence/{snapshot_id}').json() == before

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

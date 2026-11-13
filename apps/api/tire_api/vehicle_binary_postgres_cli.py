"""Explicit stopped-writer PG vehicle migration with a snapshot database backup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .external_fact_governance import GovernanceError
from .external_fact_governance_cli import _Parser, _password, _request
from .external_fact_governance_postgres import postgres_connect_args, postgres_engine
from .vehicle_binary_migration import VehicleBinaryMigrationError
from .vehicle_binary_postgres import migrate_postgres


def snapshot_backup(connection, parameters, password, pg_bin, backup_file):
    output = Path(backup_file)
    program = Path(pg_bin) / ('pg_dump.exe' if os.name == 'nt' else 'pg_dump')
    if (not output.is_absolute() or output.is_symlink() or output.exists() or not output.parent.is_dir()
            or not program.is_absolute() or not program.is_file() or program.is_symlink()):
        raise VehicleBinaryMigrationError('vehicle_binary_backup_path_invalid')
    snapshot = connection.exec_driver_sql('SELECT pg_export_snapshot()').scalar()
    environment = {name: value for name, value in os.environ.items() if not name.upper().startswith('PG')}
    variables = {'host': 'PGHOST', 'port': 'PGPORT', 'dbname': 'PGDATABASE', 'user': 'PGUSER',
                 'sslmode': 'PGSSLMODE', 'sslrootcert': 'PGSSLROOTCERT', 'sslcertmode': 'PGSSLCERTMODE',
                 'gssencmode': 'PGGSSENCMODE', 'require_auth': 'PGREQUIREAUTH', 'channel_binding': 'PGCHANNELBINDING',
                 'connect_timeout': 'PGCONNECT_TIMEOUT', 'client_encoding': 'PGCLIENTENCODING'}
    environment.update({variables[name]: str(value) for name, value in parameters.items() if name in variables})
    environment['PGPASSWORD'] = password
    try:
        with output.open('xb') as stream:
            process = subprocess.run([str(program), '--format=custom', '--no-password', '--snapshot', snapshot],
                                     stdout=stream, stderr=subprocess.PIPE, env=environment, timeout=120)
            stream.flush()
            os.fsync(stream.fileno())
        if process.returncode != 0 or output.stat().st_size < 5:
            raise VehicleBinaryMigrationError('vehicle_binary_backup_failed')
        digest = hashlib.sha256()
        with output.open('rb') as stream:
            if stream.read(5) != b'PGDMP':
                raise VehicleBinaryMigrationError('vehicle_binary_backup_failed')
            stream.seek(0)
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return {'format': 'pg_dump_custom', 'sha256': digest.hexdigest(), 'bytes': output.stat().st_size,
                'exported_snapshot': True}
    except VehicleBinaryMigrationError:
        raise
    except Exception:
        raise VehicleBinaryMigrationError('vehicle_binary_backup_failed') from None
    finally:
        environment.pop('PGPASSWORD', None)


def main(argv=None):
    engine = None
    result = {'ok': False, 'code': 'vehicle_binary_migration_failed'}
    try:
        parser = _Parser(description='Explicit PostgreSQL vehicle 024 maintenance with snapshot backup.')
        parser.add_argument('--postgres-profile', required=True)
        parser.add_argument('--pg-bin', required=True)
        parser.add_argument('--backup-file', required=True)
        parser.add_argument('--offline-confirmed', action='store_true', required=True)
        args = parser.parse_args(argv)
        if not sys.stdin.isatty():
            raise GovernanceError('interactive_authentication_required')
        parameters = postgres_connect_args(_request(args.postgres_profile))
        password = _password('Maintenance PostgreSQL password: ')
        try:
            engine = postgres_engine(parameters, password)
            result = {'ok': True, **migrate_postgres(engine, offline_confirmed=args.offline_confirmed,
                backup=lambda connection: snapshot_backup(connection, parameters, password, args.pg_bin, args.backup_file))}
        finally:
            del password
    except (VehicleBinaryMigrationError, GovernanceError) as error:
        result = {'ok': False, 'code': error.code}
    except (Exception, KeyboardInterrupt):
        result = {'ok': False, 'code': 'vehicle_binary_migration_failed'}
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                result = {'ok': False, 'code': 'vehicle_binary_migration_failed'}
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

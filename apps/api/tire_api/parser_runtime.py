"""Bounded, terminable subprocess execution of a fixed trusted parser catalog.

Untrusted source content is JSON-framed data. This is process fault isolation;
the child retains OS-user filesystem rights and has no kernel network sandbox.
"""
import asyncio
import base64
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from uuid import uuid4

from .parser_limits import CPU_SECONDS, MEMORY_BYTES, WindowsJob, apply_parent_linux_limits
from . import parser_bundles as bundles

PROTOCOL = 'parser-json@2'
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_PROTOCOL_BYTES = 12 * 1024 * 1024
MAX_OUTPUT_BYTES = 4 * 1024 * 1024
MAX_STDERR_BYTES = 64 * 1024
TIMEOUT_SECONDS = 8.0
MAX_CONCURRENT = 2
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_ROOT = Path(__file__).resolve().parent
_CHILD = _ROOT / 'parser_child.py'
_HOST_ROOT = Path(__file__).resolve().parent


class ParserRunError(Exception):
    def __init__(self, code, receipt=None):
        super().__init__(code)
        self.code = code
        self.receipt = receipt or {}


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('duplicate_json_key')
            result[key] = item
        return result

    def invalid(_value):
        raise ValueError('nonfinite_json')

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite_json')
        return number

    return json.loads(value, object_pairs_hook=pairs, parse_constant=invalid, parse_float=finite)


def _specs():
    from .adapters.michelin_regions import MICHELIN_REGIONS
    from .adapters import hankook, toyo, xiaomi, nhtsa, pirelli
    values = {'michelin-us': ('michelin-us-astro@2.0.0', 'tire', ['adapters/michelin.py', 'adapters/michelin_regions.py', 'adapters/registry.py'])}
    for source, config in MICHELIN_REGIONS.items():
        values[source] = (config['parser_version'], 'tire', ['adapters/michelin.py', 'adapters/michelin_regions.py', 'adapters/registry.py'])
    for adapter in (hankook, toyo, pirelli):
        values[adapter.SOURCE_CONFIG['id']] = (adapter.PARSER_VERSION, 'tire', [f'adapters/{adapter.__name__.rsplit(".", 1)[1]}.py', 'adapters/registry.py'])
    values[xiaomi.SOURCE_ID] = (xiaomi.PARSER_VERSION, 'vehicle', ['adapters/xiaomi.py', 'adapters/transport.py', 'adapters/robots.py', 'captures.py', 'db.py'])
    values[nhtsa.SOURCE_ID] = (nhtsa.PARSER_VERSION, 'recall', ['adapters/nhtsa.py', 'adapters/transport.py', 'adapters/robots.py', 'captures.py'])
    return values


def limits():
    return {'input_bytes': MAX_BODY_BYTES, 'output_bytes': MAX_OUTPUT_BYTES,
            'stderr_bytes': MAX_STDERR_BYTES, 'wall_seconds': TIMEOUT_SECONDS, 'cpu_seconds': CPU_SECONDS,
            'memory_bytes': MEMORY_BYTES, 'max_concurrent': MAX_CONCURRENT}


def query_fields(target_kind, query):
    if target_kind == 'vehicle':
        return {'vehicle_id'}
    if target_kind == 'recall':
        return {'search', 'offset'} if isinstance(query, dict) and 'search' in query else {'campaign_number'}
    return {'model', 'size'}


def source_catalog():
    return {source: {'parser_version': value[0], 'target_kind': value[1]} for source, value in _specs().items()}


def _host_digest():
    files = {'parser_child.py': _CHILD, **{name: _HOST_ROOT / name for name in
             ('parser_runtime.py', 'parser_limits.py', 'parser_bundles.py')}}
    return bundles.digest({name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()})


def descriptor_for_manifest(manifest, source_id):
    if not isinstance(source_id, str) or source_id not in manifest['parsers']:
        raise ParserRunError('parser_source_not_allowed')
    entry = manifest['parsers'][source_id]
    parser_digest = bundles.digest({'bundle_id': manifest['bundle_id'], 'source_id': source_id, **entry})
    execution_digest = bundles.digest({'host_digest': _host_digest(), 'bundle_id': manifest['bundle_id'],
        'source_id': source_id, 'parser_digest': parser_digest, 'protocol': PROTOCOL, 'limits': limits()})
    return {'source_id': source_id, **entry, 'parser_digest': parser_digest, 'bundle_id': manifest['bundle_id'],
            'execution_digest': execution_digest, 'runtime_version': PROTOCOL,
            'isolation': 'process_fault_isolation', 'network_enforced': False,
            'python_network_guard': True, 'limits': limits()}


def _deployed_manifest():
    return bundles.snapshot_manifest(_ROOT, source_catalog(), PROTOCOL, limits())


def current_parser(source_id):
    try:
        return descriptor_for_manifest(_deployed_manifest(), source_id)
    except bundles.BundleError as error:
        raise ParserRunError(error.code) from None


def parser_catalog():
    try:
        manifest = _deployed_manifest()
        return {source: descriptor_for_manifest(manifest, source) for source in manifest['parsers']}
    except bundles.BundleError as error:
        raise ParserRunError(error.code) from None


def _environment(directory):
    environment = {'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1', 'TEMP': directory, 'TMP': directory}
    if sys.platform == 'win32':
        system_root = os.environ.get('SystemRoot') or os.environ.get('SYSTEMROOT')
        if not system_root or not Path(system_root).is_dir():
            raise ParserRunError('parser_isolation_unavailable')
        environment.update(SystemRoot=system_root, WINDIR=system_root)
    elif sys.platform == 'linux':
        environment['LANG'] = 'C.UTF-8'
    else:
        raise ParserRunError('parser_isolation_unavailable')
    return environment


def _command():
    executable = Path(getattr(sys, '_base_executable', sys.executable)).resolve(strict=True)
    directories = sorted({str(Path(sysconfig.get_path(name)).resolve(strict=True)) for name in ('purelib', 'platlib')})
    if not executable.is_file() or any(not Path(value).is_dir() for value in directories):
        raise ParserRunError('parser_isolation_unavailable')
    return [str(executable), '-I', '-S', '-B', str(_CHILD), *directories]


def _check_preparation_budget(cancelled, deadline):
    if cancelled.is_set():
        raise ParserRunError('parser_cancelled')
    if time.monotonic() >= deadline:
        raise ParserRunError('parser_timeout')


def _run_sync(request, descriptor, cancelled, execution):
    start = time.monotonic()
    receipt = {'run_id': request['run_id'], 'source_id': descriptor['source_id'], 'parser_version': descriptor['parser_version'],
        'parser_digest': descriptor['parser_digest'], 'pid': None, 'exit_code': None, 'isolation': 'process_fault_isolation',
        'network_enforced': False, 'python_network_guard': True, 'limits': descriptor['limits'], 'reaped': False,
        'bundle_id': request['bundle_id'], 'input_hash': request['input_hash'],
        'execution_digest': request['execution_digest'], 'deployment_revision': request['deployment_revision']}
    deadline = start + TIMEOUT_SECONDS
    acquired, process, job = False, None, None
    threads, buffers, errors = [], {'stdout': bytearray(), 'stderr': bytearray()}, []
    failure = None
    response = None
    try:
        while not acquired:
            if cancelled.is_set():
                raise ParserRunError('parser_cancelled')
            if time.monotonic() >= deadline:
                raise ParserRunError('parser_timeout')
            acquired = _slots.acquire(timeout=0.02)
        encoded = json.dumps(request, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        if len(encoded) > MAX_PROTOCOL_BYTES:
            raise ParserRunError('parser_input_too_large')
        _check_preparation_budget(cancelled, deadline)
        with tempfile.TemporaryDirectory(prefix='tire-parser-') as directory:
            try:
                package_root = Path(directory) / 'package' / 'tire_api'
                if execution['sealed']:
                    source_root = bundles.verify_bundle(request['manifest'])['package_root']
                else:
                    source_root = execution['source_root']
                _check_preparation_budget(cancelled, deadline)
                bundles.copy_verified(source_root, request['manifest'], package_root, source=not execution['sealed'])
                _check_preparation_budget(cancelled, deadline)
                command = [*_command(), '--execution-root', str(package_root.parent)]
                environment = _environment(directory)
                _check_preparation_budget(cancelled, deadline)
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    cwd=directory, env=environment, shell=False, close_fds=True, bufsize=0,
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
                    start_new_session=sys.platform == 'linux')
                receipt['pid'] = process.pid
                if sys.platform == 'win32':
                    try:
                        job = WindowsJob(process)
                    except Exception:
                        raise ParserRunError('parser_isolation_unavailable') from None
                    receipt['limits_backend'] = 'windows_job_object'
                else:
                    try:
                        apply_parent_linux_limits(process.pid)
                    except Exception:
                        raise ParserRunError('parser_isolation_unavailable') from None
                    receipt['limits_backend'] = 'linux_resource_process_group'
                _check_preparation_budget(cancelled, deadline)

                def reader(stream, name, maximum):
                    try:
                        while chunk := stream.read(65536):
                            if len(buffers[name]) + len(chunk) > maximum:
                                errors.append('parser_output_too_large' if name == 'stdout' else 'parser_stderr_too_large')
                                return
                            buffers[name].extend(chunk)
                    except OSError:
                        errors.append('parser_protocol_invalid')

                def writer():
                    try:
                        _check_preparation_budget(cancelled, deadline)
                        process.stdin.write(b'GO\n')
                        data = memoryview(encoded)
                        while data:
                            written = process.stdin.write(data[:65536])
                            if not written:
                                return
                            data = data[written:]
                    except ParserRunError as error:
                        errors.append(error.code)
                    except (BrokenPipeError, OSError):
                        pass
                    finally:
                        process.stdin.close()

                for name, stream, maximum in (('stdout', process.stdout, MAX_OUTPUT_BYTES), ('stderr', process.stderr, MAX_STDERR_BYTES)):
                    thread = threading.Thread(target=reader, args=(stream, name, maximum), name=f'tire-parser-{name}-{process.pid}', daemon=True)
                    threads.append(thread)
                    thread.start()
                thread = threading.Thread(target=writer, name=f'tire-parser-input-{process.pid}', daemon=True)
                threads.append(thread)
                thread.start()
                while True:
                    if cancelled.is_set():
                        raise ParserRunError('parser_cancelled')
                    if errors:
                        raise ParserRunError(errors[0])
                    if time.monotonic() >= deadline:
                        raise ParserRunError('parser_timeout')
                    if process.poll() is not None and not any(thread.is_alive() for thread in threads):
                        break
                    time.sleep(0.01)
                if process.returncode:
                    code = {77: 'parser_isolation_unavailable', 78: 'parser_protocol_invalid',
                            79: 'parser_code_mismatch', 80: 'parser_output_too_large'}.get(process.returncode, 'parser_crashed')
                    raise ParserRunError(code)
                try:
                    response = strict_json(bytes(buffers['stdout']))
                    if not isinstance(response, dict) or response.get('protocol') != PROTOCOL or response.get('run_id') != request['run_id'] or type(response.get('ok')) is not bool:
                        raise ValueError('invalid_response')
                    if not response['ok']:
                        if set(response) != {'protocol', 'run_id', 'ok', 'error'} or response['error'] not in {'parser_schema_changed', 'parser_failed'} | bundles.ERROR_CODES:
                            raise ValueError('invalid_error')
                        raise ParserRunError(response['error'])
                    if set(response) != {'protocol', 'run_id', 'ok', 'payload', 'source_id', 'parser_version', 'parser_digest',
                                         'limits_backend', 'bundle_id', 'input_hash', 'execution_digest', 'deployment_revision'}:
                        raise ValueError('invalid_response_keys')
                    for name in ('source_id', 'parser_version', 'parser_digest', 'limits_backend', 'bundle_id',
                                 'input_hash', 'execution_digest', 'deployment_revision'):
                        if response[name] != receipt[name]:
                            raise ValueError('invalid_response_identity')
                    expected = dict if descriptor['target_kind'] == 'vehicle' or descriptor['target_kind'] == 'recall' and 'search' in request['query'] else list
                    if not isinstance(response['payload'], expected):
                        raise ValueError('invalid_payload_type')
                    bundles.verify_tree(package_root, request['manifest'])
                    if execution['sealed']:
                        bundles.verify_bundle(request['manifest'])
                    elif bundles._metadata(bundles._tree(source_root, source=True)) != request['manifest']['files']:
                        raise ParserRunError('parser_code_mismatch')
                    if descriptor_for_manifest(request['manifest'], descriptor['source_id'])['execution_digest'] != descriptor['execution_digest']:
                        raise ParserRunError('parser_code_mismatch')
                except (ValueError, TypeError, KeyError, RecursionError, UnicodeError):
                    raise ParserRunError('parser_protocol_invalid') from None
            finally:
                if process is not None:
                    try:
                        if job:
                            job.terminate()
                        elif sys.platform == 'linux':
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                        elif process.poll() is None:
                            process.kill()
                        process.wait(timeout=3)
                    finally:
                        if job:
                            job.close()
                        receipt['exit_code'] = process.returncode
                        receipt['reaped'] = process.returncode is not None
                        for thread in threads:
                            thread.join(timeout=2)
                        for stream in (process.stdin, process.stdout, process.stderr):
                            stream.close()
                    if not receipt['reaped'] or any(thread.is_alive() for thread in threads):
                        raise ParserRunError('parser_cleanup_failed')
    except ParserRunError as error:
        failure = error.code
    except bundles.BundleError as error:
        failure = error.code
    except Exception:
        failure = 'parser_isolation_unavailable' if process is None else 'parser_cleanup_failed'
    finally:
        if acquired:
            _slots.release()
        receipt.update(elapsed_ms=round((time.monotonic() - start) * 1000), stdout_bytes=len(buffers['stdout']), stderr_bytes=len(buffers['stderr']))
    if failure:
        raise ParserRunError(failure, receipt)
    return {'payload': response['payload'], 'receipt': receipt}


def input_hash(request, raw):
    return bundles.digest({name: request[name] for name in ('run_id', 'source_id', 'parser_version', 'parser_digest',
        'bundle_id', 'execution_digest', 'deployment_revision', 'query')} | {'raw_sha256': hashlib.sha256(raw).hexdigest()})


async def parse_isolated(source_id, body, query, parser_version, parser_digest, *, bundle_manifest=None, deployment_revision=None):
    try:
        manifest = (bundles.checked_manifest(bundle_manifest, protocol=PROTOCOL, limits=limits())
                    if bundle_manifest is not None else _deployed_manifest())
        descriptor = descriptor_for_manifest(manifest, source_id)
    except bundles.BundleError as error:
        raise ParserRunError(error.code) from None
    if descriptor['parser_version'] != parser_version:
        raise ParserRunError('parser_version_mismatch')
    if descriptor['parser_digest'] != parser_digest:
        raise ParserRunError('parser_code_mismatch')
    if isinstance(body, str):
        try:
            body = body.encode('utf-8', errors='strict')
        except UnicodeError:
            raise ParserRunError('parser_input_invalid') from None
    if not isinstance(body, bytes) or not body:
        raise ParserRunError('parser_input_invalid')
    if len(body) > MAX_BODY_BYTES:
        raise ParserRunError('parser_input_too_large')
    if deployment_revision is not None and (type(deployment_revision) is not int or not 0 <= deployment_revision <= 2**53):
        raise ParserRunError('parser_input_invalid')
    allowed = query_fields(descriptor['target_kind'], query)
    if (not isinstance(query, dict) or set(query) - allowed or any(not isinstance(value, str) or len(value) > 256 for value in query.values())
            or descriptor['target_kind'] == 'vehicle' and not query.get('vehicle_id')
            or descriptor['target_kind'] == 'recall' and set(query) != allowed):
        raise ParserRunError('parser_input_invalid')
    request = {'protocol': PROTOCOL, 'run_id': uuid4().hex, 'source_id': source_id, 'parser_version': parser_version,
               'parser_digest': parser_digest, 'query': dict(query), 'body_base64': base64.b64encode(body).decode('ascii'),
               'manifest': manifest, 'bundle_id': manifest['bundle_id'], 'execution_digest': descriptor['execution_digest'],
               'deployment_revision': deployment_revision}
    request['input_hash'] = input_hash(request, body)
    cancelled = threading.Event()
    execution = {'sealed': bundle_manifest is not None, 'source_root': _ROOT}
    task = asyncio.create_task(asyncio.to_thread(_run_sync, request, descriptor, cancelled, execution))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        # Cancellation is returned only after the supervisor has killed/reaped
        # the process and joined pipe workers. Cancelling to_thread alone cannot
        # terminate a running thread or parser.
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
            except ParserRunError:
                break
        if task.done():
            try:
                task.result()
            except ParserRunError:
                pass
        raise

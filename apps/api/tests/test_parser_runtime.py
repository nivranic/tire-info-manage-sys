"""Real parser processes and actual OS resource limits; no HTTP test backdoor."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from tire_api import parser_runtime as runtime
from tire_api.adapters import hankook, toyo, xiaomi, pirelli
from tire_api.adapters.michelin import parse_michelin_html
from test_michelin import _page, _cn_body
from test_brand_adapters import hankook_body, toyo_body, REAL_FIXTURES
from test_vehicles import body as vehicle_body


@pytest.fixture(autouse=True)
def stable_deployed_source(monkeypatch, tmp_path):
    # Other agents may edit unrelated package modules during a test run. Each
    # test has a trusted source snapshot, as a real immutable deployment does.
    source = tmp_path / 'deployed_source'
    for path in runtime._ROOT.rglob('*.py'):
        target = source / path.relative_to(runtime._ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    monkeypatch.setattr(runtime, '_ROOT', source)


def execute(source='michelin-us', body=None, query=None):
    descriptor = runtime.current_parser(source)
    return asyncio.run(runtime.parse_isolated(source, _page() if body is None else body, query or {},
        descriptor['parser_version'], descriptor['parser_digest']))


@pytest.mark.parametrize('source', ['michelin-us', 'michelin-uk', 'michelin-fr', 'michelin-de', 'michelin-cn', 'toyo-us', 'hankook-us', 'pirelli-us', 'xiaomi-cn-vehicles'])
def test_real_child_matches_fixed_pure_parser(source):
    query = {}
    if source.startswith('michelin-'):
        region = source.rsplit('-', 1)[1].upper()
        body = _cn_body() if region == 'CN' else _page()
        expected = parse_michelin_html(body, query, region=region)
    elif source == 'toyo-us':
        body, expected = toyo_body(), toyo.parse_html(toyo_body(), query)
    elif source == 'hankook-us':
        body, expected = hankook_body(), hankook.parse_html(hankook_body(), query)
    elif source == 'pirelli-us':
        query = {'model': 'P ZERO (PZ4)', 'size': '265/40R20'}
        body = (REAL_FIXTURES / 'pirelli-pz4-265-40-r20-excerpt.html').read_text(encoding='utf-8')
        expected = pirelli.parse_html(body, query)
    else:
        body, query = vehicle_body(), {'vehicle_id': xiaomi.CURRENT_ID}
        expected = xiaomi.parse_config(body)
    value = execute(source, body, query)
    assert value['payload'] == expected
    receipt = value['receipt']
    assert receipt['pid'] != os.getpid() and receipt['exit_code'] == 0 and receipt['reaped']
    assert receipt['isolation'] == 'process_fault_isolation' and receipt['network_enforced'] is False
    assert receipt['python_network_guard'] is True and receipt['stderr_bytes'] == 0
    assert receipt['limits_backend'] == ('windows_job_object' if sys.platform == 'win32' else 'linux_resource_process_group')


@pytest.mark.parametrize('source,filename,parser', [
    ('toyo-us', 'toyo-proxes-sport-excerpt.json', toyo.parse_html),
    ('hankook-us', 'hankook-runflat-pair-excerpt.html', hankook.parse_html),
])
def test_saved_real_source_excerpts_roundtrip_child(source, filename, parser):
    body = (REAL_FIXTURES / filename).read_text(encoding='utf-8')
    assert execute(source, body)['payload'] == parser(body, {})


PROBE = r'''
import json,os,sys,time
from pathlib import Path
assert sys.stdin.buffer.read(3)==b'GO\n'
case=sys.argv[1]
sys.path.extend(sys.argv[2:])
sys.path.append(PACKAGE_ROOT)
from tire_api.parser_limits import apply_child_limits,python_network_guard,MEMORY_BYTES
backend=apply_child_limits()
if case=='blocked_input':
    sys.stderr.buffer.write(b'entered-blocked-input');sys.stderr.buffer.flush()
    time.sleep(60)
request=json.loads(sys.stdin.buffer.read())
if case=='crash': os._exit(61)
if case=='hang':
    sys.stderr.buffer.write(b'entered-hang');sys.stderr.buffer.flush()
    time.sleep(60)
if case=='cpu':
    while True: pass
if case=='memory':
    value=bytearray(MEMORY_BYTES*2)
    os._exit(62)
if case=='stdout':
    sys.stdout.buffer.write(b'x'*(4*1024*1024+65536));sys.stdout.buffer.flush();time.sleep(60)
if case=='stderr':
    sys.stderr.buffer.write(b'x'*(64*1024+65536));sys.stderr.buffer.flush();time.sleep(60)
if case=='malformed':
    print('{"protocol":1,"protocol":2}');sys.stdout.flush();os._exit(0)
if case=='nonfinite':
    print('{"bad":1e999}');sys.stdout.flush();os._exit(0)
payload=[]
if case=='environment':
    forbidden=['TI_OPENAI_API_KEY','DATABASE_URL','HTTP_PROXY','HTTPS_PROXY','PYTHONPATH','TI_PARSER_TEST_SECRET']
    payload=[{'forbidden_present':[name for name in forbidden if name in os.environ],
              'cwd_is_temporary':Path.cwd().name.startswith('tire-parser-'),'no_site':bool(sys.flags.no_site),'isolated':bool(sys.flags.isolated)}]
if case=='network_guard':
    python_network_guard()
    import socket
    try: socket.socket()
    except PermissionError: payload=[{'python_socket_denied':True}]
    else: payload=[{'python_socket_denied':False}]
if case=='spawn':
    import subprocess
    try:
        child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
        child.wait(timeout=2)
        payload=[{'spawned':True,'child_exit':child.returncode}]
    except OSError: payload=[{'spawned':False}]
if case=='echo': time.sleep(0.2)
result={'protocol':request['protocol'],'run_id':request['run_id'],'ok':True,'payload':payload,
        'source_id':request['source_id'],'parser_version':request['parser_version'],
        'parser_digest':request['parser_digest'],'limits_backend':backend,
        **{key:request[key] for key in ('bundle_id','input_hash','execution_digest','deployment_revision')}}
print(json.dumps(result));sys.stdout.flush()
'''


def probe_child(monkeypatch, tmp_path, case):
    """Tests alone substitute the parent command; no production source/HTTP flag."""
    command = runtime._command()
    script = tmp_path / f'probe_{case}.py'
    # The raw string above intentionally spells \n in Python source, not an
    # actual line break inside the bytes literal.
    script.write_text(PROBE.replace('PACKAGE_ROOT', repr(str(Path(runtime.__file__).parent.parent))), encoding='utf-8')
    monkeypatch.setattr(runtime, '_command', lambda: [*command[:4], str(script), case, *command[5:]])


@pytest.mark.parametrize('case,code', [('crash', 'parser_crashed'), ('hang', 'parser_timeout'),
    ('blocked_input', 'parser_timeout'), ('stdout', 'parser_output_too_large'), ('stderr', 'parser_stderr_too_large'),
    ('malformed', 'parser_protocol_invalid'), ('nonfinite', 'parser_protocol_invalid')])
def test_child_failures_are_bounded_killed_and_reaped(monkeypatch, tmp_path, case, code):
    probe_child(monkeypatch, tmp_path, case)
    # Keep the production wall budget: it includes verified package copying.
    # A 1.5s override can expire before Popen on Windows and never run the probe.
    with pytest.raises(runtime.ParserRunError) as raised:
        execute(body='x' * (1024 * 1024) if case == 'blocked_input' else _page())
    assert raised.value.code == code
    receipt = raised.value.receipt
    assert receipt['pid'] and receipt['reaped'] and receipt['exit_code'] is not None
    if case in {'hang', 'blocked_input'}:
        assert receipt['stderr_bytes'] > 0  # The intended blocked child branch ran.
    assert receipt['stdout_bytes'] <= runtime.MAX_OUTPUT_BYTES and receipt['stderr_bytes'] <= runtime.MAX_STDERR_BYTES
    assert not any(thread.name.startswith('tire-parser-') and thread.name.endswith(str(receipt['pid'])) for thread in threading.enumerate())


@pytest.mark.parametrize('case', ['memory', 'cpu'])
def test_real_kernel_memory_and_cpu_limits(monkeypatch, tmp_path, case):
    probe_child(monkeypatch, tmp_path, case)
    monkeypatch.setattr(runtime, 'TIMEOUT_SECONDS', 15)
    with pytest.raises(runtime.ParserRunError) as raised:
        execute()
    assert raised.value.code == 'parser_crashed'
    assert raised.value.receipt['reaped'] and raised.value.receipt['exit_code'] not in (None, 0, 62)
    assert raised.value.receipt['elapsed_ms'] < 15000


def test_clean_environment_isolated_imports_and_python_guard(monkeypatch, tmp_path):
    for name in ('TI_OPENAI_API_KEY', 'DATABASE_URL', 'HTTP_PROXY', 'HTTPS_PROXY', 'PYTHONPATH', 'TI_PARSER_TEST_SECRET'):
        monkeypatch.setenv(name, 'synthetic-never-forward')
    probe_child(monkeypatch, tmp_path, 'environment')
    result = execute()['payload'][0]
    assert result == {'forbidden_present': [], 'cwd_is_temporary': True, 'no_site': True, 'isolated': True}
    monkeypatch.undo()
    probe_child(monkeypatch, tmp_path, 'network_guard')
    value = execute()
    assert value['payload'] == [{'python_socket_denied': True}]
    assert value['receipt']['network_enforced'] is False  # not a kernel security claim


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job active-process enforcement')
def test_windows_job_blocks_descendant_even_without_python_audit_guard(monkeypatch, tmp_path):
    probe_child(monkeypatch, tmp_path, 'spawn')
    assert execute()['payload'] == [{'spawned': False}]


def test_cancel_waits_for_real_child_reaping(monkeypatch, tmp_path):
    probe_child(monkeypatch, tmp_path, 'hang')
    processes = []
    original = runtime.subprocess.Popen
    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
    async def cancelled():
        descriptor = runtime.current_parser('michelin-us')
        task = asyncio.create_task(runtime.parse_isolated('michelin-us', _page(), {}, descriptor['parser_version'], descriptor['parser_digest']))
        for _ in range(200):
            if processes: break
            await asyncio.sleep(0.01)
        assert processes
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(cancelled())
    assert len(processes) == 1 and processes[0].returncode is not None
    assert not any(thread.name.startswith('tire-parser-') and thread.name.endswith(str(processes[0].pid)) for thread in threading.enumerate())


def test_process_concurrency_never_exceeds_two(monkeypatch, tmp_path):
    probe_child(monkeypatch, tmp_path, 'echo')
    # Six requests need three waves of verified copying, execution and cleanup.
    # This checks concurrency, not that all three waves fit one 8s wall budget.
    monkeypatch.setattr(runtime, 'TIMEOUT_SECONDS', 3 * runtime.TIMEOUT_SECONDS)
    original = runtime.subprocess.Popen
    processes, counts, lock = [], [], threading.Lock()
    first_wave = threading.Barrier(runtime.MAX_CONCURRENT)
    overlap_errors = []
    def popen(*args, **kwargs):
        with lock:
            process = original(*args, **kwargs)
            processes.append(process)
            counts.append(sum(child.poll() is None for child in processes))
            synchronize = len(processes) <= runtime.MAX_CONCURRENT
        if synchronize:
            try:
                # Both real children wait for GO until their handles return.
                first_wave.wait(timeout=runtime.TIMEOUT_SECONDS)
            except threading.BrokenBarrierError as error:
                # Return the handle so the supervisor can always reap it.
                overlap_errors.append(error)
        return process
    monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: execute(), range(6)))
    assert not overlap_errors
    assert max(counts) == runtime.MAX_CONCURRENT == 2 and len(processes) == 6
    assert all(row['receipt']['reaped'] and row['receipt']['exit_code'] == 0 for row in results)
    assert all(process.returncode == 0 for process in processes)
    assert {row['receipt']['pid'] for row in results} == {process.pid for process in processes}
    assert not any(thread.name.startswith('tire-parser-') and
                   any(thread.name.endswith(f'-{process.pid}') for process in processes)
                   for thread in threading.enumerate())


def test_queue_wait_consumes_wall_budget_before_process_spawn(monkeypatch):
    assert runtime.TIMEOUT_SECONDS == 8.0 and runtime.MAX_CONCURRENT == 2
    # Occupied real slots make deadline expiry deterministic; shorten only this
    # test's wait instead of spending the production eight seconds asleep.
    monkeypatch.setattr(runtime, 'TIMEOUT_SECONDS', 0.1)
    def no_process(*args, **kwargs):
        raise AssertionError('queued request must time out before spawning')
    monkeypatch.setattr(runtime.subprocess, 'Popen', no_process)
    held_slots = 0
    try:
        for _ in range(runtime.MAX_CONCURRENT):
            assert runtime._slots.acquire(blocking=False)
            held_slots += 1
        with pytest.raises(runtime.ParserRunError) as raised:
            execute()
        assert raised.value.code == 'parser_timeout'
        receipt = raised.value.receipt
        assert receipt['pid'] is None and receipt['exit_code'] is None and not receipt['reaped']
        assert receipt['stdout_bytes'] == receipt['stderr_bytes'] == 0
        assert receipt['elapsed_ms'] >= runtime.TIMEOUT_SECONDS * 1000
    finally:
        for _ in range(held_slots):
            runtime._slots.release()


@pytest.mark.parametrize('stage', ['copy', 'environment'])
@pytest.mark.parametrize('failure', ['timeout', 'cancelled'])
def test_preparation_budget_stops_before_process_spawn(monkeypatch, stage, failure):
    assert runtime.TIMEOUT_SECONDS == 8.0 and runtime.MAX_CONCURRENT == 2
    clock, observed = {'now': 100.0}, {}
    monkeypatch.setattr(runtime, 'time', SimpleNamespace(monotonic=lambda: clock['now'], sleep=time.sleep))
    original_run = runtime._run_sync

    def observe(request, descriptor, cancelled, execution):
        observed['cancelled'] = cancelled
        return original_run(request, descriptor, cancelled, execution)

    monkeypatch.setattr(runtime, '_run_sync', observe)
    owner, name = (runtime.bundles, 'copy_verified') if stage == 'copy' else (runtime, '_environment')
    original_prepare = getattr(owner, name)

    def prepare(*args, **kwargs):
        value = original_prepare(*args, **kwargs)
        if failure == 'timeout':
            clock['now'] += runtime.TIMEOUT_SECONDS
        else:
            observed['cancelled'].set()
        return value

    def no_process(*args, **kwargs):
        raise AssertionError('expired or cancelled preparation must not spawn')

    monkeypatch.setattr(owner, name, prepare)
    monkeypatch.setattr(runtime.subprocess, 'Popen', no_process)
    with pytest.raises(runtime.ParserRunError) as raised:
        execute()
    assert raised.value.code == 'parser_' + failure
    receipt = raised.value.receipt
    assert receipt['pid'] is None and receipt['exit_code'] is None and not receipt['reaped']
    assert receipt['stdout_bytes'] == receipt['stderr_bytes'] == 0


@pytest.mark.parametrize('stage', ['limits', 'writer'])
@pytest.mark.parametrize('failure', ['timeout', 'cancelled'])
def test_preparation_budget_never_sends_go_and_reaps_child(monkeypatch, stage, failure):
    assert runtime.TIMEOUT_SECONDS == 8.0 and runtime.MAX_CONCURRENT == 2
    clock, observed, processes, writes = {'now': 100.0}, {}, [], []
    monkeypatch.setattr(runtime, 'time', SimpleNamespace(monotonic=lambda: clock['now'], sleep=time.sleep))
    original_run, original_popen = runtime._run_sync, runtime.subprocess.Popen

    def expire():
        if failure == 'timeout':
            clock['now'] += runtime.TIMEOUT_SECONDS
        else:
            observed['cancelled'].set()

    def observe(request, descriptor, cancelled, execution):
        observed['cancelled'] = cancelled
        return original_run(request, descriptor, cancelled, execution)

    class ObservedInput:
        def __init__(self, stream):
            self.stream = stream

        def write(self, data):
            writes.append(bytes(data))
            return self.stream.write(data)

        def close(self):
            self.stream.close()

    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        process.stdin = ObservedInput(process.stdin)
        return process

    monkeypatch.setattr(runtime, '_run_sync', observe)
    monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
    if stage == 'limits':
        name = 'WindowsJob' if sys.platform == 'win32' else 'apply_parent_linux_limits'
        original_limits = getattr(runtime, name)

        def limits(*args, **kwargs):
            value = original_limits(*args, **kwargs)
            expire()
            return value

        monkeypatch.setattr(runtime, name, limits)
    else:
        class ExpiringInputThread(threading.Thread):
            def start(self):
                if self.name.startswith('tire-parser-input-'):
                    expire()
                super().start()

        monkeypatch.setattr(runtime, 'threading', SimpleNamespace(Thread=ExpiringInputThread, Event=threading.Event))
    with pytest.raises(runtime.ParserRunError) as raised:
        execute()
    assert raised.value.code == 'parser_' + failure
    receipt = raised.value.receipt
    assert len(processes) == 1 and processes[0].returncode is not None
    assert receipt['pid'] == processes[0].pid and receipt['reaped']
    assert writes == [] and receipt['stdout_bytes'] == receipt['stderr_bytes'] == 0
    assert not any(thread.name.startswith('tire-parser-') and thread.name.endswith(str(processes[0].pid))
                   for thread in threading.enumerate())


def test_rejects_untrusted_selector_or_bad_envelope_before_spawn(monkeypatch):
    def no_process(): raise AssertionError('invalid request must not spawn')
    monkeypatch.setattr(runtime, '_command', no_process)
    spec = runtime.current_parser('michelin-us')
    for source, body, query, version, digest, code in [
        ('../../evil.py', b'x', {}, spec['parser_version'], spec['parser_digest'], 'parser_source_not_allowed'),
        ('michelin-us', b'x', {}, 'different', spec['parser_digest'], 'parser_version_mismatch'),
        ('michelin-us', b'x', {}, spec['parser_version'], '0' * 64, 'parser_code_mismatch'),
        ('michelin-us', b'x' * (runtime.MAX_BODY_BYTES + 1), {}, spec['parser_version'], spec['parser_digest'], 'parser_input_too_large'),
        ('michelin-us', b'x', {'module': 'os'}, spec['parser_version'], spec['parser_digest'], 'parser_input_invalid'),
        ('michelin-us', b'x', {'model': float('nan')}, spec['parser_version'], spec['parser_digest'], 'parser_input_invalid'),
    ]:
        with pytest.raises(runtime.ParserRunError, match=f'^{code}$'):
            asyncio.run(runtime.parse_isolated(source, body, query, version, digest))


def test_domain_dependency_change_invalidates_frozen_digest(monkeypatch, tmp_path):
    original = runtime.current_parser('michelin-us')
    for path in runtime._ROOT.rglob('*.py'):
        target = tmp_path / path.relative_to(runtime._ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    domain = tmp_path / 'domain.py'
    domain.write_bytes(domain.read_bytes() + b'\n# synthetic dependency change\n')
    monkeypatch.setattr(runtime, '_ROOT', tmp_path)
    assert runtime.current_parser('michelin-us')['parser_digest'] != original['parser_digest']
    with pytest.raises(runtime.ParserRunError, match='parser_code_mismatch'):
        asyncio.run(runtime.parse_isolated('michelin-us', _page(), {}, original['parser_version'], original['parser_digest']))


def test_child_ignores_timestamp_valid_stale_bytecode(monkeypatch, tmp_path):
    package = tmp_path / 'tire_api'
    for path in runtime._ROOT.rglob('*.py'):
        target = package / path.relative_to(runtime._ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    # Exercise the current supervisor's bootstrap, including external cache probes.
    (package / 'parser_child.py').write_bytes(runtime._CHILD.read_bytes())
    source = package / '__init__.py'
    # Both sources are equal length with identical integer mtime. Default
    # timestamp pyc validation would execute the stale failing module.
    source.write_text('raise RuntimeError("stale bytecode")\n', encoding='utf-8')
    timestamp = source.stat().st_mtime
    cached = py_compile.compile(str(source), doraise=True)
    source.write_text('#aise RuntimeError("stale bytecode")\n', encoding='utf-8')
    os.utime(source, (timestamp, timestamp))
    assert Path(cached).is_file()
    monkeypatch.setattr(runtime, '_ROOT', package)
    monkeypatch.setattr(runtime, '_CHILD', package / 'parser_child.py')
    value = execute()
    assert value['payload'] == parse_michelin_html(_page(), {})
    assert value['receipt']['reaped'] and value['receipt']['exit_code'] == 0


def test_host_ignores_timestamp_valid_stale_bytecode(monkeypatch, tmp_path):
    host = tmp_path / 'stale-host'
    host.mkdir()
    for name in ('parser_runtime.py', 'parser_limits.py', 'parser_bundles.py', 'parser_child.py'):
        original = runtime._CHILD if name == 'parser_child.py' else runtime._HOST_ROOT / name
        shutil.copyfile(original, host / name)
    source = host / 'parser_runtime.py'
    prefix = source.read_bytes()
    source.write_bytes(prefix + b'\nraise RuntimeError("stale host bytecode")\n')
    timestamp = source.stat().st_mtime
    cached = py_compile.compile(str(source), doraise=True)
    # The pyc remains timestamp/size-valid but contains a failing host module.
    source.write_bytes(prefix + b'\n#aise RuntimeError("stale host bytecode")\n')
    os.utime(source, (timestamp, timestamp))
    assert Path(cached).is_file()
    monkeypatch.setattr(runtime, '_HOST_ROOT', host)
    monkeypatch.setattr(runtime, '_CHILD', host / 'parser_child.py')
    value = execute()
    assert value['payload'] == parse_michelin_html(_page(), {})
    assert value['receipt']['reaped'] and value['receipt']['exit_code'] == 0


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Job initialization')
def test_failed_job_setup_never_releases_parser_gate(monkeypatch):
    processes = []
    original = runtime.subprocess.Popen
    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    def denied(_process): raise OSError('synthetic job setup failure')
    monkeypatch.setattr(runtime.subprocess, 'Popen', popen)
    monkeypatch.setattr(runtime, 'WindowsJob', denied)
    with pytest.raises(runtime.ParserRunError) as raised:
        execute()
    assert raised.value.code == 'parser_isolation_unavailable'
    assert raised.value.receipt['reaped'] and raised.value.receipt['stdout_bytes'] == 0
    assert len(processes) == 1 and processes[0].returncode is not None

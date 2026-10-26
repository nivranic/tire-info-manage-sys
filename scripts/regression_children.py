"""Exact, source-bound child launches for the private API/Worker regression.

This is a reviewed-code Python audit boundary, not an OS security sandbox.
Never persist argv/environment, including hashes of password-bearing values.
"""
from collections import Counter
import ast
import hashlib
import inspect
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import threading
from types import CodeType
from urllib.parse import unquote, urlsplit, parse_qs


class ChildDenied(PermissionError):
    pass


# Public source bytes, never runtime arguments or credential-derived digests.
REVIEWED = {
    'apps/api/tests/test_parser_runtime.py': 'ab6876a773acdac3d48e9dfe799d3284e55f25680741048c841b36bebec9e90b',
    'apps/api/tests/test_parser_bundles.py': 'b61d29c4cd8373168e9532e2a79c0fe9f06652e6d37d407b4ee924b27ff6dd1c',
    'apps/api/tests/test_adapter_import_behavior.py': 'e365639027b8fc681ce600856bf71382ddefab285130ec91eac5e5d72bc66d01',
    'apps/api/tests/test_auth_governance.py': '5a23fe46ccd753e72cfa97df7e6f274673ec60d977c5474e1e03a5430e63acb7',
    'apps/api/tests/test_auth_lifecycle.py': 'fc15caa941f3ec8fa89086ea51864fe01878552bd34319794305329a516af61a',
    'apps/api/tests/test_identity_migration.py': '592bbbfe9d0068a511b5c9c7e355f1ac43494e4bc7e1c84f16c988b203a1c650',
    'apps/api/tests/test_fitment_relations.py': '5fb901ac31e84704d7196ebc8afffe0609cd0e0a517b6f068ad4b93c2b118280',
    'apps/api/tests/test_raw_captures.py': '85cfcd2f6d66f453983ba3b1c5c610d4f44598df989839ce26a896b1289ff321',
    'apps/api/tests/test_device_ai_public_contract.py': '54d0bf931d0b08abdf3e8e8312d77f6ae937f6c9d0c3d35d1c6b7102e12f2312',
    'apps/api/tests/test_device_ai_routes_prepare.py': 'b2b2d8bd1dafae78307382ad9197652518908f0a524ae4eba5492488ca944c67',
    'apps/api/tire_api/parser_child.py': '830b9f38c0504faf4c16cc2f4f7c455abab9de75ca3b73983596268ade85e788',
    'apps/api/tire_api/parser_limits.py': 'af8b43d7e352e4b35126e743a3e63e16c5c54fcb9ac3e8e7853dc8bc1cc1adf6',
    'apps/api/tire_api/parser_runtime.py': '3258853b27d2c4348717fa2b54ff057b136cf5e1fe751a5eadf2daf0e5e7e566',
    'apps/api/tire_api/manage.py': '78d8598a3ce35e07b682415fb250a8c21583ddd363248c95ab8bd817c2c71bfd',
    'scripts/identity_contract.py': 'd518bf77981005c7808279119326f9c05eb77643a10cdb9e4e26b3939623ea05',
    'packages/api-client/tests/device-ai/json-esm-hook.mjs': 'f4327b15575b1f82f5bbc48469f84990a6b9127f6eb17ff4973b7a7fa6e5404d',
    'packages/api-client/tests/device-ai/no-artifacts-hook.mjs': '787b64dd38915cd78b17812271b22be8bac93cd4d952fe9e9edeb6b2363587cc',
    'packages/api-client/package.json': '71a4620555797dff9bbc11e0bc9c39f9e5716900f10b6743eaf46a72fd15b7b5',
    'apps/api/tests/test_raw_evidence_v2_sdk.py': 'f62e6f5dd1db7b62bbbde7777c69c90b242d96ed9dfab2f899d7258622c64268',
    'packages/api-client/tests/raw-evidence-v2.mts': 'db7bf5e993a89f226feae671a72cbb8c2385563441eb612e0cd8a644377d527c',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def private_sqlite_url(value, private):
    """Only explicit SQLite paths in this run, including reviewed readonly URIs."""
    if not isinstance(value, str) or not value.startswith('sqlite:///'):
        return False
    value = value[len('sqlite:///'):]
    if value == ':memory:':
        return True
    if value.startswith('file:'):
        parsed = urlsplit(value)
        if parsed.netloc not in ('', 'localhost') or parsed.fragment:
            return False
        query = parse_qs(parsed.query)
        if query.get('mode') == ['memory']:
            return True
        value = unquote(parsed.path)
        if sys.platform == 'win32' and len(value) > 3 and value[0] == '/' and value[2] == ':':
            value = value[1:]
    if '?' in value or '#' in value or not Path(value).is_absolute():
        return False
    return Path(value).resolve().is_relative_to(private)


class ChildPolicy:
    def __init__(self, repo_root, private_root, output_root):
        self.repo = Path(repo_root).resolve(strict=True)
        self.private = Path(private_root).resolve(strict=True)
        self.output = Path(output_root).resolve(strict=True)
        if not self.private.is_relative_to(self.output) or self.output == self.repo:
            raise ValueError('r82_private_root_contract')
        self.phase = 'bootstrap'
        self._counts = {}
        self._lock = threading.RLock()
        self._local = threading.local()
        self._original = subprocess.Popen
        self._signature = inspect.signature(self._original)
        self._installed = False
        self._processes = []
        self._native_create = None
        if sys.platform == 'win32':
            import _winapi
            self._native_create = _winapi.CreateProcess
        self.python = Path(sys.executable).resolve(strict=True)
        self.base_python = Path(getattr(sys, '_base_executable', sys.executable)).resolve(strict=True)
        node = shutil.which('node')
        self.node = Path(node).resolve(strict=True) if node else None
        self.dependencies = sorted({str(Path(sysconfig.get_path(n)).resolve(strict=True)) for n in ('purelib', 'platlib')})
        self.bootstrap = self.repo / 'scripts/regression_child.py'
        self.node_guard = self.repo / 'scripts/regression_node_guard.cjs'
        self._support_hashes = {p: digest(p) for p in (self.bootstrap, self.node_guard)}
        self._verify_sources()
        self._trees = {p: ast.parse((self.repo / p).read_text(encoding='utf-8'))
                       for p in REVIEWED if p.startswith('apps/api/tests/')}
        probe_tree = self._trees['apps/api/tests/test_parser_runtime.py']
        self.probe = next(ast.literal_eval(n.value) for n in probe_tree.body
                          if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'PROBE' for t in n.targets))
        self.probe = self.probe.replace('PACKAGE_ROOT', repr(str(self.repo / 'apps/api')))
        self.import_scripts = [textwrap.dedent(n.args[0].value) for n in ast.walk(
            self._trees['apps/api/tests/test_adapter_import_behavior.py'])
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == 'fresh_import'
            and n.args and isinstance(n.args[0], ast.Constant)]
        self.fitment = self._literal('test_fitment_relations.py', 'code')
        self.node_scripts = [self._literal(name, 'script') for name in
                             ('test_device_ai_public_contract.py', 'test_device_ai_routes_prepare.py',
                              'test_raw_evidence_v2_sdk.py')]
        self.crash = 'from test_raw_captures import crash_inside_parser; import sys; crash_inside_parser(sys.argv[1])'
        bundle_test = 'apps/api/tests/test_parser_bundles.py'
        reviewed_precedence_cases = {
            'test_real_distinct_code_a_b_a_and_installed_package_precedence',
            'test_reconstructed_eight_source_eager_bundle_runs_tire_and_rejects_new_sources',
            'test_real_nine_source_archive_runs_saved_tire_and_recall_and_rejects_pirelli',
            'test_reconstructed_eager_ten_bundle_keeps_own_code_with_current_lazy_install',
        }
        lambda_lines = {node.lineno for function in self._trees[bundle_test].body
                        if isinstance(function, ast.FunctionDef) and function.name in reviewed_precedence_cases
                        for node in ast.walk(function) if isinstance(node, ast.Lambda)}
        test_code = compile((self.repo / bundle_test).read_text(encoding='utf-8'), str(self.repo / bundle_test), 'exec')
        self._precedence_lambdas = {code.co_firstlineno: code for code in self._code_objects(test_code)
                                   if code.co_name == '<lambda>' and code.co_firstlineno in lambda_lines}
        runtime_path = self.repo / 'apps/api/tire_api/parser_runtime.py'
        runtime_code = compile(runtime_path.read_text(encoding='utf-8'), str(runtime_path), 'exec')
        self._runtime_codes = {code.co_name: code for code in runtime_code.co_consts
                               if isinstance(code, CodeType) and code.co_name in {'_command', '_run_sync'}}

    @staticmethod
    def _code_objects(code):
        yield code
        for value in code.co_consts:
            if isinstance(value, CodeType):
                yield from ChildPolicy._code_objects(value)

    @staticmethod
    def _same_code(actual, reviewed):
        # pytest assertion rewriting does not change these assertion-free lambdas.
        # Bind public executable structure and location, never runtime arguments.
        return (isinstance(actual, CodeType) and reviewed is not None
                and Path(actual.co_filename).resolve() == Path(reviewed.co_filename).resolve()
                and all(getattr(actual, name) == getattr(reviewed, name) for name in
                        ('co_name', 'co_firstlineno', 'co_code', 'co_consts', 'co_names', 'co_freevars')))

    def _reviewed_installed_dependency(self, dependencies, argv):
        """Only the four pinned installed-package precedence lambda closures."""
        if len(dependencies) != len(self.dependencies) + 1 or dependencies[:-1] != self.dependencies:
            return False
        runtime = sys.modules.get('tire_api.parser_runtime')
        command = getattr(runtime, '_command', None)
        code = getattr(command, '__code__', None)
        if not isinstance(code, CodeType) or not self._same_code(code, self._precedence_lambdas.get(code.co_firstlineno)):
            return False
        if code.co_freevars != ('original_command', 'source') or not command.__closure__:
            return False
        original, source = [cell.cell_contents for cell in command.__closure__]
        if (not self._same_code(getattr(original, '__code__', None), self._runtime_codes['_command'])
                or not isinstance(source, Path) or source.name != 'tire_api'
                or source.parent.name != 'trusted-install' or not self._inside(source)
                or not source.is_dir() or source.absolute() != source.resolve(strict=True)
                or dependencies[-1] != str(source.parent)):
            return False
        frame = sys._getframe(1)
        try:
            while frame is not None:
                if (self._same_code(frame.f_code, self._runtime_codes['_run_sync'])
                        and frame.f_locals.get('command') == argv):
                    return True
                frame = frame.f_back
            return False
        finally:
            del frame

    def _literal(self, filename, name):
        return next(ast.literal_eval(n.value) for n in ast.walk(self._trees['apps/api/tests/' + filename])
                    if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)
                    and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))

    def _bump(self, name):
        with self._lock:
            self._counts.setdefault(self.phase, Counter())[name] += 1

    def _deny(self, category):
        self._bump('denied.' + category)
        raise ChildDenied('r82_child_denied:' + category)

    def _verify_sources(self):
        for relative, expected in REVIEWED.items():
            if digest(self.repo / relative) != expected:
                self._deny('reviewed_source_changed')
        for path, expected in self._support_hashes.items():
            if digest(path) != expected:
                self._deny('bootstrap_changed')

    def _inside(self, value):
        try:
            return Path(value).resolve().is_relative_to(self.private)
        except (OSError, TypeError, ValueError):
            return False

    def _exact_executable(self, value, expected):
        try:
            return expected is not None and Path(value).is_absolute() and Path(value).resolve(strict=True) == expected
        except (OSError, TypeError, ValueError):
            return False

    def _parser(self, argv, cwd, env, options):
        if not self._exact_executable(argv[0], self.base_python) or argv[1:4] != ['-I', '-S', '-B']:
            self._deny('parser_interpreter')
        directory = Path(cwd).resolve()
        if not directory.name.startswith('tire-parser-') or not self._inside(directory):
            self._deny('parser_cwd')
        if options.get('stdin') != subprocess.PIPE or any(options.get(k) != subprocess.PIPE for k in ('stdout', 'stderr')):
            self._deny('parser_pipes')
        if options.get('close_fds', True) is not True or options.get('bufsize') != 0:
            self._deny('parser_handles')
        if len(argv) < 7 or argv[-2:] != ['--execution-root', str(directory / 'package')]:
            self._deny('parser_execution_root')
        child = Path(argv[4])
        if not child.is_absolute() or (child.resolve() != self.repo / 'apps/api/tire_api/parser_child.py' and not self._inside(child)):
            self._deny('parser_script')
        category = 'managed_parser'
        if digest(child) == REVIEWED['apps/api/tire_api/parser_child.py']:
            dependencies = argv[5:-2]
        else:
            cases = {'crash', 'hang', 'cpu', 'memory', 'stdout', 'stderr', 'malformed', 'nonfinite',
                     'environment', 'network_guard', 'spawn', 'echo', 'blocked_input'}
            if len(argv) < 8 or argv[5] not in cases or child.name != 'probe_' + argv[5] + '.py':
                self._deny('parser_probe_case')
            # write_text uses platform newline conversion. Compare the exact generated bytes.
            expected = self.probe.replace('\n', os.linesep).encode('utf-8')
            if not self._inside(child) or child.read_bytes() != expected:
                self._deny('parser_probe_template')
            category, dependencies = 'parser_probe.' + argv[5], argv[6:-2]
        if dependencies != self.dependencies:
            if category != 'managed_parser' or not self._reviewed_installed_dependency(dependencies, argv):
                self._deny('parser_dependencies')
            category = 'managed_parser.installed_precedence'
        allowed = {'PYTHONIOENCODING', 'PYTHONUTF8', 'TEMP', 'TMP', 'SystemRoot', 'WINDIR',
                   'PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432', 'LANG'}
        if set(env) - allowed or env.get('PYTHONIOENCODING') != 'utf-8' or env.get('PYTHONUTF8') != '1':
            self._deny('parser_environment')
        if any(Path(env.get(k, '')).resolve() != directory for k in ('TEMP', 'TMP')):
            self._deny('parser_temp')
        if sys.platform == 'win32':
            system_root = os.environ.get('SystemRoot') or os.environ.get('SYSTEMROOT')
            if not system_root or any(env.get(k) != system_root for k in ('SystemRoot', 'WINDIR')):
                self._deny('parser_system_root')
            architectures = [env[k] for k in ('PROCESSOR_ARCHITECTURE', 'PROCESSOR_ARCHITEW6432') if k in env]
            if not architectures or any(v.upper() not in {'AMD64', 'X86', 'ARM64', 'ARM', 'IA64'} for v in architectures):
                self._deny('parser_architecture')
            if options.get('creationflags', 0) != subprocess.CREATE_NO_WINDOW:
                self._deny('parser_creationflags')
        return category, argv, str(directory), dict(env)

    def _environment(self, env, database=None):
        env = dict(env)
        for name, value in env.items():
            upper = name.upper()
            if (upper.endswith(('_PROXY', '_API_KEY', '_TOKEN', '_PASSWORD', '_SECRET', '_ACCESS_KEY_ID', '_SECRET_ACCESS_KEY'))
                    or upper.startswith(('OPENAI_', 'ANTHROPIC_', 'AWS_', 'AZURE_', 'GOOGLE_', 'GCP_', 'HF_', 'HUGGINGFACE_'))
                    or upper in ('NODE_OPTIONS', 'NODE_PATH', 'PYTHONSTARTUP', 'PYTHONHOME', 'CODEX_DEV_TEST_URL')) and value:
                self._deny('credential_or_injection_environment')
        current = env.get('TIRE_DATABASE_URL')
        other = env.get('DATABASE_URL')
        for value in (current, other, database):
            if value is not None and not private_sqlite_url(value, self.private):
                self._deny('nonprivate_database_environment')
        selected = database or current or other or 'sqlite:///' + (self.private / 'child-bootstrap.db').as_posix()
        # Existing reviewed tests set only TIRE_DATABASE_URL. Both incoming URLs
        # must be private; only this exact command's selected private URL wins.
        env['TIRE_DATABASE_URL'] = env['DATABASE_URL'] = selected
        database_path = selected[len('sqlite:///'):]
        object_default = (Path(database_path + '.objects') if Path(database_path).is_absolute()
                          else self.private / 'objects')
        for name, default in {'TEMP': self.private / 'tmp', 'TMP': self.private / 'tmp',
                              'TMPDIR': self.private / 'tmp', 'TI_OBJECT_STORE_ROOT': object_default,
                              'TI_PARSER_BUNDLE_ROOT': Path.cwd() / 'data/parser-bundles'}.items():
            if name in env and (not Path(env[name]).is_absolute() or not self._inside(env[name])):
                self._deny('nonprivate_path_environment')
            env.setdefault(name, str(default))
        allowed_imports = {str(self.repo / p) for p in ('apps/api', 'apps/api/tests', 'apps/worker', 'scripts')}
        if any(str(Path(p).resolve()) not in allowed_imports for p in env.get('PYTHONPATH', '').split(os.pathsep) if p):
            self._deny('pythonpath')
        # No sitecustomize or cwd imports are used by the isolated bootstrap.
        env.pop('PYTHONPATH', None)
        env.update(TI_AI_ENABLED='0', TI_EMBEDDINGS_ENABLED='0', TI_OBSERVABILITY_ENABLED='0',
                   TI_OBJECT_STORE_BACKEND='filesystem', PYTHONDONTWRITEBYTECODE='1',
                   PYTHONIOENCODING='utf-8', PYTHONUTF8='1', R82_PRIVATE_ROOT=str(self.private),
                   R82_REPO_ROOT=str(self.repo), R82_OUTPUT_ROOT=str(self.output))
        return env

    def _prepare(self, options):
        argv = options['args']
        if not isinstance(argv, (list, tuple)) or not argv or not all(isinstance(a, (str, os.PathLike)) for a in argv):
            self._deny('argv_shape')
        argv = [os.fspath(a) for a in argv]
        if options.get('shell', False) is not False or options.get('executable') not in (None, argv[0]):
            self._deny('shell_or_executable_override')
        if options.get('preexec_fn') is not None or options.get('pass_fds') or options.get('startupinfo') is not None:
            self._deny('startup_override')
        self._verify_sources()
        cwd = options.get('cwd') or os.getcwd()
        env = options.get('env') if options.get('env') is not None else os.environ
        if not self._inside(cwd) and Path(cwd).resolve() != self.repo:
            self._deny('cwd_outside')
        if argv[1:4] == ['-I', '-S', '-B']:
            return self._parser(argv, cwd, env, options)
        category, mode, payload, rest, database = None, None, None, [], None
        if self._exact_executable(argv[0], self.python):
            if argv[1:4] == ['-m', 'tire_api.manage', 'expire-sessions'] and len(argv) == 4:
                category, mode, payload, rest = 'manage_expire', 'module', 'tire_api.manage', argv[3:]
            elif ((len(argv) == 7 and argv[1:6] == ['-m', 'tire_api.manage', 'reset-password', '--username', 'root']
                  and argv[6].startswith('--new-password=') and 8 <= len(argv[6]) - len('--new-password=') <= 200)):
                category, mode, payload, rest = 'manage_reset', 'module', 'tire_api.manage', argv[3:]
            elif argv[1:] == [str(self.repo / 'scripts/identity_contract.py'), 'preview']:
                category, mode, payload, rest = 'identity_preview', 'script', argv[1], ['preview']
            elif argv[1:] == ['-c', self.fitment]:
                category, mode, payload = 'fitment_initialize', 'code', self.fitment
            elif len(argv) == 4 and argv[1:3] == ['-c', self.crash] and private_sqlite_url(argv[3], self.private):
                category, mode, payload, rest, database = 'capture_crash', 'code', self.crash, [argv[3]], argv[3]
            elif len(argv) >= 6 and argv[1:4] == ['-I', '-B', '-c'] and argv[4] in self.import_scripts and argv[5] == str(self.repo / 'apps/api'):
                index, supplied = self.import_scripts.index(argv[4]), argv[6:]
                valid = (index == 0 and supplied in [['pirelli', 'parse_html'], ['toyo', 'parse_html'], ['hankook', 'parse_html'], ['michelin', 'parse_michelin_html']]
                         or index == 1 and supplied in [['attribute'], ['from_import'], ['star_import']]
                         or index == 2 and not supplied)
                if not valid:
                    self._deny('fresh_import_arguments')
                category, mode, payload, rest = 'fresh_import', 'isolated_code', argv[4], argv[5:]
        elif self._exact_executable(argv[0], self.node):
            for index, script in enumerate(self.node_scripts):
                hooks = ['packages/api-client/tests/device-ai/json-esm-hook.mjs']
                if index:
                    hooks.insert(0, 'packages/api-client/tests/device-ai/no-artifacts-hook.mjs')
                expected = [argv[0], '--experimental-transform-types']
                for hook in hooks:
                    expected += ['--import', './' + hook]
                expected += ['--input-type=module', '-e', script]
                if argv == expected and Path(cwd).resolve() == self.repo:
                    result = [argv[0], '--require', str(self.node_guard), '--experimental-transform-types']
                    for hook in hooks:
                        result += ['--import', (self.repo / hook).as_uri()]
                    result += ['--input-type=module', '-e', script]
                    return 'node_wire_' + str(index + 1), result, str(self.private), self._environment(env)
        if category is None:
            self._deny('unreviewed_command')
        if not self._inside(cwd):
            self._deny('python_cwd')
        environment = self._environment(env, database)
        # -I also prevents inherited sitecustomize/PYTHONPATH from executing
        # before the child installs its own stdlib-only boundary.
        result = [argv[0], '-I', '-B', str(self.bootstrap), mode, payload, *rest]
        return category, result, str(Path(cwd).resolve()), environment

    def install(self):
        if self._installed:
            raise RuntimeError('r82_child_policy_already_installed')
        policy = self

        if sys.platform == 'win32':
            import _winapi

            def guarded_create_process(*args, **kwargs):
                ticket = getattr(policy._local, 'ticket', None)
                if ticket is None or ticket['events'] != 1 or ticket.get('native_active'):
                    policy._deny('native_launch_without_ticket')
                # CPython's native audit command-line field is one character
                # on this installed build (captured by a pre-launch selfcheck).
                # Validate the real complete native call before reaching C;
                # never treat that lossy field as command-line authorization.
                if (kwargs or len(args) != 9 or args[0] != ticket['executable']
                        or args[1] != ticket['commandline'] or args[6] != ticket['env']
                        or args[7] != ticket['cwd']):
                    policy._deny('native_launch_ticket_mismatch')
                ticket['native_active'] = True
                try:
                    return policy._native_create(*args)
                finally:
                    ticket['native_active'] = False
            _winapi.CreateProcess = guarded_create_process

        def guarded_init(process, *args, **kwargs):
            options = dict(policy._signature.bind(*args, **kwargs).arguments)
            category, command, cwd, env = policy._prepare(options)
            if getattr(policy._local, 'ticket', None) is not None:
                policy._deny('nested_launch')
            options.update(args=command, cwd=cwd, env=env, executable=command[0], shell=False)
            ticket = {'argv': command, 'commandline': subprocess.list2cmdline(command), 'cwd': cwd,
                      'env': env, 'executable': command[0], 'events': 0,
                      'stdin_pipe': options.get('stdin') == subprocess.PIPE}
            policy._local.ticket = ticket
            policy._bump('authorized.' + category)
            try:
                policy._original.__init__(process, **options)
                with policy._lock:
                    policy._processes.append(process)
                policy._bump('started.' + category)
            except BaseException:
                policy._bump('launch_failed.' + category)
                raise
            finally:
                policy._local.ticket = None
        # asyncio.windows_utils subclasses Popen at import time. Preserve its
        # class contract, including methods and generic aliases, before imports.
        class GuardedPopen(policy._original):
            __init__ = guarded_init
        subprocess.Popen = GuardedPopen
        self._installed = True

    def audit_launch(self, executable, args, cwd, env):
        """Validate the pending Popen / CreateProcess audit, never grant here."""
        ticket = getattr(self._local, 'ticket', None)
        if ticket is None:
            self._deny('launch_without_ticket')
        if executable != ticket['executable'] or cwd != ticket['cwd']:
            self._deny('launch_ticket_mismatch')
        if env is None:
            if (sys.platform != 'win32' or ticket['events'] != 1 or not ticket.get('native_active')
                    or not isinstance(args, str)):
                self._deny('native_audit_without_validated_call')
        elif args not in (ticket['argv'], ticket['commandline']) or env != ticket['env'] or ticket['events'] != 0:
            self._deny('launch_environment_or_command_mismatch')
        # CPython Windows emits Popen and CreateProcess, POSIX only Popen.
        if ticket['events'] >= (2 if sys.platform == 'win32' else 1):
            self._deny('launch_ticket_reused')
        ticket['events'] += 1
        self._bump('audit_event')

    def allow_pipe_descriptor(self, fd):
        """Only Popen's current authorized stdin pipe while it wraps p2cwrite."""
        ticket = getattr(self._local, 'ticket', None)
        if not isinstance(fd, int) or ticket is None or not ticket['stdin_pipe'] or sys.platform != 'win32':
            return False
        import _winapi
        import msvcrt
        try:
            if _winapi.GetFileType(msvcrt.get_osfhandle(fd)) != _winapi.FILE_TYPE_PIPE:
                return False
        except (OSError, ValueError):
            return False
        frame = sys._getframe(1)
        try:
            while frame is not None:
                if (frame.f_code is self._original.__init__.__code__
                        and frame.f_locals.get('p2cwrite') == fd):
                    return True
                frame = frame.f_back
            return False
        finally:
            del frame

    def snapshot(self):
        with self._lock:
            counts = {phase: dict(counter) for phase, counter in self._counts.items()}
            processes = tuple(self._processes)
        return {'counts': counts, 'process_count': len(processes),
                'exit_counts': dict(Counter(str(p.poll()) for p in processes)),
                'live_process_count': sum(p.poll() is None for p in processes)}

    def denied_count(self, phase):
        with self._lock:
            return sum(value for key, value in self._counts.get(phase, {}).items() if key.startswith('denied.'))

"""Python audit boundary for the isolated API/Worker regression harness.

This is not an OS sandbox. Install before product imports; subprocess enforcement
is delegated to ChildPolicy. No product module is imported by this module.
"""
from collections import Counter
from functools import wraps
import builtins
import hashlib
import io
import os
from pathlib import Path
import socket
import sqlite3
import sqlite3.dbapi2
import stat
import sys
import threading
from urllib.parse import parse_qs, unquote, urlsplit


# Product tests may temporarily replace Path.resolve process-wide. Keep the
# trusted resolver acquired before product imports for this boundary's paths.
TRUSTED_PATH_RESOLVE = Path.resolve


METRICS_NODEID = 'apps/api/tests/test_telemetry.py::test_explicit_worker_http_export_is_loopback_guarded_and_closes'


class GuardDenied(PermissionError):
    """Fixed-category exception; never includes launch, environment or request data."""


class RegressionGuard:
    def __init__(self, repo_root, private_root, output_root, child_policy=None):
        self.repo_root = TRUSTED_PATH_RESOLVE(Path(repo_root), strict=True)
        self.output_root = TRUSTED_PATH_RESOLVE(Path(output_root), strict=True)
        self.private_root = TRUSTED_PATH_RESOLVE(Path(private_root), strict=True)
        if (not self.output_root.is_relative_to(self.repo_root / '.artifacts')
                or self.output_root == self.repo_root / '.artifacts'
                or not self.private_root.is_relative_to(self.output_root)):
            raise ValueError('regression_guard_invalid_private_roots')
        self.child_policy = child_policy
        self.phase = 'bootstrap'
        self._counts = {}
        self._denials = []
        self._local = threading.local()
        self._installed = False
        self._test_nodeid = None
        self._metrics = []
        self._metrics_class = None
        self._trusted_fds = {}
        for descriptor in (1, 2):
            self._trust_fd(descriptor)  # Existing runner output streams; no pathname is acquired here.
        self._original = {
            'pair': socket.socketpair, 'listen': socket.socket.listen,
            'connect_ex': socket.socket.connect_ex, 'getaddrinfo': socket.getaddrinfo,
            'getfqdn': socket.getfqdn, 'sqlite_connect': sqlite3.connect,
            'sqlite_factory': sqlite3.Connection,
            'open': builtins.open, 'io_open': io.open, 'os_open': os.open,
            'os_close': os.close, 'os_dup': os.dup,
        }
        self.backup_path = self.repo_root / '.artifacts/runtime/round38-before.sqlite'
        self.backup_uri = self.backup_path.as_uri() + '?mode=ro&immutable=1'
        self.backup_before = self._record(self.backup_path) if self.backup_path.is_file() else None

    def _record(self, path):
        raw = Path(path).read_bytes()
        return {'path': Path(path).relative_to(self.repo_root).as_posix(),
                'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

    def _bump(self, name):
        self._counts.setdefault(self.phase, Counter())[name] += 1

    def _frames(self):
        frames, frame = [], sys._getframe(1)
        try:
            while frame is not None and len(frames) < 64:
                raw = frame.f_code.co_filename
                if raw.startswith('<'):
                    label = raw
                else:
                    path = TRUSTED_PATH_RESOLVE(Path(raw))
                    try:
                        label = path.relative_to(self.repo_root).as_posix()
                    except ValueError:
                        try:
                            label = 'python-base/' + path.relative_to(Path(sys.base_prefix)).as_posix()
                        except ValueError:
                            label = 'external/' + path.name
                frames.append({'path': label, 'function': frame.f_code.co_name, 'line': frame.f_lineno})
                frame = frame.f_back
        finally:
            del frame
        return frames

    def _deny(self, category, classification='unclassified'):
        self._bump('denied.' + category)
        self._denials.append({'phase': self.phase, 'category': category,
                              'classification': classification, 'frames': self._frames()})
        raise GuardDenied('regression_guard_denied:' + category)

    def denied_count(self, phase):
        return sum(v for k, v in self._counts.get(phase, {}).items() if k.startswith('denied.'))

    def _inside(self, path, root=None):
        if isinstance(path, int):
            if path in self._trusted_fds and self._fd_identity(path) == self._trusted_fds[path]:
                return True
            # Frozen importlib uses nt.open directly, bypassing os.open's
            # returned-FD tracking before FileIO(fd) emits its own open audit.
            target = self._descriptor_path(path)
            if target is None or not target.is_absolute():
                return False
            boundary = root or self.output_root
            if sys.platform == 'win32' and target.drive.casefold() != boundary.drive.casefold():
                return False
            try:
                allowed = TRUSTED_PATH_RESOLVE(target).is_relative_to(boundary)
            except (OSError, ValueError):
                return False
            if allowed:
                self._trust_fd(path)
                self._bump('allowed.resolved_private_descriptor')
            return allowed
        try:
            return TRUSTED_PATH_RESOLVE(Path(os.fsdecode(path))).is_relative_to(root or self.output_root)
        except (TypeError, ValueError, OSError):
            return False

    @staticmethod
    def _descriptor_path(descriptor):
        try:
            if sys.platform == 'win32':
                import ctypes
                from ctypes import wintypes
                import msvcrt
                final_path = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
                final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                final_path.restype = wintypes.DWORD
                buffer = ctypes.create_unicode_buffer(32768)
                size = final_path(msvcrt.get_osfhandle(descriptor), buffer, len(buffer), 0)
                if not size or size >= len(buffer):
                    return None
                value = buffer.value
                if value.startswith('\\\\?\\UNC\\'):
                    value = '\\\\' + value[8:]
                elif value.startswith('\\\\?\\'):
                    value = value[4:]
                return Path(value)
            return Path(os.readlink('/proc/self/fd/' + str(descriptor)))
        except (OSError, ValueError, TypeError):
            return None

    @staticmethod
    def _fd_identity(descriptor):
        try:
            value = os.fstat(descriptor)
            return value.st_dev, value.st_ino, stat.S_IFMT(value.st_mode)
        except (OSError, ValueError):
            return None

    def _trust_fd(self, descriptor):
        identity = self._fd_identity(descriptor)
        if identity is not None:
            self._trusted_fds[descriptor] = identity

    def sqlite_kind(self, target):
        try:
            value = os.fsdecode(target)
        except (TypeError, ValueError):
            return None
        if value == ':memory:':
            return 'memory'
        if value == self.backup_uri and self.backup_before is not None:
            return 'r38_readonly'
        if value.startswith('file:'):
            parsed = urlsplit(value)
            query = parse_qs(parsed.query, keep_blank_values=True)
            if parsed.netloc not in ('', 'localhost') or parsed.fragment:
                return None
            if parsed.path == ':memory:' or query.get('mode') == ['memory']:
                return 'memory'
            value = unquote(parsed.path)
            if sys.platform == 'win32' and len(value) > 3 and value[0] == '/' and value[2] == ':':
                value = value[1:]
        if value and self._inside(value, self.private_root):
            return 'private'
        return None

    def verify_backup(self):
        """Return before/after byte bindings; raise GuardDenied if they differ."""
        after = self._record(self.backup_path) if self.backup_path.is_file() else None
        stable = after == self.backup_before
        if not stable:
            self._deny('r38_backup_changed')
        return {'before': self.backup_before, 'after': after, 'unchanged': stable}

    def _authorizer(self, kind, action, _first, _second, _database, _trigger):
        category = None
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            category = 'sqlite_attach' if action == sqlite3.SQLITE_ATTACH else 'sqlite_detach'
        elif kind == 'r38_readonly' and action in {
            sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE, sqlite3.SQLITE_CREATE_TEMP_TRIGGER, sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER, sqlite3.SQLITE_CREATE_VIEW, sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_DROP_TEMP_INDEX, sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER, sqlite3.SQLITE_DROP_TEMP_VIEW, sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW, sqlite3.SQLITE_ALTER_TABLE, sqlite3.SQLITE_REINDEX,
            sqlite3.SQLITE_ANALYZE, sqlite3.SQLITE_CREATE_VTABLE, sqlite3.SQLITE_DROP_VTABLE,
        }:
            category = 'sqlite_r38_write'
        if category is not None:
            self._bump('denied.' + category)
            self._denials.append({'phase': self.phase, 'category': category,
                                  'classification': 'unclassified', 'frames': self._frames()})
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def _known_ipv6_probe(self, sock, address):
        if address != ('::1', 0) or sock.family != socket.AF_INET6:
            return False
        expected = self.repo_root / 'apps/api/.venv/Lib/site-packages/urllib3/util/connection.py'
        frame = sys._getframe(1)
        try:
            while frame is not None:
                if (frame.f_code.co_name == '_has_ipv6' and TRUSTED_PATH_RESOLVE(Path(frame.f_code.co_filename)) == expected
                        and frame.f_globals.get('__name__') == 'urllib3.util.connection'):
                    caller = frame.f_back
                    return (caller is not None and caller.f_code.co_name == '<module>'
                            and TRUSTED_PATH_RESOLVE(Path(caller.f_code.co_filename)) == expected)
                frame = frame.f_back
        finally:
            del frame
        return False

    def set_test_nodeid(self, nodeid):
        if nodeid is not None and not isinstance(nodeid, str):
            raise ValueError('regression_guard_invalid_nodeid')
        if nodeid != self._test_nodeid:
            for entry in self._metrics:
                if not entry['closed']:
                    self._deny('metrics_listener_leaked')
            self._metrics.clear()
        self._test_nodeid = nodeid

    def _metrics_endpoint(self, address, *, closed=False):
        if self._test_nodeid != METRICS_NODEID:
            return None
        for entry in self._metrics:
            if entry['closed'] == closed and entry['address'] == address:
                return entry
        return None

    def register_metrics_runtime(self, runtime_type):
        """Call after natural collection imports, never import the product here."""
        module = sys.modules.get('tire_api.telemetry')
        method = getattr(runtime_type, 'start_metrics_server', None)
        if (module is None or getattr(module, 'TelemetryRuntime', None) is not runtime_type
                or getattr(runtime_type, '__module__', None) != 'tire_api.telemetry'
                or method is None):
            raise ValueError('regression_guard_untrusted_metrics_runtime')
        if self._metrics_class is runtime_type:
            return
        if self._metrics_class is not None or TRUSTED_PATH_RESOLVE(Path(method.__code__.co_filename)) != self.repo_root / 'apps/api/tire_api/telemetry.py':
            raise ValueError('regression_guard_untrusted_metrics_source')
        original_shutdown = runtime_type.shutdown
        guard = self

        @wraps(method)
        def guarded_start(runtime, port):
            if self._test_nodeid != METRICS_NODEID or type(port) is not int or port != 0:
                self._deny('metrics_start_not_authorized')
            if getattr(self._local, 'metrics_start', None) is not None:
                self._deny('metrics_nested_start')
            entry = {'runtime': runtime, 'socket': None, 'address': None, 'closed': False, 'close_probe_used': False}
            self._local.metrics_start = entry
            try:
                result = method(runtime, port)
                server = runtime._http_server
                if (entry['socket'] is None or server.socket is not entry['socket']
                        or entry['socket'].getsockname() != ('127.0.0.1', result['port'])
                        or result['address'] != '127.0.0.1'):
                    self._deny('metrics_listener_identity_mismatch')
                entry['address'] = entry['socket'].getsockname()
                self._metrics.append(entry)
                self._bump('allowed.metrics_listener_registered')
                return result
            finally:
                self._local.metrics_start = None

        @wraps(original_shutdown)
        def guarded_shutdown(runtime):
            result = original_shutdown(runtime)
            for entry in guard._metrics:
                if entry['runtime'] is runtime and not entry['closed']:
                    if entry['socket'].fileno() != -1:
                        guard._deny('metrics_listener_not_closed')
                    entry['closed'] = True
                    guard._bump('allowed.metrics_listener_closed')
            return result

        runtime_type.start_metrics_server = guarded_start
        runtime_type.shutdown = guarded_shutdown
        self._metrics_class = runtime_type

    def audit(self, event, args):
        pair = getattr(self._local, 'pair', None)
        metrics = getattr(self._local, 'metrics_start', None)
        if event == 'socket.bind':
            sock, address = args
            if (pair is not None and pair['listener'] is None and isinstance(address, tuple)
                    and address[0] in ('127.0.0.1', '::1') and address[1] == 0):
                pair['listener'] = sock
                self._bump('allowed.socketpair_bind')
                return
            if (metrics is not None and self._test_nodeid == METRICS_NODEID and metrics['socket'] is None
                    and address == ('127.0.0.1', 0) and sock.family == socket.AF_INET
                    and sock.type == socket.SOCK_STREAM):
                metrics['socket'] = sock
                self._bump('allowed.metrics_bind')
                return
            classification = 'known_urllib3_ipv6_import_probe' if self._known_ipv6_probe(sock, address) else 'unclassified'
            self._deny('network_bind', classification)
        if event == 'socket.connect':
            sock, address = args
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if address == expected and expected[0] in ('127.0.0.1', '::1') and expected[1] != 0:
                    pair['connected'] = True
                    self._bump('allowed.socketpair_connect')
                    return
            if self._metrics_endpoint(address) is not None:
                self._bump('allowed.metrics_connect')
                return
            closed = self._metrics_endpoint(address, closed=True)
            if (closed is not None and not closed['close_probe_used']
                    and getattr(self._local, 'connect_ex_socket', None) is sock):
                closed['close_probe_used'] = True
                self._bump('allowed.metrics_closed_connect_ex')
                return
            self._deny('network_connect')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyaddr',
                     'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            self._deny('network_dns_or_datagram')
        if event in ('subprocess.Popen', '_winapi.CreateProcess'):
            if self.child_policy is None:
                self._deny('child_process')
            if event == 'subprocess.Popen':
                self.child_policy.audit_launch(args[0], args[1], args[2], args[3])
            else:
                self.child_policy.audit_launch(args[0], args[1], args[2], None)
            self._bump('delegated.child_launch_audit')
        if event in ('os.system', 'os.posix_spawn', 'os.posix_spawnp', 'os.fork', 'os.forkpty', 'os.exec', 'os.spawn'):
            self._deny('child_process')
        if event == 'sqlite3.connect':
            kind = self.sqlite_kind(args[0])
            context = getattr(self._local, 'sqlite_open', None)
            if (kind is None or context is None or context['target'] != args[0] or context['consumed']
                    or (str(args[0]).startswith('file:') and context['uri'] is not True)):
                self._deny('sqlite_nonprivate_or_untrusted_uri')
            context['consumed'] = True
            self._bump('allowed.sqlite_' + kind)
        if event == 'sqlite3.connect/handle':
            context = getattr(self._local, 'sqlite_open', None)
            if context is None or not context['consumed'] or context['handle'] is not None:
                self._deny('sqlite_unexpected_handle')
            context['handle'] = args[0]
            self._bump('observed.sqlite_handle_created')
        if event == 'open':
            path, mode, flags = args
            writing = ((isinstance(mode, str) and any(c in mode for c in 'wax+'))
                       or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing:
                allowed = self._inside(path)
                pipe_check = getattr(self.child_policy, 'allow_pipe_descriptor', None)
                if not allowed and isinstance(path, int) and pipe_check is not None and pipe_check(path):
                    allowed = True
                    self._bump('allowed.child_stdin_pipe_descriptor')
                if not allowed:
                    self._deny('filesystem_write_outside')
                self._bump('allowed.file_write')
        mutations = {'os.mkdir': (0, 2), 'os.remove': (0, 1), 'os.rmdir': (0, 1),
                     'os.chmod': (0, 2), 'os.truncate': (0, None), 'os.utime': (0, 3)}
        if event in mutations:
            index, dir_index = mutations[event]
            if (not self._inside(args[index]) or (dir_index is not None and len(args) > dir_index
                    and args[dir_index] not in (None, -1))):
                self._deny('filesystem_mutation_outside')
            self._bump('allowed.filesystem_mutation')
        if event in ('os.rename', 'os.replace', 'os.symlink', 'os.link'):
            if not self._inside(args[0]) or not self._inside(args[1]) or any(fd not in (None, -1) for fd in args[2:] if isinstance(fd, int) and not isinstance(fd, bool)):
                self._deny('filesystem_move_or_link_outside')
            self._bump('allowed.filesystem_mutation')
        if event == 'os.chdir' and not self._inside(args[0]):
            self._deny('cwd_outside')

    def install(self):
        if self._installed:
            raise RuntimeError('regression_guard_already_installed')

        def guarded_pair(*args, **kwargs):
            if getattr(self._local, 'pair', None) is not None:
                self._deny('nested_socketpair')
            self._local.pair = {'listener': None, 'connected': False}
            try:
                return self._original['pair'](*args, **kwargs)
            finally:
                self._local.pair = None

        def guarded_listen(listener, *args, **kwargs):
            pair = getattr(self._local, 'pair', None)
            metrics = getattr(self._local, 'metrics_start', None)
            if pair is not None and pair['listener'] is listener:
                self._bump('allowed.socketpair_listen')
            elif metrics is not None and metrics['socket'] is listener and self._test_nodeid == METRICS_NODEID:
                self._bump('allowed.metrics_listen')
            else:
                self._deny('network_listen')
            return self._original['listen'](listener, *args, **kwargs)

        def guarded_connect_ex(sock, *args, **kwargs):
            self._local.connect_ex_socket = sock
            try:
                return self._original['connect_ex'](sock, *args, **kwargs)
            finally:
                self._local.connect_ex_socket = None

        def guarded_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            if (host == '127.0.0.1' and self._metrics_endpoint((host, port)) is not None
                    and family in (0, socket.AF_INET) and type in (0, socket.SOCK_STREAM)
                    and proto in (0, socket.IPPROTO_TCP) and flags == 0):
                self._bump('allowed.metrics_numeric_address_without_dns')
                return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', (host, port))]
            return self._original['getaddrinfo'](host, port, family, type, proto, flags)

        def guarded_getfqdn(name=''):
            metrics = getattr(self._local, 'metrics_start', None)
            if (name == '127.0.0.1' and metrics is not None and metrics['socket'] is not None
                    and self._test_nodeid == METRICS_NODEID):
                self._bump('allowed.metrics_server_name_without_dns')
                return 'localhost'
            return self._original['getfqdn'](name)

        def guarded_connect(*args, **kwargs):
            target = args[0] if args else kwargs.get('database')
            uri = kwargs.get('uri', args[7] if len(args) > 7 else False)
            factory = kwargs.get('factory', args[5] if len(args) > 5 else self._original['sqlite_factory'])
            if factory is not self._original['sqlite_factory']:
                self._deny('sqlite_unreviewed_factory')
            kind = self.sqlite_kind(target)
            if kind is None or (str(target).startswith('file:') and uri is not True):
                self._deny('sqlite_nonprivate_or_untrusted_uri')
            previous = getattr(self._local, 'sqlite_open', None)
            ticket = {'target': target, 'uri': uri, 'consumed': False, 'handle': None}
            self._local.sqlite_open = ticket
            try:
                connection = self._original['sqlite_connect'](*args, **kwargs)
                try:
                    if ticket['handle'] is not connection:
                        self._deny('sqlite_connection_identity_mismatch')
                    connection.set_authorizer(lambda *values: self._authorizer(kind, *values))
                    self._bump('allowed.sqlite_authorizer_installed')
                except BaseException:
                    connection.close()
                    raise
                return connection
            finally:
                self._local.sqlite_open = previous

        def track_open(original, *args, **kwargs):
            stream = original(*args, **kwargs)
            mode = kwargs.get('mode', args[1] if len(args) > 1 else 'r')
            if isinstance(mode, str) and any(c in mode for c in 'wax+'):
                try:
                    self._trust_fd(stream.fileno())
                except (AttributeError, OSError, ValueError):
                    pass
            return stream

        def guarded_os_open(*args, **kwargs):
            if kwargs.get('dir_fd') not in (None, -1):
                self._deny('filesystem_untrusted_dir_fd')
            descriptor = self._original['os_open'](*args, **kwargs)
            if self._inside(args[0] if args else kwargs.get('path')):
                self._trust_fd(descriptor)
            return descriptor

        def guarded_close(descriptor):
            result = self._original['os_close'](descriptor)
            self._trusted_fds.pop(descriptor, None)
            return result

        def guarded_dup(descriptor):
            duplicate = self._original['os_dup'](descriptor)
            if self._inside(descriptor):
                self._trust_fd(duplicate)
            return duplicate

        if sys.platform == 'win32':
            socket.socketpair = guarded_pair
        socket.socket.listen = guarded_listen
        socket.socket.connect_ex = guarded_connect_ex
        socket.getaddrinfo = guarded_getaddrinfo
        socket.getfqdn = guarded_getfqdn
        sqlite3.connect = guarded_connect
        sqlite3.dbapi2.connect = guarded_connect
        builtins.open = lambda *a, **kw: track_open(self._original['open'], *a, **kw)
        io.open = lambda *a, **kw: track_open(self._original['io_open'], *a, **kw)
        os.open = guarded_os_open
        os.close = guarded_close
        os.dup = guarded_dup
        sys.addaudithook(self.audit)
        self._installed = True

    def snapshot(self):
        return {'schema': 'regression-guard@1',
                'phase_counts': {p: dict(sorted(c.items())) for p, c in sorted(self._counts.items())},
                'denials': list(self._denials),
                'known_blocked_ipv6_probes': sum(d['classification'] == 'known_urllib3_ipv6_import_probe' for d in self._denials),
                'metrics': {'active_listeners': sum(not entry['closed'] for entry in self._metrics),
                            'retained_closed_endpoints': sum(entry['closed'] for entry in self._metrics)},
                'backup_binding': self.backup_before,
                'limits': ['Python audit/wrappers only; not an OS sandbox or native syscall guarantee.',
                           'Inherited stdout/stderr and descriptors acquired through guarded private opens may be wrapped.',
                           'All ATTACH/DETACH denied; no current suite requirement identified.',
                           'ChildPolicy owns exact launch templates and child bootstrap propagation.']}

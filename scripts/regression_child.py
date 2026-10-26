"""Stdlib-only child bootstrap. Imported before any reviewed application code.

This audit/stdlib API boundary is not an OS sandbox. Production Parser children
never run this file: their existing Job, GO gate and network guard stay intact.
"""
import os
from pathlib import Path
import platform
import runpy
import socket
import sqlite3
import sqlite3.dbapi2
import sys
import tempfile
import threading
from urllib.parse import parse_qs, unquote, urlsplit


class ChildBoundary:
    def __init__(self, private_root):
        self.private = Path(private_root).resolve(strict=True)
        self.counts = {}
        self._pair = threading.local()
        self._sqlite = threading.local()
        self._original_pair = socket.socketpair
        self._original_listen = socket.socket.listen
        self._original_connect = sqlite3.connect
        self._connection_type = sqlite3.Connection

    def deny(self, category):
        self.counts[category] = self.counts.get(category, 0) + 1
        raise PermissionError('r82_child_boundary:' + category)

    def inside(self, value):
        if isinstance(value, int):
            if value in (1, 2):
                return True  # The parent's explicitly captured stdout/stderr.
            try:
                if sys.platform == 'win32':
                    import ctypes
                    from ctypes import wintypes
                    import msvcrt
                    final_path = ctypes.WinDLL('kernel32', use_last_error=True).GetFinalPathNameByHandleW
                    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
                    final_path.restype = wintypes.DWORD
                    buffer = ctypes.create_unicode_buffer(32768)
                    size = final_path(msvcrt.get_osfhandle(value), buffer, len(buffer), 0)
                    if not size or size >= len(buffer):
                        return False
                    value = buffer.value
                    if value.startswith('\\\\?\\'):
                        value = value[4:]
                else:
                    value = os.readlink('/proc/self/fd/' + str(value))
            except (OSError, ValueError):
                return False
        try:
            return Path(os.fsdecode(value)).resolve().is_relative_to(self.private)
        except (OSError, TypeError, ValueError):
            return False

    def sqlite_allowed(self, value):
        try:
            value = os.fsdecode(value)
        except (TypeError, ValueError):
            return False
        if value == ':memory:':
            return True
        if value.startswith('file:'):
            parsed = urlsplit(value)
            if parsed.netloc not in ('', 'localhost') or parsed.fragment:
                return False
            if parsed.path == ':memory:' or parse_qs(parsed.query).get('mode') == ['memory']:
                return True
            value = unquote(parsed.path)
            if sys.platform == 'win32' and len(value) > 3 and value[0] == '/' and value[2] == ':':
                value = value[1:]
        return bool(value) and self.inside(value)

    def _authorizer(self, action, _first, _second, _database, _trigger):
        if action in (sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH):
            self.counts['sqlite_attach_detach'] = self.counts.get('sqlite_attach_detach', 0) + 1
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def audit(self, event, args):
        pair = getattr(self._pair, 'current', None)
        if event == 'socket.bind':
            address = args[1]
            if (pair is not None and pair['listener'] is None and isinstance(address, tuple)
                    and address[0] in ('127.0.0.1', '::1') and address[1] == 0):
                pair['listener'] = args[0]
                return
            self.deny('network_bind')
        if event == 'socket.connect':
            if pair is not None and pair['listener'] is not None and not pair['connected']:
                expected = pair['listener'].getsockname()
                if args[1] == expected and expected[0] in ('127.0.0.1', '::1') and expected[1] != 0:
                    pair['connected'] = True
                    return
            self.deny('network_connect')
        if event in ('socket.getaddrinfo', 'socket.gethostbyname', 'socket.gethostbyname_ex',
                     'socket.gethostbyaddr', 'socket.getnameinfo', 'socket.sendto', 'socket.sendmsg'):
            self.deny('network_dns_or_datagram')
        if event in ('subprocess.Popen', '_winapi.CreateProcess', 'os.system', 'os.posix_spawn',
                     'os.posix_spawnp', 'os.fork', 'os.forkpty', 'os.exec') or event.startswith('os.spawn'):
            self.deny('descendant_process')
        if event == 'sqlite3.connect':
            ticket = getattr(self._sqlite, 'connecting', None)
            if ticket is None or ticket['target'] != args[0] or ticket['consumed']:
                self.deny('sqlite_unwrapped')
            if str(args[0]).startswith('file:') and ticket['uri'] is not True:
                self.deny('sqlite_uri_flag')
            if not self.sqlite_allowed(args[0]):
                self.deny('sqlite_nonprivate')
            ticket['consumed'] = True
        if event == 'open':
            path, mode, flags = args
            writing = ((isinstance(mode, str) and any(c in mode for c in 'wax+')) or
                       (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)))
            if writing and not self.inside(path):
                self.deny('filesystem_write_outside')
        if event in ('os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate', 'os.utime'):
            if not self.inside(args[0]):
                self.deny('filesystem_mutation_outside')
        if event in ('os.rename', 'os.replace', 'os.link', 'os.symlink'):
            if not self.inside(args[0]) or not self.inside(args[1]):
                self.deny('filesystem_move_outside')
        if event == 'os.chdir' and not self.inside(args[0]):
            self.deny('cwd_outside')

    def install(self):
        def connect(*args, **kwargs):
            previous = getattr(self._sqlite, 'connecting', None)
            target = args[0] if args else kwargs.get('database')
            uri = kwargs.get('uri', args[7] if len(args) > 7 else False)
            factory = kwargs.get('factory', args[5] if len(args) > 5 else self._connection_type)
            if factory is not self._connection_type:
                self.deny('sqlite_custom_factory')
            if isinstance(target, (str, bytes, os.PathLike)) and os.fsdecode(target).startswith('file:') and uri is not True:
                self.deny('sqlite_uri_flag')
            self._sqlite.connecting = {'target':target, 'uri':uri, 'consumed':False}
            try:
                connection = self._original_connect(*args, **kwargs)
                connection.set_authorizer(self._authorizer)
            except BaseException:
                if 'connection' in locals():
                    connection.close()
                raise
            finally:
                self._sqlite.connecting = previous
            return connection

        def listen(listener, *args, **kwargs):
            pair = getattr(self._pair, 'current', None)
            if pair is None or pair['listener'] is not listener:
                self.deny('network_listen')
            return self._original_listen(listener, *args, **kwargs)

        def socketpair(*args, **kwargs):
            if getattr(self._pair, 'current', None) is not None:
                self.deny('nested_socketpair')
            self._pair.current = {'listener': None, 'connected': False}
            try:
                return self._original_pair(*args, **kwargs)
            finally:
                self._pair.current = None
        sqlite3.connect = sqlite3.dbapi2.connect = connect
        socket.socket.listen = listen
        if sys.platform == 'win32':
            socket.socketpair = socketpair
        sys.addaudithook(self.audit)


def main():
    private = Path(os.environ['R82_PRIVATE_ROOT']).resolve(strict=True)
    repo = Path(os.environ['R82_REPO_ROOT']).resolve(strict=True)
    if not Path.cwd().resolve().is_relative_to(private):
        raise PermissionError('r82_child_boundary:cwd_outside')
    mode, payload, *arguments = sys.argv[1:]
    if mode not in {'module', 'script', 'code', 'isolated_code'}:
        raise PermissionError('r82_child_boundary:mode')
    for key in ('TEMP', 'TMP', 'TMPDIR', 'TI_OBJECT_STORE_ROOT', 'TI_PARSER_BUNDLE_ROOT'):
        if not Path(os.environ[key]).resolve().is_relative_to(private):
            raise PermissionError('r82_child_boundary:environment_path')
    sys.dont_write_bytecode = True
    tempfile.tempdir = os.environ['TEMP']
    # Avoid platform.win32_ver's incidental WMI subprocess, using only the
    # current interpreter's native Windows metadata (same as parent runner).
    if sys.platform == 'win32':
        def native_win32_ver(release='', version='', csd='', ptype=''):
            native = sys.getwindowsversion()
            return str(native.major), f'{native.major}.{native.minor}.{native.build}', native.service_pack, ptype
        platform.win32_ver = native_win32_ver
    boundary = ChildBoundary(private)
    boundary.install()
    if mode != 'isolated_code':
        sys.path[:0] = [str(repo / 'apps/api'), str(repo / 'apps/api/tests')]
    # Isolated probes retain their original sys.argv and insert API_ROOT only
    # themselves. No tire_api/SQLAlchemy/FastAPI import occurs in this bootstrap.
    if mode == 'module':
        if payload != 'tire_api.manage':
            boundary.deny('module')
        sys.argv = [payload, *arguments]
        runpy.run_module(payload, run_name='__main__', alter_sys=True)
    elif mode == 'script':
        if Path(payload).resolve() != repo / 'scripts/identity_contract.py':
            boundary.deny('script')
        sys.argv = [payload, *arguments]
        runpy.run_path(payload, run_name='__main__')
    else:
        sys.argv = ['-c', *arguments]
        exec(compile(payload, '<string>', 'exec'), {'__name__': '__main__', '__builtins__': __builtins__})


if __name__ == '__main__':
    main()

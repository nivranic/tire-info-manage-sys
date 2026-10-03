"""Kernel resource limits for trusted parser children, NOT an OS security sandbox.

JobObject/resource limits contain resource failures. They do not remove the
process user's filesystem permissions or enforce a kernel network boundary.
"""
import os
import sys

MEMORY_BYTES = 384 * 1024 * 1024
CPU_SECONDS = 5
MAX_ACTIVE_PROCESSES = 1


def apply_parent_linux_limits(pid):
    """Install limits before GO; child verifies them before reading its body."""
    import resource
    for name, maximum in (('RLIMIT_AS', MEMORY_BYTES), ('RLIMIT_CPU', CPU_SECONDS),
                          ('RLIMIT_CORE', 0), ('RLIMIT_FSIZE', 0), ('RLIMIT_NOFILE', 64)):
        kind = getattr(resource, name)
        _soft, hard = resource.prlimit(pid, kind)
        limit = maximum if hard == resource.RLIM_INFINITY else min(maximum, hard)
        resource.prlimit(pid, kind, (limit, limit))


def _windows():
    import ctypes
    from ctypes import wintypes as w

    class Basic(ctypes.Structure):
        _fields_ = [('PerProcessUserTimeLimit', ctypes.c_longlong), ('PerJobUserTimeLimit', ctypes.c_longlong),
            ('LimitFlags', w.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t), ('MaximumWorkingSetSize', ctypes.c_size_t),
            ('ActiveProcessLimit', w.DWORD), ('Affinity', ctypes.c_size_t), ('PriorityClass', w.DWORD), ('SchedulingClass', w.DWORD)]

    class IO(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                         'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]

    class Extended(ctypes.Structure):
        _fields_ = [('BasicLimitInformation', Basic), ('IoInfo', IO), ('ProcessMemoryLimit', ctypes.c_size_t),
            ('JobMemoryLimit', ctypes.c_size_t), ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]

    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateJobObjectW.argtypes, kernel.CreateJobObjectW.restype = [ctypes.c_void_p, w.LPCWSTR], w.HANDLE
    kernel.SetInformationJobObject.argtypes, kernel.SetInformationJobObject.restype = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD], w.BOOL
    kernel.AssignProcessToJobObject.argtypes, kernel.AssignProcessToJobObject.restype = [w.HANDLE, w.HANDLE], w.BOOL
    kernel.TerminateJobObject.argtypes, kernel.TerminateJobObject.restype = [w.HANDLE, w.UINT], w.BOOL
    kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [w.HANDLE], w.BOOL
    kernel.QueryInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]
    kernel.QueryInformationJobObject.restype = w.BOOL
    return ctypes, kernel, Extended


# Process/job user CPU time + active process + process/job committed memory +
# terminate the entire child job when its sole supervisor handle closes.
WINDOWS_FLAGS = 0x2 | 0x4 | 0x8 | 0x100 | 0x200 | 0x2000


class WindowsJob:
    def __init__(self, process):
        ctypes, kernel, Extended = _windows()
        self.kernel = kernel
        self.handle = kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('parser_job_create_failed')
        try:
            limits = Extended()
            limits.BasicLimitInformation.LimitFlags = WINDOWS_FLAGS
            limits.BasicLimitInformation.PerProcessUserTimeLimit = CPU_SECONDS * 10_000_000
            limits.BasicLimitInformation.PerJobUserTimeLimit = CPU_SECONDS * 10_000_000
            limits.BasicLimitInformation.ActiveProcessLimit = MAX_ACTIVE_PROCESSES
            limits.ProcessMemoryLimit = limits.JobMemoryLimit = MEMORY_BYTES
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
                raise OSError('parser_job_limits_failed')
            if not kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise OSError('parser_job_assignment_failed')
        except BaseException:
            self.close()
            raise

    def terminate(self):
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 125):
            raise OSError('parser_job_termination_failed')

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def apply_child_limits():
    """Run after GO, before reading the untrusted request or importing parsers."""
    if sys.platform == 'win32':
        ctypes, kernel, Extended = _windows()
        actual, size = Extended(), ctypes.c_ulong()
        if not kernel.QueryInformationJobObject(None, 9, ctypes.byref(actual), ctypes.sizeof(actual), ctypes.byref(size)):
            raise OSError('parser_job_verification_failed')
        basic = actual.BasicLimitInformation
        if (basic.LimitFlags & WINDOWS_FLAGS != WINDOWS_FLAGS or basic.ActiveProcessLimit != 1
                or actual.ProcessMemoryLimit != MEMORY_BYTES or actual.JobMemoryLimit != MEMORY_BYTES
                or basic.PerProcessUserTimeLimit != CPU_SECONDS * 10_000_000
                or basic.PerJobUserTimeLimit != CPU_SECONDS * 10_000_000):
            raise OSError('parser_job_verification_failed')
        kernel.SetErrorMode(0x1 | 0x2 | 0x8000)
        return 'windows_job_object'
    if sys.platform == 'linux':
        import resource
        for name, maximum in (('RLIMIT_AS', MEMORY_BYTES), ('RLIMIT_CPU', CPU_SECONDS),
                              ('RLIMIT_CORE', 0), ('RLIMIT_FSIZE', 0), ('RLIMIT_NOFILE', 64)):
            kind = getattr(resource, name)
            soft, hard = resource.getrlimit(kind)
            if soft == resource.RLIM_INFINITY or hard == resource.RLIM_INFINITY or soft > maximum or hard > maximum:
                raise OSError('parser_resource_verification_failed')
        return 'linux_resource_process_group'
    raise OSError('parser_platform_not_supported')


def python_network_guard():
    """Defense in depth for trusted Python code; native syscalls can bypass it."""
    denied = {'socket.__new__', 'socket.connect', 'socket.bind', 'socket.getaddrinfo',
              'subprocess.Popen', 'os.system', 'os.posix_spawn', 'os.posix_spawnp',
              'os.fork', 'os.forkpty', 'os.exec', '_winapi.CreateProcess'}

    def hook(event, _args):
        if event in denied:
            raise PermissionError('parser_python_io_denied')

    sys.addaudithook(hook)

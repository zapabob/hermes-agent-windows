"""Fail-closed entry point for delegated native Windows processes.

The profile is bound by trusted host code for the duration of a delegated
operation. Tool arguments cannot choose or amend the profile.
"""

from __future__ import annotations

import ctypes
import io
import os
import re
import subprocess
import sys
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Protocol, Sequence
from ctypes import wintypes


class NativeBoundaryError(RuntimeError):
    """Base class for a refused or unavailable native isolation boundary."""


class NativeExecutionDenied(NativeBoundaryError):
    """The requested process is outside the trusted execution profile."""


class NativeExecutionUnavailable(NativeBoundaryError):
    """The required native Windows boundary could not be established."""


@dataclass(frozen=True, slots=True)
class NativeExecutionProfile:
    """Host-owned filesystem and resource policy for one delegated operation."""

    workspace: Path
    working_directory: Path
    toolchain_roots: tuple[Path, ...]
    private_temp: Path
    generation: int
    appcontainer_name: str
    max_processes: int = 32
    memory_limit_bytes: int = 1_073_741_824
    safe_environment: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("profile generation must be positive")
        if (
            len(self.appcontainer_name) > 64
            or not re.fullmatch(r"HermesDelegated-[A-Za-z0-9_.-]+", self.appcontainer_name)
        ):
            raise ValueError("AppContainer name must be host-generated")
        if self.max_processes < 1 or self.memory_limit_bytes < 1:
            raise ValueError("native process limits must be positive")
        environment_names: set[str] = set()
        for key, value in self.safe_environment:
            if not key or "=" in key or "\0" in key or "\0" in value:
                raise ValueError("invalid safe environment entry")
            normalized_key = key.upper()
            if normalized_key in environment_names:
                raise ValueError(f"duplicate environment variable: {key}")
            environment_names.add(normalized_key)
            if normalized_key in _RESERVED_ENVIRONMENT:
                raise ValueError(f"environment variable is controlled by the host: {key}")


class OwnedProcessHandle(Protocol):
    """The process and its OS containment handles, owned as one resource."""

    pid: int

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def communicate(self, input: str | None = None, timeout: float | None = None): ...

    def kill_tree(self) -> None: ...

    def close(self) -> None: ...


_ACTIVE_PROFILE: ContextVar[NativeExecutionProfile | None] = ContextVar(
    "hermes_native_execution_profile", default=None
)

_RESERVED_ENVIRONMENT = frozenset(
    {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC"}
)


def new_native_execution_profile(
    *,
    workspace: Path,
    working_directory: Path,
    toolchain_roots: Sequence[Path],
    private_temp: Path,
    generation: int,
    appcontainer_name: str | None = None,
    safe_environment: Sequence[tuple[str, str]] = (),
) -> NativeExecutionProfile:
    """Create host-owned per-operation policy with an unregistered package name."""

    return NativeExecutionProfile(
        workspace=Path(workspace),
        working_directory=Path(working_directory),
        toolchain_roots=tuple(Path(root) for root in toolchain_roots),
        private_temp=Path(private_temp),
        generation=generation,
        appcontainer_name=appcontainer_name or f"HermesDelegated-{uuid.uuid4().hex}",
        safe_environment=tuple(safe_environment),
    )


@contextmanager
def bind_native_execution_profile(
    profile: NativeExecutionProfile,
) -> Iterator[None]:
    """Bind an immutable host-selected profile to the current delegated turn."""

    token: Token[NativeExecutionProfile | None] = _ACTIVE_PROFILE.set(profile)
    try:
        yield
    finally:
        _ACTIVE_PROFILE.reset(token)


def active_native_execution_profile() -> NativeExecutionProfile:
    """Return the profile only inside an authorized delegated-child context."""

    from agent.delegation_context import is_delegated_child_context

    profile = _ACTIVE_PROFILE.get()
    if not is_delegated_child_context() or profile is None:
        raise NativeExecutionDenied(
            "delegated native execution requires an authorized host profile"
        )
    return profile


def launch_restricted(
    argv: Sequence[str],
    profile: NativeExecutionProfile | None = None,
    *,
    cwd: Path | None = None,
) -> OwnedProcessHandle:
    """Launch one process inside the active profile's native OS boundary.

    A profile argument is accepted for host call-site convenience but must be
    the exact object already bound by trusted host code. It is never policy
    input from a Hermes tool call.
    """

    if sys.platform != "win32":
        raise NativeExecutionUnavailable("native delegated isolation requires Windows")
    active = active_native_execution_profile()
    if profile is not None and profile is not active:
        raise NativeExecutionDenied("process profile does not match host authority")
    if not argv:
        raise NativeExecutionDenied("empty process argument vector")
    if cwd is not None and Path(cwd) != active.working_directory:
        raise NativeExecutionDenied("working directory does not match host profile")
    executable, normalized_argv, effective_cwd = _validate_launch_request(
        active, argv, cwd
    )
    return _create_appcontainer_process(
        active, executable, normalized_argv, effective_cwd
    )


def _validate_launch_request(
    profile: NativeExecutionProfile,
    argv: Sequence[str],
    cwd: Path | None,
) -> tuple[Path, tuple[str, ...], Path]:
    if len(argv) > 256 or any(not isinstance(arg, str) or "\0" in arg for arg in argv):
        raise NativeExecutionDenied("invalid process argument vector")
    if any(len(arg) > 32767 for arg in argv):
        raise NativeExecutionDenied("process argument exceeds Windows command-line limit")

    workspace = _resolve_plain_directory(profile.workspace, "workspace")
    private_temp = _resolve_plain_directory(profile.private_temp, "private temp")
    workdir = _resolve_plain_directory(cwd or profile.working_directory, "working directory")
    if not _is_within(workdir, workspace):
        raise NativeExecutionDenied("working directory escapes delegated workspace")
    if not _is_within(private_temp, workspace):
        raise NativeExecutionDenied("private temp escapes delegated workspace")

    roots = tuple(_resolve_plain_directory(root, "toolchain root") for root in profile.toolchain_roots)
    candidate = Path(argv[0])
    if not candidate.is_absolute():
        raise NativeExecutionDenied("executable path must be absolute")
    executable = _resolve_plain_file(candidate, "executable")
    if not any(_is_within(executable, root) for root in roots):
        raise NativeExecutionDenied("executable is outside approved toolchain roots")
    if executable.suffix.casefold() not in {".exe", ".com"}:
        raise NativeExecutionDenied("native launch accepts executable images only")

    arguments = tuple(str(executable) if index == 0 else arg for index, arg in enumerate(argv))
    return executable, arguments, workdir


def _resolve_plain_directory(path: Path, label: str) -> Path:
    result = _resolve_plain_path(path, label)
    if not result.is_dir():
        raise NativeExecutionDenied(f"{label} is not a directory")
    return result


def _resolve_plain_file(path: Path, label: str) -> Path:
    result = _resolve_plain_path(path, label)
    if not result.is_file():
        raise NativeExecutionDenied(f"{label} is not a regular file")
    return result


def _resolve_plain_path(path: Path, label: str) -> Path:
    supplied = Path(path).absolute()
    if str(supplied.anchor).startswith("\\\\"):
        raise NativeExecutionDenied(f"{label} cannot use a remote or device path")
    if any(":" in component for component in supplied.parts[1:]):
        raise NativeExecutionDenied(f"{label} cannot use an alternate data stream")
    current = Path(supplied.anchor)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = [wintypes.LPCWSTR]
    get_attributes.restype = wintypes.DWORD
    for component in supplied.parts[1:]:
        current /= component
        attrs = get_attributes(str(current))
        if attrs == 0xFFFFFFFF:
            raise NativeExecutionDenied(f"{label} does not exist or is inaccessible")
        if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
            raise NativeExecutionDenied(f"{label} contains a symlink or reparse point")
    return supplied.resolve(strict=True)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", wintypes.LPVOID),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _StartupInfoW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _StartupInfoExW(ctypes.Structure):
    _fields_ = [("StartupInfo", _StartupInfoW), ("lpAttributeList", wintypes.LPVOID)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _JobBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount",
        "WriteOperationCount",
        "OtherOperationCount",
        "ReadTransferCount",
        "WriteTransferCount",
        "OtherTransferCount",
    )]


class _JobExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _derive_appcontainer_sid(name: str):
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    derive = userenv.DeriveAppContainerSidFromAppContainerName
    derive.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.LPVOID)]
    derive.restype = ctypes.c_long
    sid = wintypes.LPVOID()
    result = derive(name, ctypes.byref(sid))
    if result < 0:
        raise NativeExecutionUnavailable(
            f"could not derive an ephemeral AppContainer SID (HRESULT 0x{result & 0xFFFFFFFF:08x})"
        )
    return sid


def _appcontainer_sid_string(sid) -> str:
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    text = wintypes.LPWSTR()
    advapi.ConvertSidToStringSidW.argtypes = [wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)]
    advapi.ConvertSidToStringSidW.restype = wintypes.BOOL
    if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return text.value
    finally:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        kernel32.LocalFree.restype = wintypes.HLOCAL
        kernel32.LocalFree(text)


def _create_appcontainer_process(
    profile: NativeExecutionProfile,
    executable: Path,
    argv: Sequence[str],
    cwd: Path,
) -> "_WindowsOwnedProcessHandle":
    if os.name != "nt":
        raise NativeExecutionUnavailable("AppContainer process creation requires Windows")

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    sid = _derive_appcontainer_sid(profile.appcontainer_name)
    job = None
    ownership_transferred = False
    process_info = _ProcessInformation()
    pipe_handles: list[int] = []
    attribute_list = None
    attribute_list_initialized = False
    stdout_stream = None
    stdin_stream = None
    stdin_fd = None
    stdout_fd = None
    try:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        security = _SecurityAttributes(
            ctypes.sizeof(_SecurityAttributes), None, True
        )
        kernel32.CreatePipe.argtypes = [
            ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
            ctypes.POINTER(_SecurityAttributes), wintypes.DWORD,
        ]
        kernel32.CreatePipe.restype = wintypes.BOOL
        kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
        kernel32.SetHandleInformation.restype = wintypes.BOOL
        child_stdin = wintypes.HANDLE()
        parent_stdin = wintypes.HANDLE()
        parent_stdout = wintypes.HANDLE()
        child_stdout = wintypes.HANDLE()
        if not kernel32.CreatePipe(ctypes.byref(child_stdin), ctypes.byref(parent_stdin), ctypes.byref(security), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        pipe_handles.extend([child_stdin.value, parent_stdin.value])
        if not kernel32.CreatePipe(ctypes.byref(parent_stdout), ctypes.byref(child_stdout), ctypes.byref(security), 0):
            raise ctypes.WinError(ctypes.get_last_error())
        pipe_handles.extend([parent_stdout.value, child_stdout.value])
        if not kernel32.SetHandleInformation(parent_stdin, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.SetHandleInformation(parent_stdout, 1, 0):
            raise ctypes.WinError(ctypes.get_last_error())

        caps = _SecurityCapabilities(sid, None, 0, 0)
        startup = _StartupInfoExW()
        startup.StartupInfo.cb = ctypes.sizeof(_StartupInfoExW)
        startup.StartupInfo.dwFlags = 0x00000100  # STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = child_stdin
        startup.StartupInfo.hStdOutput = child_stdout
        startup.StartupInfo.hStdError = child_stdout

        kernel32.InitializeProcThreadAttributeList.argtypes = [
            wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_size_t)
        ]
        kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
        attribute_size = ctypes.c_size_t()
        kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(attribute_size))
        if not attribute_size.value:
            raise ctypes.WinError(ctypes.get_last_error())
        attribute_list = ctypes.create_string_buffer(attribute_size.value)
        if not kernel32.InitializeProcThreadAttributeList(
            attribute_list, 2, 0, ctypes.byref(attribute_size)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        attribute_list_initialized = True
        startup.lpAttributeList = ctypes.cast(attribute_list, wintypes.LPVOID)
        kernel32.DeleteProcThreadAttributeList.argtypes = [wintypes.LPVOID]
        kernel32.DeleteProcThreadAttributeList.restype = None

        update = kernel32.UpdateProcThreadAttribute
        update.argtypes = [
            wintypes.LPVOID, wintypes.DWORD, ctypes.c_size_t, wintypes.LPVOID,
            ctypes.c_size_t, wintypes.LPVOID, ctypes.POINTER(ctypes.c_size_t),
        ]
        update.restype = wintypes.BOOL
        handle_list = (wintypes.HANDLE * 2)(child_stdin, child_stdout)
        if not update(startup.lpAttributeList, 0, 0x00020002, handle_list, ctypes.sizeof(handle_list), None, None):
            raise ctypes.WinError(ctypes.get_last_error())
        if not update(
            startup.lpAttributeList, 0, 0x00020009,
            ctypes.byref(caps), ctypes.sizeof(caps), None, None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = _JobExtendedLimitInformation()
        limits.BasicLimitInformation.LimitFlags = 0x00002008 | 0x00000100  # kill-on-close, process-count, per-process memory
        limits.BasicLimitInformation.ActiveProcessLimit = profile.max_processes
        limits.ProcessMemoryLimit = profile.memory_limit_bytes
        set_job = kernel32.SetInformationJobObject
        set_job.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        set_job.restype = wintypes.BOOL
        if not set_job(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())

        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
        env = _build_child_environment(profile)
        env_block = ctypes.create_unicode_buffer(
            "\0".join(f"{key}={value}" for key, value in sorted(env.items(), key=lambda item: item[0].casefold())) + "\0\0"
        )
        create = kernel32.CreateProcessW
        create.argtypes = [
            wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.LPVOID, wintypes.LPVOID,
            wintypes.BOOL, wintypes.DWORD, wintypes.LPVOID, wintypes.LPCWSTR,
            ctypes.POINTER(_StartupInfoExW), ctypes.POINTER(_ProcessInformation),
        ]
        create.restype = wintypes.BOOL
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.TerminateProcess.restype = wintypes.BOOL
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        flags = 0x00080000 | 0x00000004 | 0x00000400 | 0x08000000  # EXTENDED, SUSPENDED, UNICODE_ENV, NO_WINDOW
        if not create(
            str(executable), command_line, None, None, True, flags, env_block,
            str(cwd), ctypes.byref(startup), ctypes.byref(process_info),
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        if not kernel32.AssignProcessToJobObject(job, process_info.hProcess):
            error = ctypes.get_last_error()
            kernel32.TerminateProcess(process_info.hProcess, 0xC000013A)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            raise NativeExecutionUnavailable(
                f"could not assign delegated process to its owned job (WinError {error})"
            )

        resume = kernel32.ResumeThread
        resume.argtypes = [wintypes.HANDLE]
        resume.restype = wintypes.DWORD
        if resume(process_info.hThread) == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        kernel32.CloseHandle(process_info.hThread)
        process_info.hThread = None

        import msvcrt

        stdin_fd = msvcrt.open_osfhandle(parent_stdin.value, os.O_WRONLY | os.O_BINARY)
        pipe_handles.remove(parent_stdin.value)
        stdin_stream = io.open(stdin_fd, "w", encoding="utf-8", errors="replace", newline="")
        stdin_fd = None
        stdout_fd = msvcrt.open_osfhandle(parent_stdout.value, os.O_RDONLY | os.O_BINARY)
        pipe_handles.remove(parent_stdout.value)
        stdout_stream = io.open(stdout_fd, "r", encoding="utf-8", errors="replace", newline="")
        stdout_fd = None

        for handle in (child_stdin.value, child_stdout.value):
            kernel32.CloseHandle(handle)
            pipe_handles.remove(handle)
        owned = _WindowsOwnedProcessHandle(
            process_info.hProcess, job, process_info.dwProcessId, stdin_stream, stdout_stream,
            profile.appcontainer_name, tuple(argv),
        )
        process_info.hProcess = None
        job = None
        ownership_transferred = True
        return owned
    except NativeBoundaryError:
        raise
    except Exception as exc:
        raise NativeExecutionUnavailable(f"native Windows process launch failed: {exc}") from exc
    finally:
        if attribute_list_initialized:
            try:
                kernel32.DeleteProcThreadAttributeList(ctypes.cast(attribute_list, wintypes.LPVOID))
            except Exception:
                pass
        for handle in pipe_handles:
            if handle:
                kernel32.CloseHandle(handle)
        if stdin_fd is not None:
            os.close(stdin_fd)
        if stdout_fd is not None:
            os.close(stdout_fd)
        if not ownership_transferred:
            for stream in (stdin_stream, stdout_stream):
                if stream is not None:
                    stream.close()
        if process_info.hThread:
            kernel32.CloseHandle(process_info.hThread)
        if process_info.hProcess and not ownership_transferred:
            kernel32.TerminateProcess(process_info.hProcess, 0xC000013A)
            kernel32.WaitForSingleObject(process_info.hProcess, 5000)
            kernel32.CloseHandle(process_info.hProcess)
        if job:
            kernel32.CloseHandle(job)
        if sid:
            advapi32.FreeSid.argtypes = [wintypes.LPVOID]
            advapi32.FreeSid.restype = wintypes.LPVOID
            advapi32.FreeSid(sid)


def _build_child_environment(profile: NativeExecutionProfile) -> dict[str, str]:
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    child_env = {
        "SYSTEMROOT": system_root,
        "WINDIR": system_root,
        "PATH": os.pathsep.join(str(root) for root in profile.toolchain_roots),
        "PATHEXT": ".COM;.EXE",
        "TEMP": str(profile.private_temp),
        "TMP": str(profile.private_temp),
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    child_env.update(profile.safe_environment)
    return child_env


class _WindowsOwnedProcessHandle:
    """Popen-compatible pipes plus the process and Job Object lifetime."""

    def __init__(self, process_handle, job_handle, pid, stdin, stdout, appcontainer_name, args):
        self._process_handle = process_handle
        self._job_handle = job_handle
        self.pid = int(pid)
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = None
        self.args = args
        self.appcontainer_name = appcontainer_name
        self.returncode = None
        self._closed = False
        self._lock = threading.Lock()

    def poll(self) -> int | None:
        if self.returncode is not None:
            return self.returncode
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        if kernel32.WaitForSingleObject(self._process_handle, 0) != 0:
            return None
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(self._process_handle, ctypes.byref(code)):
            raise ctypes.WinError(ctypes.get_last_error())
        self.returncode = int(code.value)
        return self.returncode

    def wait(self, timeout: float | None = None) -> int:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        milliseconds = 0xFFFFFFFF if timeout is None else max(0, min(int(timeout * 1000), 0xFFFFFFFE))
        result = kernel32.WaitForSingleObject(self._process_handle, milliseconds)
        if result == 0x00000102:
            raise subprocess.TimeoutExpired(self.args or self.pid, timeout)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return self.poll()

    def communicate(self, input: str | None = None, timeout: float | None = None):
        output: list[str] = []
        reader_error: list[BaseException] = []

        def read_output() -> None:
            try:
                output.append(self.stdout.read())
            except BaseException as exc:
                reader_error.append(exc)

        reader = threading.Thread(target=read_output, daemon=True, name=f"hermes-native-output-{self.pid}")
        reader.start()
        try:
            if self.stdin and not self.stdin.closed:
                if input:
                    self.stdin.write(input)
                    self.stdin.flush()
                self.stdin.close()
            self.wait(timeout)
            reader.join(timeout)
            if reader.is_alive():
                self.kill_tree()
                reader.join(2)
                raise subprocess.TimeoutExpired(self.args or self.pid, timeout, output="".join(output))
            if reader_error:
                raise reader_error[0]
            return "".join(output), None
        except subprocess.TimeoutExpired as exc:
            self.kill_tree()
            reader.join(2)
            raise subprocess.TimeoutExpired(self.args or self.pid, timeout, output="".join(output)) from exc

    def kill_tree(self) -> None:
        if self._job_handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            if not kernel32.TerminateJobObject(self._job_handle, 1):
                code = ctypes.get_last_error()
                if self.poll() is None:
                    raise ctypes.WinError(code)

    def kill(self) -> None:
        self.kill_tree()

    def terminate(self) -> None:
        self.kill_tree()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                if self.stdin and not self.stdin.closed:
                    self.stdin.close()
                if self.stdout and not self.stdout.closed:
                    self.stdout.close()
            finally:
                if self.poll() is None:
                    self.kill_tree()
                    try:
                        self.wait(5)
                    except subprocess.TimeoutExpired:
                        pass
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                kernel32.CloseHandle.restype = wintypes.BOOL
                if self._process_handle:
                    kernel32.CloseHandle(self._process_handle)
                    self._process_handle = None
                if self._job_handle:
                    kernel32.CloseHandle(self._job_handle)
                    self._job_handle = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


__all__ = [
    "NativeExecutionDenied",
    "NativeExecutionProfile",
    "NativeExecutionUnavailable",
    "OwnedProcessHandle",
    "active_native_execution_profile",
    "bind_native_execution_profile",
    "launch_restricted",
    "new_native_execution_profile",
]

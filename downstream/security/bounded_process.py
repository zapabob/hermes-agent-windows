from __future__ import annotations

import os
import signal
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


class BoundedProcessOutputError(subprocess.SubprocessError):
    """Raised when captured output or the child process tree is incomplete."""

    def __init__(self, stdout: str, stderr: str, reason: str) -> None:
        super().__init__(reason)
        self.stdout = stdout
        self.stderr = stderr
        self.reason = reason


@dataclass(frozen=True)
class BoundedProcessResult:
    returncode: int
    stdout: str
    stderr: str
    output_truncated: bool


def run_bounded(
    arguments: Sequence[str],
    *,
    timeout: float,
    max_output_bytes_per_stream: int = 16 * 1024,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> BoundedProcessResult:
    """Run a command while draining both output pipes with bounded tail buffers."""
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if max_output_bytes_per_stream <= 0:
        raise ValueError("output limit must be positive")

    job_handle = _create_windows_job() if os.name == "nt" else None
    try:
        process = subprocess.Popen(
            list(arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd) if cwd is not None else None,
            env=dict(env) if env is not None else None,
            close_fds=True,
            start_new_session=(os.name != "nt"),
            creationflags=0x00000004 if os.name == "nt" else 0,  # CREATE_SUSPENDED
        )
    except Exception:
        _close_windows_job(job_handle)
        raise
    if job_handle is not None:
        try:
            _assign_windows_job(job_handle, process)
            _resume_suspended_process(process.pid)
        except Exception as exc:
            _terminate_process_tree(process, job_handle)
            _close_windows_job(job_handle)
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.SubprocessError("could not establish bounded Windows process job") from exc
    stdout = bytearray()
    stderr = bytearray()
    output_truncated = threading.Event()
    pipe_read_failed = threading.Event()
    buffers_lock = threading.Lock()

    def drain(stream, buffer: bytearray) -> None:
        try:
            while True:
                chunk = os.read(stream.fileno(), 4096)
                if not chunk:
                    return
                with buffers_lock:
                    buffer.extend(chunk)
                    overflow = len(buffer) - max_output_bytes_per_stream
                    if overflow > 0:
                        del buffer[:overflow]
                        output_truncated.set()
        except (OSError, ValueError):
            pipe_read_failed.set()
            _terminate_process_tree(process, job_handle)
            return

    assert process.stdout is not None
    assert process.stderr is not None
    readers = (
        threading.Thread(target=drain, args=(process.stdout, stdout), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr), daemon=True),
    )
    for reader in readers:
        reader.start()

    timed_out = False
    returncode: int | None = None
    readers_were_stuck = False
    process_tree_incomplete = False
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(process, job_handle)
        try:
            returncode = process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            returncode = process.poll()
    finally:
        for reader in readers:
            reader.join(timeout=0.5)
        readers_stuck = any(reader.is_alive() for reader in readers)
        readers_were_stuck = readers_stuck
        if readers_stuck:
            _terminate_process_tree(process, job_handle)
            for reader in readers:
                reader.join(timeout=0.5)
        for stream, reader in zip((process.stdout, process.stderr), readers, strict=True):
            # Closing a buffered pipe from another thread can itself block while
            # that thread is waiting on a descendant-held pipe handle.
            if reader.is_alive():
                continue
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for reader in readers:
            reader.join(timeout=0.1)
        if os.name != "nt" and _posix_process_group_exists(process.pid):
            # A descendant may deliberately close both captured pipes and
            # outlive the command. Keep the group boundary fail closed even
            # when the pipe readers already reached EOF.
            _terminate_process_tree(process, job_handle)
            process_tree_incomplete = True
        total_processes, active_processes = _windows_job_process_counts(job_handle)
        process_tree_incomplete = process_tree_incomplete or (
            total_processes >= MAX_BOUNDED_PROCESS_TREE_NODES or active_processes > 0
        )
        if process_tree_incomplete:
            _terminate_process_tree(process, job_handle)
        _close_windows_job(job_handle)

    with buffers_lock:
        out_text = bytes(stdout).decode("utf-8", errors="replace")
        err_text = bytes(stderr).decode("utf-8", errors="replace")
    if pipe_read_failed.is_set():
        raise BoundedProcessOutputError(out_text, err_text, "output_pipe_read_failed")
    if timed_out:
        raise subprocess.TimeoutExpired(
            list(arguments),
            timeout,
            output=out_text,
            stderr=err_text,
        )
    if returncode is None:
        raise subprocess.SubprocessError("process exit status unavailable")
    if readers_were_stuck or any(reader.is_alive() for reader in readers) or process_tree_incomplete:
        reason = (
            "process_tree_limit_or_active_descendant"
            if process_tree_incomplete
            else "output_pipe_not_quiescent"
        )
        raise BoundedProcessOutputError(out_text, err_text, reason)
    return BoundedProcessResult(
        returncode=int(returncode),
        stdout=out_text,
        stderr=err_text,
        output_truncated=output_truncated.is_set(),
    )


MAX_BOUNDED_PROCESS_TREE_NODES = 256


def _posix_process_group_exists(process_id: int) -> bool:
    try:
        os.killpg(process_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _windows_api():
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return ctypes, wintypes, kernel32


def _create_windows_job() -> object:
    """Create a kill-on-close job with a bounded active-process count."""
    ctypes, wintypes, kernel32 = _windows_api()
    size_t = ctypes.c_size_t

    class BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", size_t),
            ("MaximumWorkingSetSize", size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in (
            "ReadOperationCount",
            "WriteOperationCount",
            "OtherOperationCount",
            "ReadTransferCount",
            "WriteTransferCount",
            "OtherTransferCount",
        )]

    class ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimitInformation),
            ("IoInfo", IoCounters),
            ("ProcessMemoryLimit", size_t),
            ("JobMemoryLimit", size_t),
            ("PeakProcessMemoryUsed", size_t),
            ("PeakJobMemoryUsed", size_t),
        ]

    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
    info = ExtendedLimitInformation()
    # JOB_OBJECT_LIMIT_ACTIVE_PROCESS | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.BasicLimitInformation.LimitFlags = 0x00000008 | 0x00002000
    info.BasicLimitInformation.ActiveProcessLimit = MAX_BOUNDED_PROCESS_TREE_NODES
    if not kernel32.SetInformationJobObject(
        handle,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(handle)
        raise OSError(error, "SetInformationJobObject failed")
    return handle


def _assign_windows_job(handle: object, process: subprocess.Popen[bytes]) -> None:
    ctypes, wintypes, kernel32 = _windows_api()
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    process_handle = wintypes.HANDLE(int(getattr(process, "_handle")))
    if not kernel32.AssignProcessToJobObject(wintypes.HANDLE(handle), process_handle):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")


def _resume_suspended_process(process_id: int) -> None:
    ctypes, wintypes, kernel32 = _windows_api()

    class ThreadEntry32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ThreadID", wintypes.DWORD),
            ("th32OwnerProcessID", wintypes.DWORD),
            ("tpBasePri", wintypes.LONG),
            ("tpDeltaPri", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.Thread32First.restype = wintypes.BOOL
    kernel32.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry32)]
    kernel32.Thread32Next.restype = wintypes.BOOL
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.restype = wintypes.DWORD
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000004, 0)
    if not snapshot or int(snapshot) == -1:
        raise OSError(ctypes.get_last_error(), "CreateToolhelp32Snapshot failed")
    resumed = False
    try:
        entry = ThreadEntry32()
        entry.dwSize = ctypes.sizeof(entry)
        found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.th32OwnerProcessID == process_id:
                thread = kernel32.OpenThread(0x0002, False, entry.th32ThreadID)
                if not thread:
                    raise OSError(ctypes.get_last_error(), "OpenThread failed")
                try:
                    if kernel32.ResumeThread(thread) == 0xFFFFFFFF:
                        raise OSError(ctypes.get_last_error(), "ResumeThread failed")
                    resumed = True
                finally:
                    kernel32.CloseHandle(thread)
                break
            found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    if not resumed:
        raise OSError("suspended process thread was not found")


def _windows_job_process_counts(handle: object | None) -> tuple[int, int]:
    if handle is None:
        return 0, 0
    ctypes, wintypes, kernel32 = _windows_api()

    class BasicAccountingInformation(ctypes.Structure):
        _fields_ = [
            ("TotalUserTime", ctypes.c_int64),
            ("TotalKernelTime", ctypes.c_int64),
            ("ThisPeriodTotalUserTime", ctypes.c_int64),
            ("ThisPeriodTotalKernelTime", ctypes.c_int64),
            ("TotalPageFaultCount", wintypes.DWORD),
            ("TotalProcesses", wintypes.DWORD),
            ("ActiveProcesses", wintypes.DWORD),
            ("TotalTerminatedProcesses", wintypes.DWORD),
        ]

    kernel32.QueryInformationJobObject.argtypes = [
        wintypes.HANDLE,
        wintypes.INT,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    kernel32.QueryInformationJobObject.restype = wintypes.BOOL
    info = BasicAccountingInformation()
    if not kernel32.QueryInformationJobObject(
        wintypes.HANDLE(handle),
        1,  # JobObjectBasicAccountingInformation
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    ):
        return MAX_BOUNDED_PROCESS_TREE_NODES, 1
    return int(info.TotalProcesses), int(info.ActiveProcesses)


def _close_windows_job(handle: object | None) -> None:
    if handle is None:
        return
    _ctypes, wintypes, kernel32 = _windows_api()
    kernel32.CloseHandle(wintypes.HANDLE(handle))


def _terminate_process_tree(process: subprocess.Popen[bytes], job_handle: object | None = None) -> None:
    """Best-effort termination scoped to this subprocess and its descendants."""
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        return
    if job_handle is not None:
        try:
            _ctypes, wintypes, kernel32 = _windows_api()
            kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            kernel32.TerminateJobObject.restype = wintypes.BOOL
            kernel32.TerminateJobObject(wintypes.HANDLE(job_handle), 1)
        except (OSError, AttributeError):
            pass
    try:
        process.kill()
    except OSError:
        # The child may exit between poll() and kill().
        pass

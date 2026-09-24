"""Local NVIDIA device selection and bounded, read-only GPU telemetry."""

from __future__ import annotations

import csv
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from io import StringIO
from typing import Callable, Sequence


_MAX_GPU_COUNT = 16
_MAX_OUTPUT_CHARS = 16 * 1024
_MAX_LOCAL_PIDS = 4096
_MAX_TIMEOUT_SECONDS = 2.0
_UUID_RE = re.compile(r"(?:GPU|MIG)-[A-Za-z0-9_-]{1,92}\Z")


@dataclass(frozen=True, slots=True)
class NvidiaGpuTelemetry:
    """Sanitized observation for one GPU; never includes process identifiers."""

    uuid: str
    free_vram_bytes: int | None
    local_resident_bytes: int | None
    observed_at_monotonic: float


@dataclass(frozen=True, slots=True)
class NvidiaGpuProbeResult:
    """GPU probe result with bounded error codes instead of raw command output."""

    devices: tuple[NvidiaGpuTelemetry, ...] | None
    observed_at_monotonic: float | None
    error: str | None = None
    residency_error: str | None = None


def visible_cuda_devices(value: str | None = None) -> tuple[int, ...]:
    """Parse CUDA_VISIBLE_DEVICES into an ordered tuple of numeric device ids."""
    raw = os.getenv("CUDA_VISIBLE_DEVICES", "") if value is None else value
    raw = raw.strip()
    if not raw or raw == "-1":
        return ()
    devices = tuple(int(part.strip()) for part in raw.split(","))
    if any(device < 0 for device in devices) or len(set(devices)) != len(devices):
        raise ValueError("CUDA device ids must be unique non-negative integers")
    return devices


def _bounded_timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 1.0
    parsed = float(value)
    if not math.isfinite(parsed):
        return 1.0
    return min(max(parsed, 0.1), _MAX_TIMEOUT_SECONDS)


def _run_nvidia_smi(
    executable: str,
    args: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: float,
) -> tuple[str | None, str | None]:
    environment: dict[str, str] = {}
    path_parts = [os.path.dirname(os.path.abspath(executable))]
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if system_root:
            environment["SystemRoot"] = system_root
            environment["WINDIR"] = system_root
            path_parts.append(os.path.join(system_root, "System32"))
    else:
        path_parts.extend(("/usr/bin", "/bin"))
    environment["PATH"] = os.pathsep.join(part for part in path_parts if part)
    try:
        result = runner(
            [executable, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            env=environment,
        )
    except subprocess.TimeoutExpired:
        return None, "gpu_probe_timeout"
    except (OSError, ValueError, TypeError):
        return None, "gpu_probe_failed"

    output = result.stdout
    if not isinstance(output, str) or len(output) > _MAX_OUTPUT_CHARS:
        return None, "gpu_probe_output_invalid"
    if result.returncode != 0:
        return None, "gpu_probe_failed"
    return output, None


def _parse_mib(value: str) -> int | None:
    normalized = value.strip()
    if not normalized.isdecimal():
        return None
    return int(normalized) * 1024 * 1024


def _parse_gpu_rows(output: str) -> tuple[tuple[str, int | None], ...]:
    rows: list[tuple[str, int | None]] = []
    for row in csv.reader(StringIO(output)):
        if not row or len(rows) >= _MAX_GPU_COUNT:
            continue
        if len(row) != 2:
            continue
        uuid, free_mib = (part.strip() for part in row)
        if not _UUID_RE.fullmatch(uuid):
            continue
        rows.append((uuid, _parse_mib(free_mib)))
    return tuple(rows)


def _validated_local_pids(local_process_ids: Sequence[int]) -> tuple[int, ...] | None:
    if not isinstance(local_process_ids, (tuple, list)):
        return None
    if len(local_process_ids) > _MAX_LOCAL_PIDS:
        return None
    pids = tuple(local_process_ids)
    if len(pids) > _MAX_LOCAL_PIDS or any(
        isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0 for pid in pids
    ):
        return None
    return tuple(sorted(set(pids)))


def _parse_local_residency(
    output: str,
    *,
    gpu_uuids: set[str],
    local_pids: set[int],
) -> tuple[dict[str, int | None], str | None]:
    totals: dict[str, int | None] = {uuid: 0 for uuid in gpu_uuids}
    if not output.strip():
        return totals, None
    matched_rows = 0
    malformed = False
    for row in csv.reader(StringIO(output)):
        if not row:
            continue
        if len(row) != 3:
            malformed = True
            continue
        uuid, raw_pid, raw_mib = (part.strip() for part in row)
        if not raw_pid.isdecimal():
            malformed = True
            continue
        if uuid not in gpu_uuids:
            malformed = True
            continue
        pid = int(raw_pid)
        if pid not in local_pids:
            continue
        matched_rows += 1
        resident_bytes = _parse_mib(raw_mib)
        if resident_bytes is None:
            totals[uuid] = None
            continue
        current_total = totals[uuid]
        if isinstance(current_total, int):
            totals[uuid] = current_total + resident_bytes
    if malformed or not matched_rows:
        return {uuid: None for uuid in gpu_uuids}, "gpu_local_residency_unavailable"
    return totals, None


def query_nvidia_gpu_telemetry(
    local_process_ids: Sequence[int] | None = None,
    *,
    timeout_seconds: float = 1.0,
    executable_lookup: Callable[[str], str | None] = shutil.which,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    monotonic_clock: Callable[[], float] = time.monotonic,
) -> NvidiaGpuProbeResult:
    """Read GPU free VRAM and optional known-local process residency.

    The probe invokes only ``nvidia-smi`` telemetry queries. It does not start,
    stop, or configure a model service or driver. When local process ids are
    omitted, residency remains unknown; it is never reported as zero by
    inference. Raw command output, stderr, and process ids are not returned.
    """
    timeout = _bounded_timeout(timeout_seconds)
    try:
        executable = executable_lookup("nvidia-smi")
    except (OSError, ValueError, TypeError):
        executable = None
    if not executable:
        return NvidiaGpuProbeResult(None, None, error="gpu_probe_unavailable")

    output, error = _run_nvidia_smi(
        executable,
        (
            "--query-gpu=uuid,memory.free",
            "--format=csv,noheader,nounits",
        ),
        runner=runner,
        timeout=timeout,
    )
    if error:
        return NvidiaGpuProbeResult(None, None, error=error)
    assert output is not None
    parsed = _parse_gpu_rows(output)
    if not parsed:
        return NvidiaGpuProbeResult(None, None, error="gpu_probe_data_unavailable")
    # Use the earlier probe time for the combined record. The optional
    # residency query runs afterward, so this keeps freshness conservative.
    observed_at = monotonic_clock()

    residency_by_uuid: dict[str, int | None] | None = None
    residency_error: str | None = None
    if local_process_ids is None:
        residency_error = "gpu_local_residency_unavailable"
    else:
        local_pids = _validated_local_pids(local_process_ids)
        if local_pids is None:
            residency_error = "gpu_local_process_ids_invalid"
        elif not local_pids:
            residency_by_uuid = {uuid: 0 for uuid, _free in parsed}
        else:
            process_output, process_error = _run_nvidia_smi(
                executable,
                (
                    "--query-compute-apps=gpu_uuid,pid,used_memory",
                    "--format=csv,noheader,nounits",
                ),
                runner=runner,
                timeout=timeout,
            )
            if process_error or process_output is None:
                residency_error = "gpu_local_residency_unavailable"
            else:
                residency_by_uuid, residency_error = _parse_local_residency(
                    process_output,
                    gpu_uuids={uuid for uuid, _free in parsed},
                    local_pids=set(local_pids),
                )

    devices = tuple(
        NvidiaGpuTelemetry(
            uuid=uuid,
            free_vram_bytes=free_vram,
            local_resident_bytes=(
                residency_by_uuid.get(uuid) if residency_by_uuid is not None else None
            ),
            observed_at_monotonic=observed_at,
        )
        for uuid, free_vram in parsed
    )
    return NvidiaGpuProbeResult(
        devices=devices,
        observed_at_monotonic=observed_at,
        residency_error=residency_error,
    )


__all__ = [
    "NvidiaGpuProbeResult",
    "NvidiaGpuTelemetry",
    "query_nvidia_gpu_telemetry",
    "visible_cuda_devices",
]

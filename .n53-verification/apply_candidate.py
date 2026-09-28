"""Verification-only patch builder. Refuses any source other than the reviewed blob."""
import ast
import hashlib
from pathlib import Path

EXPECTED_BLOB = "d1f602f41c41e9e752a3af3067e79cf6c6f7f6e6"

HELPERS = '''class _WindowsGatewayPauseRecoveryError(RuntimeError):
    """Both failures plus the existing owner's still-pending recovery token."""

    def __init__(self, pause_error, recovery_error, token):
        super().__init__(
            f"Windows gateway pause failed: {pause_error}; recovery also failed: {recovery_error}")
        self.pause_error = pause_error
        self.recovery_error = recovery_error
        self.windows_gateway_resume = token


@contextmanager
def _windows_gateway_pause_recovery(token):
    """Compensate only this pause attempt, through the existing restart owner."""
    try:
        yield
    except BaseException as pause_error:
        # Passive dead-attestation plans are not effects of this failed pause.
        # Never turn abort recovery into an unrelated profile's cold-start.
        token.pop("cold_start_profiles", None)
        token.pop("cold_start_if_installed", None)
        if token.get("profiles") or token.get("unmapped") or token.get("services"):
            from hermes_cli.update_cmd import _m
            try:
                _m()._resume_windows_gateways_after_update(token)
            except BaseException as recovery_error:
                raise _WindowsGatewayPauseRecoveryError(
                    pause_error, recovery_error, token) from pause_error
        raise


'''

PAUSE = '''def _pause_windows_gateways_for_update() -> dict | None:
    """Stop discovered Windows gateways; own recovery from the first pause effect."""
    from hermes_cli.update_cmd import _m
    if not _m()._is_windows():
        return None
    with _abort_on_error("Could not prepare Windows gateway pause for update"):
        from gateway.status import get_process_start_time, terminate_pid
        from hermes_cli.gateway import _capture_gateway_argv
    profile_processes, service_gateways, service_gateway_pids, running_pids = _discover_windows_gateways()
    if not running_pids:
        token = _windows_cold_start_plan()
        probe = token if token is not None else {"resume_needed": True, "profiles": {}, "unmapped_pids": [], "unmapped": []}
        _record_attested_cold_start_profiles(probe, set())
        return probe if probe.get("cold_start_profiles") else token

    # Finish discovery and replay preparation BEFORE the first marker/socket write.
    mapped_pids = [pid for pid in running_pids if pid in profile_processes and pid not in service_gateway_pids]
    for pid in mapped_pids:
        str(profile_processes[pid].profile), Path(profile_processes[pid].path), int(pid)
    launcher_pids = _m()._venv_launcher_ancestors(mapped_pids)
    service_owned_pids = set(service_gateway_pids)
    for service in service_gateways:
        service_owned_pids.add(int(service.service_pid))
        service_owned_pids.update(int(pid) for pid, _ in getattr(service, "descendant_identities", ()))
    if set(launcher_pids) & service_owned_pids:
        raise RuntimeError("Windows launcher/service ownership overlaps; no gateways were paused")
    unmapped_pids = [pid for pid in running_pids if pid not in profile_processes and pid not in service_gateway_pids]
    prepared_unmapped = {
        int(pid): {"pid": int(pid), "argv": _try_call(lambda p=int(pid): _capture_gateway_argv(p),
                  "Could not capture argv for unmapped gateway %s: %s", int(pid))}
        for pid in unmapped_pids
    }
    running_profiles = {str(p.profile) for p in profile_processes.values()} | {str(s.profile) for s in service_gateways}
    # Do not discover a DIFFERENT incarnation after pause and authorize its termination.
    start_times = {int(pid): get_process_start_time(int(pid))
                   for pid in set(mapped_pids) | set(unmapped_pids) | set(launcher_pids)}
    if any(value is None for value in start_times.values()):
        raise RuntimeError("Windows gateway process identity is unavailable before pause")

    token = {"resume_needed": True, "profiles": {}, "unmapped_pids": [], "unmapped": [], "pause_attempts": {}}
    with _windows_gateway_pause_recovery(token):
        profiles, mapped_pids, socket_acks = _request_socket_pauses(
            running_pids, profile_processes, service_gateway_pids, token)
        token["profiles"] = profiles
        print("→ Stopping Windows gateway process(es) before updating Hermes...")
        drain_timeout = _gateway_drain_timeout(socket_acks)
        survivors = _m()._wait_for_windows_update_gateway_exit(mapped_pids, timeout=drain_timeout)
        force_killed = []
        for pid in sorted(set(survivors).union(unmapped_pids).union(launcher_pids)):
            if pid in prepared_unmapped:
                # A later kill failure must not restart an as-yet-unattempted target.
                token["unmapped_pids"].append(int(pid))
                token["unmapped"].append(prepared_unmapped[pid])
            with suppress(ProcessLookupError):
                terminate_pid(int(pid), force=True, expected_start_time=start_times[int(pid)])
                force_killed.append(int(pid))
        if profiles:
            print(f"  ✓ Paused gateway profile(s): {', '.join(sorted(profiles))}")
        if force_killed:
            print(f"  → Force-stopped {len(force_killed)} gateway process(es)")
        if unmapped_pids:
            print(f"  → Stopped {len(unmapped_pids)} gateway process(es) without profile mapping")
            if any(not u.get("argv") for u in token["unmapped"]):
                print("    Restart manually after update: hermes gateway run")

    # This helper already owns rollback for a failed SCM stop. Do not wrap it in
    # another rollback or replay its failed recovery. No passive cold-start plan
    # is present while it restores ordinary gateways after an SCM failure.
    token = _pause_windows_gateway_services(service_gateways, token, profiles, token["unmapped"])
    with _windows_gateway_pause_recovery(token):
        _record_attested_cold_start_profiles(token, running_profiles)
    return token
'''


def build(source):
    nodes = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)
    req = nodes["_request_socket_pauses"]
    old = "".join(lines[req.lineno - 1:req.end_lineno])
    new = old.replace(
        "def _request_socket_pauses(running_pids, profile_processes, service_gateway_pids):",
        "def _request_socket_pauses(running_pids, profile_processes, service_gateway_pids, token=None):", 1)
    new = new.replace("    profiles: dict[str, int] = {}",
                      '    profiles: dict[str, int] = token["profiles"] if token is not None else {}', 1)
    new = new.replace("        mapped_pids.append(int(pid))\n",
        '        mapped_pids.append(int(pid))\n'
        '        if token is not None:\n'
        '            token["pause_attempts"][str(proc.profile)] = {"pid": int(pid), "state": "unknown"}\n', 1)
    new = new.replace("                socket_acks.append(ack)\n",
        '                socket_acks.append(ack)\n'
        '                if token is not None:\n'
        '                    token["pause_attempts"][str(proc.profile)]["state"] = "acknowledged"\n', 1)
    changes = [(req.lineno - 1, req.end_lineno, HELPERS + new),
               (nodes["_pause_windows_gateways_for_update"].lineno - 1,
                nodes["_pause_windows_gateways_for_update"].end_lineno, PAUSE)]
    for first, last, replacement in sorted(changes, reverse=True):
        lines[first:last] = [replacement if replacement.endswith("\n") else replacement + "\n"]
    candidate = "".join(lines)
    ast.parse(candidate)
    return candidate


def main():
    root = Path.cwd().resolve()
    path = (root / "hermes_cli/update_cmd_windows.py").resolve(strict=True)
    if not path.is_relative_to(root):
        raise SystemExit("Source escapes checkout")
    raw = path.read_bytes()
    observed = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    if observed != EXPECTED_BLOB:
        raise SystemExit(f"Source changed: expected {EXPECTED_BLOB}, observed {observed}; re-review required")
    path.write_bytes(build(raw.decode("utf-8")).encode("utf-8"))
    print("Candidate SHA256:", hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()

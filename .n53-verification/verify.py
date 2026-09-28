"""Run pinned-source contracts, selected regressions and targeted mutations.

Only disposable CI processes/homes are used. No real installed Gateway is updated.
Every run uses the repository's canonical test runner. Invalid mutants never count.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
OUT = ROOT / 'n53-evidence'
SOURCE_PATH = ROOT / 'hermes_cli/update_cmd_windows.py'
TEST = 'tests/hermes_cli/test_windows_update_pause_transaction.py'
# CreateProcess searches System32 before PATH for an unqualified executable.
# Never launch System32/bash.exe: it is the WSL shim, not native Git Bash.
BASH = Path(os.environ['ProgramFiles']) / 'Git' / 'bin' / 'bash.exe'
REGRESSION = [
    'tests/hermes_cli/test_gateway.py',
    'tests/hermes_cli/test_gateway_windows.py',
    'tests/hermes_cli/test_update_concurrent_quarantine.py',
    'tests/hermes_cli/test_windows_gateway_cold_start_desktop_lifecycle.py',
    'tests/hermes_cli/test_update_inventory.py',
]
LIVE = [
    'tests/hermes_cli/test_venv_holder_windows_live.py',
    'tests/hermes_cli/test_taskkill_identity_windows_live.py',
]
MUTANTS = [
 ('drop_recovery', '_windows_gateway_pause_recovery', '_m()._resume_windows_gateways_after_update(token)', 'pass', 'test_partial_pause_failure_recovers_already_paused_profile'),
 ('disconnect_early_token', '_request_socket_pauses', 'token["profiles"] if token is not None else {}', '{}', 'test_partial_pause_failure_recovers_already_paused_profile'),
 ('assume_timeout_unpaused', '_request_socket_pauses', '"state": "unknown"', '"state": "not_paused"', 'test_lost_ack_is_retained_as_uncertain_on_abort'),
 ('hide_recovery_error', '_WindowsGatewayPauseRecoveryError', '; recovery also failed: {recovery_error}', '', 'test_primary_and_recovery_failures_both_remain_visible'),
 ('allow_scm_launcher_overlap', '_pause_windows_gateways_for_update', 'if set(launcher_pids) & service_owned_pids:', 'if False and set(launcher_pids) & service_owned_pids:', 'test_launcher_service_overlap_refuses_before_any_pause'),
 ('authorize_recycled_pid', '_pause_windows_gateways_for_update', 'expected_start_time=start_times[int(pid)]', 'expected_start_time=get_process_start_time(int(pid))', 'test_force_stop_uses_the_pre_pause_process_incarnation'),
 ('pause_service_gateway', '_request_socket_pauses', 'proc = None if pid in service_gateway_pids else profile_processes.get(pid)', 'proc = profile_processes.get(pid)', 'test_service_gateway_never_enters_socket_or_launcher_set'),
 ('register_unattempted_profiles', '_pause_windows_gateways_for_update', '"resume_needed": True, "profiles": {}, "unmapped_pids": [], "unmapped": [], "pause_attempts": {}', '"resume_needed": True, "profiles": {str(p.profile): int(pid) for pid, p in profile_processes.items()}, "unmapped_pids": [], "unmapped": [], "pause_attempts": {}', 'test_later_failure_recovers_only_attempted_profiles[wait_failure]'),
 ('cold_start_on_abort', '_windows_gateway_pause_recovery', 'token.pop("cold_start_profiles", None)', 'pass', 'test_abort_does_not_convert_passive_attestation_into_a_start'),
 ('accept_unknown_identity', '_pause_windows_gateways_for_update', 'if any(value is None for value in start_times.values()):', 'if False and any(value is None for value in start_times.values()):', 'test_unknown_process_identity_refuses_before_first_effect'),
]
RESULTS = []


def run(label, target, expected_failure=False, exact_count=None):
    xml = f'n53-evidence/{label}.xml'
    command = [str(BASH), 'scripts/run_tests.sh', target, '-q', f'--junitxml={xml}']
    proc = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace', timeout=900)
    (OUT / f'{label}.log').write_text(proc.stdout, encoding='utf-8')
    print(proc.stdout, flush=True)
    xml_path = ROOT / xml
    if not xml_path.is_file():
        raise RuntimeError(f'{label}: no JUnit result; not test evidence (exit {proc.returncode})')
    tree = ET.parse(xml_path)
    cases = tree.findall('.//testcase')
    failures = tree.findall('.//testcase/failure')
    errors = tree.findall('.//testcase/error')
    skipped = tree.findall('.//testcase/skipped')
    result = {'label': label, 'command': command, 'exit_code': proc.returncode,
              'tests': len(cases), 'failures': len(failures), 'errors': len(errors), 'skipped': len(skipped)}
    RESULTS.append(result)
    if errors or len(cases) <= len(skipped):
        raise RuntimeError(f'{label}: errors or no executed tests: {result}')
    if exact_count is not None and (len(cases) != exact_count or skipped):
        raise RuntimeError(f'{label}: unexpected test count or skips: {result}')
    if expected_failure:
        if proc.returncode != 1 or not failures:
            raise RuntimeError(f'{label}: not the required RED result: {result}')
        if not all('AssertionError' in (f.text or '') or 'Failed: DID NOT RAISE' in (f.text or '') for f in failures):
            raise RuntimeError(f'{label}: failure was not the designated behavioral assertion')
    elif proc.returncode != 0 or failures:
        raise RuntimeError(f'{label}: regression/positive control failed: {result}')
    print(json.dumps(result), flush=True)


def mutate(source, symbol, before, after):
    node = next(n for n in ast.parse(source).body if getattr(n, 'name', None) == symbol)
    lines = source.splitlines(keepends=True)
    part = ''.join(lines[node.lineno - 1:node.end_lineno])
    if part.count(before) != 1:
        raise RuntimeError(f'{symbol}: ambiguous mutation target')
    lines[node.lineno - 1:node.end_lineno] = [part.replace(before, after, 1)]
    result = ''.join(lines)
    ast.parse(result)
    return result


def main():
    OUT.mkdir(exist_ok=True)
    if not BASH.is_file():
        raise RuntimeError(f'Native Git for Windows Bash not found: {BASH}')
    baseline = SOURCE_PATH.read_bytes()
    (OUT / 'baseline_update_cmd_windows.py').write_bytes(baseline)
    candidate = None
    try:
        run('red', TEST, expected_failure=True, exact_count=17)
        for i, target in enumerate(REGRESSION):
            run(f'baseline-regression-{i}', target)
        subprocess.run([sys.executable, '.n53-verification/apply_candidate.py'], check=True)
        candidate = SOURCE_PATH.read_bytes()
        (OUT / 'candidate_update_cmd_windows.py').write_bytes(candidate)
        run('green', TEST, exact_count=17)
        for i, target in enumerate(REGRESSION):
            run(f'green-regression-{i}', target)
        for i, target in enumerate(LIVE):
            run(f'live-{i}', target)
        for name, symbol, before, after, test in MUTANTS:
            try:
                SOURCE_PATH.write_bytes(mutate(candidate.decode('utf-8'), symbol, before, after).encode('utf-8'))
                run(f'mutant-{name}', f'{TEST}::{test}', expected_failure=True, exact_count=1)
            finally:
                SOURCE_PATH.write_bytes(candidate)
        run('final-green', TEST, exact_count=17)
        subprocess.run(['git', 'diff', '--check'], check=True)
        (OUT / 'VERIFIED').write_text(hashlib.sha256(candidate).hexdigest() + '\n', encoding='ascii')
    finally:
        if candidate is not None:
            SOURCE_PATH.write_bytes(candidate)
        receipt = {'scope': 'real Windows/Python imports; fake OS effects in contracts; separately selected live-process tests',
                   'baseline_blob': 'd1f602f41c41e9e752a3af3067e79cf6c6f7f6e6',
                   'candidate_sha256': hashlib.sha256(candidate).hexdigest() if candidate else None,
                   'results': RESULTS}
        (OUT / 'results.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        diff = subprocess.run(['git', 'diff', '--', 'hermes_cli/update_cmd_windows.py'], capture_output=True, text=True, encoding='utf-8')
        (OUT / 'candidate.patch').write_text(diff.stdout, encoding='utf-8')


if __name__ == '__main__':
    main()

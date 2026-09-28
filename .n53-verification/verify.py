"""Native Windows TDD, targeted mutations and baseline-relative regression.

Pre-existing baseline failures are preserved, never renamed a full-suite pass.
A candidate may not add failures, skip more tests, or change the collected set.
Only disposable process fixtures are used; no installed Gateway is updated.
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


def run(label, target, expected_failure=False, exact_count=None, record_baseline=False):
    xml_path = OUT / f'{label}.xml'
    xml_path.unlink(missing_ok=True)
    command = [str(BASH), 'scripts/run_tests.sh', target, '-q', f'--junitxml=n53-evidence/{label}.xml']
    proc = subprocess.run(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding='utf-8', errors='replace', timeout=900)
    (OUT / f'{label}.log').write_text(proc.stdout, encoding='utf-8')
    print(proc.stdout, flush=True)
    if not xml_path.is_file():
        raise RuntimeError(f'{label}: no JUnit result; not test evidence (exit {proc.returncode})')
    cases = ET.parse(xml_path).findall('.//testcase')
    failures = [case.find('failure') for case in cases if case.find('failure') is not None]
    errors = [case for case in cases if case.find('error') is not None]
    identity = lambda c: f"{c.get('classname')}::{c.get('name')}"
    failed_ids = sorted(identity(c) for c in cases if c.find('failure') is not None)
    skipped_ids = sorted(identity(c) for c in cases if c.find('skipped') is not None)
    result = {'label': label, 'command': command, 'exit_code': proc.returncode,
              'tests': len(cases), 'failures': len(failures), 'errors': len(errors), 'skipped': len(skipped_ids),
              'failed_ids': failed_ids, 'skipped_ids': skipped_ids,
              'collected_ids': sorted(identity(c) for c in cases)}
    RESULTS.append(result)
    if errors or len(cases) <= len(skipped_ids):
        raise RuntimeError(f'{label}: collection errors or no executed tests')
    if exact_count is not None and (len(cases) != exact_count or skipped_ids):
        raise RuntimeError(f'{label}: unexpected test count or skips')
    if expected_failure:
        if proc.returncode != 1 or not failures:
            raise RuntimeError(f'{label}: not the required RED result')
        if not all('AssertionError' in (f.text or '') or 'Failed: DID NOT RAISE' in (f.text or '') for f in failures):
            raise RuntimeError(f'{label}: failure was not the designated behavioral assertion')
    elif record_baseline:
        if proc.returncode not in (0, 1) or (proc.returncode == 1 and not failures):
            raise RuntimeError(f'{label}: infrastructure failure is not a comparable baseline')
    elif proc.returncode != 0 or failures:
        raise RuntimeError(f'{label}: positive control failed')
    print(json.dumps({k:v for k,v in result.items() if not k.endswith('_ids')}), flush=True)
    return result


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
    baseline_results = []
    comparisons = []
    try:
        run('red', TEST, expected_failure=True, exact_count=17)
        subprocess.run([sys.executable, '.n53-verification/apply_candidate.py'], check=True)
        candidate = SOURCE_PATH.read_bytes()
        (OUT / 'candidate_update_cmd_windows.py').write_bytes(candidate)
        run('green', TEST, exact_count=17)
        for name, symbol, before, after, test in MUTANTS:
            try:
                SOURCE_PATH.write_bytes(mutate(candidate.decode('utf-8'), symbol, before, after).encode('utf-8'))
                run(f'mutant-{name}', f'{TEST}::{test}', expected_failure=True, exact_count=1)
            finally:
                SOURCE_PATH.write_bytes(candidate)
        run('post-mutation-green', TEST, exact_count=17)
        SOURCE_PATH.write_bytes(baseline)
        for i, target in enumerate(REGRESSION):
            baseline_results.append(run(f'baseline-regression-{i}', target, record_baseline=True))
        SOURCE_PATH.write_bytes(candidate)
        for i, target in enumerate(REGRESSION):
            before = baseline_results[i]
            after = run(f'candidate-regression-{i}', target, record_baseline=True)
            same_collection = before['collected_ids'] == after['collected_ids']
            new_failures = sorted(set(after['failed_ids']) - set(before['failed_ids']))
            new_skips = sorted(set(after['skipped_ids']) - set(before['skipped_ids']))
            comparison = {'file': target, 'same_collection': same_collection,
                          'baseline_failures': before['failed_ids'], 'candidate_failures': after['failed_ids'],
                          'new_failures': new_failures, 'new_skips': new_skips}
            comparisons.append(comparison)
            if not same_collection or new_failures or new_skips:
                raise RuntimeError(f'New regression or coverage loss: {comparison}')
        for i, target in enumerate(LIVE):
            run(f'live-{i}', target)
        run('final-green', TEST, exact_count=17)
        subprocess.run(['git', 'diff', '--check'], check=True)
        (OUT / 'VERIFIED').write_text(hashlib.sha256(candidate).hexdigest() + '\n', encoding='ascii')
        if any(r['failed_ids'] for r in baseline_results):
            (OUT / 'PREEXISTING_FAILURES.json').write_text(json.dumps(comparisons, indent=2) + '\n', encoding='utf-8')
    finally:
        if candidate is not None:
            SOURCE_PATH.write_bytes(candidate)
        receipt = {'scope': 'Native Windows imports; fake OS effects in contracts; baseline-relative selected regression, NOT a full-suite pass',
                   'baseline_blob': 'd1f602f41c41e9e752a3af3067e79cf6c6f7f6e6',
                   'candidate_sha256': hashlib.sha256(candidate).hexdigest() if candidate else None,
                   'regression_comparisons': comparisons, 'results': RESULTS}
        (OUT / 'results.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
        diff = subprocess.run(['git', 'diff', '--', 'hermes_cli/update_cmd_windows.py'], capture_output=True, text=True, encoding='utf-8')
        (OUT / 'candidate.patch').write_text(diff.stdout, encoding='utf-8')
        for path in REGRESSION:
            (OUT / Path(path).name).write_bytes((ROOT / path).read_bytes())


if __name__ == '__main__':
    main()

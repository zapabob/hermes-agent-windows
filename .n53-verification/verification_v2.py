"""Prepare current-platform contracts and the additional SCM RED/GREEN cases.

Verification branch only. Never imports the product module or contacts a service.
The product patch builder still refuses any blob other than the reviewed baseline.
"""
import ast
from pathlib import Path

NOT_ATTEMPTED = '''class _WindowsGatewayServiceStopNotAttempted(RuntimeError):
    """SCM discovery/identity validation failed before sending any stop request."""


'''


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise RuntimeError(f"Ambiguous source transformation: {before!r}")
    return text.replace(before, after, 1)


def harden_services(source):
    nodes = {n.name: n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
    lines = source.splitlines(keepends=True)
    changes = []
    for name in ('_stop_windows_gateway_service', '_pause_windows_gateway_services', '_wait_for_windows_update_gateway_exit'):
        node = nodes[name]
        part = ''.join(lines[node.lineno - 1:node.end_lineno])
        if name == '_stop_windows_gateway_service':
            part = NOT_ATTEMPTED + replace_once(part,
                '    psutil, service = _win_service(name)\n    _verify_service_identities(psutil, name, service, expected_service_identity, expected_gateway_identity)\n',
                '    try:\n        psutil, service = _win_service(name)\n        _verify_service_identities(psutil, name, service, expected_service_identity, expected_gateway_identity)\n'
                '    except Exception as exc:\n'
                '        # No stop was sent: do not start a concurrently stopped/replaced service.\n'
                '        raise _WindowsGatewayServiceStopNotAttempted(str(exc)) from exc\n')
        elif name == '_pause_windows_gateway_services':
            part = replace_once(part,
                '''            current_service_name = str(service.name)
            _stop_windows_gateway_service(
                current_service_name, expected_processes=tuple(getattr(service, "descendant_identities", ())),
                expected_service_identity=(int(service.service_pid), float(service.service_create_time)),
                expected_gateway_identity=(int(service.gateway_pid), float(service.gateway_create_time)),
            )''',
                '''            # Preparing arguments is not a stop attempt.
            name = str(service.name)
            expected_processes = tuple(getattr(service, "descendant_identities", ()))
            expected_service_identity = (int(service.service_pid), float(service.service_create_time))
            expected_gateway_identity = (int(service.gateway_pid), float(service.gateway_create_time))
            current_service_name = name
            _stop_windows_gateway_service(
                current_service_name, expected_processes=expected_processes,
                expected_service_identity=expected_service_identity,
                expected_gateway_identity=expected_gateway_identity,
            )''')
            part = replace_once(part,
                '        restore_names = ([current_service_name] if current_service_name else []) + list(reversed(paused_services))',
                '        restore_current = current_service_name and not isinstance(exc, _WindowsGatewayServiceStopNotAttempted)\n'
                '        restore_names = ([current_service_name] if restore_current else []) + list(reversed(paused_services))')
        else:
            part = replace_once(part, '        except Exception:\n            return False',
                '        except Exception:\n            # Inspection failure is not proof of death.\n            return True')
        changes.append((node.lineno - 1, node.end_lineno, part))
    for first, last, part in sorted(changes, reverse=True):
        lines[first:last] = [part]
    result = ''.join(lines)
    ast.parse(result)
    return result


EXTRA_TESTS = '''

def test_discovered_incarnation_change_refuses_before_pause(rig):
    rig.procs[101].create_time = 1.01
    rig.process_times[101] = 99.0
    with pytest.raises(RuntimeError, match="identity changed"):
        rig.call()
    assert not any(e[0] in {"pause", "marker", "kill", "SCM"} for e in rig.trace)


@pytest.fixture
def scm(monkeypatch):
    from gateway import status as status_mod
    from hermes_cli import update_cmd, update_cmd_windows as windows
    ns = vars(windows)
    r = types.SimpleNamespace(states={"HermesAlpha": "running", "HermesBeta": "stopped"}, trace=[],
                              inspect_error=False, uncertain_stop=False, exists=lambda pid: True)
    specs = {
        "HermesAlpha": types.SimpleNamespace(name="HermesAlpha", profile="alpha", service_pid=301,
             gateway_pid=101, service_create_time=3.01, gateway_create_time=1.01,
             descendant_identities=((101, 1.01),)),
        "HermesBeta": types.SimpleNamespace(name="HermesBeta", profile="beta", service_pid=302,
             gateway_pid=202, service_create_time=3.02, gateway_create_time=2.02,
             descendant_identities=((202, 2.02),)),
    }

    def win_service(name):
        if r.inspect_error:
            raise PermissionError("SCM access denied before stop")
        process = types.SimpleNamespace(parents=lambda: [types.SimpleNamespace(pid=301), types.SimpleNamespace(pid=302)])
        psutil = types.SimpleNamespace(Process=lambda pid: process)
        service = types.SimpleNamespace(status=lambda: r.states[name], pid=lambda: specs[name].service_pid)
        return psutil, service

    def control(verb, name, service, settled):
        r.trace.append(("control", verb, name))
        r.states[name] = settled
        if r.uncertain_stop:
            raise TimeoutError("SCM reply lost after stop")

    def restore(name):
        r.trace.append(("restore", name))
        r.states[name] = "running"

    for name, fn in {
        "_win_service": win_service,
        "_sc_exe": control,
        "_poll_until": lambda predicate, *args: predicate(),
        "_original_process_is_alive": lambda *args: False,
        "_process_create_time": lambda psutil, pid, label: {301:3.01,302:3.02,101:1.01,202:2.02}[pid],
        "_resume_windows_gateways_after_update": lambda token: r.trace.append(("ordinary",)),
    }.items():
        monkeypatch.setattr(windows, name, fn)
    monkeypatch.setattr(update_cmd, "_restore_windows_gateway_service", restore)
    monkeypatch.setattr(status_mod, "_pid_exists", lambda pid: r.exists(pid))
    r.ns = ns
    r.specs = specs
    r.pause = lambda services, token=None: windows._pause_windows_gateway_services(
        [specs[name] for name in services], token or {"resume_needed":True, "profiles":{}, "unmapped":[]},
        (token or {}).get("profiles",{}), [])
    return r


def test_pre_stop_identity_refusal_never_starts_untouched_service(scm):
    with pytest.raises(RuntimeError, match="not stably running"):
        scm.pause(["HermesBeta"])
    assert scm.states["HermesBeta"] == "stopped"
    assert not scm.trace


def test_pre_stop_access_denied_never_restores_unattempted_service(scm):
    scm.inspect_error = True
    with pytest.raises(RuntimeError, match="access denied"):
        scm.pause(["HermesBeta"])
    assert not scm.trace


def test_refusal_on_second_service_restores_only_first_service(scm):
    with pytest.raises(RuntimeError, match="not stably running"):
        scm.pause(["HermesAlpha", "HermesBeta"])
    assert scm.trace == [("control","stop","HermesAlpha"), ("restore","HermesAlpha")]
    assert scm.states == {"HermesAlpha":"running", "HermesBeta":"stopped"}


def test_uncertain_actual_stop_still_restores_current_service(scm):
    scm.uncertain_stop = True
    with pytest.raises(RuntimeError, match="reply lost"):
        scm.pause(["HermesAlpha"])
    assert scm.trace == [("control","stop","HermesAlpha"), ("restore","HermesAlpha")]
    assert scm.states["HermesAlpha"] == "running"


def test_scm_refusal_still_recovers_previously_paused_ordinary_gateways_once(scm):
    token = {"resume_needed":True, "profiles":{"alpha":101}, "unmapped":[]}
    with pytest.raises(RuntimeError, match="not stably running"):
        scm.pause(["HermesBeta"], token)
    assert scm.trace.count(("ordinary",)) == 1


def test_malformed_service_arguments_never_start_unattempted_service(scm):
    scm.specs["HermesBeta"].service_pid = "unreadable"
    with pytest.raises(RuntimeError):
        scm.pause(["HermesBeta"])
    assert not scm.trace


def test_drain_inspection_denied_is_not_reported_dead(scm):
    def denied(pid):
        raise PermissionError("access denied")
    scm.exists = denied
    assert scm.ns["_wait_for_windows_update_gateway_exit"]([101], timeout=0) == {101}


def test_drain_known_dead_stays_excluded(scm):
    scm.exists = lambda pid: False
    assert scm.ns["_wait_for_windows_update_gateway_exit"]([101], timeout=0) == set()


def test_drain_known_live_remains_a_survivor(scm):
    assert scm.ns["_wait_for_windows_update_gateway_exit"]([101], timeout=0) == {101}
'''

NEW_MUTANTS = [
 ('ignore_discovered_incarnation', '_pause_windows_gateways_for_update', 'if discovered_time > 0.0 and abs(float(start_times[int(pid)]) - discovered_time) > 0.001:', 'if False and discovered_time > 0.0:', 'test_discovered_incarnation_change_refuses_before_pause'),
 ('restore_unattempted_service', '_pause_windows_gateway_services', 'current_service_name and not isinstance(exc, _WindowsGatewayServiceStopNotAttempted)', 'current_service_name', 'test_pre_stop_identity_refusal_never_starts_untouched_service'),
 ('lose_uncertain_service_stop', '_pause_windows_gateway_services', 'current_service_name and not isinstance(exc, _WindowsGatewayServiceStopNotAttempted)', 'False', 'test_uncertain_actual_stop_still_restores_current_service'),
 ('lose_previously_stopped_service', '_pause_windows_gateway_services', 'list(reversed(paused_services))', '[]', 'test_refusal_on_second_service_restores_only_first_service'),
 ('forget_ordinary_after_scm_refusal', '_pause_windows_gateway_services', 'if profiles or unmapped:', 'if False and (profiles or unmapped):', 'test_scm_refusal_still_recovers_previously_paused_ordinary_gateways_once'),
 ('unknown_liveness_means_dead', '_wait_for_windows_update_gateway_exit', '# Inspection failure is not proof of death.\n            return True', '# Mutation: conflate unknown and dead.\n            return False', 'test_drain_inspection_denied_is_not_reported_dead'),
]


def main():
    root = Path.cwd().resolve()
    test = root / 'tests/hermes_cli/test_windows_update_pause_transaction.py'
    source = replace_once(test.read_text(encoding='utf-8'), 'pytestmark = pytest.mark.windows_only',
                          'pytestmark = pytest.mark.platforms("windows")') + EXTRA_TESTS
    ast.parse(source)
    test.write_bytes(source.encode('utf-8'))

    builder = root / '.n53-verification/apply_candidate.py'
    text = builder.read_text(encoding='utf-8')
    text = replace_once(text, 'import ast\n', 'import ast\nfrom verification_v2 import harden_services\n')
    text = replace_once(text, '    return candidate\n', '    return harden_services(candidate)\n')
    text = replace_once(text,
        '        raise RuntimeError("Windows gateway process identity is unavailable before pause")\n',
        '        raise RuntimeError("Windows gateway process identity is unavailable before pause")\n'
        '    for pid in mapped_pids:\n'
        '        discovered_time = float(getattr(profile_processes[pid], "create_time", 0.0) or 0.0)\n'
        '        if discovered_time > 0.0 and abs(float(start_times[int(pid)]) - discovered_time) > 0.001:\n'
        '            raise RuntimeError("Windows gateway process identity changed since discovery; no gateways were paused")\n')
    ast.parse(text)
    builder.write_bytes(text.encode('utf-8'))

    verifier = root / '.n53-verification/verify.py'
    text = verifier.read_text(encoding='utf-8').replace('exact_count=17', 'exact_count=27')
    text = replace_once(text, 'RESULTS = []', 'MUTANTS += ' + repr(NEW_MUTANTS) + '\nRESULTS = []')
    text = replace_once(text, "    OUT.mkdir(exist_ok=True)\n", "    OUT.mkdir(exist_ok=True)\n    (OUT / 'native_contract_tests.py').write_bytes((ROOT / TEST).read_bytes())\n")
    ast.parse(text)
    verifier.write_bytes(text.encode('utf-8'))
    print('Prepared 27 native-import contracts and 16 targeted mutation gates; baseline product is unchanged.')


if __name__ == '__main__':
    main()

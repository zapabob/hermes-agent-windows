"""Strengthen two old fake-process fixtures; run identical fixtures on both trees."""
import ast
import hashlib
import json
from pathlib import Path

from verification_v2 import replace_once

EXPECTED = {
    'test_update_concurrent_quarantine.py': 'f3b9d4efd193719f62d7220ec20c28689ceb2af8',
    'test_windows_gateway_cold_start_desktop_lifecycle.py': '64fc4367961de0e7179980cfe605d5acee215b2f',
}


def main():
    out = Path('n53-evidence')
    out.mkdir(exist_ok=True)
    receipts = []
    for name, expected in EXPECTED.items():
        path = Path('tests/hermes_cli') / name
        raw = path.read_bytes()
        blob = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
        if blob != expected:
            raise RuntimeError(f'Fixture changed: {name}: {blob}')
        (out / ('original-' + name)).write_bytes(raw)
        text = raw.decode('utf-8')
        if name == 'test_update_concurrent_quarantine.py':
            text = replace_once(text,
                '        profile="default", path=profile_home, pid=worker_pid\n',
                '        profile="default", path=profile_home, pid=worker_pid, create_time=float(worker_pid)\n')
            text = replace_once(text,
                '    drained_dead: set[int] = set()\n',
                '    drained_dead: set[int] = set()\n'
                '    # Invented PIDs must carry a real-shaped incarnation, not probe the CI host.\n'
                '    monkeypatch.setattr(\n'
                '        status_mod, "get_process_start_time",\n'
                '        lambda pid: None if int(pid) in drained_dead else float(pid),\n'
                '    )\n')
            text = replace_once(text,
                '        lambda pid, force=False, **kwargs: terminated.append(int(pid)),\n',
                '        lambda pid, force=False, **kwargs: terminated.append(\n'
                '            (int(pid), kwargs.get("expected_start_time"))),\n')
            text = replace_once(text, '    assert terminated == [launcher_pid]\n',
                '    assert terminated == [(launcher_pid, float(launcher_pid))]\n')
        else:
            text = replace_once(text,
                '    beta = SimpleNamespace(pid=777, profile="beta")\n',
                '    beta = SimpleNamespace(pid=777, profile="beta", path=homes["beta"], create_time=7.77)\n'
                '    import gateway.status as status_mod\n'
                '    original_start_time = status_mod.get_process_start_time\n'
                '    monkeypatch.setattr(\n'
                '        status_mod, "get_process_start_time",\n'
                '        lambda pid: 7.77 if int(pid) == 777 else original_start_time(pid),\n'
                '    )\n')
        ast.parse(text)
        modified = text.encode('utf-8')
        path.write_bytes(modified)
        receipts.append({'path': path.as_posix(), 'original_blob': blob,
                         'same_source_for_baseline_and_candidate': True,
                         'candidate_sha256': hashlib.sha256(modified).hexdigest()})
    (out / 'fixture-source-receipt.json').write_text(json.dumps(receipts, indent=2) + '\n', encoding='utf-8')
    print('Prepared explicit process identities in both baseline and candidate regression fixtures; no assertion removed.')


if __name__ == '__main__':
    main()

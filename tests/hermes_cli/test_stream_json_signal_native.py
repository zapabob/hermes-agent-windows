"""Native self-SIGINT from a real provider worker through the public CLI sink."""
import json
import os
from pathlib import Path
import subprocess
import sys

from tests.hermes_cli.test_stream_json_native import _PUBLIC_SCRIPT


def test_public_worker_self_sigint_preserves_terminal_jsonl(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path / '所有 signal profile'
    workspace = tmp_path / '所有 signal workspace'
    home.mkdir()
    workspace.mkdir()
    (home / 'config.yaml').write_text(
        'model:\n  default: fixture-f11\n  context_length: 131072\n  max_tokens: 256\n'
        'compression:\n  enabled: false\napprovals:\n  single_query_mode: deny\n',
        encoding='utf-8',
    )
    script = _PUBLIC_SCRIPT
    changes = [
        ('calls = []\n', 'calls = []\nsignal_observations = []\nowned_instances = []\n'),
        ('    calls.append(copy.deepcopy(kwargs))\n',
         '    calls.append(copy.deepcopy(kwargs))\n'
         '    if case == "native-worker-sigint":\n'
         '        import signal\n'
         '        assert threading.current_thread() is not threading.main_thread()\n'
         '        handler = signal.getsignal(signal.SIGINT)\n'
         '        assert callable(handler) and handler.__name__ == "_signal_handler_q"\n'
         '        signal_observations.append({"thread": threading.current_thread().name, "handler": handler.__qualname__})\n'
         '        signal.raise_signal(signal.SIGINT)\n'),
        ('class OwnedCLI:\n    def __init__(self, **kwargs):\n',
         'class OwnedCLI:\n    def __init__(self, **kwargs):\n        owned_instances.append(self)\n'),
        ('db.close()\n',
         'for owned in owned_instances:\n'
         '    if owned.agent is not None:\n'
         '        owned.agent.close()\n'
         'db.close()\n'),
        ("'calls':len(calls),'network_attempts':len(network_attempts),",
         "'calls':len(calls),'network_attempts':len(network_attempts),'denied_attempts':network_attempts,'signal_observations':signal_observations,"),
    ]
    for before, after in changes:
        assert script.count(before) == 1, before
        script = script.replace(before, after, 1)
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT'}}
    env.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
               TEMP=str(home), TMP=str(home), PYTHONPATH=str(root),
               PYTHONUTF8='1', PYTHONIOENCODING='utf-8', TERMINAL_CWD=str(workspace))
    result = subprocess.run([sys.executable, '-c', script, 'native-worker-sigint'],
                            cwd=workspace, env=env, capture_output=True,
                            encoding='utf-8', timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    (home / 'signal-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = [json.loads(line) for line in report['stdout'].splitlines()]
    terminal = [row for row in rows if row['type'] == 'result']
    assert len(terminal) == 1 and rows[-1] is terminal[0]
    assert report['exit_code'] == terminal[0]['exit_code'] == 130
    assert terminal[0]['error'] == 'Interrupted'
    assert report['calls'] == 1
    assert report['network_attempts'] == len(report['denied_attempts'])
    assert len(report['signal_observations']) == 1
    observed = report['signal_observations'][0]
    assert observed['thread'] != 'MainThread'
    assert observed['handler'].endswith('_signal_handler_q')

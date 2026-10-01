"""Public pre-agent failure envelope through an owned empty session store."""
import json
import os
from pathlib import Path
import subprocess
import sys

from tests.hermes_cli.test_stream_json_native import _PUBLIC_SCRIPT


def test_public_empty_resume_latest_keeps_jsonl_stdout(tmp_path):
    root = Path(__file__).resolve().parents[2]
    home = tmp_path/'所有 empty history'
    workspace = tmp_path/'所有 workspace'
    home.mkdir()
    workspace.mkdir()
    (home/'config.yaml').write_text(
        'model:\n  default: fixture-f11\n  context_length: 131072\n  max_tokens: 256\n'
        'compression:\n  enabled: false\napprovals:\n  single_query_mode: deny\n', encoding='utf-8')
    source = "argv=['chat','-q',query,'--quiet','--ignore-rules']"
    assert _PUBLIC_SCRIPT.count(source) == 1
    script = _PUBLIC_SCRIPT.replace(source, source[:-1]+",'--resume','latest']", 1)
    environment = {k:v for k,v in os.environ.items() if k.upper() in
                   {'SYSTEMROOT','WINDIR','COMSPEC','PATH','PATHEXT'}}
    environment.update(HERMES_HOME=str(home), HOME=str(home), USERPROFILE=str(home),
                       TEMP=str(home), TMP=str(home), PYTHONPATH=str(root),
                       PYTHONUTF8='1', PYTHONIOENCODING='utf-8', TERMINAL_CWD=str(workspace))
    outcome = subprocess.run([sys.executable,'-c',script,'credentials-fail'],
                             cwd=workspace,env=environment,capture_output=True,
                             encoding='utf-8',timeout=90)
    assert outcome.returncode == 0, outcome.stdout+outcome.stderr
    envelope = json.loads(outcome.stdout)
    assert envelope['calls'] == 0 and envelope['exit_code'] == 1
    rows = [json.loads(line) for line in envelope['stdout'].splitlines()]
    assert [row['type'] for row in rows] == ['system','result']
    assert rows[0]['subtype'] == 'init' and rows[-1]['exit_code'] == 1
    assert 'No previous' in envelope['stderr']

"""Owned real-config helpers; copied unchanged from sealed T06e fixture methods."""
import copy
import os
from pathlib import Path
import yaml
import pytest
from hermes_cli import config as config_owner
from hermes_constants import get_hermes_home
from tests.gateway.test_approval_decision_ownership import until
from tests.gateway.test_queued_followup_processing_hooks import SESSION_KEY
from tools import approval


def seed_owned_config(tmp_path, *, existing=False):
    root = Path(os.environ['STEER_OWNED_ROOT']).resolve()
    home = get_hermes_home().resolve()
    assert home.is_relative_to(root), 'config must stay inside the owned Job'
    seed = {
        'model': {'default': 'owned-permanent-proof'},
        'terminal': {'cwd': str(tmp_path)},
        'display': {'tool_progress': False},
        'command_allowlist': ['owned-existing-consent'] if existing else [],
    }
    config_owner.save_config(copy.deepcopy(seed), strip_defaults=False)
    approval.load_permanent(set(seed['command_allowlist']))
    return home / 'config.yaml', seed



def read_owned_config(path, seed):
    disk = yaml.safe_load(path.read_text(encoding='utf-8'))
    readback = config_owner.load_config()
    for key in ('model', 'terminal', 'display'):
        for field, value in seed[key].items():
            assert disk[key][field] == readback[key][field] == value, (key, field)
    assert set(disk['command_allowlist']) == set(readback['command_allowlist'])
    return set(disk['command_allowlist'])



async def pending(task):
    await until(lambda: bool(approval._gateway_queues.get(SESSION_KEY)) or task.done())
    assert not task.done(), 'real Gateway caller bypassed the approval queue'
    return approval._gateway_queues[SESSION_KEY][0]



def resolve(entry, choice):
    assert approval.resolve_gateway_approval(
        SESSION_KEY, choice, request_id=entry.data['request_id'],
    ) == 1
    assert entry.result == choice



@pytest.fixture(autouse=True)
def owned_config_scope(_hermetic_environment, tmp_path, monkeypatch):
    """Use pytest's already-isolated HOME when no outer owned Job supplies one."""
    if not os.environ.get('STEER_OWNED_ROOT'):
        assert get_hermes_home().resolve().is_relative_to(tmp_path.resolve())
        monkeypatch.setenv('STEER_OWNED_ROOT', str(tmp_path.resolve()))

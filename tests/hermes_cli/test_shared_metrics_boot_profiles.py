"""Real startup consent reconciliation with isolated config and SQLite."""
import pytest
from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from hermes_cli.observability import relay_shared_metrics as runtime
from hermes_cli.observability.shared_metrics import SharedMetricsStore
from hermes_cli.observability.shared_metrics_sender import reconcile_send_consent
from hermes_cli.sqlite_util import write_txn

@pytest.mark.parametrize('existing', [False, True])
def test_disabled_boot_does_not_create_store_but_closes_existing_consent(tmp_path, monkeypatch, existing):
    home = tmp_path / 'profile'
    home.mkdir()
    (home / 'config.yaml').write_text('telemetry:\n  shared_metrics:\n    enabled: false\n    send: false\n', encoding='utf-8')
    token = set_hermes_home_override(home)
    monkeypatch.setattr(runtime, '_consent_reconcile_done', set())
    try:
        if existing:
            store = SharedMetricsStore()
            with store._connection() as connection:
                with write_txn(connection):
                    reconcile_send_consent(connection, True)
        runtime._reconcile_send_consent_once()
        if existing:
            with store._connection() as connection:
                assert connection.execute('SELECT COUNT(*) FROM send_consent_windows WHERE closed_at IS NULL').fetchone()[0] == 0
        else:
            assert not (home / 'telemetry').exists()
    finally:
        reset_hermes_home_override(token)


def test_boot_reconciles_each_profile_in_same_process(tmp_path, monkeypatch):
    stores = []
    homes = [tmp_path / 'one', tmp_path / 'two']
    for home in homes:
        home.mkdir()
        (home / 'config.yaml').write_text('telemetry:\n  shared_metrics:\n    enabled: false\n    send: false\n', encoding='utf-8')
        token = set_hermes_home_override(home)
        try:
            store = SharedMetricsStore()
            with store._connection() as connection:
                with write_txn(connection):
                    reconcile_send_consent(connection, True)
            stores.append(store)
        finally:
            reset_hermes_home_override(token)
    monkeypatch.setattr(runtime, '_consent_reconcile_done', set())
    remaining = []
    for home, store in zip(homes, stores):
        token = set_hermes_home_override(home)
        try:
            runtime._reconcile_send_consent_once()
            with store._connection() as connection:
                remaining.append(connection.execute('SELECT COUNT(*) FROM send_consent_windows WHERE closed_at IS NULL').fetchone()[0])
        finally:
            reset_hermes_home_override(token)
    assert remaining == [0, 0], remaining


def test_failed_read_can_retry_without_marking_profile_done(tmp_path, monkeypatch):
    from hermes_cli import config
    from hermes_constants import hermes_home_key

    home = tmp_path / 'retry'
    home.mkdir()
    (home / 'config.yaml').write_text('telemetry:\n  shared_metrics:\n    enabled: false\n    send: false\n', encoding='utf-8')
    original = config.read_raw_config_readonly
    calls = []
    def read():
        calls.append(True)
        if len(calls) == 1:
            raise OSError('synthetic temporary read failure')
        return original()
    monkeypatch.setattr(config, 'read_raw_config_readonly', read)
    monkeypatch.setattr(runtime, '_consent_reconcile_done', set())
    token = set_hermes_home_override(home)
    try:
        runtime._reconcile_send_consent_once()
        assert hermes_home_key() not in runtime._consent_reconcile_done
        runtime._reconcile_send_consent_once()
        assert hermes_home_key() in runtime._consent_reconcile_done
        runtime._reconcile_send_consent_once()
        assert len(calls) == 2
        assert not (home / 'telemetry').exists()
    finally:
        reset_hermes_home_override(token)

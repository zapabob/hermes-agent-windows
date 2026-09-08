"""Real telemetry worker and profile config reader; sender boundary intercepted."""
import threading
import pytest
from types import SimpleNamespace
from hermes_constants import set_hermes_home_override, reset_hermes_home_override, get_hermes_home
from hermes_cli.observability.relay_shared_metrics import _Runtime
from hermes_cli.observability import shared_metrics_sender
from hermes_cli.observability.shared_metrics import SharedMetricsStore


@pytest.mark.parametrize('caller_profile', ['worker', 'default'])
def test_send_thread_preserves_profile_consent_context(tmp_path, monkeypatch, caplog, caller_profile):
    default = tmp_path / 'default'
    worker = tmp_path / 'worker'
    for home, sending in ((default, 'false'), (worker, 'true')):
        home.mkdir()
        (home / 'config.yaml').write_text(
            'telemetry:\n  shared_metrics:\n    enabled: true\n    send: ' + sending + '\n', encoding='utf-8')
    monkeypatch.setenv('HERMES_HOME', str(default))
    observations = []
    class CaptureSender:
        def __init__(self, store, endpoint, *, consent_check):
            self.check = consent_check
        def send_pending(self):
            observations.append((get_hermes_home(), self.check()))
            (worker / 'config.yaml').write_text(
                'telemetry:\n  shared_metrics:\n    enabled: true\n    send: false\n', encoding='utf-8')
            observations.append((get_hermes_home(), self.check()))
    monkeypatch.setattr(shared_metrics_sender, 'SharedMetricsSender', CaptureSender)
    runtime = object.__new__(_Runtime)
    runtime._profile_home = worker
    runtime._send_lock = threading.RLock()
    runtime._send_thread = None
    runtime.subscriber = SimpleNamespace(store=SharedMetricsStore(database_path=worker / 'metrics.sqlite3', outbox_directory=worker / 'outbox'))

    calling_home = worker if caller_profile == 'worker' else default
    token = set_hermes_home_override(calling_home)
    try:
        runtime._send_exported_packages()
        assert runtime._send_thread is not None
        runtime._send_thread.join(timeout=5)
        assert not runtime._send_thread.is_alive()
        assert not [r for r in caplog.records if r.levelno >= 30], caplog.text
        assert observations == [(worker, True), (worker, False)], observations
        assert get_hermes_home() == calling_home
    finally:
        reset_hermes_home_override(token)
        if runtime._send_thread is not None:
            runtime._send_thread.join(timeout=5)

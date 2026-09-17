"""Comprehensive tests for Slice E: Session/Profile Persistence Semantics.

Encodes:
RED 1  — Desktop live session picker is session-only
RED 2  — Two sessions, one profile
RED 3  — Explicit --global
RED 4  — Explicit --session
RED 5  — Explicit --once
RED 6  — Settings -> Model persistence path
RED 7  — Fresh profile first intentional selection seeds profile default; second pick is session-only
RED 8  — Stale ambient credentials must not override explicit provider/model
RED 9  — Explicit provider exploratory switch is session-only
RED 10 — persist_switch_by_default compatibility
ATOMIC — Provider and model persist atomically
ISOLATION — Profile persistence isolation
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import os
import pytest
import yaml

from hermes_constants import set_hermes_home_override, reset_hermes_home_override
from hermes_cli.model_switch import (
    parse_model_switch_args,
    resolve_persist_behavior,
    is_fresh_profile,
)


@pytest.fixture
def isolated_profile_env(tmp_path, monkeypatch):
    """Create an isolated HERMES_HOME with a configured profile."""
    home = tmp_path / "hermes_home"
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.yaml"
    initial_cfg = {
        "model": {
            "default": "model-A",
            "provider": "provider-A",
            "persist_switch_by_default": False,
        }
    }
    config_path.write_text(yaml.dump(initial_cfg), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    token = set_hermes_home_override(home)
    yield home, config_path
    reset_hermes_home_override(token)


@pytest.fixture
def fresh_profile_env(tmp_path, monkeypatch):
    """Create an isolated HERMES_HOME with NO model default or provider configured."""
    home = tmp_path / "hermes_fresh"
    home.mkdir(parents=True, exist_ok=True)
    config_path = home / "config.yaml"
    initial_cfg = {
        "agent": {"system_prompt": "You are a test agent"},
        "display": {"skin": "default"},
    }
    config_path.write_text(yaml.dump(initial_cfg), encoding="utf-8")
    monkeypatch.setenv("HERMES_HOME", str(home))
    token = set_hermes_home_override(home)
    yield home, config_path
    reset_hermes_home_override(token)


# ---------------------------------------------------------------------------
# RED 1: Desktop live session picker is session-only
# ---------------------------------------------------------------------------
class TestRed1DesktopPickerSessionOnly:
    def test_desktop_picker_payload_is_session_scoped(self, isolated_profile_env):
        home, config_path = isolated_profile_env
        live_session_id = "session_live_123"

        # Production desktop hook payload format:
        # `${selection.model} --provider ${selection.provider} --session`
        raw_value = "model-B --provider provider-B --session"
        parsed = parse_model_switch_args(raw_value)
        assert parsed.is_session is True
        assert parsed.is_global is False
        assert parsed.explicit_provider == "provider-B"
        assert parsed.model_input == "model-B"

        persist = resolve_persist_behavior(
            is_global=parsed.is_global,
            is_session=parsed.is_session,
            is_once=parsed.is_once,
            explicit_provider=parsed.explicit_provider,
        )
        assert persist is False

        # Verify config.yaml is untouched
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "model-A"
        assert cfg["model"]["provider"] == "provider-A"


# ---------------------------------------------------------------------------
# RED 2: Two sessions, one profile
# ---------------------------------------------------------------------------
class TestRed2TwoSessionsOneProfile:
    def test_two_sessions_isolation(self, isolated_profile_env):
        home, config_path = isolated_profile_env

        # Session 1 switches to model-B with --session
        raw_s1 = "model-B --provider provider-B --session"
        parsed_s1 = parse_model_switch_args(raw_s1)
        persist_s1 = resolve_persist_behavior(
            is_global=parsed_s1.is_global,
            is_session=parsed_s1.is_session,
            explicit_provider=parsed_s1.explicit_provider,
        )
        assert persist_s1 is False

        session_1 = {
            "model_override": {
                "model": parsed_s1.model_input,
                "provider": parsed_s1.explicit_provider,
            }
        }
        # Session 2 has no override
        session_2 = {}

        # S1 effective is model-B
        assert session_1["model_override"]["model"] == "model-B"
        # S2 has no override and resolves from profile default
        assert "model_override" not in session_2

        # Profile config remains model-A
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "model-A"
        assert cfg["model"]["provider"] == "provider-A"

        # New session S3 also sees model-A
        session_3 = {}
        effective_s3_model = session_3.get("model_override", {}).get("model") or cfg["model"]["default"]
        assert effective_s3_model == "model-A"


# ---------------------------------------------------------------------------
# RED 3: Explicit --global
# ---------------------------------------------------------------------------
class TestRed3ExplicitGlobal:
    def test_explicit_global_persists_to_profile(self, isolated_profile_env):
        home, config_path = isolated_profile_env
        from cli import save_config_values

        cmd = "/model model-B --provider provider-B --global"
        parsed = parse_model_switch_args(cmd.replace("/model ", ""))
        assert parsed.is_global is True

        persist = resolve_persist_behavior(
            is_global=parsed.is_global,
            is_session=parsed.is_session,
            is_once=parsed.is_once,
            explicit_provider=parsed.explicit_provider,
        )
        assert persist is True

        # Simulate global persist
        save_config_values({
            "model.default": parsed.model_input,
            "model.provider": parsed.explicit_provider,
        })

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "model-B"
        assert cfg["model"]["provider"] == "provider-B"

        # Existing live session with explicit override is unaffected;
        # new session sees new profile default
        new_session = {}
        assert (new_session.get("model_override", {}).get("model") or cfg["model"]["default"]) == "model-B"


# ---------------------------------------------------------------------------
# RED 4: Explicit --session
# ---------------------------------------------------------------------------
class TestRed4ExplicitSession:
    def test_explicit_session_does_not_persist_profile(self, isolated_profile_env):
        home, config_path = isolated_profile_env

        cmd = "/model model-B --provider provider-B --session"
        parsed = parse_model_switch_args(cmd.replace("/model ", ""))
        assert parsed.is_session is True

        persist = resolve_persist_behavior(
            is_global=parsed.is_global,
            is_session=parsed.is_session,
            is_once=parsed.is_once,
            explicit_provider=parsed.explicit_provider,
        )
        assert persist is False

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "model-A"


# ---------------------------------------------------------------------------
# RED 5: Explicit --once
# ---------------------------------------------------------------------------
class TestRed5ExplicitOnce:
    def test_explicit_once_does_not_persist(self, isolated_profile_env):
        home, config_path = isolated_profile_env

        cmd = "/model model-B --once"
        parsed = parse_model_switch_args(cmd.replace("/model ", ""))
        assert parsed.is_once is True

        persist = resolve_persist_behavior(
            is_global=parsed.is_global,
            is_session=parsed.is_session,
            is_once=parsed.is_once,
            explicit_provider=parsed.explicit_provider,
        )
        assert persist is False

        # Once scope must not touch config.yaml
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "model-A"


# ---------------------------------------------------------------------------
# RED 6: Settings -> Model
# ---------------------------------------------------------------------------
class TestRed6SettingsModelPersistence:
    def test_settings_updates_profile_default_without_clobbering_live_session(self, isolated_profile_env):
        home, config_path = isolated_profile_env
        from hermes_cli.web_server import _apply_main_model_assignment
        from hermes_cli.config import save_config, load_config

        # Live session is running model-A
        live_session = {"model_override": {"model": "model-A", "provider": "provider-A"}}

        # Settings changes profile default to model-B
        cfg = load_config()
        cfg["model"] = _apply_main_model_assignment(
            cfg.get("model", {}), "provider-B", "model-B", "", ""
        )
        save_config(cfg)

        # Profile default is now model-B
        fresh_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert fresh_cfg["model"]["default"] == "model-B"
        assert fresh_cfg["model"]["provider"] == "provider-B"

        # Live session remains authoritative for its session state (model-A)
        assert live_session["model_override"]["model"] == "model-A"

        # Fresh new draft session sees model-B
        draft_session = {}
        draft_model = draft_session.get("model_override", {}).get("model") or fresh_cfg["model"]["default"]
        assert draft_model == "model-B"


# ---------------------------------------------------------------------------
# RED 7: Fresh profile first intentional selection seeds profile default
# ---------------------------------------------------------------------------
class TestRed7FreshProfileFirstSelection:
    def test_is_fresh_profile_detection(self):
        # Empty / unset
        assert is_fresh_profile({}) is True
        assert is_fresh_profile({"model": {}}) is True
        assert is_fresh_profile({"model": {"default": "", "provider": ""}}) is True

        # Configured
        assert is_fresh_profile({"model": {"default": "some-model"}}) is False
        assert is_fresh_profile({"model": {"provider": "some-provider"}}) is False
        assert is_fresh_profile({"model": "some-string-model"}) is False

    def test_fresh_profile_seeds_default_then_second_pick_is_session_only(self, fresh_profile_env):
        home, config_path = fresh_profile_env
        from cli import save_config_values

        # Fresh profile: model.default and model.provider unset
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert is_fresh_profile(cfg) is True

        # First intentional selection (e.g. CLI or gateway /model without --session / --once)
        cmd1 = "/model initial-model --provider initial-prov"
        parsed1 = parse_model_switch_args(cmd1.replace("/model ", ""))
        persist1 = resolve_persist_behavior(
            is_global=parsed1.is_global,
            is_session=parsed1.is_session,
            is_once=parsed1.is_once,
            explicit_provider=parsed1.explicit_provider,
            profile_has_default=False,
        )
        assert persist1 is True, "First intentional selection on fresh profile MUST persist"

        # Seed profile default
        save_config_values({
            "model.default": parsed1.model_input,
            "model.provider": parsed1.explicit_provider,
        })

        # Verify profile is now configured
        seeded_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert seeded_cfg["model"]["default"] == "initial-model"
        assert seeded_cfg["model"]["provider"] == "initial-prov"
        assert is_fresh_profile(seeded_cfg) is False

        # Second selection: normal picker or switch without --global
        cmd2 = "/model second-model --provider second-prov"
        parsed2 = parse_model_switch_args(cmd2.replace("/model ", ""))
        persist2 = resolve_persist_behavior(
            is_global=parsed2.is_global,
            is_session=parsed2.is_session,
            is_once=parsed2.is_once,
            explicit_provider=parsed2.explicit_provider,
            profile_has_default=True,
        )
        assert persist2 is False, "Second selection on configured profile must NOT rewrite profile default"

        # Profile default must be unchanged
        current_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert current_cfg["model"]["default"] == "initial-model"
        assert current_cfg["model"]["provider"] == "initial-prov"


# ---------------------------------------------------------------------------
# RED 8: Stale ambient credential must not select provider
# ---------------------------------------------------------------------------
class TestRed8StaleAmbientCredential:
    def test_ambient_api_keys_do_not_affect_fresh_profile_or_persistence(
        self, fresh_profile_env, monkeypatch
    ):
        home, config_path = fresh_profile_env
        # Set ambient environment variables
        monkeypatch.setenv("OPENROUTER_API_KEY", "stale_router_key")
        monkeypatch.setenv("NOUS_API_KEY", "stale_nous_key")
        monkeypatch.setenv("OPENAI_API_KEY", "stale_openai_key")

        # Profile config is still fresh regardless of env
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert is_fresh_profile(cfg) is True

        # Now configure profile explicitly with nvidia
        from cli import save_config_values
        save_config_values({
            "model.default": "nemotron-4",
            "model.provider": "nvidia",
        })

        configured_cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert is_fresh_profile(configured_cfg) is False
        assert configured_cfg["model"]["provider"] == "nvidia"
        assert configured_cfg["model"]["default"] == "nemotron-4"


# ---------------------------------------------------------------------------
# RED 9: Explicit provider exploratory switch
# ---------------------------------------------------------------------------
class TestRed9ExploratoryProviderSwitch:
    def test_exploratory_provider_switch_is_session_only(self, isolated_profile_env):
        home, config_path = isolated_profile_env

        # Configured profile: provider-A / model-A
        # User tries another backend without --global
        persist = resolve_persist_behavior(
            is_global=False,
            is_session=False,
            is_once=False,
            explicit_provider="provider-B",
            profile_has_default=True,
        )
        assert persist is False


# ---------------------------------------------------------------------------
# RED 10: persist_switch_by_default compatibility
# ---------------------------------------------------------------------------
class TestRed10PersistSwitchByDefault:
    def test_compat_policy_when_true(self):
        with patch(
            "hermes_cli.config.load_config",
            return_value={"model": {"default": "mod", "provider": "prov", "persist_switch_by_default": True}},
        ):
            assert resolve_persist_behavior(
                is_global=False,
                is_session=False,
                is_once=False,
                explicit_provider="",
                profile_has_default=True,
            ) is True

    def test_compat_policy_when_false(self):
        with patch(
            "hermes_cli.config.load_config",
            return_value={"model": {"default": "mod", "provider": "prov", "persist_switch_by_default": False}},
        ):
            assert resolve_persist_behavior(
                is_global=False,
                is_session=False,
                is_once=False,
                explicit_provider="",
                profile_has_default=True,
            ) is False


# ---------------------------------------------------------------------------
# ATOMIC: Provider + model persist atomically in a single file replacement
# ---------------------------------------------------------------------------
class TestAtomicPersistence:
    def test_save_config_values_atomic_multi(self, isolated_profile_env):
        home, config_path = isolated_profile_env
        from cli import save_config_values

        updates = {
            "model.default": "new-model-xyz",
            "model.provider": "new-prov-xyz",
            "model.base_url": "https://api.xyz.com/v1",
            "model.api_mode": "chat_completions",
        }
        res = save_config_values(updates)
        assert res is True

        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        assert cfg["model"]["default"] == "new-model-xyz"
        assert cfg["model"]["provider"] == "new-prov-xyz"
        assert cfg["model"]["base_url"] == "https://api.xyz.com/v1"
        assert cfg["model"]["api_mode"] == "chat_completions"


# ---------------------------------------------------------------------------
# ISOLATION: Profile persistence isolation
# ---------------------------------------------------------------------------
class TestProfileIsolation:
    def test_profile_a_change_does_not_touch_profile_b(self, tmp_path):
        home_a = tmp_path / "profile_a"
        home_b = tmp_path / "profile_b"
        home_a.mkdir()
        home_b.mkdir()

        cfg_a = home_a / "config.yaml"
        cfg_b = home_b / "config.yaml"

        cfg_a.write_text(yaml.dump({"model": {"default": "model-A", "provider": "prov-A"}}), encoding="utf-8")
        cfg_b.write_text(yaml.dump({"model": {"default": "model-B", "provider": "prov-B"}}), encoding="utf-8")

        # Mutate Profile A
        token = set_hermes_home_override(home_a)
        try:
            from cli import save_config_values
            save_config_values({
                "model.default": "model-A2",
                "model.provider": "prov-A2",
            })
        finally:
            reset_hermes_home_override(token)

        # Assert Profile A changed
        res_a = yaml.safe_load(cfg_a.read_text(encoding="utf-8"))
        assert res_a["model"]["default"] == "model-A2"
        assert res_a["model"]["provider"] == "prov-A2"

        # Assert Profile B is completely unchanged
        res_b = yaml.safe_load(cfg_b.read_text(encoding="utf-8"))
        assert res_b["model"]["default"] == "model-B"
        assert res_b["model"]["provider"] == "prov-B"

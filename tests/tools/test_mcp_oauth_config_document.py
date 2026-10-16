"""Preserve raw authority and atomic-replacement failure semantics."""

import pytest
import yaml

from hermes_cli.config import read_user_config_document, read_user_config_raw
from tools.mcp_oauth_state import StaleOAuthCommitError, config_entry, oauth_state_lock
from utils import atomic_replace


@pytest.mark.parametrize("text", ["", "# comment\n", "null\n", "[]\n", "true\n", "plain\n"])
def test_existing_non_mapping_never_permits_initial_oauth_setup(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    before = path.read_bytes()
    existing_paths = {item.name for item in tmp_path.iterdir()}
    with pytest.raises(StaleOAuthCommitError):
        config_entry(tmp_path, "fixture")
    assert read_user_config_raw(path) == {}
    assert read_user_config_document(path) == yaml.safe_load(text)
    assert path.read_bytes() == before
    assert {item.name for item in tmp_path.iterdir()} == existing_paths


def test_missing_authority_permits_initial_setup_but_document_reader_raises(tmp_path):
    path = tmp_path / "config.yaml"
    assert config_entry(tmp_path, "fixture") is None
    assert read_user_config_raw(path) == {}
    with pytest.raises(FileNotFoundError):
        read_user_config_document(path)
    assert not path.exists()


@pytest.mark.parametrize("kind", ["malformed", "directory", "invalid_utf8"])
def test_invalid_authority_is_not_normalized_to_missing(tmp_path, kind):
    path = tmp_path / "config.yaml"
    if kind == "directory":
        path.mkdir()
        expected = OSError
    else:
        path.write_bytes(b"mcp_servers: [" if kind == "malformed" else b"\xff")
        expected = yaml.YAMLError if kind == "malformed" else UnicodeError
    with pytest.raises(expected):
        config_entry(tmp_path, "fixture")


@pytest.mark.parametrize("prior", [None, "mcp_servers: [", "null\n", "[]\n"])
def test_restore_repairs_prior_document_and_advances_authority(tmp_path, prior):
    target = tmp_path / "config.yaml"
    if prior is not None:
        target.write_text(prior, encoding="utf-8")
    candidate = tmp_path / "replacement.yaml"
    candidate.write_text("mcp_servers:\n  fixture:\n    url: https://new.example.invalid/mcp\n", encoding="utf-8")
    with oauth_state_lock(tmp_path) as state:
        previous_generation = state.generation("config", "fixture")
    atomic_replace(candidate, target)
    assert config_entry(tmp_path, "fixture") == {"url": "https://new.example.invalid/mcp"}
    with oauth_state_lock(tmp_path) as state:
        assert state.generation("config", "fixture") > previous_generation


@pytest.mark.parametrize("candidate_text", [None, "mcp_servers: [", b"\xff"])
def test_missing_or_invalid_candidate_cannot_replace_saved_authority(tmp_path, candidate_text):
    target = tmp_path / "config.yaml"
    target.write_text("mcp_servers:\n  fixture:\n    url: https://old.example.invalid/mcp\n", encoding="utf-8")
    candidate = tmp_path / "replacement.yaml"
    if candidate_text is not None:
        candidate.write_bytes(candidate_text if isinstance(candidate_text, bytes) else candidate_text.encode("utf-8"))
    before = target.read_bytes()
    with oauth_state_lock(tmp_path) as state:
        generation = state.generation("config", "fixture")
    with pytest.raises((FileNotFoundError, yaml.YAMLError, UnicodeError)):
        atomic_replace(candidate, target)
    assert target.read_bytes() == before
    with oauth_state_lock(tmp_path) as state:
        assert state.generation("config", "fixture") == generation


def test_authorization_reader_does_not_acquire_config_lock(tmp_path, monkeypatch):
    from hermes_cli import config

    class ForbiddenLock:
        def __enter__(self):
            raise AssertionError("Config lock would invert the OAuth writer lock order")

        def __exit__(self, *_):
            pass

    monkeypatch.setattr(config, "_CONFIG_LOCK", ForbiddenLock())
    (tmp_path / "config.yaml").write_text("mcp_servers: {}\n", encoding="utf-8")
    with oauth_state_lock(tmp_path):
        assert config_entry(tmp_path, "fixture") is None

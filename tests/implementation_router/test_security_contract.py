"""Credential-free admission and process inheritance contracts; no live credentials."""
from __future__ import annotations

import dataclasses
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def route_config():
    return {"enabled": True, "roles": {
        "planner": {"provider": "provider-one", "model": "team/planner-v9", "reasoning_effort": "provider-specific"},
        "worker": {"provider": "local-compatible", "model": "custom/worker:quantised"},
        "reviewer": {"provider": "provider-two", "model": "other/reviewer"},
    }}


class SecurityContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.r = importlib.import_module("downstream.implementation_router.routes")
            self.s = importlib.import_module("downstream.implementation_router.security")
        except ModuleNotFoundError:
            self.fail("ImplementationRouter contract is not implemented on this base")

    def test_routes_are_operator_defined_not_a_model_name_allowlist(self):
        table = self.r.RoutingTable.from_config(route_config())
        self.assertTrue(table.enabled)
        self.assertEqual(table.for_role("worker").model, "custom/worker:quantised")
        self.assertEqual(table.for_role("planner").reasoning_effort, "provider-specific")

    def test_unconfigured_router_is_disabled(self):
        for value in (None, {}, {"enabled": False}):
            self.assertFalse(self.r.RoutingTable.from_config(value).enabled)

    def test_truthy_strings_do_not_enable_execution(self):
        for value in ("true", "false", 1, [], {}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.r.RoutingTable.from_config({**route_config(), "enabled": value})

    def test_credentials_and_second_auth_stores_are_not_route_options(self):
        for key in ("api_key", "access_token", "refresh_token", "headers", "base_url", "auth_profile", "env", "client", "fallback"):
            config = route_config()
            config["roles"]["worker"][key] = "synthetic-secret-do-not-display"
            with self.subTest(key=key), self.assertRaises(ValueError) as caught:
                self.r.RoutingTable.from_config(config)
            self.assertNotIn("synthetic-secret", str(caught.exception))

    def test_unknown_or_missing_roles_never_fall_back_to_parent(self):
        for role in ("worker", "reviewer", "planner"):
            config = route_config()
            del config["roles"][role]
            with self.subTest(role=role), self.assertRaises(ValueError):
                self.r.RoutingTable.from_config(config)
        with self.assertRaises(ValueError):
            self.r.RoutingTable.from_config(route_config()).for_role("admin")

    def test_routes_snapshot_operator_config_and_cannot_be_mutated(self):
        raw = route_config()
        table = self.r.RoutingTable.from_config(raw)
        raw["roles"]["worker"]["model"] = "changed"
        self.assertNotEqual(table.for_role("worker").model, "changed")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            table.for_role("worker").model = "changed"
        self.assertEqual(table.fingerprint(), self.r.RoutingTable.from_config(route_config()).fingerprint())

    def test_bad_ids_and_secret_bearing_urls_are_rejected_without_echo(self):
        for provider, model in (("https://user:secret@host", "m"), ("valid", "https://user:secret@host/m"), ("valid", "m\nsecret"), ("", "m")):
            config = route_config()
            config["roles"]["worker"] = {"provider": provider, "model": model}
            with self.subTest(provider=provider), self.assertRaises(ValueError) as caught:
                self.r.RoutingTable.from_config(config)
            self.assertNotIn("secret", str(caught.exception))

    def test_environment_is_constructed_not_copied_from_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"UNREGISTERED_FUTURE_CREDENTIAL": "sentinel", "OPENAI_API_KEY": "sentinel", "PATH": "sentinel", "PYTHONPATH": "sentinel", "BASH_ENV": "sentinel"}):
                env = self.s.child_environment(Path(directory), (Path(sys.executable).parent,), system_root=self.system_root())
            self.assertFalse("sentinel" in json.dumps(env), "ambient synthetic credential reached child environment")
            self.assertFalse("UNREGISTERED_FUTURE_CREDENTIAL" in env)
            self.assertFalse("PYTHONPATH" in env)
            self.assertFalse("BASH_ENV" in env)
            self.assertEqual(Path(env["HERMES_HOME"]), Path(directory).resolve() / "hermes")
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")

    @staticmethod
    def system_root():
        return Path(os.environ["SystemRoot"]) if os.name == "nt" else None

    def test_child_and_grandchild_do_not_inherit_ambient_secrets(self):
        sentinel = "synthetic-router-secret-not-a-real-credential"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            env = self.s.child_environment(root, (Path(sys.executable).parent,), system_root=self.system_root())
            for value in ("home", "hermes", "codex", "config", "cache", "data", "temp"):
                (root / value).mkdir(exist_ok=True)
            grandchild = "import json,os; print(json.dumps(dict(os.environ)))"
            child = ("import json,os,subprocess,sys; "
                     f"p=subprocess.run([sys.executable,'-I','-c',{grandchild!r}],capture_output=True,text=True,check=True,close_fds=True); "
                     "print(json.dumps({'child':dict(os.environ),'grandchild':json.loads(p.stdout)}))")
            with patch.dict(os.environ, {"AWS_SECRET_ACCESS_KEY": sentinel, "CLAUDE_CODE_OAUTH_TOKEN": sentinel,
                                         "GITHUB_TOKEN": sentinel, "UNREGISTERED_FUTURE_CREDENTIAL": sentinel}):
                outcome = subprocess.run([sys.executable, "-I", "-c", child], env=env, cwd=root,
                                         capture_output=True, text=True, timeout=15, check=True, close_fds=True)
            values = json.loads(outcome.stdout)
            self.assertFalse(sentinel in outcome.stdout, "synthetic credential reached a descendant")
            for lineage in values.values():
                self.assertFalse("UNREGISTERED_FUTURE_CREDENTIAL" in lineage)
                self.assertFalse("CLAUDE_CODE_OAUTH_TOKEN" in lineage)
                self.assertEqual(lineage["HOME"], str(root.resolve() / "home"))
                self.assertEqual(lineage["CODEX_HOME"], str(root.resolve() / "codex"))

    @unittest.skipIf(os.name == "nt", "POSIX descriptor check; Windows handle isolation requires native adapter")
    def test_inheritable_parent_descriptor_is_closed_at_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            fd = os.open(Path(directory) / "secret-fixture", os.O_CREAT | os.O_RDWR, 0o600)
            try:
                os.set_inheritable(fd, True)
                code = f"import os,sys\ntry: os.fstat({fd})\nexcept OSError: sys.exit(0)\nelse: sys.exit(9)"
                runtime_root = Path(directory) / "runtime"
                runtime_root.mkdir()
                env = self.s.child_environment(runtime_root, (Path(sys.executable).parent,))
                p = subprocess.run([sys.executable, "-I", "-c", code], env=env, close_fds=True, timeout=10)
                self.assertEqual(p.returncode, 0)
            finally:
                os.close(fd)

    def test_relative_paths_and_missing_runtime_directories_fail_closed(self):
        with self.assertRaises(ValueError):
            self.s.child_environment(Path("relative"), (Path(sys.executable).parent,))
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            self.s.child_environment(Path(directory), (Path(directory) / "missing",))

    def test_security_receipt_is_bound_to_run_workspace_and_routes(self):
        routes = self.r.RoutingTable.from_config(route_config())
        receipt = self.s.CredentialFreeAdmission("run-a", "workspace-a", routes.fingerprint())
        self.s.validate_admission(receipt, "run-a", "workspace-a", routes)
        for value in (None, True, dataclasses.asdict(receipt), dataclasses.replace(receipt, run_id="other"),
                      dataclasses.replace(receipt, workspace_id="other"), dataclasses.replace(receipt, route_fingerprint="b" * 64),
                      dataclasses.replace(receipt, contract="legacy-direct-credentials")):
            with self.subTest(value=type(value)), self.assertRaises(ValueError):
                self.s.validate_admission(value, "run-a", "workspace-a", routes)

    def test_existing_auth_material_cannot_be_adopted_as_private_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "hermes").mkdir()
            (root / "hermes" / "auth.json").write_text("synthetic-fixture", encoding="utf-8")
            with self.assertRaises(ValueError):
                self.s.child_environment(root, (Path(sys.executable).parent,), system_root=self.system_root())

    def test_path_separator_cannot_add_an_unapproved_search_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "runtime"
            root.mkdir()
            bad = Path(directory) / ("approved" + os.pathsep + "unapproved")
            bad.mkdir()
            with self.assertRaises(ValueError):
                self.s.child_environment(root, (bad,), system_root=self.system_root())

    def test_disabled_config_still_rejects_credential_fields(self):
        config = route_config()
        config["enabled"] = False
        config["roles"]["worker"]["api_key"] = "synthetic-fixture"
        with self.assertRaises(ValueError):
            self.r.RoutingTable.from_config(config)

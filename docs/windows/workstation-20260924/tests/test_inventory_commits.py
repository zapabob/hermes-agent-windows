from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "inventory_commits.py"
SPEC = importlib.util.spec_from_file_location("workstation_inventory", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)


class TestFrozenInventory(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        self.refs: list[str] = []
        for index in range(4):
            (self.repo / "fixture.txt").write_text(str(index), encoding="utf-8")
            self.run_git("add", "fixture.txt")
            self.run_git("commit", "-q", "-m", f"fixture {index}")
            self.refs.append(self.run_git("rev-parse", "HEAD").strip())
        self.output = self.root / "inventory"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args],
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

    def generate(self, *, legacy: Path | None = None, output: Path | None = None,
                 integration_head: str | None = None, refs: list[str] | None = None) -> dict:
        frozen = refs or self.refs
        return inventory.generate(
            self.repo,
            frozen[0],
            frozen[1],
            frozen[2],
            frozen[3],
            integration_head or self.run_git("rev-parse", "HEAD").strip(),
            output or self.output,
            legacy,
        )

    def jsonl(self, name: str) -> list[dict]:
        path = self.output / name
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_complete_windows_are_metadata_only_and_git_is_unchanged(self) -> None:
        before_status = self.run_git("status", "--porcelain")
        before_head = self.run_git("rev-parse", "HEAD")
        result = self.generate()

        self.assertEqual(result["status"], "METADATA_ENUMERATED_NOT_REVIEWED")
        self.assertTrue(result["metadata_complete"])
        self.assertFalse(result["semantic_review_complete"])
        self.assertEqual(result["range_unique_commit_count"], 3)
        self.assertEqual(result["unique_metadata_rows"], 3)
        self.assertEqual(result["window_counts"], {
            "historical_to_v0213": 1,
            "v0213_to_v0214": 1,
            "v0214_to_ceiling": 1,
        })
        self.assertEqual(len(self.jsonl("historical_to_v0213.jsonl")), 1)
        self.assertEqual(len(self.jsonl("v0213_to_v0214.jsonl")), 1)
        self.assertEqual(len(self.jsonl("v0214_to_ceiling.jsonl")), 1)
        self.assertEqual(len(self.jsonl("metadata_universe.jsonl")), 3)
        self.assertTrue(all(row["semantic_review_status"] == "UNREVIEWED"
                            for row in self.jsonl("metadata_universe.jsonl")))
        self.assertEqual(before_status, self.run_git("status", "--porcelain"))
        self.assertEqual(before_head, self.run_git("rev-parse", "HEAD"))

    def test_legacy_decisions_and_overlapping_sources_do_not_double_count(self) -> None:
        ledger = self.root / "legacy.yaml"
        ledger.write_text(
            "commit_count: 3\ncommits:\n"
            f'  - sha: "{self.refs[0]}"\n    decision: COMPOSE\n    categories:\n      - "DOCS_ONLY"\n'
            f'  - sha: "{self.refs[1]}"\n    decision: ADOPT\n    categories:\n      - "SECURITY_CRITICAL"\n'
            f'  - sha: "{self.refs[1]}"\n    decision: ADOPT\n    categories:\n      - "SECURITY_CRITICAL"\n',
            encoding="utf-8",
        )
        result = self.generate(legacy=ledger)
        universe = self.jsonl("metadata_universe.jsonl")
        overlap = next(row for row in universe if row["sha"] == self.refs[1])

        self.assertEqual(result["legacy_rows"], 3)
        self.assertEqual(result["legacy_prior_decisions"], {"COMPOSE": 1, "ADOPT": 2})
        self.assertEqual(result["range_unique_commit_count"], 3)
        self.assertEqual(result["unique_metadata_rows"], 4)
        self.assertEqual(overlap["source_windows"], ["historical_to_v0213"])
        self.assertEqual(overlap["prior_decisions"], ["ADOPT"])
        self.assertEqual(overlap["prior_categories"], ["SECURITY_CRITICAL"])
        self.assertTrue(overlap["critical_review_required"])
        self.assertEqual(result["critical_legacy_rows_unreviewed"], 2)
        self.assertEqual(result["critical_legacy_unique_shas_unreviewed"], 1)
        self.assertEqual(result["legacy_uncategorized_rows"], 0)
        self.assertEqual(overlap["adoption_claim_status"], "UNVERIFIED")
        self.assertEqual(overlap["test_receipts"], [])
        self.assertEqual(len(self.jsonl("historical_ledger_reaudit.jsonl")), 3)
        ledger_rows = self.jsonl("historical_ledger_reaudit.jsonl")
        self.assertTrue(all(row["decision_status"] == "UNVERIFIED_NO_RECEIPT_RECORDED"
                            for row in ledger_rows))
        self.assertTrue(all(row["critical_review_required"] for row in ledger_rows[1:]))

    def test_unknown_and_mismatched_integration_heads_refuse_output(self) -> None:
        with self.assertRaisesRegex(inventory.InventoryError, "INVALID_FROZEN_SHA"):
            self.generate(integration_head="UNKNOWN")
        with self.assertRaisesRegex(inventory.InventoryError, "INTEGRATION_HEAD_MISMATCH"):
            self.generate(integration_head=self.refs[2])
        self.assertFalse(self.output.exists())

    def test_missing_frozen_object_refuses_complete_inventory(self) -> None:
        absent = "0" * 40
        with self.assertRaisesRegex(inventory.InventoryError, "HISTORY_INCOMPLETE: missing frozen commit"):
            self.generate(refs=[absent, *self.refs[1:]])
        self.assertFalse(self.output.exists())

    def test_missing_legacy_commit_object_refuses_complete_inventory(self) -> None:
        ledger = self.root / "legacy.yaml"
        ledger.write_text(f"commit_count: 1\ncommits:\n  - sha: {'f' * 40}\n    decision: ADOPT\n",
                          encoding="utf-8")
        with self.assertRaisesRegex(inventory.InventoryError, "HISTORY_INCOMPLETE"):
            self.generate(legacy=ledger)
        self.assertFalse(self.output.exists())

    def test_successful_legacy_walk_missing_sha_refuses_output(self) -> None:
        base_branch = self.run_git("branch", "--show-current").strip()
        self.run_git("checkout", "-q", "-b", "legacy-only")
        (self.repo / "legacy.txt").write_text("legacy", encoding="utf-8")
        self.run_git("add", "legacy.txt")
        self.run_git("commit", "-q", "-m", "legacy-only")
        legacy_sha = self.run_git("rev-parse", "HEAD").strip()
        self.run_git("checkout", "-q", base_branch)
        self.assertNotIn(legacy_sha, self.refs)

        ledger = self.root / "legacy.yaml"
        ledger.write_text(
            f"commit_count: 1\ncommits:\n  - sha: {legacy_sha}\n    decision: ADOPT\n",
            encoding="utf-8",
        )
        original_run = inventory.subprocess.run
        omitted_legacy_walks: list[list[str]] = []

        def omit_legacy_sha(command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
            if "rev-list" in command and "--no-walk=unsorted" in command:
                omitted_legacy_walks.append(command)
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            return original_run(command, **kwargs)

        with patch.object(inventory.subprocess, "run", side_effect=omit_legacy_sha):
            with self.assertRaisesRegex(inventory.InventoryError, "HISTORY_INCOMPLETE"):
                self.generate(legacy=ledger)

        self.assertEqual(len(omitted_legacy_walks), 1)
        self.assertFalse(self.output.exists())

    def test_non_ancestor_frozen_order_refuses_inventory(self) -> None:
        with self.assertRaisesRegex(inventory.InventoryError, "HISTORY_NONLINEAR_OR_INCOMPLETE"):
            self.generate(refs=[self.refs[1], self.refs[0], self.refs[2], self.refs[3]])
        self.assertFalse(self.output.exists())

    def test_shallow_repository_refuses_complete_inventory(self) -> None:
        shallow = self.root / "shallow"
        subprocess.check_call(["git", "clone", "--depth=1", "--quiet", self.repo.as_uri(), str(shallow)])
        with self.assertRaisesRegex(inventory.InventoryError, "HISTORY_INCOMPLETE: shallow"):
            inventory.generate(shallow, *self.refs, self.refs[3], self.root / "shallow-output")
        self.assertFalse((self.root / "shallow-output").exists())

    def test_legacy_declared_count_must_match_streamed_rows(self) -> None:
        ledger = self.root / "legacy.yaml"
        ledger.write_text(f"commit_count: 2\ncommits:\n  - sha: {self.refs[1]}\n    decision: ADOPT\n",
                          encoding="utf-8")
        with self.assertRaisesRegex(inventory.InventoryError, "LEGACY_COUNT_MISMATCH"):
            list(inventory.legacy_rows(ledger))

    def test_process_environment_excludes_provider_and_git_override_secrets(self) -> None:
        with patch.dict(os.environ, {
            "OPENAI_API_KEY": "synthetic", "ANTHROPIC_API_KEY": "synthetic",
            "GIT_SSH_COMMAND": "untrusted", "GIT_DIR": "untrusted",
        }):
            env = inventory.clean_git_env()
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("GIT_SSH_COMMAND", env)
        self.assertNotIn("GIT_DIR", env)
        self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(env["GIT_NO_REPLACE_OBJECTS"], "1")

    def test_merge_commit_is_present_with_both_parents(self) -> None:
        self.run_git("checkout", "-q", "-b", "feature", self.refs[2])
        (self.repo / "feature.txt").write_text("feature", encoding="utf-8")
        self.run_git("add", "feature.txt")
        self.run_git("commit", "-q", "-m", "feature")
        feature = self.run_git("rev-parse", "HEAD").strip()
        self.run_git("checkout", "-q", "-b", "other", self.refs[2])
        (self.repo / "other.txt").write_text("other", encoding="utf-8")
        self.run_git("add", "other.txt")
        self.run_git("commit", "-q", "-m", "other")
        self.run_git("merge", "--no-ff", "-q", "feature", "-m", "merge")
        merged = self.run_git("rev-parse", "HEAD").strip()
        self.generate(refs=[self.refs[0], self.refs[1], self.refs[2], merged])
        row = next(item for item in self.jsonl("v0214_to_ceiling.jsonl") if item["sha"] == merged)
        self.assertEqual(len(row["parents"]), 2)
        self.assertIn(feature, row["parents"])

    def _assert_generate_releases_resources(self, *, fail_after_staged_file: bool) -> None:
        scratch_dirs: list[Path] = []
        stage_dirs: list[Path] = []
        connections: list[inventory.sqlite3.Connection] = []
        real_temporary_directory = inventory.tempfile.TemporaryDirectory
        real_mkdtemp = inventory.tempfile.mkdtemp
        real_connect = inventory.sqlite3.connect
        real_jsonl = inventory._jsonl
        jsonl_writes = 0

        def track_temporary_directory(*args, **kwargs):
            temporary_directory = real_temporary_directory(*args, **kwargs)
            scratch_dirs.append(Path(temporary_directory.name))
            return temporary_directory

        def track_mkdtemp(*args, **kwargs):
            path = real_mkdtemp(*args, **kwargs)
            if kwargs.get("prefix") == ".workstation-inventory-":
                stage_dirs.append(Path(path))
            return path

        def track_connect(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            return connection

        def write_then_maybe_fail(path, rows):
            nonlocal jsonl_writes
            count = real_jsonl(path, rows)
            jsonl_writes += 1
            if fail_after_staged_file and jsonl_writes == 1:
                raise RuntimeError("synthetic inventory write failure")
            return count

        with (
            patch.object(inventory.tempfile, "TemporaryDirectory", side_effect=track_temporary_directory),
            patch.object(inventory.tempfile, "mkdtemp", side_effect=track_mkdtemp),
            patch.object(inventory.sqlite3, "connect", side_effect=track_connect),
            patch.object(inventory, "_jsonl", side_effect=write_then_maybe_fail),
        ):
            if fail_after_staged_file:
                with self.assertRaisesRegex(RuntimeError, "synthetic inventory write failure"):
                    self.generate()
            else:
                self.generate()

        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(inventory.sqlite3.ProgrammingError, "closed"):
            connections[0].execute("SELECT 1")

        self.assertEqual(len(scratch_dirs), 1)
        self.assertFalse(scratch_dirs[0].exists())
        self.assertEqual(len(stage_dirs), 1)
        self.assertFalse(stage_dirs[0].exists())
        if fail_after_staged_file:
            self.assertFalse(self.output.exists())
        else:
            self.assertTrue((self.output / "metadata_universe.jsonl").is_file())

    def test_generate_closes_sqlite_and_removes_temp_dirs_on_success(self) -> None:
        self._assert_generate_releases_resources(fail_after_staged_file=False)

    def test_generate_closes_sqlite_and_removes_temp_dirs_on_exception(self) -> None:
        self._assert_generate_releases_resources(fail_after_staged_file=True)

    def test_nonempty_output_is_preserved(self) -> None:
        self.output.mkdir()
        sentinel = self.output / "keep.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        with self.assertRaisesRegex(inventory.InventoryError, "OUTPUT_NOT_EMPTY"):
            self.generate()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


class TestFrozenCampaignInventory(unittest.TestCase):
    def test_successful_legacy_inventory_preserves_frozen_source_digest(self) -> None:
        campaign_dir = Path(__file__).resolve().parents[1]
        repo = campaign_dir.parents[2]
        freeze = json.loads((campaign_dir / "freeze.json").read_text(encoding="utf-8"))
        inventory_config = freeze["inventory"]
        expected_digest = inventory_config["legacy_source_sha256"]
        legacy_path = repo / inventory_config["legacy_source_path"]
        self.assertEqual(inventory.file_sha256(legacy_path), expected_digest)

        upstream = freeze["upstream"]
        integration_head = inventory.git(repo, "rev-parse", "--verify", "HEAD^{commit}")
        with tempfile.TemporaryDirectory(prefix="f00-legacy-digest-") as temp_dir:
            result = inventory.generate(
                repo,
                upstream["historical_snapshot_sha"],
                upstream["v0213_release_sha"],
                upstream["v0214_release_sha"],
                upstream["campaign_ceiling_sha"],
                integration_head,
                Path(temp_dir) / "inventory",
                legacy_path,
            )
            ledger_path = Path(temp_dir) / "inventory" / "historical_ledger_reaudit.jsonl"
            ledger_rows = [
                json.loads(line)
                for line in ledger_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(result["legacy_source_sha256"], expected_digest)
        self.assertEqual(result["legacy_rows"], inventory_config["legacy_row_count"])
        self.assertEqual(len(ledger_rows), result["legacy_rows"])
        self.assertTrue(ledger_rows)
        self.assertTrue(all(row.get("source_sha256") == expected_digest for row in ledger_rows))


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Read-only frozen Git metadata inventory; never performs semantic adoption review."""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
from typing import Iterator

SHA = re.compile(r"^[0-9a-f]{40}$")
LOG = logging.getLogger("workstation_inventory")
WINDOWS = ("historical_to_v0213", "v0213_to_v0214", "v0214_to_ceiling")
U1_WINDOWS = ("legacy_ceiling_to_v0215", "v0215_to_u1")


class InventoryError(RuntimeError):
    """A frozen-input or completeness invariant prevented inventory output."""


def validate_sha(value: str) -> str:
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise InventoryError("INVALID_FROZEN_SHA: require a lowercase full 40-character SHA")
    return value


def clean_git_env() -> dict[str, str]:
    """Pass only process essentials; do not inherit credentials or Git overrides."""
    allowed = {
        "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "TMPDIR", "LANG", "LC_ALL",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
    })
    return env


def git(repo: Path, *args: str, timeout: float = 60) -> str:
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(repo), *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            env=clean_git_env(),
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryError("GIT_UNAVAILABLE_OR_TIMEOUT") from exc
    if result.returncode:
        # Do not echo Git stderr: it may include private remotes or local paths.
        command = args[0] if args else "unknown"
        raise InventoryError(f"GIT_COMMAND_FAILED: {command} exit={result.returncode}")
    try:
        return result.stdout.decode("utf-8", errors="strict").strip()
    except UnicodeError as exc:
        raise InventoryError("GIT_OUTPUT_NOT_UTF8") from exc


@contextmanager
def log_lines(repo: Path, start: str, end: str) -> Iterator[Iterator[str]]:
    """Spool large metadata instead of buffering a whole Git history in memory."""
    with tempfile.TemporaryFile(mode="w+b") as spool:
        try:
            result = subprocess.run(
                ["git", "--no-pager", "-C", str(repo), "log", "--no-show-signature",
                 "--no-decorate", "--format=%H%x09%P%x09%T", f"{start}..{end}", "--"],
                stdin=subprocess.DEVNULL,
                stdout=spool,
                stderr=subprocess.DEVNULL,
                env=clean_git_env(),
                timeout=180,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise InventoryError("GIT_LOG_UNAVAILABLE_OR_TIMEOUT") from exc
        if result.returncode:
            raise InventoryError("GIT_LOG_FAILED")
        spool.seek(0)
        def rows() -> Iterator[str]:
            for raw in spool:
                try:
                    yield raw.decode("ascii", errors="strict").rstrip("\r\n")
                except UnicodeError as exc:
                    raise InventoryError("GIT_LOG_METADATA_NOT_ASCII") from exc
        yield rows()


def legacy_rows(path: Path) -> Iterator[tuple[int, str, str, tuple[str, ...]]]:
    """Stream SHA, prior decision and category from the known YAML row layout."""
    count = 0
    declared: int | None = None
    in_commits = False
    in_categories = False
    pending_sha: str | None = None
    pending_decision: str | None = None
    pending_categories: list[str] = []
    sha_row = re.compile(r"""^  - sha:\s*["']?([0-9a-f]{40})["']?\s*$""")
    decision_row = re.compile(r"^    decision:\s*([A-Z_]+)\s*$")
    categories_header = re.compile(r"^    categories:\s*$")
    category_row = re.compile(r"""^      - ["']?([A-Z_]+)["']?\s*$""")

    def emit() -> tuple[int, str, str, tuple[str, ...]]:
        nonlocal count
        if pending_sha is None:
            raise InventoryError("LEGACY_ROW_MISSING_SHA")
        if pending_decision is None:
            raise InventoryError("LEGACY_DECISION_MISSING")
        count += 1
        return count, pending_sha, pending_decision, tuple(pending_categories)

    with path.open("r", encoding="utf-8-sig", newline=None) as handle:
        for line in handle:
            if line.startswith("commit_count:"):
                try:
                    declared = int(line.split(":", 1)[1].strip())
                except ValueError as exc:
                    raise InventoryError("LEGACY_DECLARED_COUNT_INVALID") from exc
            if line.rstrip() == "commits:":
                in_commits = True
                continue
            if not in_commits:
                continue
            match = sha_row.fullmatch(line.rstrip())
            if match:
                if pending_sha is not None:
                    yield emit()
                pending_sha = validate_sha(match.group(1))
                pending_decision = None
                pending_categories = []
                in_categories = False
                continue
            if line.startswith("  - "):
                raise InventoryError("LEGACY_LAYOUT_UNSUPPORTED")
            decision_match = decision_row.fullmatch(line.rstrip())
            if decision_match:
                if pending_sha is None or pending_decision is not None:
                    raise InventoryError("LEGACY_DECISION_AMBIGUOUS")
                pending_decision = decision_match.group(1)
                in_categories = False
                continue
            if categories_header.fullmatch(line.rstrip()):
                if pending_sha is None:
                    raise InventoryError("LEGACY_CATEGORY_WITHOUT_COMMIT")
                in_categories = True
                continue
            if in_categories:
                if not line.strip():
                    continue
                category_match = category_row.fullmatch(line.rstrip())
                if category_match:
                    category = category_match.group(1)
                    if category not in pending_categories:
                        pending_categories.append(category)
                    continue
                if line.startswith("    ") and not line.startswith("      "):
                    in_categories = False
                elif line.startswith("      "):
                    raise InventoryError("LEGACY_CATEGORY_LAYOUT_UNSUPPORTED")

    if pending_sha is not None:
        yield emit()
    if not in_commits or declared is None or count != declared:
        raise InventoryError("LEGACY_COUNT_MISMATCH_OR_UNSUPPORTED_LAYOUT")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def commit_parents(repo: Path, shas: list[str]) -> dict[str, list[str]]:
    """Resolve parents for ledger-only rows through a metadata-only Git walk."""
    if not shas:
        return {}
    payload = "".join(f"{sha}\n" for sha in shas)
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(repo), "rev-list", "--parents", "--no-walk=unsorted", "--stdin"],
            input=payload,
            capture_output=True,
            text=True,
            encoding="ascii",
            errors="strict",
            env=clean_git_env(),
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise InventoryError("LEGACY_COMMIT_METADATA_UNAVAILABLE") from exc
    if result.returncode:
        raise InventoryError("HISTORY_INCOMPLETE: legacy commit metadata unavailable")
    parents_by_sha: dict[str, list[str]] = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if not fields:
            continue
        sha = validate_sha(fields[0])
        parents_by_sha[sha] = [validate_sha(parent) for parent in fields[1:]]
    if set(parents_by_sha) != set(shas):
        raise InventoryError("HISTORY_INCOMPLETE: legacy commit object missing")
    return parents_by_sha


def commit_trees(repo: Path, shas: list[str]) -> dict[str, str]:
    """Resolve every historical tree from exact commit objects in one Git batch."""
    if not shas:
        return {}
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(repo), "cat-file", "--batch"],
            input="".join(f"{sha}\n" for sha in shas).encode("ascii"),
            capture_output=True,
            env=clean_git_env(),
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryError("LEGACY_TREE_METADATA_UNAVAILABLE") from exc
    if result.returncode:
        raise InventoryError("HISTORY_INCOMPLETE: legacy commit tree unavailable")
    stream = io.BytesIO(result.stdout)
    trees: dict[str, str] = {}
    for expected in shas:
        header = stream.readline().rstrip(b"\n")
        fields = header.split(b" ")
        if len(fields) != 3 or fields[0] != expected.encode("ascii") or fields[1] != b"commit":
            raise InventoryError("HISTORY_INCOMPLETE: legacy commit batch mismatch")
        try:
            size = int(fields[2])
            payload = stream.read(size)
            tree_line = payload.split(b"\n", 1)[0]
            tree = tree_line.removeprefix(b"tree ").decode("ascii")
        except (ValueError, UnicodeError) as exc:
            raise InventoryError("LEGACY_TREE_METADATA_INVALID") from exc
        if len(payload) != size or stream.read(1) != b"\n" or not tree_line.startswith(b"tree "):
            raise InventoryError("LEGACY_TREE_METADATA_INVALID")
        trees[expected] = validate_sha(tree)
    if stream.read(1):
        raise InventoryError("LEGACY_TREE_METADATA_TRAILING_BYTES")
    return trees


def _jsonl(path: Path, rows: Iterator[dict]) -> int:
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def generate(
    repo: Path,
    historical: str,
    release_base: str,
    release: str,
    ceiling: str,
    integration_head: str,
    output: Path,
    legacy: Path | None = None,
    *,
    release_r2: str | None = None,
    ceiling_u1: str | None = None,
    history_repo: Path | None = None,
) -> dict:
    refs = [validate_sha(value) for value in (historical, release_base, release, ceiling)]
    if (release_r2 is None) != (ceiling_u1 is None):
        raise InventoryError("INCOMPLETE_NEW_CAMPAIGN: require both R2 and U1")
    window_names = WINDOWS
    if release_r2 is not None and ceiling_u1 is not None:
        refs.extend((validate_sha(release_r2), validate_sha(ceiling_u1)))
        window_names += U1_WINDOWS
    integration_head = validate_sha(integration_head)
    repo = repo.resolve(strict=True)
    history = history_repo.resolve(strict=True) if history_repo is not None else repo
    try:
        actual_head = git(repo, "rev-parse", "--verify", "HEAD^{commit}")
    except InventoryError as exc:
        raise InventoryError("INTEGRATION_HEAD_UNKNOWN") from exc
    if actual_head != integration_head:
        raise InventoryError("INTEGRATION_HEAD_MISMATCH")
    if git(history, "rev-parse", "--is-shallow-repository") != "false":
        raise InventoryError("HISTORY_INCOMPLETE: shallow repository")

    for ref in refs:
        try:
            resolved = git(history, "rev-parse", "--verify", f"{ref}^{{commit}}")
        except InventoryError as exc:
            raise InventoryError("HISTORY_INCOMPLETE: missing frozen commit") from exc
        if resolved != ref:
            raise InventoryError("FROZEN_OBJECT_IS_NOT_COMMIT")
    for older, newer in zip(refs, refs[1:]):
        result = subprocess.run(
            ["git", "--no-pager", "-C", str(history), "merge-base", "--is-ancestor", older, newer],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=clean_git_env(),
            timeout=60,
            check=False,
        )
        if result.returncode:
            raise InventoryError("HISTORY_NONLINEAR_OR_INCOMPLETE")

    legacy_path: Path | None = None
    legacy_hash: str | None = None
    if legacy is not None:
        legacy_path = legacy.resolve(strict=True)
        legacy_hash = file_sha256(legacy_path)

    out = output.absolute()
    if out.is_symlink():
        raise InventoryError("OUTPUT_SYMLINK_REFUSED")
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise InventoryError("OUTPUT_NOT_EMPTY")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out == repo or out in repo.parents:
        raise InventoryError("OUTPUT_PATH_NOT_ALLOWED")

    stage = Path(tempfile.mkdtemp(prefix=".workstation-inventory-", dir=out.parent))
    scratch_name: str | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="workstation-inventory-db-") as scratch:
            scratch_name = scratch
            db_path = Path(scratch) / "index.sqlite"
            with closing(sqlite3.connect(db_path)) as db:
                db.execute("CREATE TABLE rows (sha TEXT PRIMARY KEY, parents TEXT, tree_oid TEXT, windows TEXT NOT NULL, prior_decisions TEXT NOT NULL, prior_categories TEXT NOT NULL)")
                db.execute("CREATE TABLE ledger (row_number INTEGER PRIMARY KEY, sha TEXT NOT NULL, decision TEXT NOT NULL, categories TEXT NOT NULL)")

                def upsert(sha: str, parents: list[str] | None = None, tree_oid: str | None = None,
                           window: str | None = None,
                           prior: str | None = None, prior_category: str | None = None) -> None:
                    old = db.execute("SELECT parents, tree_oid, windows, prior_decisions, prior_categories FROM rows WHERE sha=?", (sha,)).fetchone()
                    windows = json.loads(old[2]) if old else []
                    decisions = json.loads(old[3]) if old else []
                    categories = json.loads(old[4]) if old else []
                    if window in window_names and window not in windows:
                        if any(existing in window_names for existing in windows):
                            raise InventoryError("UPSTREAM_WINDOWS_OVERLAP")
                        windows.append(window)
                    if prior is not None and prior not in decisions:
                        decisions.append(prior)
                    if prior_category is not None and prior_category not in categories:
                        categories.append(prior_category)
                    parent_json = json.dumps(parents) if parents is not None else (old[0] if old else None)
                    tree_oid = validate_sha(tree_oid) if tree_oid is not None else (old[1] if old else None)
                    if old and old[1] is not None and tree_oid != old[1]:
                        raise InventoryError("COMMIT_TREE_MISMATCH")
                    db.execute(
                        "INSERT OR REPLACE INTO rows VALUES(?,?,?,?,?,?)",
                        (sha, parent_json, tree_oid, json.dumps(windows), json.dumps(decisions), json.dumps(categories)),
                    )

                window_counts: dict[str, int] = {}
                for name, older, newer in zip(window_names, refs, refs[1:]):
                    count = 0
                    with log_lines(history, older, newer) as lines:
                        for line in lines:
                            fields = line.split("\t")
                            if len(fields) != 3:
                                raise InventoryError("GIT_LOG_METADATA_INVALID")
                            sha = validate_sha(fields[0])
                            parents = [validate_sha(parent) for parent in fields[1].split()]
                            upsert(sha, parents, validate_sha(fields[2]), name)
                            count += 1
                    window_counts[name] = count
                    db.commit()

                legacy_count = 0
                prior_counts: dict[str, int] = {}
                category_counts: dict[str, int] = {}
                critical_legacy_rows = 0
                critical_legacy_shas: set[str] = set()
                uncategorized_legacy_rows = 0
                if legacy_path is not None:
                    for row_number, sha, decision, categories in legacy_rows(legacy_path):
                        upsert(sha, prior=decision)
                        for category in categories:
                            upsert(sha, prior_category=category)
                            category_counts[category] = category_counts.get(category, 0) + 1
                        db.execute("INSERT INTO ledger VALUES(?,?,?,?)", (row_number, sha, decision, json.dumps(categories)))
                        legacy_count += 1
                        prior_counts[decision] = prior_counts.get(decision, 0) + 1
                        if not categories:
                            uncategorized_legacy_rows += 1
                        if {"SECURITY_CRITICAL", "DATA_INTEGRITY"}.intersection(categories):
                            critical_legacy_rows += 1
                            critical_legacy_shas.add(sha)
                    db.commit()

                ledger_shas = [row[0] for row in db.execute("SELECT DISTINCT sha FROM ledger ORDER BY sha")]
                parent_map = commit_parents(history, ledger_shas)
                tree_map = commit_trees(history, ledger_shas)
                if set(parent_map) != set(tree_map):
                    raise InventoryError("HISTORY_INCOMPLETE: legacy tree set mismatch")
                for sha, parents in parent_map.items():
                    upsert(sha, parents=parents, tree_oid=tree_map[sha])
                db.commit()

                if sum(window_counts.values()) != db.execute(
                    "SELECT COUNT(*) FROM rows WHERE windows != '[]'"
                ).fetchone()[0]:
                    raise InventoryError("UPSTREAM_WINDOW_ACCOUNTING_MISMATCH")

                range_unique = db.execute("SELECT COUNT(*) FROM rows WHERE windows != '[]'").fetchone()[0]
                unique_commits = db.execute("SELECT COUNT(*) FROM rows").fetchone()[0]
                staged_inventory = stage
                for name in window_names:
                    def range_rows(window_name: str = name) -> Iterator[dict]:
                        query = "SELECT sha, parents, tree_oid, windows, prior_decisions, prior_categories FROM rows ORDER BY sha"
                        for sha, parents_json, tree_oid, windows_json, decisions_json, categories_json in db.execute(query):
                            if window_name in json.loads(windows_json):
                                yield {
                                    "sha": sha,
                                    "parents": json.loads(parents_json) if parents_json else [],
                                    "tree_oid": tree_oid,
                                    "window": window_name,
                                    "prior_decisions": json.loads(decisions_json),
                                    "prior_categories": json.loads(categories_json),
                                    "classification": "UNREVIEWED",
                                    "codegraph_status": "REQUIRES_EXECUTION",
                                    "test_receipts": [],
                                }
                    _jsonl(staged_inventory / f"{name}.jsonl", range_rows())

                def ledger_records() -> Iterator[dict]:
                    for row_number, sha, decision, categories_json, tree_oid in db.execute(
                        "SELECT ledger.row_number, ledger.sha, ledger.decision, ledger.categories, rows.tree_oid "
                        "FROM ledger JOIN rows ON rows.sha=ledger.sha ORDER BY ledger.row_number"
                    ):
                        categories = json.loads(categories_json)
                        yield {
                            "row_number": row_number,
                            "sha": sha,
                            "tree_oid": tree_oid,
                            "prior_decision": decision,
                            "prior_categories": categories,
                            "critical_review_required": bool({"SECURITY_CRITICAL", "DATA_INTEGRITY"}.intersection(categories)),
                            "decision_status": "UNVERIFIED_NO_RECEIPT_RECORDED",
                            "current_classification": "UNREVIEWED",
                            "source_sha256": legacy_hash,
                            "implementation_commits": [],
                            "test_receipts": [],
                        }
                ledger_output_count = _jsonl(staged_inventory / "historical_ledger_reaudit.jsonl", ledger_records())
                if ledger_output_count != legacy_count:
                    raise InventoryError("LEGACY_OUTPUT_COUNT_MISMATCH")

                def universe_records() -> Iterator[dict]:
                    for sha, parents_json, tree_oid, windows_json, decisions_json, categories_json in db.execute("SELECT * FROM rows ORDER BY sha"):
                        decisions = json.loads(decisions_json)
                        yield {
                            "sha": sha,
                            "parents": json.loads(parents_json) if parents_json is not None else None,
                            "tree_oid": tree_oid,
                            "source_windows": json.loads(windows_json),
                            "prior_decisions": decisions,
                            "prior_categories": json.loads(categories_json),
                            "critical_review_required": bool({"SECURITY_CRITICAL", "DATA_INTEGRITY"}.intersection(json.loads(categories_json))),
                            "metadata_status": "ENUMERATED",
                            "semantic_review_status": "UNREVIEWED",
                            "adoption_claim_status": "UNVERIFIED" if decisions else "NO_PRIOR_CLAIM",
                            "implementation_commits": [],
                            "test_receipts": [],
                            "codegraph_status": "REQUIRES_EXECUTION",
                            "codegraph_evidence_refs": [],
                        }
                _jsonl(staged_inventory / "metadata_universe.jsonl", universe_records())
                db.commit()

                summary = {
                    "schema_version": 1,
                    "status": "METADATA_ENUMERATED_NOT_REVIEWED",
                    "metadata_complete": True,
                    "semantic_review_complete": False,
                    "integration_local_head": integration_head,
                    "frozen_commits": dict(zip(
                        ("historical", "release_base", "release", "ceiling", "release_r2", "ceiling_u1"), refs
                    )),
                    "window_counts": window_counts,
                    "range_unique_commit_count": range_unique,
                    "legacy_source_sha256": legacy_hash,
                    "legacy_rows": legacy_count,
                    "legacy_prior_decisions": prior_counts,
                    "legacy_category_counts": category_counts,
                    "legacy_uncategorized_rows": uncategorized_legacy_rows,
                    "critical_legacy_rows_unreviewed": critical_legacy_rows,
                    "critical_legacy_unique_shas_unreviewed": len(critical_legacy_shas),
                    "unique_metadata_rows": unique_commits,
                    "all_metadata_rows_unreviewed": unique_commits,
                    "historical_ledger_receipts_verified": 0,
                    "codegraph_queries_run": 0,
                    "generated_at_utc": datetime.now(timezone.utc).isoformat(),
                }

        if out.exists():
            out.rmdir()
        os.replace(stage, out)
        return summary
    except BaseException:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--historical", required=True)
    parser.add_argument("--release-base", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--ceiling", required=True)
    parser.add_argument("--integration-head", required=True)
    parser.add_argument("--legacy-ledger", type=Path)
    parser.add_argument("--release-r2")
    parser.add_argument("--ceiling-u1")
    parser.add_argument("--history-repo", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = generate(
            args.repo, args.historical, args.release_base, args.release, args.ceiling,
            args.integration_head, args.output, args.legacy_ledger,
            release_r2=args.release_r2,
            ceiling_u1=args.ceiling_u1,
            history_repo=args.history_repo,
        )
    except (InventoryError, OSError, UnicodeError, sqlite3.Error) as exc:
        LOG.error("Inventory did not complete: %s", exc)
        return 2
    LOG.info(
        "Metadata rows=%d across %d upstream commits; semantic review remains unreviewed",
        result["unique_metadata_rows"], result["range_unique_commit_count"],
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    raise SystemExit(main())

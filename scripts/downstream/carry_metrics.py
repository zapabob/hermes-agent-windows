#!/usr/bin/env python3
"""Generate reproducible downstream carry-surface metrics."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / ".codex/UPSTREAM_SNAPSHOT.json"
CARRY = ROOT / "CARRY.yaml"
JSON_REPORT = ROOT / "_docs/carry-surface-20260826.json"
MD_REPORT = ROOT / "_docs/carry-surface-20260826.md"
# Exact report paths stay listed for ledger/docs compatibility; the whole
# `_docs/` tree is excluded below so impl logs cannot self-invalidate --check.
EXCLUDED = {path.relative_to(ROOT).as_posix() for path in (JSON_REPORT, MD_REPORT)}
EXCLUDED_PREFIXES = ("_docs/",)
LOW_COUPLING = ("tests/", "docs/", "_docs/", ".github/", "website/docs/")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        text=True,
    ).stdout


def is_excluded(path: str) -> bool:
    if path in EXCLUDED:
        return True
    return path.startswith(EXCLUDED_PREFIXES)


def semantic_coupling(path: str, carry_paths: set[str]) -> int:
    if path in carry_paths:
        return 3
    return 1 if path.startswith(LOW_COUPLING) else 2


def report_definitions() -> dict[str, Any]:
    """Metric definitions — pure, no git object reachability required.

    Python CI checks out with depth=1; callers that only need the HEAD-based
    diff / `_docs/` exclusion contracts must not invoke calculate().
    """
    return {
        "loc": "added plus deleted lines from frozen upstream to committed HEAD",
        "upstream_owned": "path exists in the frozen upstream tree",
        "utr": "upstream-owned fork LOC divided by all fork-specific LOC",
        "cs": "count of upstream-owned files directly modified",
        "cwc": "sum(upstream frequency * patch size * semantic coupling)",
        "coupling_3": "path is named by CARRY.yaml",
        "coupling_2": "other runtime or source path",
        "coupling_1": "test, docs, workflow, or generated documentation path",
        "excluded": sorted(EXCLUDED),
        "excluded_prefixes": list(EXCLUDED_PREFIXES),
    }


def upstream_frequencies(merge_base: str, upstream: str) -> Counter[str]:
    output = git(
        "log",
        "--format=format:@@COMMIT",
        "--name-only",
        "--no-renames",
        f"{merge_base}..{upstream}",
    )
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    for line in [*output.splitlines(), "@@COMMIT"]:
        if line == "@@COMMIT":
            counts.update(seen)
            seen.clear()
        elif line:
            seen.add(line)
    return counts


def calculate() -> dict[str, Any]:
    snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    upstream = str(snapshot["upstream_head_sha"])
    merge_base = str(snapshot["merge_base_sha"])
    upstream_paths = set(git("ls-tree", "-r", "--name-only", upstream).splitlines())
    frequencies = upstream_frequencies(merge_base, upstream)
    carry_data = yaml.safe_load(CARRY.read_text(encoding="utf-8"))
    carry_paths = {
        path for entry in carry_data["carry"] for path in entry["upstream_paths"]
    }

    # Diff committed HEAD against frozen upstream — never the dirty worktree.
    # Worktree diffs baked local WIP into prior regenerations and made CI
    # (clean checkout) disagree with the committed reports.
    rows: list[tuple[int, int, str]] = []
    for line in git(
        "diff", "--numstat", "--no-renames", upstream, "HEAD", "--"
    ).splitlines():
        added, deleted, path = line.split("\t", 2)
        if not is_excluded(path) and added != "-" and deleted != "-":
            rows.append((int(added), int(deleted), path))

    all_loc = sum(added + deleted for added, deleted, _ in rows)
    upstream_rows = [row for row in rows if row[2] in upstream_paths]
    upstream_loc = sum(added + deleted for added, deleted, _ in upstream_rows)
    details = []
    for added, deleted, path in upstream_rows:
        patch_size = added + deleted
        coupling = semantic_coupling(path, carry_paths)
        frequency = frequencies[path]
        details.append({
            "path": path,
            "added": added,
            "deleted": deleted,
            "patch_size": patch_size,
            "upstream_frequency": frequency,
            "semantic_coupling": coupling,
            "cwc": frequency * patch_size * coupling,
        })
    details.sort(key=lambda item: (-item["cwc"], -item["patch_size"], item["path"]))
    return {
        "schema_version": 1,
        "snapshot_sha": upstream,
        "merge_base_sha": merge_base,
        "definitions": report_definitions(),
        "summary": {
            "all_fork_specific_loc": all_loc,
            "upstream_owned_fork_loc": upstream_loc,
            "fork_owned_loc": all_loc - upstream_loc,
            "utr": round(upstream_loc / all_loc, 6) if all_loc else 0.0,
            "carry_surface_files": len(upstream_rows),
            "cwc": sum(item["cwc"] for item in details),
        },
        "top_carry_risks": details[:25],
    }


def markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    rows = [
        "# Carry-surface metrics, 2026-08-26",
        "",
        f"Frozen upstream: {report['snapshot_sha']}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| All fork-specific LOC | {summary['all_fork_specific_loc']} |",
        f"| Upstream-owned fork LOC | {summary['upstream_owned_fork_loc']} |",
        f"| Fork-owned LOC | {summary['fork_owned_loc']} |",
        f"| UTR | {summary['utr']:.6f} |",
        f"| Carry Surface | {summary['carry_surface_files']} files |",
        f"| CWC | {summary['cwc']} |",
        "",
        "LOC is added plus deleted lines relative to the frozen upstream tree.",
        "The `_docs/` tree (including these reports) is excluded to avoid",
        "self-referential totals from impl logs and regenerated metrics.",
        "Totals are computed from committed HEAD, not a dirty worktree.",
        "Coupling is 3 for CARRY.yaml paths, 2 for other runtime/source paths,",
        "and 1 for tests, docs, workflows, and generated documentation.",
        "",
        "## Highest CWC paths",
        "",
        "| Path | Frequency | Patch | Coupling | CWC |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    rows.extend(
        f"| {item['path']} | {item['upstream_frequency']} | {item['patch_size']} | "
        f"{item['semantic_coupling']} | {item['cwc']} |"
        for item in report["top_carry_risks"]
    )
    rows.extend([
        "",
        "This is a coupling report, not a target to improve by relocating code",
        "without reducing its actual dependency on upstream behavior.",
        "",
    ])
    return "\n".join(rows)


def serialized() -> tuple[str, str]:
    report = calculate()
    return (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        markdown(report),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    json_text, md_text = serialized()
    if args.check:
        if (
            JSON_REPORT.read_text(encoding="utf-8") != json_text
            or MD_REPORT.read_text(encoding="utf-8") != md_text
        ):
            print("Carry metrics are stale. Regenerate without --check.")
            return 1
        print("Carry metrics are current.")
        return 0
    JSON_REPORT.write_text(json_text, encoding="utf-8", newline="\n")
    MD_REPORT.write_text(md_text, encoding="utf-8", newline="\n")
    print(f"Wrote {JSON_REPORT.relative_to(ROOT)}")
    print(f"Wrote {MD_REPORT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

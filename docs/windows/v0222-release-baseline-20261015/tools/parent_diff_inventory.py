"""Read-only, byte-safe parent-edge inventory for frozen adoption inputs."""
from __future__ import annotations

import importlib.util
import argparse
import base64
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess

_metadata_path = Path(__file__).resolve().parents[2] / "workstation-20260924/tools/inventory_commits.py"
_spec = importlib.util.spec_from_file_location("frozen_metadata_inventory", _metadata_path)
assert _spec is not None and _spec.loader is not None
_metadata = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_metadata)
InventoryError = _metadata.InventoryError
clean_git_env = _metadata.clean_git_env
validate_sha = _metadata.validate_sha


def parse_pair_stream(stream):
    """Parse explicit pair frames; filenames are never split on newlines."""
    seen = set()
    current = None
    while True:
        first = stream.read(1)
        if not first:
            if current is not None:
                yield current
            return
        if first == b"P":
            line = first + stream.readline()
            match = re.fullmatch(rb"PAIR ([0-9a-f]{40}) ([0-9a-f]{40}|ROOT)\n", line)
            if match is None:
                raise InventoryError("INVALID_PAIR_HEADER")
            child, parent = match[1].decode(), match[2].decode()
            parent = None if parent == "ROOT" else parent
            key = child, parent
            if key in seen:
                raise InventoryError("DUPLICATE_PARENT_EDGE")
            seen.add(key)
            trees = stream.readline().rstrip(b"\n").split(b" ")
            if len(trees) != 2 or (trees[0] != b"ROOT" and re.fullmatch(rb"[0-9a-f]{40}", trees[0]) is None) or re.fullmatch(rb"[0-9a-f]{40}", trees[1]) is None:
                raise InventoryError("INVALID_PAIR_TREES")
            if (parent is None) != (trees[0] == b"ROOT"):
                raise InventoryError("ROOT_PAIR_MISMATCH")
            if current is not None:
                yield current
            current = {"commit": child, "parent": parent, "old_tree": trees[0].decode() if parent is not None else None, "new_tree": trees[1].decode(), "changes": []}
            continue
        if first != b":" or current is None:
            raise InventoryError("UNFRAMED_PARENT_DIFF")
        header = first + _nul(stream)
        match = re.fullmatch(rb":([0-7]{6}) ([0-7]{6}) ([0-9a-f]{40}) ([0-9a-f]{40}) ([ACDMRTUXB][0-9]*)", header)
        if match is None:
            raise InventoryError("INVALID_RAW_DIFF_HEADER")
        path = _nul(stream)
        if not path:
            raise InventoryError("EMPTY_GIT_PATH")
        change = {"old_mode": match[1].decode(), "new_mode": match[2].decode(), "before": match[3].decode(), "after": match[4].decode(), "status": match[5].decode(), **_path(path)}
        if match[5][:1] in (b"R", b"C"):
            change.update(_path(path, "old_path"))
            following = _nul(stream)
            if not following:
                raise InventoryError("EMPTY_GIT_PATH")
            change.update(_path(following))
        current["changes"].append(change)


def _nul(stream):
    value = bytearray()
    while True:
        byte = stream.read(1)
        if not byte:
            raise InventoryError("TRUNCATED_NUL_RECORD")
        if byte == b"\0":
            return bytes(value)
        value += byte


def _path(raw, key="path"):
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        text = None
    return {key: text, key + "_b64": base64.b64encode(raw).decode("ascii")}


def _git(repo, *args, data=None, output=None, timeout=300):
    try:
        result = subprocess.run(["git", "--no-pager", "--no-optional-locks", "-C", str(repo), *args], input=data, stdin=None if data is not None else subprocess.DEVNULL, stdout=output if output is not None else subprocess.PIPE, stderr=subprocess.PIPE, env=clean_git_env(), timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InventoryError("GIT_UNAVAILABLE_OR_TIMEOUT") from exc
    if result.returncode:
        raise InventoryError(f"GIT_COMMAND_FAILED:{args[0]}:{result.returncode}")
    return result.stdout


def _scalar(repo, *args):
    return _git(repo, *args).decode("ascii").strip()


def _metadata_rows(repo, base, end):
    raw = _git(repo, "log", "--no-show-signature", "--no-decorate", "--reverse", "--topo-order", "-z", "--format=%H%x00%P%x00%T%x00%s%x00", f"{base}..{end}", "--")
    rows = []
    fields = raw.split(b"\0") if raw else [b""]
    if fields.pop() != b"" or len(fields) % 5:
        raise InventoryError("INVALID_COMMIT_METADATA")
    for offset in range(0, len(fields), 5):
        if fields[offset + 4] != b"":
            raise InventoryError("INVALID_COMMIT_SEPARATOR")
        sha, parents, tree = (field.decode("ascii") for field in fields[offset:offset + 3])
        subject = _path(fields[offset + 3], "subject")
        rows.append({"commit": validate_sha(sha), "parents": [validate_sha(p) for p in parents.split()], "tree": validate_sha(tree), **subject, "disposition": "UNASSESSED", "semantic_review_status": "UNREVIEWED"})
    if len({row["commit"] for row in rows}) != len(rows):
        raise InventoryError("DUPLICATE_COMMIT_METADATA")
    return rows


def _tree_paths(repo, commit):
    values = {}
    for record in _git(repo, "ls-tree", "-r", "--full-tree", "-z", commit).split(b"\0"):
        if not record:
            continue
        header, path = record.split(b"\t", 1)
        mode, kind, oid = header.split(b" ")
        values[path] = {"mode": mode.decode(), "kind": kind.decode(), "oid": validate_sha(oid.decode())}
    return values


def _signature(changes, inverse=False):
    rows = []
    for change in changes:
        before = (change["old_mode"], change["before"], change.get("old_path_b64", change["path_b64"]))
        after = (change["new_mode"], change["after"], change["path_b64"])
        rows.append((after, before) if inverse else (before, after))
    return hashlib.sha256(json.dumps(sorted(rows), separators=(",", ":")).encode()).hexdigest()


def _describe(edge, final_paths):
    removed, added = defaultdict(list), defaultdict(list)
    tags = set()
    for change in edge["changes"]:
        path = base64.b64decode(change["path_b64"])
        final = final_paths.get(path)
        change["stable_path_observation"] = "ABSENT" if final is None else (
            "REINTRODUCED" if change["after"] == "0" * 40 else
            "EXACT_OBJECT" if final["oid"] == change["after"] and final["mode"] == change["new_mode"] else "CHANGED_OBJECT"
        )
        if change["status"] == "D":
            removed[change["old_mode"], change["before"]].append(change["path_b64"])
        if change["status"] == "A":
            added[change["new_mode"], change["after"]].append(change["path_b64"])
        text = change["path"] or ""
        prefix = text.split("/", 1)[0]
        if prefix in {"tests", "tests-js"}:
            tags.add("TEST_PATH")
        elif prefix in {"docs", "_docs", "website"} or text.endswith(".md"):
            tags.add("DOC_PATH")
        elif text.rsplit("/", 1)[-1] in {"uv.lock", "pyproject.toml", "package.json", "package-lock.json", "go.mod", "go.sum", "Cargo.toml", "Cargo.lock"}:
            tags.add("DEPENDENCY_PATH")
        else:
            tags.add("SOURCE_OR_OTHER_PATH")
        if any(word in text.lower() for word in ("oauth", "auth", "security", "approval", "credential", "sandbox")):
            tags.add("SECURITY_REVIEW_CUE_NOT_A_VERDICT")
        if "windows" in text.lower() or "win_pty" in text.lower() or text.endswith(".ps1"):
            tags.add("WINDOWS_PATH")
    edge["exact_blob_moves"] = [{"mode": mode, "blob": oid, "old_paths_b64": sorted(removed[mode, oid]), "new_paths_b64": sorted(added[mode, oid])} for mode, oid in sorted(removed.keys() & added.keys())]
    edge["surface_tags"] = sorted(tags) if tags else ["EMPTY_PARENT_DIFF"]
    edge["delta_sha256"] = _signature(edge["changes"])
    edge["inverse_delta_sha256"] = _signature(edge["changes"], inverse=True)
    return edge


def generate(repo, base, end, expected_tree, output):
    repo, output = Path(repo).resolve(strict=True), Path(output).resolve(strict=False)
    base, end, expected_tree = (validate_sha(value) for value in (base, end, expected_tree))
    if output == repo or output.is_relative_to(repo):
        raise InventoryError("OUTPUT_INSIDE_REFERENCE_REPOSITORY")
    if output.exists() and any(output.iterdir()):
        raise InventoryError("OUTPUT_EXISTS_REFUSE_OVERWRITE")
    if _scalar(repo, "rev-parse", "--is-shallow-repository") != "false":
        raise InventoryError("HISTORY_INCOMPLETE:shallow")
    for sha in (base, end):
        if _scalar(repo, "rev-parse", "--verify", sha + "^{commit}") != sha:
            raise InventoryError("FROZEN_COMMIT_MISMATCH")
    if _scalar(repo, "rev-parse", end + "^{tree}") != expected_tree:
        raise InventoryError("FROZEN_TREE_MISMATCH")
    rows = _metadata_rows(repo, base, end)
    expected_count = int(_scalar(repo, "rev-list", "--count", f"{base}..{end}"))
    if len(rows) != expected_count:
        raise InventoryError("COMMIT_COUNT_MISMATCH")
    trees = {row["commit"]: row["tree"] for row in rows}
    missing = sorted({parent for row in rows for parent in row["parents"]} - trees.keys())
    if missing:
        for line in _git(repo, "log", "--no-show-signature", "--no-walk=unsorted", "--format=%H %T", "--stdin", data="".join(sha + "\n" for sha in missing).encode()).splitlines():
            sha, tree = line.decode("ascii").split()
            trees[validate_sha(sha)] = validate_sha(tree)
        if any(sha not in trees for sha in missing):
            raise InventoryError("MISSING_PARENT_OBJECT")
    final_paths = _tree_paths(repo, end)
    output.mkdir(parents=True, exist_ok=True)
    payload, roots, expected_edges = bytearray(), [], []
    for row in rows:
        if not row["parents"]:
            roots.append(row)
            expected_edges.append((row["commit"], None))
        for parent in row["parents"]:
            expected_edges.append((row["commit"], parent))
            payload.extend(f"PAIR {row['commit']} {parent}\n{trees[parent]} {row['tree']}\n".encode("ascii"))
    raw_path = output / "parent-diffs.raw"
    with raw_path.open("wb") as stream:
        if payload:
            _git(repo, "diff-tree", "--stdin", "-r", "--raw", "-z", "--no-commit-id", "--no-renames", "--no-ext-diff", "--no-textconv", "--abbrev=40", data=bytes(payload), output=stream, timeout=900)
        for row in roots:
            stream.write(f"PAIR {row['commit']} ROOT\nROOT {row['tree']}\n".encode("ascii"))
            stream.flush()
            _git(repo, "diff-tree", "--root", "-r", "--raw", "-z", "--no-commit-id", "--no-renames", "--no-ext-diff", "--no-textconv", "--abbrev=40", row["commit"], output=stream)
    edges = {}
    with raw_path.open("rb") as stream:
        for edge in parse_pair_stream(stream):
            edges[edge["commit"], edge["parent"]] = _describe(edge, final_paths)
    if set(edges) != set(expected_edges):
        raise InventoryError("PARENT_EDGE_COUNT_MISMATCH")
    signatures, category_counts, observations = defaultdict(list), Counter(), Counter()
    with (output / "history-index.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            row["parent_diffs"] = [edges[row["commit"], parent] for parent in row["parents"] or [None]]
            for edge in row["parent_diffs"]:
                if edge["changes"]:
                    edge["exact_inverse_candidates"] = list(signatures[edge["inverse_delta_sha256"]])
                    edge["exact_reapply_candidates"] = list(signatures[edge["delta_sha256"]])
                    signatures[edge["delta_sha256"]].append({"commit": row["commit"], "parent": edge["parent"]})
                category_counts.update(edge["surface_tags"])
                observations.update(change["stable_path_observation"] for change in edge["changes"])
            stream.write(json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
    first_parent = _git(repo, "rev-list", "--first-parent", "--reverse", f"{base}..{end}")
    (output / "first-parent.txt").write_bytes(first_parent)
    files = {}
    for name in ("parent-diffs.raw", "history-index.jsonl", "first-parent.txt"):
        path = output / name
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        files[name] = {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}
    result = {"schema_version": 1, "status": "PARENT_PATH_BLOB_ENUMERATED_NOT_SEMANTICALLY_REVIEWED", "base": base, "end": end, "tree": expected_tree, "commit_count": len(rows), "parent_edge_count": len(edges), "root_edge_count": len(roots), "empty_parent_edge_count": sum(not edge["changes"] for edge in edges.values()), "first_parent_count": len(first_parent.splitlines()), "parent_edges_complete": True, "semantic_review_complete": False, "unassessed_commit_count": len(rows), "surface_tags_are_triage_only": True, "path_surface_edge_counts": dict(sorted(category_counts.items())), "stable_path_observations": dict(sorted(observations.items())), "files": files, "rename_policy": "No heuristic rename limit; exact blob relocation candidates retain all raw paths. Other renames remain unreviewed.", "raw_path_encoding": "Authoritative base64 bytes plus nullable strict UTF-8 display; NUL framed", "operator_config_or_runtime_accessed": False}
    (output / "inventory-completeness.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "base", "end", "expected-tree", "output"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    result = generate(args.repo, args.base, args.end, args.expected_tree, args.output)
    print(json.dumps({key: result[key] for key in ("status", "commit_count", "parent_edge_count", "empty_parent_edge_count", "first_parent_count")}))


if __name__ == "__main__":
    main()

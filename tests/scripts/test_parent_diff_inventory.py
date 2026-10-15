"""Frozen full-DAG enumeration, including empty merge parents and raw paths."""
import base64
import importlib.util
import io
import json
from pathlib import Path
import subprocess

import pytest

MODULE = Path(__file__).resolve().parents[2] / "docs/windows/v0222-release-baseline-20261015/tools/parent_diff_inventory.py"
SPEC = importlib.util.spec_from_file_location("parent_diff_inventory", MODULE)
inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(inventory)
A, B, C, D = (letter * 40 for letter in "abcd")


def pair(child=A, parent=B, old_tree=C, new_tree=D):
    return f"PAIR {child} {parent}\n{old_tree} {new_tree}\n".encode("ascii")


def raw(path, status="M", before=C, after=D):
    return f":100644 100644 {before} {after} {status}\0".encode("ascii") + path + b"\0"


def test_empty_parent_is_retained_and_paths_are_nul_delimited():
    name = "日本語 folder/line\nbreak.py".encode("utf-8")
    unusual = b"odd-\xff.bin"
    stream = pair() + pair(child=B, parent=C) + raw(name) + raw(unusual)
    rows = list(inventory.parse_pair_stream(io.BytesIO(stream)))
    assert len(rows) == 2 and rows[0]["changes"] == []
    assert rows[1]["changes"][0]["path"] == name.decode("utf-8")
    assert base64.b64decode(rows[1]["changes"][1]["path_b64"]) == unusual
    assert rows[1]["changes"][1]["path"] is None


def test_rename_records_keep_both_raw_paths():
    data = pair() + raw(b"from\nname", "R100") + b"to\tname\0"
    change = list(inventory.parse_pair_stream(io.BytesIO(data)))[0]["changes"][0]
    assert change["old_path"] == "from\nname" and change["path"] == "to\tname"


@pytest.mark.parametrize("data", [pair() + raw(b"x")[:-1], pair() + b":broken\0x\0", pair() + pair(), b"unexpected\n", pair().replace(A.encode(), b"not-a-sha", 1)])
def test_malformed_or_duplicate_records_fail_closed(data):
    with pytest.raises(inventory.InventoryError):
        list(inventory.parse_pair_stream(io.BytesIO(data)))


@pytest.fixture
def history(tmp_path):
    repo = tmp_path / "reference.git"
    repo.mkdir()
    def git(*args, data=None):
        return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "-c", "commit.gpgSign=false", "-C", str(repo), *args], input=data, env=inventory.clean_git_env(), stderr=subprocess.PIPE)
    git("init", "--bare", "-q")
    blob = git("hash-object", "-w", "--stdin", data=b"fixture\n").strip()
    def tree(path):
        return git("mktree", "-z", data=b"100644 blob " + blob + b"\t" + path + b"\0").decode().strip()
    old_tree, new_tree = tree(b"old.py"), tree("日本語 folder\n.py".encode("utf-8"))
    def commit(tree_id, parents=(), subject="fixture"):
        args = ["commit-tree", tree_id]
        for parent in parents:
            args += ["-p", parent]
        return git(*args, data=(subject + "\n").encode()).decode().strip()
    base = commit(old_tree)
    left = commit(new_tree, [base], "move exact blob")
    right = commit(old_tree, [base], "fix security misleading empty commit")
    merge = commit(new_tree, [left, right], "preserve first parent tree")
    return repo, git, base, left, right, merge, new_tree


def test_complete_dag_has_each_merge_parent_including_equal_tree(history, tmp_path):
    repo, git, base, left, right, merge, tree = history
    before = git("for-each-ref")
    result = inventory.generate(repo, base, merge, tree, tmp_path / "out")
    rows = [json.loads(line) for line in (tmp_path / "out/history-index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert result["commit_count"] == 3 and result["parent_edge_count"] == 4
    assert result["parent_edges_complete"] is True and result["semantic_review_complete"] is False
    assert {row["commit"] for row in rows} == {left, right, merge}
    merged = next(row for row in rows if row["commit"] == merge)
    assert [edge["parent"] for edge in merged["parent_diffs"]] == [left, right]
    assert merged["parent_diffs"][0]["changes"] == []
    assert merged["parent_diffs"][1]["exact_blob_moves"], "exact identity relocation must be visible without rename heuristics"
    assert all(row["disposition"] == "UNASSESSED" for row in rows)
    assert git("for-each-ref") == before


def test_deleted_path_final_tree_is_explicit(history, tmp_path):
    repo, _git, _base, _left, right, merge, tree = history
    inventory.generate(repo, right, merge, tree, tmp_path / "out")
    rows = [json.loads(line) for line in (tmp_path / "out/history-index.jsonl").read_text(encoding="utf-8").splitlines()]
    deleted = [change for row in rows for edge in row["parent_diffs"] for change in edge["changes"] if change["status"] == "D"]
    assert deleted and all(change["stable_path_observation"] == "ABSENT" for change in deleted)


def test_unrelated_root_parent_is_included_without_writing_reference_refs(history, tmp_path):
    repo, git, base, left, _right, _merge, tree = history
    orphan = git("commit-tree", tree, data=b"unrelated root\n").decode().strip()
    merged = git("commit-tree", tree, "-p", left, "-p", orphan, data=b"join histories\n").decode().strip()
    out = tmp_path / "out"
    result = inventory.generate(repo, base, merged, tree, out)
    rows = [json.loads(line) for line in (out / "history-index.jsonl").read_text(encoding="utf-8").splitlines()]
    root = next(row for row in rows if row["commit"] == orphan)
    assert root["parents"] == [] and root["parent_diffs"][0]["parent"] is None
    assert root["parent_diffs"][0]["changes"]
    assert result["root_edge_count"] == 1


def test_inverse_and_reapply_are_blob_candidates_not_semantic_acceptance(history, tmp_path):
    repo, git, base, left, _right, _merge, tree = history
    base_tree = git("rev-parse", base + "^{tree}").decode().strip()
    reverted = git("commit-tree", base_tree, "-p", left, data=b"not named revert\n").decode().strip()
    reapplied = git("commit-tree", tree, "-p", reverted, data=b"not named reapply\n").decode().strip()
    out = tmp_path / "out"
    inventory.generate(repo, base, reapplied, tree, out)
    rows = [json.loads(line) for line in (out / "history-index.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[1]["parent_diffs"][0]["exact_inverse_candidates"] == [{"commit": left, "parent": base}]
    assert rows[2]["parent_diffs"][0]["exact_reapply_candidates"] == [{"commit": left, "parent": base}]
    assert all(row["semantic_review_status"] == "UNREVIEWED" for row in rows)


def test_wrong_tree_and_shallow_inputs_do_not_publish(history, tmp_path):
    repo, _git, base, _left, _right, merge, tree = history
    out = tmp_path / "out"
    with pytest.raises(inventory.InventoryError, match="TREE"):
        inventory.generate(repo, base, merge, A, out)
    assert not out.exists()
    (repo / "shallow").write_text(base + "\n", encoding="utf-8")
    with pytest.raises(inventory.InventoryError, match="shallow"):
        inventory.generate(repo, base, merge, tree, out)
    assert not out.exists()


def test_existing_output_is_never_overwritten(history, tmp_path):
    repo, _git, base, _left, _right, merge, tree = history
    out = tmp_path / "out"
    out.mkdir()
    marker = out / "operator.txt"
    marker.write_text("preserve", encoding="utf-8")
    with pytest.raises(inventory.InventoryError, match="OUTPUT"):
        inventory.generate(repo, base, merge, tree, out)
    assert marker.read_text(encoding="utf-8") == "preserve"


def test_reference_repository_cannot_be_used_as_output(history):
    repo, _git, base, _left, _right, merge, tree = history
    with pytest.raises(inventory.InventoryError, match="INSIDE_REFERENCE"):
        inventory.generate(repo, base, merge, tree, repo / "accidental-output")
    assert not (repo / "accidental-output").exists()

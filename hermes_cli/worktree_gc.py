"""On-demand worktree + branch reclaim (``hermes worktree`` / ``/worktree prune``).

The startup pruner in ``cli._prune_stale_worktrees`` is deliberately
conservative and silent: it runs before the banner on every ``hermes -w``
launch, so it only reaps clean, fully-merged scratch trees past an age tier
and preserves everything else. That policy is correct for an unattended
startup path — but it means real installs accumulate two kinds of debris the
startup pass can never touch:

- **Preserved trees** whose only "dirt" is untracked scratch (PR body drafts,
  logs) on an otherwise merged branch — preserved forever by the dirty guard.
- **Orphaned local branches** beyond the two auto-generated prefixes the
  startup pass deletes (``hermes/hermes-*``, ``pr-*``): salvage lanes, port
  branches, feature branches whose PRs merged months ago. Multi-agent boxes
  reach hundreds.

This module is the *attended* counterpart: an explicit, loud, dry-run-first
reclaim the user invokes, so it can be more thorough while staying just as
safe. Invariants shared with the startup pruner (never violated here either):

- tracked modifications are NEVER deleted, at any age, in any mode;
- unique unpushed commits are NEVER deleted (``git cherry`` patch-equivalence
  decides "unique"; shallow repos are deepened bloblessly first so the
  verdict is trustworthy);
- live-locked trees (owning pid alive) are never touched;
- a branch is deleted only after its worktree removal succeeded — a failed
  removal must not orphan reachable commits;
- untracked-only dirt is ARCHIVED to ``~/.hermes/archive/worktree-prune/``
  before its tree is reaped, never destroyed.

Classification primitives are imported from ``cli`` so the two paths can
never drift apart on what "dirty", "unpushed", or "merged" means.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

# Branches never considered for deletion, in any mode.
_PROTECTED_BRANCHES = {"main", "master", "develop", "dev", "trunk"}

# Trees owned by another lifecycle (kanban dispatcher gc) — never touched.
_KANBAN_RE = re.compile(r"^t_[0-9a-f]+$")

# Bounded cherry probe: a branch this far ahead of upstream is a stale-base
# lane, not merged scratch; checking it is expensive and it stays preserved.
_MAX_CHERRY_AHEAD = 50


@dataclass
class TreeRecord:
    name: str
    path: str
    branch: str
    age_days: float
    size_mb: Optional[int]
    verdict: str          # reap | reap-archive | keep
    reason: str
    untracked: List[str] = field(default_factory=list)
    head_oid: str = ""


@dataclass
class BranchRecord:
    name: str
    verdict: str          # delete | keep
    reason: str
    tip_oid: str = ""


def _git(args: list, cwd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run git, translating timeouts into a nonzero returncode.

    Every verdict in this module fails safe toward "keep" on a nonzero
    returncode, so a hung/slow git call (large repos make ``git cherry``
    genuinely slow) must degrade to keep — never crash the whole audit
    (live-verified failure on a 746MB .git: TimeoutExpired escaped and
    aborted the branch audit mid-list).
    """
    from hermes_cli._subprocess_compat import run_internal_git

    return run_internal_git(args, cwd, timeout=timeout)


def _gh(args: list, cwd: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run gh with the same fail-closed timeout contract as git."""
    from hermes_cli._subprocess_compat import run_internal_gh
    return run_internal_gh(args, cwd, timeout=timeout)


def _oid(ref: str, cwd: str) -> str:
    result = _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], cwd=cwd, timeout=5)
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch_pr_merged_at_tip(tree_path: str, branch: str, tip_oid: str) -> bool:
    """Accept a merged PR only when its recorded head is this exact tip.

    A branch name is reusable.  A historical merged PR with the same name is
    therefore not evidence that the current branch contents landed.
    """
    if not branch or not tip_oid:
        return False
    published = _git(
        ["for-each-ref", "--format=%(refname:strip=3)", "refs/remotes"],
        cwd=tree_path, timeout=5,
    )
    if published.returncode != 0 or branch not in published.stdout.splitlines():
        return False
    result = _gh(
        ["pr", "list", "--head", branch, "--state", "merged", "--json",
         "headRefOid", "--limit", "20"],
        cwd=tree_path,
    )
    if result.returncode != 0:
        return False
    try:
        prs = json.loads(result.stdout or "[]")
        return isinstance(prs, list) and any(
            isinstance(pr, dict) and pr.get("headRefOid") == tip_oid for pr in prs
        )
    except (TypeError, ValueError):
        return False


def _tree_size_mb(path: Path) -> Optional[int]:
    """Cheap directory size via ``du -sm`` — best-effort, None on failure."""
    try:
        result = subprocess.run(
            ["du", "-sm", str(path)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.split()[0])
    except Exception:
        pass
    return None


def _dirty_split(path: str) -> tuple[bool, List[str]]:
    """Return (has_tracked_modifications, untracked_paths).

    ``git status --porcelain`` counts untracked scratch equally with real
    edits; the reclaim policy treats them very differently (tracked = real
    work, untracked = archivable scratch), so split here.
    """
    try:
        result = _git(["status", "--porcelain"], cwd=path, timeout=10)
        if result.returncode != 0:
            return True, []  # fail safe: treat as real work
        tracked = False
        untracked: List[str] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            if line.startswith("??"):
                untracked.append(line[3:].strip())
            else:
                tracked = True
        return tracked, untracked
    except Exception:
        return True, []


def _archive_untracked(tree: Path, untracked: List[str]) -> Optional[Path]:
    """Move untracked files out of a doomed tree. Returns the archive dir.

    Never destroys: on any move failure the caller must treat the tree as
    keep. Costs almost nothing and removes the "did I just delete
    something?" question.
    """
    stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.time_ns()}"
    dest = (
        Path.home() / ".hermes" / "archive" / "worktree-prune"
        / f"{tree.name}-{stamp}"
    )
    moved: List[tuple[Path, Path]] = []
    try:
        for rel in untracked:
            src = tree / rel
            if not src.exists() and not src.is_symlink():
                raise FileNotFoundError(f"untracked archive source disappeared: {src}")
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(target))
            moved.append((src, target))
        return dest if dest.exists() else None
    except Exception as exc:
        logger.warning("Could not archive untracked files from %s: %s", tree, exc)
        # A cross-device shutil.move can raise after creating the target and
        # removing the source. Include that partially completed current entry
        # in rollback even though the call never returned normally.
        try:
            if ((not src.exists() and not src.is_symlink())
                    and (target.exists() or target.is_symlink())
                    and (src, target) not in moved):
                moved.append((src, target))
        except UnboundLocalError:
            pass
        rollback_failures: List[str] = []
        for src, target in reversed(moved):
            try:
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(src))
            except Exception as rollback_exc:
                rollback_failures.append(f"{target} -> {src}: {rollback_exc}")
        if rollback_failures:
            logger.error(
                "Archive rollback from %s was incomplete; preserved copies remain "
                "under %s: %s",
                tree, dest, "; ".join(rollback_failures),
            )
        return None


def audit_worktrees(
    repo_root: str,
    *,
    with_sizes: bool = True,
    allow_deepen: bool = False,
    allow_cache_write: bool = False,
) -> List[TreeRecord]:
    """Classify every tree under ``.worktrees/``.

    The default is genuinely read-only for ``list`` and dry-run callers:
    shallow history is not fetched and the merge cache is not persisted.
    Mutation requires an explicit opt-in from a non-dry-run reclaim path.
    """
    import cli as _cli  # lazy: cli.py is heavy

    worktrees_dir = Path(repo_root) / ".worktrees"
    if not worktrees_dir.exists():
        return []

    shallow = _cli._repo_is_shallow(repo_root)
    if shallow and allow_deepen:
        _cli._deepen_shallow_repo(repo_root)
        shallow = _cli._repo_is_shallow(repo_root)

    merge_cache = _cli._load_worktree_merge_cache()
    cache_size_before = len(merge_cache)

    now = time.time()
    records: List[TreeRecord] = []
    for entry in sorted(worktrees_dir.iterdir()):
        if not entry.is_dir():
            continue
        try:
            age_days = (now - entry.stat().st_mtime) / 86400.0
        except Exception:
            continue
        size_mb = _tree_size_mb(entry) if with_sizes else None

        try:
            branch_result = _git(["branch", "--show-current"], cwd=str(entry), timeout=5)
            branch = branch_result.stdout.strip()
        except Exception:
            branch = ""
        head_oid = _oid("HEAD", str(entry))

        def rec(verdict: str, reason: str, untracked: Optional[List[str]] = None):
            records.append(TreeRecord(
                name=entry.name, path=str(entry), branch=branch,
                age_days=age_days, size_mb=size_mb,
                verdict=verdict, reason=reason,
                untracked=untracked or [],
                head_oid=head_oid,
            ))

        if _KANBAN_RE.match(entry.name):
            rec("keep", "kanban task tree (owned by kanban gc)")
            continue

        if not head_oid:
            rec("keep", "could not resolve worktree HEAD")
            continue

        lock_state = _cli._worktree_lock_is_live(repo_root, str(entry), timeout=5)
        if lock_state == "live":
            rec("keep", "in use by a running hermes session")
            continue

        tracked_dirty, untracked = _dirty_split(str(entry))
        if tracked_dirty:
            rec("keep", "uncommitted tracked changes (real work)")
            continue

        if _cli._worktree_has_unpushed_commits(str(entry), timeout=5):
            if shallow:
                rec("keep", "shallow history; cannot verify merged commits read-only")
                continue
            merged = _cli._worktree_commits_all_merged_upstream(
                str(entry), timeout=30, cache=merge_cache,
                max_ahead=_MAX_CHERRY_AHEAD,
            )
            if not merged:
                merged = _branch_pr_merged_at_tip(
                    str(entry), branch, head_oid,
                )
                if not merged:
                    rec("keep", "unpushed commits not found upstream")
                    continue

        if untracked:
            rec("reap-archive",
                f"merged/pushed; {len(untracked)} untracked file(s) will be archived",
                untracked)
        else:
            rec("reap", "clean and fully merged/pushed")

    if allow_cache_write and len(merge_cache) != cache_size_before:
        _cli._save_worktree_merge_cache(merge_cache)
    return records


def _tree_revalidation_failure(
    repo_root: str,
    record: TreeRecord,
    *,
    expected_untracked: Optional[List[str]] = None,
) -> Optional[str]:
    """Return why an audited tree is no longer safe, else ``None``.

    This intentionally recomputes every mutable safety input.  Audit output is
    presentation state, not authority to delete later.
    """
    import cli as _cli

    entry = Path(record.path)
    if not entry.is_dir():
        return "worktree path disappeared"
    branch_result = _git(["branch", "--show-current"], cwd=record.path, timeout=5)
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else ""
    head_oid = _oid("HEAD", record.path)
    if not head_oid or head_oid != record.head_oid or branch != record.branch:
        return "HEAD or branch changed after audit"

    tracked_dirty, untracked = _dirty_split(record.path)
    if tracked_dirty:
        return "tracked changes appeared after audit"
    expected = record.untracked if expected_untracked is None else expected_untracked
    if sorted(untracked) != sorted(expected):
        return "untracked files changed after audit"

    if _cli._worktree_lock_is_live(repo_root, record.path, timeout=5) == "live":
        return "worktree became live-locked after audit"

    if _cli._worktree_has_unpushed_commits(record.path, timeout=5):
        merged = _cli._worktree_commits_all_merged_upstream(
            record.path, timeout=30, cache=None, max_ahead=_MAX_CHERRY_AHEAD,
        )
        if not merged:
            merged = _branch_pr_merged_at_tip(record.path, branch, head_oid)
        if not merged:
            return "unique or unmerged commits appeared after audit"

    # Close ref movement during the checks above as far as git's non-atomic
    # worktree API permits. Any later branch movement is caught again before
    # branch deletion, after the tree itself is removed.
    if _oid("HEAD", record.path) != record.head_oid:
        return "HEAD changed during safety revalidation"
    return None


def _branch_revalidation_failure(repo_root: str, record: BranchRecord) -> Optional[str]:
    """Recompute branch reachability and checkout state just before delete."""
    if record.name in _PROTECTED_BRANCHES:
        return "branch is protected"
    if not record.tip_oid or _oid(record.name, repo_root) != record.tip_oid:
        return "branch tip changed after audit"

    wt = _git(["worktree", "list", "--porcelain"], cwd=repo_root, timeout=10)
    if wt.returncode != 0:
        return "could not verify checked-out branches"
    active = {
        line.split("branch refs/heads/", 1)[-1].strip()
        for line in wt.stdout.splitlines()
        if line.startswith("branch refs/heads/")
    }
    if record.name in active:
        return "branch became checked out after audit"

    upstream = next((candidate for candidate in ("origin/HEAD", "origin/main", "origin/master")
                     if _oid(candidate, repo_root)), None)
    if upstream is None:
        return "could not resolve upstream"

    ancestor = _git(
        ["merge-base", "--is-ancestor", record.name, upstream],
        cwd=repo_root, timeout=10,
    )
    safe = ancestor.returncode == 0
    if not safe:
        ahead = _git(
            ["rev-list", "--count", f"{upstream}..{record.name}"],
            cwd=repo_root, timeout=10,
        )
        try:
            ahead_count = int(ahead.stdout.strip()) if ahead.returncode == 0 else -1
        except ValueError:
            ahead_count = -1
        if ahead_count == 0:
            safe = True
        elif 0 < ahead_count <= _MAX_CHERRY_AHEAD:
            cherry = _git(["cherry", upstream, record.name], cwd=repo_root, timeout=30)
            lines = [line for line in cherry.stdout.splitlines() if line.strip()]
            safe = cherry.returncode == 0 and bool(lines) and all(
                line.startswith("-") for line in lines
            )
    if not safe:
        return "branch is no longer fully merged or patch-equivalent upstream"
    if _oid(record.name, repo_root) != record.tip_oid:
        return "branch tip changed during safety revalidation"
    return None


def _delete_branch_atomic(repo_root: str, record: BranchRecord) -> subprocess.CompletedProcess:
    """Delete only the exact ref value that passed safety revalidation."""
    return _git(
        ["update-ref", "-d", f"refs/heads/{record.name}", record.tip_oid],
        cwd=repo_root, timeout=10,
    )


def reclaim_worktrees(
    repo_root: str,
    *,
    dry_run: bool = False,
    records: Optional[List[TreeRecord]] = None,
) -> List[str]:
    """Remove every reap-verdict tree from a frozen audit list.

    Operates ONLY on the provided (or freshly computed) audit records — never
    re-globs inside the destructive loop, so trees created by concurrent
    sessions after the audit are out of scope by construction.
    """
    if records is None:
        import cli as _cli

        if not dry_run and _cli._repo_is_shallow(repo_root):
            _cli._deepen_shallow_repo(repo_root)
        records = audit_worktrees(
            repo_root, with_sizes=False, allow_cache_write=not dry_run,
        )
    elif not dry_run:
        import cli as _cli

        # Deepening is allowed for an attended destructive run, but it must
        # never replace the caller's frozen scope with a fresh directory glob.
        if _cli._repo_is_shallow(repo_root):
            _cli._deepen_shallow_repo(repo_root)
    actions: List[str] = []
    for record in records:
        if record.verdict not in {"reap", "reap-archive"}:
            continue
        if dry_run:
            actions.append(f"would remove {record.name} ({record.reason})")
            continue

        entry = Path(record.path)
        archived = False
        failure = _tree_revalidation_failure(repo_root, record)
        if failure:
            actions.append(f"kept {record.name} ({failure})")
            continue
        if record.verdict == "reap-archive" and record.untracked:
            archive = _archive_untracked(entry, record.untracked)
            if archive is None:
                actions.append(f"kept {record.name} (archive of untracked files failed)")
                continue
            actions.append(f"archived {len(record.untracked)} untracked file(s) → {archive}")
            archived = True

        failure = _tree_revalidation_failure(
            repo_root, record, expected_untracked=[] if archived else None,
        )
        if failure:
            actions.append(f"kept {record.name} ({failure})")
            continue

        # Dead-pid locks must be unlocked before ordinary remove can proceed.
        # Do not use --force: Git's own last-moment dirty guard closes the
        # remaining race after our explicit revalidation.
        try:
            _git(["worktree", "unlock", record.path], cwd=repo_root, timeout=10)
        except Exception:
            pass

        failure = _tree_revalidation_failure(
            repo_root, record, expected_untracked=[] if archived else None,
        )
        if failure:
            actions.append(f"kept {record.name} ({failure})")
            continue

        try:
            remove_result = _git(
                ["worktree", "remove", record.path],
                cwd=repo_root, timeout=30,
            )
            if remove_result.returncode != 0:
                actions.append(
                    f"failed to remove {record.name}: {remove_result.stderr.strip()}"
                )
                continue
            if record.branch and record.branch not in _PROTECTED_BRANCHES:
                branch_record = BranchRecord(
                    record.branch, "delete", "worktree was safely reclaimed",
                    tip_oid=record.head_oid,
                )
                branch_failure = _branch_revalidation_failure(repo_root, branch_record)
                if branch_failure:
                    actions.append(
                        f"kept branch {record.branch} ({branch_failure})"
                    )
                else:
                    branch_delete = _delete_branch_atomic(repo_root, branch_record)
                    if branch_delete.returncode != 0:
                        actions.append(
                            f"failed to delete {record.branch}: "
                            f"{branch_delete.stderr.strip()}"
                        )
            actions.append(f"removed {record.name}")
        except Exception as exc:
            actions.append(f"failed to remove {record.name}: {exc}")

    if not dry_run:
        try:
            _git(["worktree", "prune"], cwd=repo_root, timeout=15)
        except Exception:
            pass
    return actions


def audit_branches(repo_root: str, *, allow_deepen: bool = False) -> List[BranchRecord]:
    """Classify local branches: safe to delete when their content is on
    upstream (fully merged OR every commit patch-equivalent via ``git
    cherry``) and they are not checked out anywhere.

    Generalizes the startup pass's prefix list (``hermes/hermes-*``/``pr-*``)
    to EVERY local branch, because deletion is gated on content reachability
    rather than name: a branch whose commits are all upstream loses nothing
    when its ref goes. Branch names checked out in any worktree, protected
    names, and branches with unique commits are kept.
    """
    import cli as _cli

    shallow = _cli._repo_is_shallow(repo_root)
    if shallow and allow_deepen:
        _cli._deepen_shallow_repo(repo_root)
        shallow = _cli._repo_is_shallow(repo_root)

    upstream = None
    for candidate in ("origin/HEAD", "origin/main", "origin/master"):
        probe = _git(["rev-parse", "--verify", "--quiet", candidate], cwd=repo_root, timeout=5)
        if probe.returncode == 0:
            upstream = candidate
            break
    if upstream is None:
        return []

    result = _git(["branch", "--format=%(refname:short)"], cwd=repo_root, timeout=10)
    if result.returncode != 0:
        return []
    branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]

    if shallow:
        return [
            BranchRecord(
                branch, "keep", "shallow history; cannot verify reachability read-only",
                _oid(branch, repo_root),
            )
            for branch in branches
        ]

    active: set = set()
    wt = _git(["worktree", "list", "--porcelain"], cwd=repo_root, timeout=10)
    for line in wt.stdout.splitlines():
        if line.startswith("branch refs/heads/"):
            active.add(line.split("branch refs/heads/", 1)[-1].strip())

    merged_result = _git(["branch", "--merged", upstream, "--format=%(refname:short)"],
                         cwd=repo_root, timeout=15)
    merged = {b.strip() for b in merged_result.stdout.splitlines() if b.strip()}

    def _classify_branch(branch: str) -> BranchRecord:
        tip_oid = _oid(branch, repo_root)
        if not tip_oid:
            return BranchRecord(branch, "keep", "could not resolve branch tip")
        if branch in _PROTECTED_BRANCHES or branch in active:
            return BranchRecord(branch, "keep", "protected or checked out", tip_oid)
        if branch in merged:
            return BranchRecord(branch, "delete", "fully merged into " + upstream, tip_oid)
        # Rebase merges rewrite SHAs, so --merged misses them; cherry
        # patch-equivalence catches the dominant leak. Bounded: a branch
        # far ahead is a stale-base lane, keep it.
        ahead = _git(["rev-list", "--count", f"{upstream}..{branch}"], cwd=repo_root, timeout=10)
        if ahead.returncode != 0:
            return BranchRecord(
                branch, "keep", "could not verify (git rev-list failed)", tip_oid,
            )
        try:
            ahead_count = int(ahead.stdout.strip() or "0")
        except ValueError:
            ahead_count = _MAX_CHERRY_AHEAD + 1
        if ahead_count == 0:
            return BranchRecord(branch, "delete", "no commits beyond " + upstream, tip_oid)
        if ahead_count > _MAX_CHERRY_AHEAD:
            return BranchRecord(branch, "keep", f"{ahead_count} commits ahead (stale-base lane)", tip_oid)
        cherry = _git(["cherry", upstream, branch], cwd=repo_root, timeout=30)
        if cherry.returncode != 0:
            return BranchRecord(branch, "keep", "could not verify (git cherry failed)", tip_oid)
        lines = [ln for ln in cherry.stdout.splitlines() if ln.strip()]
        if lines and all(ln.startswith("-") for ln in lines):
            return BranchRecord(branch, "delete", "all commits patch-equivalent upstream", tip_oid)
        unique = sum(1 for ln in lines if ln.startswith("+"))
        return BranchRecord(branch, "keep", f"{unique} unique commit(s) not upstream", tip_oid)

    # Read-only classification — parallel, like the tree audit (a busy
    # multi-agent box carries hundreds of local branches; serial cherry
    # probes at ~0.2-1s each make the audit minutes long).
    import concurrent.futures

    workers = max(1, min(8, (os.cpu_count() or 4), len(branches)))
    if workers > 1:
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="hermes-branch-gc"
            ) as pool:
                return list(pool.map(_classify_branch, branches))
        except Exception:
            pass
    return [_classify_branch(b) for b in branches]


def reclaim_branches(
    repo_root: str,
    *,
    dry_run: bool = False,
    records: Optional[List[BranchRecord]] = None,
) -> List[str]:
    """Delete every delete-verdict branch from a frozen audit list."""
    if records is None:
        if not dry_run:
            import cli as _cli

            if _cli._repo_is_shallow(repo_root):
                _cli._deepen_shallow_repo(repo_root)
        records = audit_branches(repo_root)
    actions: List[str] = []
    for record in records:
        if record.verdict != "delete":
            continue
        if dry_run:
            actions.append(f"would delete branch {record.name} ({record.reason})")
            continue
        failure = _branch_revalidation_failure(repo_root, record)
        if failure:
            actions.append(f"kept branch {record.name} ({failure})")
            continue
        result = _delete_branch_atomic(repo_root, record)
        if result.returncode == 0:
            actions.append(f"deleted branch {record.name}")
        else:
            actions.append(f"failed to delete {record.name}: {result.stderr.strip()}")
    return actions


def worktrees_summary(repo_root: str) -> tuple[int, Optional[int]]:
    """(tree_count, total_size_mb) for the escalation notice. Size is
    best-effort with a hard timeout so the startup path never stalls."""
    worktrees_dir = Path(repo_root) / ".worktrees"
    if not worktrees_dir.exists():
        return 0, None
    try:
        count = sum(1 for e in worktrees_dir.iterdir() if e.is_dir())
    except Exception:
        return 0, None
    size_mb: Optional[int] = None
    try:
        result = subprocess.run(
            ["du", "-sm", str(worktrees_dir)],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
        if result.returncode == 0 and result.stdout.strip():
            size_mb = int(result.stdout.split()[0])
    except Exception:
        pass
    return count, size_mb

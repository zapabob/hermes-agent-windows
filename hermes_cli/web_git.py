"""Backend git operations for the desktop coding rail + Codex-style review pane.

The desktop's git affordances (coding-rail status, worktree lanes, review pane,
branch switch) run as Electron-local git on the user's machine. On a *remote*
gateway those would operate on the wrong filesystem, so this module mirrors them
over the dashboard's authenticated REST surface — the same pattern as ``/api/fs``.

Everything shells out to the system ``git`` (and ``gh`` for ship info / PRs).
Reads degrade to ``None`` / empty on a non-repo; mutations raise so the renderer
can surface a toast. Callers pass an already path-hardened ``cwd``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from hermes_cli._subprocess_compat import noninteractive_git_env

_GIT_TIMEOUT = 30
_GH_TIMEOUT = 30
_MAX_BUFFER = 32 * 1024 * 1024
_UNTRACKED_LINE_MAX_BYTES = 1024 * 1024
_UNTRACKED_SCAN_CAP = 500
_COMMIT_CONTEXT_DIFF_MAX_CHARS = 120_000
_COMMIT_CONTEXT_UNTRACKED_MAX = 80
_HISTORY_LIMIT_DEFAULT = 50
_HISTORY_LIMIT_MAX = 100
_TRUNK_BRANCHES = ("main", "master")


def _git(cwd: str, args: list[str], *, timeout: int = _GIT_TIMEOUT) -> tuple[int, str, str]:
    """Run ``git`` in ``cwd``. Returns (returncode, stdout, stderr); never raises
    on a non-zero exit (callers decide what an error means).

    Runs non-interactively (stdin nulled, ``GIT_TERMINAL_PROMPT=0``): these
    calls serve authenticated REST requests from the dashboard/desktop, so a
    credential prompt from ``fetch``/``push``/``pull`` could never be answered
    — it would just hang the request until the timeout. Failing fast surfaces
    the real auth error in the toast instead."""
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True, encoding='utf-8', errors='replace',
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            env=noninteractive_git_env(),
        )
    except (OSError, subprocess.SubprocessError):
        return 1, "", "git invocation failed"
    return proc.returncode, proc.stdout, proc.stderr


def _git_out(cwd: str, args: list[str]) -> str:
    """stdout of a git command, or "" on any failure."""
    code, out, _ = _git(cwd, args)
    return out if code == 0 else ""


def _git_ok(cwd: str, args: list[str]) -> None:
    """Run a git mutation, raising RuntimeError with stderr on failure."""
    code, _, err = _git(cwd, args)
    if code != 0:
        raise RuntimeError(err.strip() or f"git {' '.join(args)} failed")


def _is_dir(cwd: str) -> bool:
    try:
        return Path(cwd).is_dir()
    except OSError:
        return False


# ── shared helpers ───────────────────────────────────────────────────────────


def resolve_rename_path(raw: str) -> str:
    """``old => new`` (and ``dir/{old => new}/f``) → the NEW path, so a row
    addresses the real file for diff/stage."""
    path = str(raw or "").strip()
    if " => " not in path:
        return path
    head, _, tail = path.partition("{")
    if tail and "}" in tail:
        inner, _, suffix = tail.partition("}")
        _, _, to = inner.partition(" => ")
        return f"{head}{to}{suffix}".replace("//", "/")
    return path.split(" => ")[-1].strip()


def _numstat(cwd: str, args: list[str]) -> dict[str, tuple[int, int]]:
    """``git diff --numstat`` → {path: (added, removed)}; binary files (``-``) → 0."""
    out = _git_out(cwd, ["diff", "--numstat", *args])
    counts: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added = 0 if parts[0] == "-" else int(parts[0] or 0)
        removed = 0 if parts[1] == "-" else int(parts[1] or 0)
        counts[resolve_rename_path(parts[2])] = (added, removed)
    return counts


def _untracked_insertions(cwd: str, rel: str) -> int:
    """Line count of an untracked file (newlines + a final unterminated line),
    so the review tree can show +N for new files. Binary / oversized → 0."""
    try:
        target = Path(cwd) / rel
        st = target.stat()
        if not os.path.isfile(target) or st.st_size > _UNTRACKED_LINE_MAX_BYTES:
            return 0
        data = target.read_bytes()
        if b"\0" in data:
            return 0
        lines = data.count(b"\n")
        return lines + 1 if data and not data.endswith(b"\n") else lines
    except OSError:
        return 0


def _fill_untracked_counts(cwd: str, files: list[dict]) -> None:
    for file in files:
        if file["status"] == "?" and file["added"] == 0 and file["removed"] == 0:
            file["added"] = _untracked_insertions(cwd, file["path"])


def _branch_base(cwd: str) -> str | None:
    """Merge-base with the remote default branch for "all branch changes"."""
    candidates: list[str] = []
    head = _git_out(cwd, ["rev-parse", "--abbrev-ref", "origin/HEAD"]).strip()
    if head:
        candidates.append(head)
    candidates += ["origin/main", "origin/master", "main", "master"]
    for ref in candidates:
        base = _git_out(cwd, ["merge-base", "HEAD", ref]).strip()
        if base:
            return base
    return None


def _default_branch_name(cwd: str) -> str | None:
    """The repo's trunk name ("main"/"master"/…), preferring origin/HEAD."""
    head = _git_out(cwd, ["rev-parse", "--abbrev-ref", "origin/HEAD"]).strip()
    if head and head != "origin/HEAD":
        return head.split("/", 1)[-1]
    for ref in (
        "refs/heads/main",
        "refs/heads/master",
        "refs/remotes/origin/main",
        "refs/remotes/origin/master",
    ):
        code, _, _ = _git(cwd, ["rev-parse", "--verify", "--quiet", ref])
        if code == 0:
            return ref.split("/")[-1]
    return None


# ── porcelain v2 status parsing ──────────────────────────────────────────────


def _walk_entries(raw: str):
    """Yield (tag, xy, path) per changed file from ``git status --porcelain=v2 -z``,
    skipping branch headers and the rename/copy origin-path records. One walker
    feeds the rail, the review list, and the commit flow."""
    records = raw.split("\0")
    i = 0
    while i < len(records):
        rec = records[i]
        tag = rec[0] if rec else ""
        if tag == "?":
            yield "?", "??", rec[2:]
        elif tag == "u":
            yield "u", rec.split(" ")[1], rec.split(" ", 10)[-1]
        elif tag in ("1", "2"):
            xy = rec.split(" ")[1]
            path = rec.split(" ", 8)[-1] if tag == "1" else rec.split(" ", 9)[-1]
            if tag == "2":
                i += 1  # rename/copy: the origin path is the next NUL record
            yield tag, xy, resolve_rename_path(path)
        i += 1


def _entry_staged(tag: str, xy: str) -> bool:
    """A tracked entry whose index (staged) code is set."""
    return tag in ("1", "2") and xy[0] not in (".", "?")


def _classify(tag: str, xy: str, path: str) -> dict:
    y = xy[1] if len(xy) > 1 else "."
    return {
        "path": path,
        "staged": _entry_staged(tag, xy),
        "unstaged": tag == "?" or (tag in ("1", "2") and y not in (".", "?")),
        "untracked": tag == "?",
        "conflicted": tag == "u",
    }


def _status_letter(tag: str, xy: str) -> str:
    if tag in ("?", "u"):
        return tag.upper() if tag == "u" else "?"
    code = xy[0] if xy[0] != "." else (xy[1] if len(xy) > 1 else ".")
    return (code if code != "." else "M").upper()


# ── coding rail ──────────────────────────────────────────────────────────────


def repo_status(cwd: str) -> dict | None:
    """Compact working-tree status for the coding rail. None on a non-repo."""
    if not _is_dir(cwd):
        return None

    code, raw, _ = _git(cwd, ["status", "--porcelain=v2", "--branch", "-z"])
    if code != 0:
        return None

    branch: str | None = None
    detached = False
    ahead = behind = 0
    for rec in raw.split("\0"):
        if rec.startswith("# branch.head "):
            head = rec[len("# branch.head ") :]
            detached = head == "(detached)"
            branch = None if detached else head
        elif rec.startswith("# branch.ab "):
            for tok in rec.split()[2:]:
                if tok.startswith("+"):
                    ahead = int(tok[1:] or 0)
                elif tok.startswith("-"):
                    behind = int(tok[1:] or 0)

    files = [_classify(tag, xy, path) for tag, xy, path in _walk_entries(raw)]

    # +/- vs HEAD (tracked), then fold in untracked insertions — `git diff HEAD`
    # ignores them, so a new-file-only turn would otherwise read +0 (bounded scan).
    added = removed = 0
    for a, r in _numstat(cwd, ["HEAD"]).values():
        added += a
        removed += r
    added += sum(_untracked_insertions(cwd, f["path"]) for f in files[:_UNTRACKED_SCAN_CAP] if f["untracked"])

    return {
        "branch": branch,
        "defaultBranch": _default_branch_name(cwd),
        "detached": detached,
        "ahead": ahead,
        "behind": behind,
        "staged": sum(f["staged"] for f in files),
        "unstaged": sum(f["unstaged"] for f in files),
        "untracked": sum(f["untracked"] for f in files),
        "conflicted": sum(f["conflicted"] for f in files),
        "changed": len(files),
        "added": added,
        "removed": removed,
        "files": files[:200],
    }


# ── review pane ──────────────────────────────────────────────────────────────


def review_list(cwd: str, scope: str, base_ref: str | None) -> dict:
    """Changed files for a scope. Mirrors the Electron reviewList shapes."""
    if not _is_dir(cwd):
        return {"files": [], "base": None}

    if scope in ("branch", "lastTurn"):
        base = _branch_base(cwd) if scope == "branch" else base_ref
        if not base:
            return {"files": [], "base": None}
        rng = f"{base}...HEAD" if scope == "branch" else base
        files = [
            {"path": path, "added": a, "removed": r, "status": "M", "staged": False}
            for path, (a, r) in _numstat(cwd, [rng]).items()
        ]
        if scope == "lastTurn":
            seen = {f["path"] for f in files}
            _, raw, _ = _git(cwd, ["status", "--porcelain=v2", "-z"])
            files += [
                {"path": path, "added": 0, "removed": 0, "status": "?", "staged": False}
                for tag, _xy, path in _walk_entries(raw)
                if tag == "?" and path not in seen
            ]
        files.sort(key=lambda f: f["path"])
        _fill_untracked_counts(cwd, files)
        return {"files": files, "base": base}

    code, raw, _ = _git(cwd, ["status", "--porcelain=v2", "-z"])
    if code != 0:
        return {"files": [], "base": None}
    staged = _numstat(cwd, ["--cached"])
    unstaged = _numstat(cwd, [])

    files = []
    for tag, xy, path in _walk_entries(raw):
        sa, sr = staged.get(path, (0, 0))
        ua, ur = unstaged.get(path, (0, 0))
        files.append(
            {
                "path": path,
                "added": sa + ua,
                "removed": sr + ur,
                "status": _status_letter(tag, xy),
                "staged": _entry_staged(tag, xy),
            }
        )
    files.sort(key=lambda f: f["path"])
    _fill_untracked_counts(cwd, files)
    return {"files": files, "base": None}


def review_diff(cwd: str, file_path: str, scope: str, base_ref: str | None, staged: bool) -> str:
    if not _is_dir(cwd):
        return ""
    if scope == "branch":
        base = _branch_base(cwd)
        return _git_out(cwd, ["diff", f"{base}...HEAD", "--", file_path]) if base else ""
    if scope == "lastTurn":
        return _git_out(cwd, ["diff", base_ref, "--", file_path]) if base_ref else ""
    if staged:
        return _git_out(cwd, ["diff", "--cached", "--", file_path])
    worktree = _git_out(cwd, ["diff", "--", file_path])
    if worktree.strip():
        return worktree
    # Untracked: synthesize an all-add diff (exits non-zero by design).
    _, out, _ = _git(cwd, ["diff", "--no-index", "--", os.devnull, file_path])
    return out


def _history_limit(value: int | None) -> int:
    try:
        return max(1, min(_HISTORY_LIMIT_MAX, int(value or _HISTORY_LIMIT_DEFAULT)))
    except (TypeError, ValueError):
        return _HISTORY_LIMIT_DEFAULT


def _commit_id(value: str) -> bool:
    """Only accept object ids returned by the history list, never arbitrary refs."""
    return bool(re.fullmatch(r"[0-9a-fA-F]{7,64}", str(value or "")))


def review_history(cwd: str, limit: int | None = None) -> list[dict]:
    """Compact, bounded commit history for the Desktop review pane."""
    if not _is_dir(cwd):
        return []

    code, raw, _ = _git(
        cwd,
        [
            "log",
            f"--max-count={_history_limit(limit)}",
            "--date=iso-strict",
            "--format=%H%x1f%h%x1f%P%x1f%an%x1f%aI%x1f%s%x1e",
        ],
    )
    if code != 0:
        return []

    commits = []
    for raw_record in raw.split("\x1e"):
        # `git log` appends a physical line ending after each format record.
        # Remove only that delimiter before validating the following SHA.
        record = raw_record.lstrip("\r\n")
        if not record:
            continue
        fields = record.split("\x1f")
        if len(fields) != 6:
            continue
        sha, short_sha, parents, author, authored_at, subject = fields
        if not _commit_id(sha) or not short_sha or not authored_at:
            continue
        commits.append(
            {
                "sha": sha,
                "shortSha": short_sha,
                "parents": [parent for parent in parents.split() if _commit_id(parent)],
                "author": author,
                "authoredAt": authored_at,
                "subject": subject,
            }
        )
    return commits


def review_history_diff(cwd: str, sha: str) -> str:
    """Read a selected commit's unified diff; reject arbitrary revision expressions."""
    if not _is_dir(cwd) or not _commit_id(sha):
        return ""
    return _git_out(cwd, ["show", "--format=", "--find-renames", "--find-copies", "--no-ext-diff", sha, "--"])


def file_diff_vs_head(cwd: str, file_path: str) -> str:
    """Working-tree-vs-HEAD diff for one file (the preview's diff view). Unlike
    review_diff, never all-adds a clean tracked file; only a genuinely untracked one."""
    if not _is_dir(cwd):
        return ""
    head = _git_out(cwd, ["diff", "HEAD", "--", file_path])
    if head.strip():
        return head
    status = _git_out(cwd, ["status", "--porcelain", "--", file_path])
    if not status.strip().startswith("??"):
        return ""
    _, out, _ = _git(cwd, ["diff", "--no-index", "--", os.devnull, file_path])
    return out


def review_stage(cwd: str, file_path: str | None) -> dict:
    _git_ok(cwd, ["add", "--", file_path] if file_path else ["add", "-A"])
    return {"ok": True}


def review_unstage(cwd: str, file_path: str | None) -> dict:
    _git_ok(cwd, ["reset", "-q", "HEAD", "--", file_path] if file_path else ["reset", "-q", "HEAD"])
    return {"ok": True}


def review_revert(cwd: str, file_path: str | None) -> dict:
    """Discard changes back to the committed state (restore tracked, remove untracked)."""
    target = ["--", file_path] if file_path else ["--", "."]
    _git(cwd, ["checkout", "HEAD", *target])
    _git(cwd, ["clean", "-fd", *target])
    return {"ok": True}


def review_rev_parse(cwd: str, ref: str | None) -> str | None:
    out = _git_out(cwd, ["rev-parse", ref or "HEAD"]).strip()
    return out or None


def review_commit(cwd: str, message: str, push: bool) -> dict:
    """Commit the working tree; stage everything first when nothing is staged."""
    _, raw, _ = _git(cwd, ["status", "--porcelain=v2", "-z"])
    if not any(_entry_staged(tag, xy) for tag, xy, _ in _walk_entries(raw)):
        _git_ok(cwd, ["add", "-A"])
    _git_ok(cwd, ["commit", "-m", message])
    if push:
        _review_push(cwd)
    return {"ok": True}


def _review_push(cwd: str) -> None:
    upstream = _git_out(cwd, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]).strip()
    if upstream:
        _git_ok(cwd, ["push"])
        return
    branch = _git_out(cwd, ["rev-parse", "--abbrev-ref", "HEAD"]).strip()
    if branch and branch != "HEAD":
        _git_ok(cwd, ["push", "-u", "origin", branch])


def review_push(cwd: str) -> dict:
    _review_push(cwd)
    return {"ok": True}


def review_commit_context(cwd: str) -> dict:
    """Diff of what WILL commit + recent subjects, for drafting a commit message."""
    if not _is_dir(cwd):
        return {"diff": "", "recent": ""}
    code, raw, _ = _git(cwd, ["status", "--porcelain=v2", "-z"])
    if code != 0:
        return {"diff": "", "recent": ""}
    entries = list(_walk_entries(raw))

    has_staged = any(_entry_staged(tag, xy) for tag, xy, _ in entries)
    diff = _git_out(cwd, ["diff", "--cached"]) if has_staged else _git_out(cwd, ["diff", "HEAD"])
    if len(diff) > _COMMIT_CONTEXT_DIFF_MAX_CHARS:
        omitted = len(diff) - _COMMIT_CONTEXT_DIFF_MAX_CHARS
        diff = f"{diff[:_COMMIT_CONTEXT_DIFF_MAX_CHARS]}\n# diff truncated: {omitted} chars omitted\n"

    untracked = [path for tag, _xy, path in entries if tag == "?"]
    if untracked:
        visible = untracked[:_COMMIT_CONTEXT_UNTRACKED_MAX]
        note = "\n# New (untracked) files:\n" + "".join(f"#   {p}\n" for p in visible)
        if len(untracked) > len(visible):
            note += f"#   ... {len(untracked) - len(visible)} more omitted\n"
        diff = f"{diff}{note}" if diff else note

    return {"diff": diff or "", "recent": _git_out(cwd, ["log", "-n", "10", "--pretty=format:%s"]).strip()}


# ── ship flow (gh) ───────────────────────────────────────────────────────────


def _gh(cwd: str, args: list[str]) -> tuple[bool, str]:
    if not shutil.which("gh"):
        return False, ""
    # Same non-interactive contract as _git: these serve REST requests, so gh
    # must fail fast instead of prompting (GH_PROMPT_DISABLED is gh's own
    # documented kill-switch for interactive prompts).
    env = noninteractive_git_env()
    env["GH_PROMPT_DISABLED"] = "1"
    try:
        proc = subprocess.run(
            ["gh", *args], cwd=cwd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=_GH_TIMEOUT,
            stdin=subprocess.DEVNULL, env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    return proc.returncode == 0, proc.stdout or ""


def review_ship_info(cwd: str) -> dict:
    """gh availability/auth + this branch's PR. ghReady false when gh missing/unauthed."""
    if not _is_dir(cwd):
        return {"ghReady": False, "pr": None}
    auth_ok, _ = _gh(cwd, ["auth", "status"])
    if not auth_ok:
        return {"ghReady": False, "pr": None}
    view_ok, out = _gh(cwd, ["pr", "view", "--json", "url,state,number"])
    if not view_ok:
        return {"ghReady": True, "pr": None}
    try:
        pr = json.loads(out)
    except json.JSONDecodeError:
        return {"ghReady": True, "pr": None}
    if pr and pr.get("url"):
        return {"ghReady": True, "pr": {"url": pr["url"], "state": pr.get("state"), "number": pr.get("number")}}
    return {"ghReady": True, "pr": None}


# GraphQL asks per branch, so the answer can't be crowded out the way a
# `gh pr list` page can. Aliases let one request carry many branches; 50 keeps
# the document well inside GitHub's node budget.
_PR_QUERY_BRANCH_CHUNK = 50
_PR_QUERY_BRANCH_CAP = 300


_PR_NODE_FIELDS = "number state isDraft isCrossRepository title url headRefName"


def _pr_query(owner: str, name: str, branches: list[str], numbers: list[int]) -> str:
    fields = [
        f"b{i}: pullRequests(headRefName: {json.dumps(branch)}, first: 5, "
        f"orderBy: {{field: CREATED_AT, direction: DESC}}) "
        f"{{ nodes {{ {_PR_NODE_FIELDS} }} }}"
        for i, branch in enumerate(branches)
    ]
    # A PR recovered from a transcript is known by number, and asking for it
    # directly also tells us its branch — so it lands in the same by-branch map
    # as everything else.
    fields += [f"n{i}: pullRequest(number: {n}) {{ {_PR_NODE_FIELDS} }}" for i, n in enumerate(numbers)]
    return (
        f"query {{ repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{\n"
        + "\n".join(fields)
        + "\n} }"
    )


def _pr_payload(pr: dict) -> dict:
    return {
        "branch": str(pr.get("headRefName")),
        "draft": bool(pr.get("isDraft")),
        "number": int(pr.get("number") or 0),
        "state": str(pr.get("state") or "").lower(),
        "title": str(pr.get("title") or ""),
        "url": str(pr.get("url") or ""),
    }


def review_pr_list(cwd: str, branches: list[str], numbers: list[int] = None) -> dict:
    """The PRs on the given branches (plus any asked for by number). Asks GitHub
    about the branches we actually have sessions on rather than listing the
    repo's newest PRs and hoping ours are in the page."""
    if not _is_dir(cwd):
        return {"ghReady": False, "prs": []}
    wanted = list(dict.fromkeys(str(b) for b in (branches or []) if b))[:_PR_QUERY_BRANCH_CAP]
    by_number = list(dict.fromkeys(int(n) for n in (numbers or []) if n))[:_PR_QUERY_BRANCH_CAP]
    if not wanted and not by_number:
        return {"ghReady": False, "prs": []}
    repo_ok, repo_out = _gh(cwd, ["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"])
    owner, _, name = repo_out.strip().partition("/")
    if not repo_ok or not owner or not name:
        # gh missing, unauthenticated, or no GitHub remote — all "nothing to badge".
        return {"ghReady": False, "prs": []}

    prs: list[dict] = []
    chunks = [
        (wanted[i : i + _PR_QUERY_BRANCH_CHUNK], [])
        for i in range(0, len(wanted), _PR_QUERY_BRANCH_CHUNK)
    ] + [
        ([], by_number[i : i + _PR_QUERY_BRANCH_CHUNK])
        for i in range(0, len(by_number), _PR_QUERY_BRANCH_CHUNK)
    ]
    for branch_chunk, number_chunk in chunks:
        ok, out = _gh(cwd, ["api", "graphql", "-f", f"query={_pr_query(owner, name, branch_chunk, number_chunk)}"])
        if not ok:
            continue
        try:
            repository = (json.loads(out).get("data") or {}).get("repository") or {}
        except json.JSONDecodeError:
            continue  # A malformed chunk drops its branches; the rest still resolve.
        for key, field in repository.items():
            if not field:
                continue
            if key.startswith("n"):
                # Asked for by number, so it's ours by construction — a fork PR
                # can't be recovered from our own transcript.
                if field.get("headRefName"):
                    prs.append(_pr_payload(field))
                continue
            # Fork PRs share our branch namespace: a contributor's `main` is how
            # a session sitting on trunk ends up badged with a stranger's closed
            # PR. Only this repo's own branches describe our sessions.
            nodes = field.get("nodes") or []
            pr = next((n for n in nodes if n and not n.get("isCrossRepository")), None)
            if pr and pr.get("headRefName"):
                prs.append(_pr_payload(pr))
    return {"ghReady": True, "prs": prs}


def review_create_pr(cwd: str) -> dict:
    """Create a PR for the current branch (push first), letting gh fill title/body."""
    try:
        _review_push(cwd)
    except RuntimeError:
        pass
    created, out = _gh(cwd, ["pr", "create", "--fill"])
    if not created:
        raise RuntimeError("gh pr create failed (is gh installed and authenticated?)")
    url = next((line for line in reversed(out.strip().splitlines()) if line.strip()), "")
    return {"url": url}


# ── worktrees & branches ─────────────────────────────────────────────────────


def _parse_worktrees(out: str) -> list[dict]:
    trees: list[dict] = []
    cur: dict | None = None
    for line in out.split("\n"):
        if line.startswith("worktree "):
            if cur:
                trees.append(cur)
            cur = {"path": line[9:].strip(), "branch": None, "detached": False, "bare": False, "locked": False}
        elif cur is None:
            continue
        elif line.startswith("branch "):
            cur["branch"] = line[7:].strip().replace("refs/heads/", "", 1)
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
        elif line.startswith("locked"):
            cur["locked"] = True
    if cur:
        trees.append(cur)
    return trees


def worktree_list(cwd: str) -> list[dict]:
    out = _git_out(cwd, ["worktree", "list", "--porcelain"])
    if not out:
        return []
    return [
        {
            "path": tree["path"],
            "branch": tree["branch"],
            "isMain": index == 0,
            "detached": tree["detached"],
            "locked": tree["locked"],
        }
        for index, tree in enumerate(_parse_worktrees(out))
    ]


def _main_root(cwd: str) -> str:
    for tree in worktree_list(cwd):
        if tree["isMain"]:
            return tree["path"]
    return cwd


def _sanitize_branch(name: str) -> str:
    value = str(name or "")
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"[^\w./-]", "", value)
    value = re.sub(r"-{2,}", "-", value)
    value = re.sub(r"/{2,}", "/", value)
    value = re.sub(r"\.{2,}", ".", value)
    return re.sub(r"^[-./]+|[-./]+$", "", value)


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(name or "").strip().lower())
    slug = re.sub(r"^-+|-+$", "", slug)[:40].rstrip("-")
    return slug or "work"


def _default_branch(cwd: str) -> str:
    remote = _git_out(
        cwd, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
    ).strip().replace("origin/", "", 1)
    if remote:
        return remote
    configured = _git_out(cwd, ["config", "--get", "init.defaultBranch"]).strip()
    if configured:
        return configured
    for branch in _TRUNK_BRANCHES:
        if _git_out(cwd, ["show-ref", "--verify", f"refs/heads/{branch}"]).strip():
            return branch
    return ""


def _ensure_repo(cwd: str) -> None:
    """A new project folder may not be a repo (or has no commit to branch from);
    init it with a root commit so worktrees just work. No-op for a committed repo."""
    inside = _git_out(cwd, ["rev-parse", "--is-inside-work-tree"]).strip()
    needs_root = False
    if inside != "true":
        _git_ok(cwd, ["init"])
        needs_root = True
    else:
        code, _, _ = _git(cwd, ["rev-parse", "--verify", "HEAD"])
        needs_root = code != 0
    if needs_root:
        _git_ok(
            cwd,
            [
                "-c",
                "user.email=hermes@localhost",
                "-c",
                "user.name=Hermes",
                "commit",
                "--allow-empty",
                "-m",
                "Initial commit",
            ],
        )


def _unique_dir(base: str) -> str:
    candidate = base
    n = 1
    while os.path.exists(candidate):
        n += 1
        candidate = f"{base}-{n}"
    return candidate


def _remote_of_ref(cwd: str, name: str) -> str:
    """The remote a ref belongs to ("origin" for "origin/main"), or "" when the
    name is not a remote-tracking ref in this repo. Asks git rather than
    assuming the remote is called "origin" (mirrors the Electron op)."""
    if "/" not in name:
        return ""
    code, _, _ = _git(cwd, ["show-ref", "--verify", "--quiet", f"refs/remotes/{name}"])
    if code != 0:
        return ""
    return name.split("/", 1)[0]


def worktree_add(cwd: str, options: dict) -> dict:
    _ensure_repo(cwd)
    root = _main_root(cwd)
    options = options or {}

    requested = _sanitize_branch(options.get("existingBranch") or "")
    if options.get("existingBranch"):
        if not requested:
            raise RuntimeError("Branch name is required.")
        # "origin/feature" is a remote-tracking ref, not a branch git can check
        # out — `git worktree add <dir> origin/feature` detaches HEAD. Create a
        # local branch with the same short name that tracks the remote ref,
        # like `git switch feature` does for a branch on exactly one remote.
        # (Parity with the Electron op; a remote gateway serves this mirror, so
        # the desktop's convert-a-branch flow must behave identically. #81724)
        remote = _remote_of_ref(root, requested)
        existing = requested.split("/", 1)[1] if remote else requested
        if not remote and existing == _default_branch(root):
            _git_ok(root, ["switch", existing])
            return {"path": root, "branch": existing, "repoRoot": root}
        target = _unique_dir(os.path.join(root, ".worktrees", _slugify(existing)))
        if remote:
            # Best-effort freshness: the remote-tracking ref is stale if the
            # user did not fetch recently. On failure (offline, branch gone)
            # the last known ref is still there to branch from.
            _git(root, ["fetch", remote, existing])
            _git_ok(root, ["worktree", "add", "--track", "-b", existing, target, requested])
            return {"path": target, "branch": existing, "repoRoot": root}
        _git_ok(root, ["worktree", "add", target, existing])
        return {"path": target, "branch": existing, "repoRoot": root}

    slug = _slugify(options.get("name") or f"work-{os.urandom(4).hex()}")
    branch = _sanitize_branch(options.get("branch") or "") or f"hermes/{slug}"
    target = _unique_dir(os.path.join(root, ".worktrees", slug))
    args = ["worktree", "add", "-b", branch, target]
    if options.get("base"):
        base = str(options["base"])
        # Remote-tracking branches may be stale or missing; fetch just that
        # branch so the local ref is up to date before branching. Ignore fetch
        # failures (offline / no remote) — git will use whatever local ref
        # exists, or raise a clear error below if the ref is entirely missing.
        if base.startswith("origin/"):
            remote_branch = base[len("origin/"):]
            _git(root, ["fetch", "origin", remote_branch])
            # Branching off a remote-tracking ref auto-sets up tracking (the
            # new branch silently wired to origin's upstream). The user wants a
            # standalone local branch — like `git checkout origin/main && git
            # checkout -b new` — so suppress it (parity with the Electron op).
            args.append("--no-track")
        args.append(base)
    code, _, err = _git(root, args)
    if code != 0:
        if "already exists" in (err or "").lower():
            _git_ok(root, ["worktree", "add", target, branch])
        else:
            raise RuntimeError(err.strip() or "git worktree add failed")
    return {"path": target, "branch": branch, "repoRoot": root}


def worktree_remove(cwd: str, worktree_path: str, force: bool) -> dict:
    root = _main_root(cwd)
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(worktree_path)
    _git_ok(root, args)
    return {"removed": worktree_path}


def branch_list(cwd: str) -> list[dict]:
    """Branches for the convert-a-branch picker: local heads first, then the
    remote-tracking refs that have no local head yet (a teammate's branch is
    reachable without a manual checkout). Parity with the Electron op — a
    remote gateway serves this mirror for the same desktop UI (#81724)."""
    out = _git_out(
        cwd, ["for-each-ref", f"--format={_SEP}%(refname:short){_SEP}%(objectname)", "--sort=-committerdate", "refs/heads"]
    )
    if not out:
        return []
    trees = worktree_list(cwd)
    path_by_branch = {t["branch"]: t["path"] for t in trees if t["branch"]}
    trunk = _default_branch(cwd)
    def _parse_ref(line: str) -> dict[str, str]:
        parts = line.split(_SEP, 2)
        if len(parts) != 3:
            return {"name": "", "sha": ""}
        return {"name": parts[1], "sha": parts[2]}
    locals_ = [_parse_ref(line) for line in out.split("\n") if line.strip()]
    local_set = set(l["name"] for l in locals_)
    remote_out = _git_out(
        cwd, ["for-each-ref", f"--format={_SEP}%(refname:short){_SEP}%(objectname)", "--sort=-committerdate", "refs/remotes"]
    )
    remotes = [
        entry
        for entry in [_parse_ref(line) for line in remote_out.split("\n") if line.strip()]
        if entry["name"]
        # "origin/HEAD" is a symbolic alias for the remote's default branch —
        # not a branch, and a duplicate row in the list.
        and not entry["name"].endswith("/HEAD")
        # A remote branch tracked locally is reachable via its local head; a
        # second row is noise, and checking out the remote ref detaches HEAD.
        and entry["name"].split("/", 1)[-1] not in local_set
    ]
    return [
        *(
            {
                "name": entry["name"],
                "checkedOut": entry["name"] in path_by_branch,
                "isDefault": bool(trunk and entry["name"] == trunk),
                "isRemote": False,
                "worktreePath": path_by_branch.get(entry["name"]),
                "sha": entry["sha"]
            }
            for entry in locals_
        ),
        *(
            {
                # No local checkout, and never the local trunk.
                "name": entry["name"],
                "checkedOut": False,
                "isDefault": False,
                "isRemote": True,
                "worktreePath": None,
                "sha": entry["sha"]
            }
            for entry in remotes
        ),
    ]


def branch_switch(cwd: str, branch: str) -> dict:
    target = _sanitize_branch(branch)
    if not target:
        raise RuntimeError("Branch name is required.")
    _git_ok(cwd, ["switch", target])
    return {"branch": target}


# ── scm rail (branches/tags/stashes CRUD + fetch/pull) ───────────────────────
# Mirror of the Electron SCM-rail ops (apps/desktop/electron/git-ref-ops.ts) so
# a *remote* gateway serves the same rail. Shapes, validation and failure
# semantics are identical; validation uses git's own ref grammar
# (`check-ref-format`) at the boundary — never `_sanitize_branch`, because a
# rewritten name would hide a typo the user should see.

_SEP = "\x1f"


def _assert_branch_name(cwd: str, name: str) -> str:
    label = str(name or "").strip()
    if not label:
        raise RuntimeError("Branch name is required.")
    code, _, _ = _git(cwd, ["check-ref-format", "--branch", label])
    if code != 0:
        raise RuntimeError("Invalid branch name.")
    return label


def _assert_tag_name(cwd: str, name: str) -> str:
    label = str(name or "").strip()
    if not label:
        raise RuntimeError("Tag name is required.")
    code, _, _ = _git(cwd, ["check-ref-format", f"refs/tags/{label}"])
    if code != 0:
        raise RuntimeError("Invalid tag name.")
    return label


def _assert_ref_arg(value: str, label: str) -> str:
    """A ref the renderer picked from a listing — option-like or whitespace-
    bearing values can't come from those lists, so reject them outright."""
    clean = str(value or "").strip()
    if not clean or re.search(r"\s", clean) or clean.startswith("-"):
        raise RuntimeError(f"Invalid {label}.")
    return clean


def _assert_remote_name(value: str) -> str:
    """Remote names follow a tighter grammar than refs: no slash, no leading dash."""
    clean = str(value or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", clean):
        raise RuntimeError("Invalid remote name.")
    return clean


def _assert_stash_index(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise RuntimeError("Invalid stash index.") from None
    if n < 0 or n > 100_000:
        raise RuntimeError("Invalid stash index.")
    return n


def tag_list(cwd: str) -> list[dict]:
    """Tags newest-first: name, peeled commit sha ('' for a lightweight tag),
    tag-object sha, author date, subject. Degrades to [] on a non-repo."""
    if not _is_dir(cwd):
        return []
    out = _git_out(
        cwd,
        [
            "for-each-ref",
            "--sort=-creatordate",
            f"--format=%(refname:short){_SEP}%(*objectname){_SEP}%(objectname){_SEP}%(creatordate:iso-strict){_SEP}%(subject)",
            "refs/tags",
        ],
    )
    tags = []
    for line in out.splitlines():
        parts = line.split(_SEP)
        if len(parts) < 4 or not parts[0]:
            continue
        name, peeled, obj, date = parts[:4]
        sha = peeled or obj
        tags.append(
            {
                "name": name,
                "sha": sha,
                "shortSha": sha[:7],
                "date": date,
                "subject": _SEP.join(parts[4:]),
            }
        )
    return tags


_STASH_RE = re.compile(r"^stash@\{(\d+)\}$")


def stash_list(cwd: str) -> list[dict]:
    """Stash rows from the stash reflog (`stash@{N}`, sha, date, message — git
    prefixes "On <branch>: " unless a message was set). Degrades to [] on a
    non-repo / no stashes (`git log -g refs/stash` exits non-zero then)."""
    if not _is_dir(cwd):
        return []
    out = _git_out(cwd, ["log", "-g", f"--format=%gd{_SEP}%H{_SEP}%aI{_SEP}%s", "refs/stash"])
    stashes = []
    for line in out.splitlines():
        parts = line.split(_SEP)
        if len(parts) < 3:
            continue
        rid, sha, date = parts[:3]
        match = _STASH_RE.match(rid or "")
        stashes.append(
            {
                "index": int(match.group(1)) if match else -1,
                "id": rid,
                "sha": sha,
                "shortSha": sha[:7],
                "date": date,
                "message": _SEP.join(parts[3:]),
            }
        )
    return stashes


def branch_create(cwd: str, name: str, base: str | None) -> dict:
    name = _assert_branch_name(cwd, name)
    args = ["branch", name]
    if base:
        args.append(_assert_ref_arg(base, "branch base"))
    _git_ok(cwd, args)
    return {"ok": True}


def branch_rename(cwd: str, name: str, new_name: str) -> dict:
    _assert_branch_name(cwd, new_name)
    _git_ok(cwd, ["branch", "-m", _assert_ref_arg(name, "branch"), new_name])
    return {"ok": True}


def branch_delete(cwd: str, name: str, force: bool) -> dict:
    # `-d` refuses an unmerged branch and the currently checked-out branch;
    # git's own guards do that work. `force` opts into `-D`.
    _git_ok(cwd, ["branch", "-D" if force else "-d", _assert_ref_arg(name, "branch")])
    return {"ok": True}


def tag_create(cwd: str, name: str, target: str | None) -> dict:
    name = _assert_tag_name(cwd, name)
    args = ["tag", name]
    if target:
        args.append(_assert_ref_arg(target, "tag target"))
    _git_ok(cwd, args)
    return {"ok": True}


def tag_delete(cwd: str, name: str) -> dict:
    _git_ok(cwd, ["tag", "-d", _assert_ref_arg(name, "tag")])
    return {"ok": True}


def stash_create(cwd: str, message: str | None, include_untracked: bool) -> dict:
    """`git stash push` with no changes exits 0 ("No local changes to save"),
    so creating an empty stash is not an error — the renderer decides whether
    to disable the button from the status it already has."""
    args = ["stash", "push"]
    if include_untracked:
        args.append("-u")
    note = str(message or "").strip()[:1000]
    if note:
        args += ["-m", note]
    _git_ok(cwd, args)
    return {"ok": True}


def stash_apply(cwd: str, index: int) -> dict:
    # Conflicts raise so the renderer can offer a path forward instead of
    # pretending the apply landed.
    _git_ok(cwd, ["stash", "apply", str(_assert_stash_index(index))])
    return {"ok": True}


def stash_drop(cwd: str, index: int) -> dict:
    # Bare index, never ``stash@{N}``: on native Windows the MSYS runtime strips the braces
    # from git.exe's argv, so the selector would reach git as ``stash@N`` (#87542).
    _git_ok(cwd, ["stash", "drop", str(_assert_stash_index(index))])
    return {"ok": True}


def git_fetch(cwd: str, remote: str | None) -> dict:
    """Prune stale remote-tracking refs by default — matches VS Code's fetch
    and keeps the branch list honest after a teammate deletes a branch."""
    args = ["fetch", "--prune"]
    if remote:
        args.append(_assert_remote_name(remote))
    _git_ok(cwd, args)
    return {"ok": True}


def git_pull(cwd: str, rebase: bool) -> dict:
    args = ["pull"]
    if rebase:
        args.append("--rebase")
    _git_ok(cwd, args)
    return {"ok": True}


def base_branch_list(cwd: str) -> list[dict]:
    """Local heads + remote-tracking refs for the base-branch picker.

    The remote default (origin/HEAD) is flagged so the UI can preselect it.
    """
    out = _git_out(
        cwd,
        [
            "for-each-ref",
            "--format=%(refname:short)\t%(committerdate:iso)",
            "--sort=-committerdate",
            "refs/heads",
            "refs/remotes",
        ],
    )
    if not out:
        return []
    remote_default = _git_out(
        cwd, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"]
    ).strip()
    local_default = _default_branch(cwd) if not remote_default else ""
    result: list[dict] = []
    for line in out.split("\n"):
        line = line.strip()
        if not line:
            continue
        name = line.split("\t")[0]
        result.append(
            {
                "name": name,
                "isRemote": name.startswith("origin/"),
                # origin/HEAD when a remote exists; otherwise the local
                # default (main/master/init.defaultBranch) so a no-remote
                # repo still flags its trunk.
                "isDefault": bool(
                    (remote_default and name == remote_default)
                    or (not remote_default and local_default and name == local_default)
                ),
            }
        )
    return result

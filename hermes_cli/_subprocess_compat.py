"""Windows subprocess compatibility helpers.

Hermes is developed on Linux / macOS and tested natively on Windows too.
Several common subprocess patterns break silently-or-loudly on Windows:

* ``["npm", "install", ...]`` — on Windows ``npm`` is ``npm.cmd``, a batch
  shim.  ``subprocess.Popen(["npm", ...])`` fails with WinError 193
  ("not a valid Win32 application") because CreateProcessW can't run a
  ``.cmd`` file without ``shell=True`` or PATHEXT resolution.

* ``start_new_session=True`` — on POSIX, this maps to ``os.setsid()`` and
  actually detaches the child.  On Windows it's silently ignored; the
  Windows equivalent is the ``CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW``
  creationflags bundle, which Python only applies when you pass it
  explicitly.

* Console-window flashes — every ``subprocess.Popen`` of a ``.exe`` on
  Windows spawns a cmd window briefly unless ``CREATE_NO_WINDOW`` is
  passed.  Cosmetic but jarring for background daemons.

This module centralizes the platform-branching logic so the rest of the
codebase doesn't sprinkle ``if sys.platform == "win32":`` everywhere.

**All helpers are no-ops on non-Windows** — calling them in Linux/macOS
code paths is safe by design.  That's the "do no damage on POSIX"
guarantee.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from contextvars import ContextVar
from functools import wraps
from pathlib import Path
from typing import Mapping, Sequence

__all__ = [
    "IS_WINDOWS",
    "resolve_node_command",
    "split_command_line",
    "suppress_platform_ver_console",
    "windows_detach_flags",
    "windows_detach_flags_without_breakaway",
    "windows_hide_flags",
    "windows_detach_popen_kwargs",
    "bounded_git_probe",
    "bounded_probe_run",
    "noninteractive_git_env",
    "noninteractive_repo_git_env",
    "harden_git_argv",
    "FILTER_DISCOVERY_FAILED",
    "GitPolicyError",
    "run_internal_git",
    "clone_git_repository",
    "run_internal_gh",
    "pid_is_hermes",
]


IS_WINDOWS = sys.platform == "win32"

# Private launcher-to-child metadata. This is diagnostic state, not user config.
_WINDOWS_GATEWAY_BREAKAWAY_ENV = "_HERMES_GATEWAY_BREAKAWAY"


def split_command_line(line: str) -> list[str]:
    """Split a user-supplied command line into tokens, Windows-safely.

    ``shlex.split(line)`` (posix=True) treats every backslash as an escape
    character, so Windows paths are silently mangled: ``C:\\Users\\me\\out.txt``
    becomes ``C:Usersmeout.txt`` — no error, just a wrong path that then
    "succeeds" against a mangled relative filename (#83934) or makes a valid
    hook script report "not executable" (#78293).

    On Windows this uses ``posix=False``, which preserves backslashes while
    still honoring double-quoted tokens ("path with spaces"). The trade-off
    is that posix=False keeps surrounding quotes on quoted tokens, so we
    strip one layer of matching double quotes per token — that matches how
    Windows command lines are conventionally parsed. On POSIX the behavior
    is exactly ``shlex.split``.

    Raises ValueError for unbalanced quotes, same as ``shlex.split``.
    """
    if not IS_WINDOWS:
        import shlex

        return shlex.split(line)
    import shlex

    tokens = shlex.split(line, posix=False)
    out: list[str] = []
    for tok in tokens:
        if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in ("'", '"'):
            tok = tok[1:-1]
        out.append(tok)
    return out


# -----------------------------------------------------------------------------
# Node ecosystem launcher resolution
# -----------------------------------------------------------------------------


def resolve_node_command(name: str, argv: Sequence[str]) -> list[str]:
    """Resolve a Node-ecosystem command name to an absolute-path argv.

    On Windows, commands like ``npm``, ``npx``, ``yarn``, ``pnpm``,
    ``playwright``, ``prettier`` ship as ``.cmd`` files (batch shims).
    ``subprocess.Popen(["npm", "install"])`` fails with WinError 193
    because CreateProcessW doesn't execute batch files directly.

    ``shutil.which(name)`` *does* resolve ``.cmd`` via PATHEXT and returns
    the fully-qualified path — which CreateProcessW accepts because the
    extension tells Windows to route through ``cmd.exe /c``.

    On POSIX ``shutil.which`` also returns a fully-qualified path when
    found.  That's a small change from bare-name resolution (the OS does
    its own PATH search) but functionally identical and has the side
    benefit of making the argv reproducible in logs.

    Behavior when the command is not on PATH:
    - On Windows: return the bare name — caller can still try with
      ``shell=True`` as a last resort, OR the subsequent Popen will
      raise FileNotFoundError with a readable error we want to surface.
    - On POSIX: same.  Bare ``npm`` on a Linux box without npm installed
      fails the same way it did before this function existed.

    Args:
        name: The command name to resolve (``npm``, ``npx``, ``node`` …).
        argv: The remaining arguments.  Must NOT include ``name`` itself —
            this function builds the full argv list.

    Returns:
        A list suitable for passing to subprocess.Popen/run/call.
    """
    resolved = shutil.which(name)
    if resolved:
        return [resolved, *argv]
    return [name, *argv]


# -----------------------------------------------------------------------------
# Detached / hidden process creation
# -----------------------------------------------------------------------------


# Win32 CreationFlags — defined here rather than imported from subprocess
# because CREATE_NO_WINDOW and DETACHED_PROCESS aren't guaranteed to be
# present on stdlib subprocess on older Pythons or non-Windows builds.
_CREATE_NEW_PROCESS_GROUP = 0x00000200
# DETACHED_PROCESS is intentionally NOT part of any flag bundle here — do not
# re-add it.  Two reasons (the recurring console-flash bug #54220 / #56747):
#
# 1. MSDN (Process Creation Flags): CREATE_NO_WINDOW "is ignored if used with
#    either CREATE_NEW_CONSOLE or DETACHED_PROCESS".  Combining them means
#    DETACHED_PROCESS governs and the no-window bit is dead.
# 2. A DETACHED_PROCESS child has NO console at all, so every console-subsystem
#    descendant it ever spawns (git, gh, cmd, node, wmic, powershell, …) must
#    allocate its OWN console — a visible flash per spawn, including spawns
#    inside third-party libraries that no per-call-site CREATE_NO_WINDOW sweep
#    can reach.  A CREATE_NO_WINDOW child instead OWNS a hidden console that
#    all descendants inherit, making "no flashing windows" a property of the
#    one daemon launch.  Root cause isolated + A/B verified on Windows 11 by
#    the desktop backend fix (commit aa2ae36c3f): with per-site hide flags
#    neutered, naive git/gh/cmd spawns don't flash under a hidden-console
#    parent and do flash under a console-less one.
_DETACHED_PROCESS = 0x00000008  # kept for reference; must stay out of bundles
_CREATE_NO_WINDOW = 0x08000000
# Escape any Win32 job object the parent process belongs to. Without this,
# a detached child still inherits its parent's job object membership, and
# when that parent (Electron, Tauri, Windows Terminal, the Desktop GUI's
# bootstrap-installer) dies, the OS tears down the whole job — taking the
# "detached" child with it. Critical for the post-update gateway watcher:
# Electron spawns the Tauri updater inside its own job, the updater spawns
# the watcher subprocess; without BREAKAWAY the watcher dies the instant
# Electron exits, so the gateway never gets respawned after a `hermes
# update` triggered from the GUI. See fix/windows-gateway-reliability.
_CREATE_BREAKAWAY_FROM_JOB = 0x01000000


def windows_detach_flags() -> int:
    """Return Win32 creationflags that detach a child from the parent
    console and process group without leaving it console-less.  0 on
    non-Windows.

    Pair with ``start_new_session=False`` (default) when calling
    subprocess.Popen — on POSIX use ``start_new_session=True`` instead,
    which maps to ``os.setsid()`` in the child.

    Rationale:
    - ``CREATE_NEW_PROCESS_GROUP`` — child has its own process group so
      Ctrl+C in the parent console doesn't propagate.
    - ``CREATE_NO_WINDOW`` — the child gets its own fresh console that is
      never shown.  This both detaches it from the parent's console
      lifetime (closing the launching terminal doesn't CTRL_CLOSE it) AND
      gives every console-subsystem descendant (git, gh, cmd, node, …) a
      console to inherit, so they don't allocate visible flashing ones.
      This deliberately replaces the old ``DETACHED_PROCESS`` approach:
      MSDN specifies CREATE_NO_WINDOW is *ignored* when combined with
      DETACHED_PROCESS, and a truly console-less daemon re-creates the
      per-descendant console-flash bug (#54220/#56747) at every spawn —
      see the note on ``_DETACHED_PROCESS`` above.
    - ``CREATE_BREAKAWAY_FROM_JOB`` — escape any job object the parent is
      in.  Electron (Desktop app) and Tauri (bootstrap installer) wrap
      their children in job objects; without breakaway, those children
      die when the parent process exits even though they have their own
      console.  This was the missing flag that made the post-update
      gateway respawn watcher silently die alongside the Tauri updater
      after the Electron Desktop's update flow finished.

    If a process is in a job that disallows breakaway (rare —
    JOB_OBJECT_LIMIT_BREAKAWAY_OK isn't set), CreateProcess returns
    ERROR_ACCESS_DENIED.  Python surfaces that as ``PermissionError``
    on the ``subprocess.Popen`` call.  Callers in this codebase already
    wrap detached spawns in ``try/except OSError`` and fall back to a
    cmd.exe wrapper, so the breakaway-denied case degrades gracefully
    rather than crashing.
    """
    if not IS_WINDOWS:
        return 0
    return (
        _CREATE_NEW_PROCESS_GROUP
        | _CREATE_NO_WINDOW
        | _CREATE_BREAKAWAY_FROM_JOB
    )


def windows_detach_flags_without_breakaway() -> int:
    """Same as :func:`windows_detach_flags` minus ``CREATE_BREAKAWAY_FROM_JOB``.

    The docstring on :func:`windows_detach_flags` notes that a process in
    a job which disallows breakaway (no ``JOB_OBJECT_LIMIT_BREAKAWAY_OK``)
    will see ``ERROR_ACCESS_DENIED`` from CreateProcess, surfacing as
    ``OSError`` (``PermissionError``) on the ``subprocess.Popen`` call.
    Callers that want to recover — by retrying without the breakaway
    bit — can pair the two helpers symbolically rather than coding the
    ``& ~0x01000000`` magic at every site:

    .. code-block:: python

        try:
            subprocess.Popen(argv, creationflags=windows_detach_flags(), …)
        except OSError:
            subprocess.Popen(
                argv,
                creationflags=windows_detach_flags_without_breakaway(),
                …,
            )

    See ``gateway_windows.py::_spawn_detached`` for the canonical
    implementation of this pattern.  Returns 0 on non-Windows.
    """
    if not IS_WINDOWS:
        return 0
    return _CREATE_NEW_PROCESS_GROUP | _CREATE_NO_WINDOW


def windows_hide_flags() -> int:
    """Return Win32 creationflags that merely hide the child's console
    window without detaching the child.  0 on non-Windows.

    Use for short-lived console apps spawned as part of a larger
    operation (``taskkill``, ``where``, version probes) where we want no
    flash but also want to collect stdout/exit code synchronously.

    The difference from :func:`windows_detach_flags`: no
    ``CREATE_NEW_PROCESS_GROUP`` / ``CREATE_BREAKAWAY_FROM_JOB`` — the
    child stays in the parent's process group and job so Ctrl+C and job
    teardown propagate normally, as a short-lived helper wants.  Stdio
    handles are inherited either way, so ``capture_output=True`` works
    with both bundles.
    """
    if not IS_WINDOWS:
        return 0
    return _CREATE_NO_WINDOW


def suppress_platform_ver_console() -> None:
    """Stub out ``platform._syscmd_ver`` on Windows so it can never flash a
    console window.  No-op on non-Windows.

    CPython's ``platform.win32_ver()`` — reached by ``platform.uname()``,
    ``platform.version()``, and ``platform.platform()`` — unconditionally
    shells out ``cmd /c ver`` via ``subprocess.check_output(..., shell=True)``
    with no ``CREATE_NO_WINDOW``.  From a windowless parent (the pythonw
    gateway and every kanban worker it spawns) that allocates a fresh
    *visible* console: one flashing ``cmd`` window per process, triggered by
    any dependency that merely touches ``platform.uname()`` at import time.

    With ``_syscmd_ver`` stubbed to return its inputs, ``win32_ver()`` hits
    the documented ``ValueError`` fallback and reads the version from
    ``sys.getwindowsversion().platform_version`` — same information, queried
    in-process, no subprocess, no window.  Verified equivalent on
    CPython 3.11 (``platform()`` → ``Windows-10-10.0.xxxxx-SP0`` either way).

    Call early, before heavyweight imports — the flash typically happens
    during a dependency's import, not from Hermes' own code.
    """
    if not IS_WINDOWS:
        return
    try:
        import platform

        if hasattr(platform, "_syscmd_ver"):
            def _quiet_syscmd_ver(system="", release="", version="",
                                  supported_platforms=("win32", "win16", "dos")):
                return system, release, version

            platform._syscmd_ver = _quiet_syscmd_ver
    except Exception:
        # Purely cosmetic hardening — never let it break startup.
        pass


def windows_detach_popen_kwargs() -> dict:
    """Return a dict of Popen kwargs that detach a child on Windows and
    fall back to the POSIX equivalent (``start_new_session=True``) on
    Linux/macOS.

    Usage pattern:

    .. code-block:: python

        subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            close_fds=True,
            **windows_detach_popen_kwargs(),
        )

    This replaces the unsafe-on-Windows pattern:

    .. code-block:: python

        subprocess.Popen(..., start_new_session=True)

    which silently fails to detach on Windows (the flag is accepted but
    has no effect — the child stays attached to the parent's console
    and dies when the console closes).
    """
    if IS_WINDOWS:
        return {"creationflags": windows_detach_flags()}
    return {"start_new_session": True}


# -----------------------------------------------------------------------------
# Non-interactive git environment (credential-prompt hang guard)
# -----------------------------------------------------------------------------


# GIT_CONFIG_KEY_n/VALUE_n overrides for internal git children: no credential/askpass prompts, no
# repo-configured fsmonitor/hooks/pager/editor/external-diff programs.
_GIT_CONFIG_INJECT_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
_GIT_CONFIG_OVERRIDES = {
    "credential.helper": "",
    "core.askPass": "",
    "core.fsmonitor": "false",
    "core.untrackedCache": "false",
    "core.hooksPath": os.devnull,
    "core.pager": "cat",
    "core.editor": "true",
    "sequence.editor": "true",
    "diff.external": "",
    # ssh itself bypasses stdin=DEVNULL/GIT_TERMINAL_PROMPT and opens /dev/tty directly — an
    # unknown host key (or password auth) prompts there and steals the caller's terminal (#104591).
    # BatchMode makes ssh fail instead of prompting; a working ssh-agent still succeeds. Injected
    # at the config layer so an explicit user GIT_SSH_COMMAND (env) still takes precedence.
    "core.sshCommand": "ssh -o BatchMode=yes",
}


def noninteractive_git_env(
    base: "Mapping[str, str] | None" = None,
) -> dict[str, str]:
    """Environment for *internal* git invocations that must never prompt.

    Copy of ``base`` (default ``os.environ``) with ``GIT_TERMINAL_PROMPT=0`` (fail instead of
    prompting), ``GCM_INTERACTIVE=Never`` (no Git Credential Manager dialog), and isolated git
    config: inherited ``GIT_CONFIG_*`` injection, global/system config, pagers, editors, fsmonitor,
    external diff and hooks are all disabled so a user's repo/global config cannot hang or mutate
    Hermes's plumbing calls. ``core.sshCommand`` is pinned to ``ssh -o BatchMode=yes`` so the ssh
    child of a fetch/ls-remote fails instead of prompting — ssh bypasses ``stdin=DEVNULL`` and
    opens ``/dev/tty`` directly (#104591); an agent-authenticated ssh still succeeds, and an
    explicit user ``GIT_SSH_COMMAND`` env var still takes precedence over this config-layer pin.
    ``GIT_ASKPASS``/``SSH_ASKPASS`` env vars are left alone, but OpenSSH BatchMode disables
    passphrase/password prompts, including SSH askpass. Usable keys and ssh-agent authentication
    still work; Git's own working askpass helper is unaffected. Pair with
    ``stdin=subprocess.DEVNULL``. Internal plumbing only — the agent-facing terminal tool has its
    own policy layer and visible PTY.

    Hermes shells out to git from many non-interactive contexts — MCP catalog installs, plugin
    install/update, profile distribution staging, worktree base fetches, desktop review-pane fetch/push.
    When the remote is private, misconfigured, or requires auth, git's default behavior is to prompt on the
    inherited terminal (or via an askpass helper), which silently hangs the operation until its timeout — or
    forever at call sites without one. Ported from openai/codex#34540 / #34612 ("detach non-interactive
    subprocesses from stdin"): a background tool invocation must fail fast with a readable error, not wait
    for input nobody can type.
    """
    env = dict(base if base is not None else os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "Never"
    # Drop caller-supplied config injection; the GIT_CONFIG_COUNT block is rebuilt below so
    # ambient -c values cannot re-enable pagers, hooks, fsmonitor, editors or credential prompts.
    for key in list(env):
        canonical = key.upper() if IS_WINDOWS else key
        if canonical in ("GIT_CONFIG", "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT") or canonical.startswith(_GIT_CONFIG_INJECT_PREFIXES):
            env.pop(key, None)
        elif key != canonical and canonical in {
            "GIT_TERMINAL_PROMPT", "GCM_INTERACTIVE", "GIT_CONFIG_GLOBAL",
            "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM", "GIT_PAGER", "PAGER", "GIT_EDITOR",
        }:
            env.pop(key, None)
    env.pop("GIT_CONFIG_COUNT", None)
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_SYSTEM"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_PAGER"] = "cat"
    env["PAGER"] = "cat"
    env["GIT_EDITOR"] = "true"
    env["GIT_CONFIG_COUNT"] = str(len(_GIT_CONFIG_OVERRIDES))
    for idx, (key, value) in enumerate(_GIT_CONFIG_OVERRIDES.items()):
        env[f"GIT_CONFIG_KEY_{idx}"] = key
        env[f"GIT_CONFIG_VALUE_{idx}"] = value
    return env


FILTER_DISCOVERY_FAILED = "git filter discovery failed"


class GitPolicyError(RuntimeError):
    """Internal Git policy refused an operation; recovery must not bypass it."""


def git_policy_environment_valid(env: Mapping[str, str], base: Mapping[str, str] | None = None) -> bool:
    """Check required controls using the existing static policy as authority."""
    expected = noninteractive_git_env(base)
    def effective(values):
        count = int(values['GIT_CONFIG_COUNT'])
        if not 1 <= count <= 1000:
            raise ValueError('invalid configuration count')
        result = {}
        for index in range(count):
            key, value = values[f'GIT_CONFIG_KEY_{index}'], values[f'GIT_CONFIG_VALUE_{index}']
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError('invalid configuration entry')
            result[key.lower()] = value
        return result
    try:
        actual = effective(env)
        if any(actual.get(key) != value for key, value in effective(expected).items()):
            return False
        names = ('GIT_TERMINAL_PROMPT', 'GCM_INTERACTIVE', 'GIT_CONFIG_GLOBAL',
                 'GIT_CONFIG_SYSTEM', 'GIT_CONFIG_NOSYSTEM', 'GIT_PAGER', 'PAGER', 'GIT_EDITOR')
        return all(env.get(key) == expected[key] for key in names)
    except (KeyError, ValueError, TypeError, AttributeError):
        return False


NO_DRIVER_DIFF_FLAGS = ("--no-ext-diff", "--no-textconv")
_FILTER_COMMAND_KEY = re.compile(r"^filter\..+\.(?:clean|smudge|process)$", re.IGNORECASE)
_INCLUDE_IF_KEY = re.compile(r"^includeif\..*\.path$", re.IGNORECASE)
_INCLUDE_KEY = re.compile(r"^include(?:if\..*)?\.path$", re.IGNORECASE)
_DISCOVERY_KEYS_REGEXP = r"^(filter\..*\.(clean|smudge|process)|include\.path|includeif\..*\.path)$"
_MAX_INCLUDE_TARGETS = 16
_MAX_FILTER_KEYS = 256
_SAFE_INLINE_CONFIG = {"user.name", "user.email", "checkout.workers", "checkout.thresholdforparallelism", "core.quotepath", "core.abbrev", "windows.appendatomically"}
_EOL_VALUES = {"core.autocrlf": {"true", "false", "input"}, "core.eol": {"lf", "crlf", "native"}}
_INTERNAL_GIT_DEADLINE: ContextVar[float | None] = ContextVar("internal_git_deadline", default=None)


def _with_git_deadline(function):
    """Share one operation budget across discovery and execution probes."""
    @wraps(function)
    def bounded(*args, timeout, **kwargs):
        previous = _INTERNAL_GIT_DEADLINE.get()
        deadline = time.monotonic() + timeout
        token = _INTERNAL_GIT_DEADLINE.set(min(previous, deadline) if previous is not None else deadline)
        try:
            return function(*args, timeout=timeout, **kwargs)
        finally:
            _INTERNAL_GIT_DEADLINE.reset(token)
    return bounded


def _git_boolean(value: str | None, cwd, base, git_bin) -> str | None:
    """Parse with the selected Git without reading repository configuration."""
    # --default is type-converted by Git. A null config source avoids parsing
    # unrelated repository values (notably the valid autocrlf=input setting).
    # A valueless config entry means true; an explicitly empty value is false.
    default = "true" if value is None else value
    result = bounded_probe_run(
        [git_bin, "config", "--file", os.devnull, "--type=bool", "--default", default,
         "--get", "hermes.policyboolean"],
        cwd=cwd, timeout=2, env=noninteractive_git_env(base),
    )
    if result is None or result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value in {"true", "false"} else None


def _effective_eol_config(cwd, base, git_bin) -> dict[str, str] | None:
    """Read only benign EOL values; executable Git config remains disabled."""
    original = os.environ if base is None else base
    env = noninteractive_git_env(original)
    controls = {"GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_NOSYSTEM"}
    for key in controls:
        env.pop(key, None)
    for key, value in original.items():
        canonical = key.upper() if IS_WINDOWS else key
        if canonical in controls:
            env[canonical] = value
    nosystem = env.get("GIT_CONFIG_NOSYSTEM")
    system_disabled = _git_boolean(nosystem, cwd, original, git_bin) if nosystem is not None else "false"
    if system_disabled is None:
        return None
    # Git silently ignores unreadable global/system sources in ordinary config
    # queries. Resolve implicit sources through the same Git, rather than
    # guessing HOME/XDG or compiled system-config paths.
    for key in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        if key == "GIT_CONFIG_SYSTEM" and system_disabled == "true":
            continue
        value = env.get(key)
        if value is None:
            path_env = noninteractive_git_env(original)
            path_env.pop(key, None)
            if key == "GIT_CONFIG_SYSTEM":
                path_env["GIT_CONFIG_NOSYSTEM"] = "0"
            paths = bounded_probe_run([git_bin, "-C", str(cwd), "var", key], timeout=2, env=path_env)
            if paths is None or paths.returncode != 0 or not paths.stdout.endswith("\n"):
                return None
            values = [line.rstrip("\r") for line in paths.stdout[:-1].split("\n")]
            if not values or len(values) > 16 or any(not path for path in values):
                return None
        else:
            values = [value]
        for value in values:
            if not value or value.lower() == os.devnull.lower():
                continue
            source = Path(value)
            if not source.is_absolute():
                source = Path(cwd) / source
            try:
                source.stat()
            except FileNotFoundError:
                continue
            except OSError:
                return None
            if not source.is_file():
                return None
            readable = bounded_probe_run(
                [git_bin, "config", "--file", str(source), "--no-includes",
                 "--name-only", "-z", "--list"], timeout=2,
                env=noninteractive_git_env(original),
            )
            if readable is None or readable.returncode != 0:
                return None
    result = bounded_probe_run(
        [git_bin, "-C", str(cwd), "config", "--includes", "-z", "--get-regexp",
         r"^(core\.autocrlf|core\.eol)$"], timeout=2, env=env,
    )
    if result is None or result.returncode not in (0, 1):
        return None
    if result.returncode == 1:
        return {} if not result.stdout else None
    fields = result.stdout.split("\0")
    if fields[-1]:
        return None
    raw_effective: dict[str, tuple[str, bool]] = {}
    for entry in fields[:-1]:
        key, separator, value = entry.partition("\n")
        key = key.lower()
        if key not in _EOL_VALUES:
            return None
        raw_effective[key] = (value, bool(separator))
    effective: dict[str, str] = {}
    for key, (raw, has_value) in raw_effective.items():
        value = raw.strip().lower()
        if key == "core.autocrlf" and value != "input":
            value = _git_boolean(raw if has_value else None, cwd, original, git_bin)
        if value not in _EOL_VALUES[key]:
            return None
        effective[key] = value
    return effective


def harden_git_argv(args: Sequence[str]) -> list[str]:
    """Disable attribute-selected diff programs on internal rendering commands."""
    out = list(args)
    index = 0
    while index < len(out):
        token = out[index]
        if token == "-c":
            if index + 1 >= len(out) or out[index + 1].partition("=")[0].lower() not in _SAFE_INLINE_CONFIG:
                raise ValueError("Unsupported internal Git configuration override")
            index += 2
        elif token.startswith("-c") and not token.startswith("--"):
            if token[2:].partition("=")[0].lower() not in _SAFE_INLINE_CONFIG:
                raise ValueError("Unsupported internal Git configuration override")
            index += 1
        elif token.startswith("-"):
            if token not in {"--no-pager", "--no-replace-objects", "--version"}:
                raise ValueError("Unsupported internal Git authority argument")
            index += 1
        else:
            if token in {"diff", "show", "log", "blame"}:
                options = out[index + 1:]
                if "--" in options:
                    options = options[:options.index("--")]
                if any(option in {"--textconv", "--ext-diff"} for option in options):
                    raise ValueError("Internal Git diff program cannot be reenabled")
                return out[:index + 1] + list(NO_DRIVER_DIFF_FLAGS) + out[index + 1:]
            break
    return out


def noninteractive_repo_git_env(
    cwd: str | os.PathLike[str],
    base: Mapping[str, str] | None = None,
    *,
    git_bin: str = "git",
    preserve_eol: bool = False,
) -> dict[str, str] | None:
    """Extend the existing policy with bounded, fail-closed filter discovery.

    Use the same selected Git for discovery and the operation. Inactive
    conditional includes are scanned because a worktree/branch change can
    activate them. This sequence is not an atomic configuration snapshot.
    """
    env = noninteractive_git_env(base)
    try:
        result = bounded_probe_run(
            [git_bin, "-C", str(cwd), "config", "--includes", "--show-origin", "-z",
             "--get-regexp", _DISCOVERY_KEYS_REGEXP], timeout=2, env=env,
        )
        if result is None or result.returncode not in (0, 1):
            return None
        if result.returncode == 1 and result.stdout:
            return None
        fields = result.stdout.split("\0")
        if fields[-1] or len(fields[:-1]) % 2:
            return None
        names: list[str] = []
        targets: set[Path] = set()
        include_entries: set[tuple[str, str, str]] = set()
        toplevel: Path | None = None
        for origin, entry in zip(fields[:-1:2], fields[1:-1:2]):
            key, separator, value = entry.partition("\n")
            if not separator:
                return None
            if not _INCLUDE_IF_KEY.fullmatch(key):
                names.append(key)
                continue
            if not origin.startswith("file:"):
                return None
            entry_identity = (origin, key, value)
            if entry_identity in include_entries:
                continue
            if len(include_entries) >= _MAX_INCLUDE_TARGETS:
                return None
            include_entries.add(entry_identity)
            origin_path = Path(origin[5:])
            if not origin_path.is_absolute():
                if env.get("GIT_DIR") or env.get("GIT_WORK_TREE"):
                    return None
                if toplevel is None:
                    top = bounded_probe_run(
                        [git_bin, "-C", str(cwd), "rev-parse", "--show-toplevel"], timeout=2, env=env,
                    )
                    if top is None or top.returncode != 0:
                        return None
                    toplevel = Path(top.stdout.rstrip("\r\n"))
                origin_path = toplevel / origin_path
            if value.startswith(("~", "%(")):
                expanded = bounded_probe_run(
                    [git_bin, "config", "--file", str(origin_path), "--path", "--fixed-value", "-z",
                     "--get", key, value], timeout=2, env=env,
                )
                if expanded is None or expanded.returncode != 0 or not expanded.stdout.endswith("\0"):
                    return None
                value = expanded.stdout[:-1]
                if "\0" in value or value.startswith(("~", "%(")):
                    return None
            target = (origin_path.parent / value).resolve()
            if target in targets or not target.exists():
                continue
            if not target.is_file() or len(targets) >= _MAX_INCLUDE_TARGETS:
                return None
            targets.add(target)
            probe = bounded_probe_run(
                [git_bin, "config", "--file", str(target), "--name-only", "-z",
                 "--get-regexp", _DISCOVERY_KEYS_REGEXP], timeout=2, env=env,
            )
            if probe is None or probe.returncode not in (0, 1):
                return None
            if probe.returncode == 1 and probe.stdout:
                return None
            found = probe.stdout.split("\0")
            if found[-1] or any(_INCLUDE_KEY.fullmatch(name) for name in found):
                return None
            names.extend(found[:-1])
        keys: list[str] = []
        required: list[str] = []
        seen: set[str] = set()
        for raw in names:
            key = raw.strip()
            if key in seen or not _FILTER_COMMAND_KEY.fullmatch(key):
                continue
            seen.add(key)
            keys.append(key)
            if len(keys) > _MAX_FILTER_KEYS:
                return None
            required_key = key.rsplit(".", 1)[0] + ".required"
            if required_key not in seen:
                seen.add(required_key)
                required.append(required_key)
        start = int(env["GIT_CONFIG_COUNT"])
        overrides = [(key, "") for key in keys] + [(key, "false") for key in required]
        if preserve_eol:
            eol = _effective_eol_config(cwd, base, git_bin)
            if eol is None:
                return None
            overrides.extend(eol.items())
        for offset, (key, value) in enumerate(overrides):
            env[f"GIT_CONFIG_KEY_{start + offset}"] = key
            env[f"GIT_CONFIG_VALUE_{start + offset}"] = value
        env["GIT_CONFIG_COUNT"] = str(start + len(overrides))
        return env
    except (OSError, ValueError, TypeError):
        return None


@_with_git_deadline
def run_internal_git(
    args: Sequence[str],
    cwd: str | os.PathLike[str],
    *,
    timeout: float,
    base: Mapping[str, str] | None = None,
    git_bin: str | None = None,
    check_policy: bool = False,
    preserve_eol: bool = True,
    binary_output: bool = False,
    max_output_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run internal plumbing through the existing environment/timeout owners."""
    binary = git_bin or shutil.which("git", path=(base if base is not None else os.environ).get("PATH"))
    try:
        argv = [binary or "git", *harden_git_argv(args)]
    except ValueError:
        if check_policy:
            raise GitPolicyError("unsupported internal git arguments")
        return subprocess.CompletedProcess([binary or "git", *args], 1, "", "unsupported internal git arguments")
    if not binary:
        return subprocess.CompletedProcess(argv, 127, "", "git executable unavailable")
    env = noninteractive_repo_git_env(cwd, base, git_bin=binary, preserve_eol=preserve_eol)
    if env is None or not git_policy_environment_valid(env, base):
        if check_policy:
            raise GitPolicyError(FILTER_DISCOVERY_FAILED)
        return subprocess.CompletedProcess(argv, 1, "", FILTER_DISCOVERY_FAILED)
    result = bounded_probe_run(argv, timeout=timeout, env=env, cwd=cwd, binary_output=binary_output,
                               **({"max_output_bytes": max_output_bytes} if max_output_bytes is not None else {}))
    if result is None:
        return subprocess.CompletedProcess(argv, 124, "", "git invocation failed or timed out")
    return result


@_with_git_deadline
def clone_git_repository(
    source: str, destination: str | os.PathLike[str], *, timeout: float,
    git_bin: str | None = None, branch: str | None = None,
    shallow: bool = False, no_checkout: bool = False,
    base: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Clone through the static policy; a fresh repo has no config to discover."""
    env = noninteractive_git_env(base)
    for key in list(env):
        canonical = key.upper() if IS_WINDOWS else key
        if canonical in {"GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
                         "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
                         "GIT_NAMESPACE", "GIT_SHALLOW_FILE"}:
            env.pop(key)
    binary = git_bin or shutil.which("git", path=env.get("PATH"))
    argv = [binary or "git", "clone", "--template="]
    if shallow:
        argv += ["--depth", "1"]
    if no_checkout:
        argv.append("--no-checkout")
    if branch is not None:
        argv += ["--branch", branch]
    destination = Path(destination).absolute()
    argv += ["--", source, str(destination)]
    if binary is None:
        return subprocess.CompletedProcess(argv, 127, "", "git executable unavailable")
    result = bounded_probe_run(argv, timeout=timeout, env=env, cwd=destination.parent)
    if result is None:
        return subprocess.CompletedProcess(argv, 124, "", "git clone timed out or could not start")
    return result


@_with_git_deadline
def run_internal_gh(
    args: Sequence[str],
    cwd: str | os.PathLike[str],
    *,
    timeout: float,
    base: Mapping[str, str] | None = None,
    gh_bin: str | None = None,
    git_bin: str | None = None,
    check_policy: bool = False,
    preserve_eol: bool = True,
    binary_output: bool = False,
    max_output_bytes: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Protect gh's delegated Git calls with the same repository policy."""
    inherited = base if base is not None else os.environ
    binary = gh_bin or shutil.which("gh", path=inherited.get("PATH"))
    git_binary = git_bin or shutil.which("git", path=inherited.get("PATH"))
    argv = [binary or "gh", *args]
    if not binary or not git_binary:
        return subprocess.CompletedProcess(argv, 127, "", "gh or git executable unavailable")
    env = noninteractive_repo_git_env(cwd, base, git_bin=git_binary, preserve_eol=preserve_eol)
    if env is None or not git_policy_environment_valid(env, base):
        if check_policy:
            raise GitPolicyError(FILTER_DISCOVERY_FAILED)
        return subprocess.CompletedProcess(argv, 1, "", FILTER_DISCOVERY_FAILED)
    env["GH_PROMPT_DISABLED"] = "1"
    env["PATH"] = str(Path(git_binary).parent) + os.pathsep + env.get("PATH", "")
    result = bounded_probe_run(argv, timeout=timeout, env=env, cwd=cwd, binary_output=binary_output,
                               **({"max_output_bytes": max_output_bytes} if max_output_bytes is not None else {}))
    if result is None:
        return subprocess.CompletedProcess(argv, 124, "", "gh invocation failed or timed out")
    return result


# -----------------------------------------------------------------------------
# Bounded, fail-open git probing (Windows post-kill deadlock guard)
# -----------------------------------------------------------------------------



def _process_start_time(pid: int) -> int | None:
    """Return the repository's stable process-start fingerprint, if available."""
    try:
        from gateway.status import get_process_start_time

        return get_process_start_time(pid)
    except Exception:
        return None


def _text_names_hermes(text: str) -> bool:
    """True when *text* names Hermes at a path-segment / token boundary.

    A bare ``"hermes" in text`` substring test would also match unrelated
    processes whose paths merely contain the letters (``...\\shermesa\\...``),
    which is exactly the false-positive class this guard exists to prevent.
    Instead, split on path separators and whitespace and require a segment
    that *starts with* ``hermes`` (``hermes``, ``hermes.exe``, ``hermes_cli``,
    ``hermes-agent``, ``hermes-runtime``) or the hidden-dir form
    ``.hermes``/``.hermes-runtime``.
    """
    for token in re.split(r"[\\/\s=,;\"']+", text.lower()):
        if token.startswith("hermes") or token.startswith(".hermes"):
            return True
    return False


def _process_command_is_hermes(pid: int) -> bool:
    """Best-effort check that *pid* currently runs Hermes code."""
    try:
        import psutil

        process = psutil.Process(pid)
        command = " ".join(process.cmdline() or [])
        executable = process.exe() or ""
        return _text_names_hermes(f"{command} {executable}")
    except Exception:
        return False


def pid_is_hermes(
    pid: int,
    *,
    expected_start_time: int | None = None,
) -> bool:
    """Return whether it is safe to use ``taskkill`` for *pid*.

    The PID must be valid, currently exist, and identify a Hermes process. When
    the caller captured a start-time fingerprint before the destructive action,
    the live process must still have the same ``(pid, start_time)`` identity.
    Any ambiguity fails closed. Non-Windows callers have no ``taskkill`` path,
    so a valid PID with no (or a matching) explicit expectation is accepted
    there — but a caller-provided fingerprint that no longer matches is a
    recycled PID on every platform and is always refused.
    """
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if not IS_WINDOWS:
        if expected_start_time is None:
            return True
        try:
            return _process_start_time(pid) == expected_start_time
        except Exception:
            return False

    try:
        current_start_time = _process_start_time(pid)
    except Exception:
        return False
    if current_start_time is None:
        return False
    if (
        expected_start_time is not None
        and current_start_time != expected_start_time
    ):
        return False
    try:
        return _process_command_is_hermes(pid)
    except Exception:
        return False


def kill_process_tree(proc: "subprocess.Popen") -> None:
    """Best-effort terminate *proc* and its descendants on both platforms.

    ``proc.kill()`` alone only terminates the direct child. On Windows a
    suspended descendant (e.g. ``git.exe``) can survive holding duplicates of the
    captured pipe handles, which keeps the pipes from reaching EOF and leaks two
    reader threads + the process per fired timeout — ``taskkill /T /F`` takes the
    whole tree down so the bounded drain that follows can actually reach EOF.
    On POSIX the same class exists: killing the launcher leaves descendants
    (credential helpers, ``git-remote-https``, hook children) running and
    holding the pipe write ends. Callers spawn the child in its own process
    group (``process_group=0``, Python ≥3.11), so when — and only
    when — the child leads its own group (``pgid == pid``), the entire group is
    signalled with ``os.killpg``. The ownership check means a fallback spawn
    that shares our group can never cause us to kill unrelated processes.
    Ported from openai/codex#36793 ("Terminate timed-out Git process trees");
    generalized for the shell-hook runner via openai/codex#37527
    ("Terminate timed-out hook process trees").

    All failures are swallowed — this is cleanup on an already-failing path, and
    the caller's contract is to fail open. ``kill()`` can raise (access denied,
    already reaped); an unhandled raise here would escape the caller's ``except``
    handler and break that contract. The ``taskkill`` spawn itself cannot
    re-enter the deadlock class it fixes: it captures no pipes (DEVNULL), so its
    own timeout cleanup has no reader threads to join.

    Delegates the tree-kill to :func:`agent.deadline.kill_process_tree`
    (#85125 4d) — same taskkill /T /F on Windows and killpg-when-leader on
    POSIX, plus a psutil descendant sweep that also reaches descendants that
    ``setsid``'d into their own sessions. On any import/delegation failure it
    falls back to the original local implementation
    (:func:`_legacy_kill_process_tree`), so the fail-open contract holds even
    in stripped environments.
    """
    try:
        from agent.deadline import kill_process_tree as _deadline_kill_tree

        _deadline_kill_tree(proc.pid)
    except Exception:
        _legacy_kill_process_tree(proc)
        return
    # Ensure Popen's own bookkeeping sees the exit (matches the legacy body:
    # a direct kill() so communicate()/wait() cannot hang on a stale handle).
    try:
        proc.kill()
    except OSError:
        pass


def _legacy_kill_process_tree(proc: "subprocess.Popen") -> None:
    """Pre-#85125 local tree-kill — fallback when agent.deadline is unavailable.

    Kept verbatim so ``kill_process_tree`` can honor its swallow-everything
    contract even when the delegation path itself fails (partial install,
    import cycle during teardown).
    """
    if not IS_WINDOWS:
        # Group-kill first: verify the child actually leads its own process
        # group before signalling it, so we never blast a shared group.
        try:
            import signal as _signal

            pgid = os.getpgid(proc.pid)
            if pgid == proc.pid:
                os.killpg(pgid, _signal.SIGKILL)  # windows-footgun: ok — inside `if not IS_WINDOWS` gate
        except Exception:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    if IS_WINDOWS:
        # No identity guard here on purpose: *proc* is our own retained
        # ``Popen`` handle. The child cannot be reaped (and its PID cannot be
        # recycled) while we still hold the handle, so an identity check could
        # only ever false-refuse a legitimate cleanup. The fail-closed
        # ``pid_is_hermes`` guard is for BARE pids from state files or process
        # scans, where recycling is real.
        try:
            subprocess.run(
                ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                timeout=2,
                check=False,
                creationflags=windows_hide_flags(),
            )
        except Exception:
            pass


def _bounded_pipe_output(proc: subprocess.Popen, timeout: float, limit: int) -> tuple[bytes, bytes] | None:
    """Bound each binary pipe while preserving the existing tree-cleanup owner."""
    failed = threading.Event()
    outputs: list[list[bytes]] = [[], []]

    def read_pipe(stream, chunks: list[bytes]) -> None:
        total = 0
        try:
            while chunk := os.read(stream.fileno(), 65536):
                total += len(chunk)
                if total > limit:
                    failed.set()
                if not failed.is_set():
                    chunks.append(chunk)
        except (OSError, ValueError):
            failed.set()
        finally:
            stream.close()

    readers = [threading.Thread(target=read_pipe, args=(stream, chunks), daemon=True)
               for stream, chunks in zip((proc.stdout, proc.stderr), outputs)]
    for reader in readers:
        reader.start()
    expires = time.monotonic() + timeout
    while not failed.is_set():
        if proc.poll() is not None and not any(reader.is_alive() for reader in readers):
            if failed.is_set():
                break
            return b"".join(outputs[0]), b"".join(outputs[1])
        remaining = expires - time.monotonic()
        if remaining <= 0:
            break
        failed.wait(min(.02, remaining))
    kill_process_tree(proc)
    drain_until = time.monotonic() + 1
    for reader in readers:
        reader.join(max(0, drain_until - time.monotonic()))
    try:
        proc.wait(timeout=max(0, drain_until - time.monotonic()))
    except subprocess.TimeoutExpired:
        pass
    return None


def bounded_probe_run(
    argv: Sequence[str],
    *,
    timeout: float,
    errors: str = "replace",
    env: Mapping[str, str] | None = None,
    cwd: str | os.PathLike[str] | None = None,
    binary_output: bool = False,
    max_output_bytes: int | None = None,
) -> "subprocess.CompletedProcess[str] | None":
    """Deadlock-safe ``subprocess.run(argv, capture_output=True, timeout=...)``
    for fail-open probe call sites. Returns a ``CompletedProcess`` when the
    child finished within *timeout* (any exit code), or ``None`` on spawn
    failure or timeout.

    Why not ``subprocess.run``: on Windows, ``run()``'s post-timeout cleanup
    calls an *unbounded* ``communicate()`` after killing the direct child.
    Killing it can leave a descendant (``git.exe`` under a launcher shim,
    ``conhost.exe`` under wmic/powershell) holding duplicates of the captured
    stdout/stderr handles, so the pipes never reach EOF and the reader-thread
    join blocks forever. The wmic / ``Get-CimInstance Win32_Process`` gateway
    scan hit exactly this during ``hermes update`` on slow-WMI machines
    (#87134); the git probes hit it first (#68609 / #66037).

    The bounded flow: an explicit ``communicate(timeout)``, then on any
    failure a tree-kill (see :func:`kill_process_tree`) plus a bounded 1s
    post-kill drain; if the pipes are still held after that, they're abandoned
    (the orphaned reader threads are daemonic and cost nothing).

    The spawn contract mirrors the ``run`` calls it replaces: PIPE/PIPE/DEVNULL,
    ``text`` with UTF-8 decoding (*errors* configurable — the process scans use
    ``"ignore"``), and the hidden-window ``creationflags`` on Windows only. On
    POSIX the child is placed in its own process group (``process_group=0``,
    Python ≥3.11) so timeout cleanup can take down descendants with the
    launcher instead of orphaning them.
    """
    if max_output_bytes is not None and (not binary_output or isinstance(max_output_bytes, bool)
                                        or not isinstance(max_output_bytes, int) or max_output_bytes <= 0):
        raise ValueError("output limit requires a positive integer and binary pipes")
    deadline = _INTERNAL_GIT_DEADLINE.get()
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        timeout = min(timeout, remaining)
    _popen_kwargs: dict = {"creationflags": windows_hide_flags()} if IS_WINDOWS else {"process_group": 0}
    if env is not None:
        _popen_kwargs["env"] = env
    if cwd is not None:
        _popen_kwargs["cwd"] = cwd
    if not binary_output:
        _popen_kwargs.update(text=True, encoding="utf-8", errors=errors)
    try:
        proc = subprocess.Popen(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            **_popen_kwargs,
        )
    except Exception:
        return None
    try:
        if deadline is not None:
            timeout = max(0, min(timeout, deadline - time.monotonic()))
        if max_output_bytes is not None:
            output = _bounded_pipe_output(proc, timeout, max_output_bytes)
            if output is None:
                return None
            stdout, stderr = output
        else:
            stdout, stderr = proc.communicate(timeout=timeout)
    except Exception:
        # Timeout OR any other communicate() failure (torn-down pipe, decode
        # error): terminate the child + descendants and drain bounded. Leaving
        # it running would leak the same suspended-descendant class this guards.
        kill_process_tree(proc)
        try:
            proc.communicate(timeout=1)
        except Exception:
            pass
        return None
    return subprocess.CompletedProcess(list(argv), proc.returncode, stdout, stderr)


def bounded_git_probe(argv: Sequence[str], *, timeout: float) -> str:
    """Run a short, throwaway ``git`` probe and return stripped stdout, or ``""``
    on ANY failure (nonzero exit, timeout, spawn error, decode error).

    This is the shared, deadlock-safe replacement for
    ``subprocess.run(["git", ...], timeout=...)`` at fail-open probe call sites
    (``tui_gateway.git_probe.run_git``, ``agent.coding_context._git``).

    Why not ``subprocess.run``: on Windows, ``run()``'s post-timeout cleanup
    calls an *unbounded* ``communicate()`` after killing git. Killing the
    PATH-resolved launcher can leave a suspended descendant ``git.exe`` holding
    duplicates of the captured stdout/stderr handles, so the pipes never reach
    EOF and the reader-thread join blocks forever. On the Desktop agent-build
    path (``_start_agent_build → _session_info → branch() → run_git``) that turned
    an optional branch label into ``agent initialization timed out``
    (issues #68609 / #66037).

    The bounded flow: an explicit ``communicate(timeout)``, then on any failure a
    tree-kill (see :func:`_kill_git_process_tree`) plus a bounded 1s post-kill
    drain; if the pipes are still held after that, they're abandoned (the orphaned
    reader threads are daemonic and cost nothing).

    The normal-path spawn contract mirrors the previous ``run`` call byte-for-byte:
    PIPE/PIPE/DEVNULL, ``text`` with UTF-8 ``errors="replace"`` decoding, and the
    hidden-window ``creationflags`` on Windows only. On POSIX the probe is
    additionally placed in its own process group (``process_group=0``,
    Python ≥3.11) so timeout cleanup can take down descendants — credential
    helpers, ``git-remote-https``, hook children — with the launcher instead of
    orphaning them (see :func:`_kill_git_process_tree`; port of
    openai/codex#36793). ``process_group`` only changes which group the child
    belongs to; it does not detach the terminal or alter the fast path.
    """
    if not argv:
        return ""
    binary = shutil.which(argv[0])
    if binary is None:
        return ""
    args = list(argv[1:])
    if len(args) >= 2 and args[0] == "-C":
        result = run_internal_git(args[2:], args[1], timeout=timeout, git_bin=binary)
    else:
        result = run_internal_git(args, os.getcwd(), timeout=timeout, git_bin=binary)
    if result.returncode != 0:
        return ""
    return (result.stdout or "").strip()


# Backward-compat alias — existing call sites/tests import the historical name.
_kill_git_process_tree = kill_process_tree

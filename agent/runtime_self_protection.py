"""Identify destructive operations against the Python runtime running Hermes.

This is a narrow, local-process safety floor. It does not grant an approval or
replace the existing command and file-tool owners.
"""

from __future__ import annotations

import ntpath
import os
import re
import shlex
import sys
import glob
from pathlib import Path


_WIN_POSIX_DRIVE = re.compile(r"^/(?:mnt/)?([a-zA-Z])/(.*)$")
_POWERSHELL_ENV = re.compile(r"(?i)\$env:([A-Za-z_][A-Za-z0-9_]*)")
_UV_INSTALL = re.compile(
    r"(?i)(?P<root>.*[/\\]uv[/\\]python[/\\]cpython-"
    r"(?P<version>\d+(?:\.\d+)*)(?:[-_][^/\\]*)?)(?:[/\\].*)?$"
)
_DELETING = frozenset({"rm", "rmdir", "rd", "del", "erase", "remove-item", "ri"})
_PREFIXES = frozenset({"sudo", "command", "nohup", "exec", "env", "nice", "time"})
_WRAPPERS = frozenset({"cmd", "powershell", "pwsh", "bash", "sh"})
_NESTED_DELETE = re.compile(
    r"(?i)(?<![A-Za-z0-9_])(?:rm|rmdir|rd|del|erase|remove-item|ri|find|uv)(?![A-Za-z0-9_])"
)


def _unquote(value: str) -> str:
    value = value.strip()
    while len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return value


def _normalize_path(
    raw: str, *, cwd: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> str:
    quoted = str(raw or "").strip()
    literal = len(quoted) >= 2 and quoted[0] == quoted[-1] == "'"
    path = _unquote(quoted)
    if not path:
        return ""
    if not literal:
        if os.name == "nt":
            path = _POWERSHELL_ENV.sub(
                lambda match: (env_overrides or {}).get(
                    match.group(1).upper(), os.environ.get(match.group(1), "")
                ), path
            )
        path = os.path.expandvars(os.path.expanduser(path))
    if os.name == "nt":
        match = _WIN_POSIX_DRIVE.match(path.replace("\\", "/"))
        if match:
            path = f"{match.group(1)}:\\{match.group(2)}"
        path = path.replace("/", "\\")
    if cwd and not os.path.isabs(path):
        path = os.path.join(cwd, path)
    try:
        return os.path.normcase(os.path.realpath(path))
    except (OSError, ValueError):
        return os.path.normcase(os.path.abspath(path))


def _pyvenv_home(prefix: str) -> str:
    try:
        lines = (Path(prefix) / "pyvenv.cfg").read_text(
            encoding="utf-8-sig", errors="replace"
        ).splitlines()
    except (OSError, ValueError):
        return ""
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key.strip().lower() == "home":
            return value.strip()
    return ""


def _protected_paths() -> tuple[tuple[str, str], ...]:
    """Read the active runtime coordinates; do not cache a changed pyvenv.cfg."""
    executable = str(getattr(sys, "executable", "") or "")
    prefix = str(getattr(sys, "prefix", "") or "")
    entries: list[tuple[str, str]] = []
    for raw, label in (
        (executable, "running Python interpreter"),
        (prefix, "running Python environment"),
        (_pyvenv_home(prefix), "running Python base interpreter"),
        (str(getattr(sys, "_base_executable", "") or ""), "running Python base interpreter"),
    ):
        normalized = _normalize_path(raw)
        if normalized and normalized not in {entry[0] for entry in entries}:
            entries.append((normalized, label))
        if label != "running Python base interpreter":
            continue
        uv_match = _UV_INSTALL.match(raw.replace("\\", "/"))
        if uv_match:
            uv_root = _normalize_path(uv_match.group("root"))
            if uv_root and uv_root not in {entry[0] for entry in entries}:
                entries.append((uv_root, f"running uv Python {uv_match.group('version')}"))
    return tuple(entries)


def _overlaps(path: str, protected: str) -> bool:
    try:
        common = os.path.commonpath((path, protected))
    except (ValueError, OSError):
        return False
    return common == path or common == protected


def is_protected_path(
    path: str, *, cwd: str | None = None,
    env_overrides: dict[str, str] | None = None,
) -> str | None:
    """Describe the active runtime touched by a write/delete path, if any."""
    resolved = _normalize_path(path, cwd=cwd, env_overrides=env_overrides)
    if not resolved:
        return None
    for protected, description in _protected_paths():
        if _overlaps(resolved, protected):
            return description
    return None


def _segments(command: str) -> list[list[str]]:
    """Split shell command separators outside quotes, preserving Windows slashes."""
    if os.name == "nt":
        # shlex(posix=False) only recognizes a quote at the start of a word;
        # $env:NAME="a; b" would otherwise split in the middle of its value.
        segments: list[list[str]] = [[]]
        word: list[str] = []
        quote: str | None = None
        escaped = False

        def finish_word() -> None:
            if word:
                segments[-1].append("".join(word))
                word.clear()

        for char in command:
            if quote:
                word.append(char)
                if escaped:
                    escaped = False
                elif char == "`":
                    escaped = True
                elif char == quote:
                    quote = None
            elif char in "\"'":
                word.append(char)
                quote = char
            elif char in " \t\r":
                finish_word()
            elif char in ";&|\n":
                finish_word()
                if segments[-1]:
                    segments.append([])
            else:
                word.append(char)
        finish_word()
        return segments

    lexer = shlex.shlex(command, posix=os.name != "nt", punctuation_chars=";&|\n")
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = command.replace("\n", ";").split()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= {";", "&", "|", "\n"}:
            segments.append([])
        else:
            segments[-1].append(token)
    return segments


def _command_name(word: str) -> str:
    word = _unquote(word)
    name = ntpath.basename(word) if os.name == "nt" else os.path.basename(word)
    name = name.lower()
    return name[:-4] if name.endswith(".exe") else name


def _strip_prefixes(words: list[str]) -> list[str]:
    remaining = words[:]
    while remaining:
        name = _command_name(remaining[0])
        if name in _PREFIXES:
            remaining.pop(0)
            if name in {"sudo", "env"}:
                while remaining and remaining[0].startswith("-"):
                    option = remaining.pop(0).lower()
                    if option in {"-u", "--user", "--unset"} and remaining:
                        remaining.pop(0)
            continue
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", _unquote(remaining[0])):
            remaining.pop(0)
            continue
        break
    return remaining


def _uv_uninstall_hit(words: list[str]) -> str | None:
    lowered = [_unquote(word).lower() for word in words]
    if len(lowered) < 3 or lowered[1:3] != ["python", "uninstall"]:
        return None
    specs = lowered[3:]
    for root, description in _protected_paths():
        if not description.startswith("running uv Python "):
            continue
        version = description.removeprefix("running uv Python ")
        root_name = ntpath.basename(root).lower()
        for spec in specs:
            if spec in {"--all", "-a", "all"}:
                return description
            if spec.startswith("-"):
                continue
            if spec == version or version.startswith(spec + ".") or root_name.startswith(spec):
                return description
    return None


def _invoked_powershell_block(command: str) -> tuple[str, str] | None:
    """Return the body and trailing command of a leading &/. script block."""
    match = re.match(r"\s*[&.]\s*\{", command)
    if not match:
        return None
    start = match.end() - 1
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(command)):
        char = command[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "`":
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return command[start + 1:index], command[index + 1:]
    return None


def _delete_operand_hit(
    word: str, *, command_name: str, cwd: str | None,
    env_overrides: dict[str, str],
) -> str | None:
    """Resolve a deletion operand, including shell-expanded filesystem globs."""
    operands = [word]
    if command_name in {"rm", "rmdir", "find"}:
        # Bash concatenates quoted and unquoted pieces before glob/brace
        # expansion: ".v"* and .v{env,other} both can name .venv.
        bash_word = word.replace('"', "").replace("'", "")
        pending = [bash_word]
        operands = []
        while pending:
            variant = pending.pop()
            brace = re.search(r"\{([^{}]*)\}", variant)
            if not brace:
                operands.append(variant)
                continue
            alternatives = brace.group(1).split(",")
            if len(alternatives) == 1:
                if ".." in alternatives[0]:
                    return "ambiguous deletion pattern"
                operands.append(variant)
                continue
            if len(operands) + len(pending) + len(alternatives) > 64:
                return "ambiguous deletion pattern"
            pending.extend(
                variant[:brace.start()] + option + variant[brace.end():]
                for option in alternatives
            )
    for operand in operands:
        hit = is_protected_path(operand, cwd=cwd, env_overrides=env_overrides)
        if hit:
            return hit
        pattern = _normalize_path(operand, cwd=cwd, env_overrides=env_overrides)
        if not glob.has_magic(pattern):
            continue
        for index, candidate in enumerate(
            glob.iglob(pattern, recursive=True, include_hidden=True)
        ):
            if index >= 256:
                return "ambiguous deletion pattern"
            hit = is_protected_path(candidate)
            if hit:
                return hit
    return None


def command_deletes_runtime(
    command: str, *, cwd: str | None = None, _depth: int = 0,
    _env_overrides: dict[str, str] | None = None,
) -> str | None:
    """Describe a direct shell deletion of the active runtime, if recognized."""
    if not command:
        return None
    if _depth > 3:
        return "uninspected nested deletion" if _NESTED_DELETE.search(command) else None
    invoked_block = _invoked_powershell_block(command)
    if invoked_block:
        body, remainder = invoked_block
        hit = command_deletes_runtime(
            body, cwd=cwd, _depth=_depth + 1, _env_overrides=_env_overrides,
        )
        if hit:
            return hit
        return command_deletes_runtime(
            remainder, cwd=cwd, _depth=_depth + 1, _env_overrides=_env_overrides,
        )
    shell_env = dict(_env_overrides or {})
    for segment in _segments(command):
        assignment_name = ""
        assignment_value = ""
        if len(segment) == 3 and segment[1] == "=":
            assignment_name, assignment_value = segment[0], segment[2]
        elif len(segment) == 1 and "=" in segment[0]:
            assignment_name, assignment_value = segment[0].split("=", 1)
        assignment = _POWERSHELL_ENV.fullmatch(assignment_name)
        if assignment and not any(marker in assignment_value for marker in ("$", "%", "`")):
            shell_env[assignment.group(1).upper()] = _unquote(assignment_value)
            continue
        words = _strip_prefixes(segment)
        if not words:
            continue
        name = _command_name(words[0])
        if name in _WRAPPERS:
            if name == "cmd":
                switches = {"/c", "/k"}
            elif name in {"bash", "sh"}:
                switches = {"-c", "-lc", "-ic", "-cl"}
            else:
                switches = {"-command", "-c"}
            command_at = next(
                (index for index, word in enumerate(words[1:], 1) if word.lower() in switches),
                None,
            )
            if command_at is not None:
                inner_words = words[command_at + 1:]
                inner = " ".join(inner_words)
                if len(inner_words) == 1:
                    inner = _unquote(inner)
                hit = command_deletes_runtime(
                    inner, cwd=cwd, _depth=_depth + 1,
                    _env_overrides=shell_env,
                )
                if hit:
                    return hit
            continue
        if name == "uv":
            hit = _uv_uninstall_hit(words)
            if hit:
                return hit
            continue
        find_delete = any(word.lower() == "-delete" for word in words[1:])
        find_exec_delete = any(
            word.lower() == "-exec"
            and index + 1 < len(words)
            and _command_name(words[index + 1]) in _DELETING
            for index, word in enumerate(words)
        )
        if name == "find" and (find_delete or find_exec_delete):
            for word in words[1:]:
                if not word.startswith("-"):
                    hit = _delete_operand_hit(
                        word, command_name=name, cwd=cwd, env_overrides=shell_env,
                    )
                    if hit:
                        return hit
            continue
        if name not in _DELETING:
            continue
        if name in {"remove-item", "ri"} and any(
            word.lower() in {"-whatif", "-whatif:$true"} for word in words[1:]
        ):
            continue
        for word in words[1:]:
            if word.startswith("-"):
                continue
            hit = _delete_operand_hit(
                word, command_name=name, cwd=cwd, env_overrides=shell_env,
            )
            if hit:
                return hit
    return None

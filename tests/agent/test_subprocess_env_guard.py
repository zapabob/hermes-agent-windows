import ast
import hashlib
import os
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

PYTHON_SCAN_DIRS = (
    "agent",
    "apps",
    "cron",
    "downstream",
    "gateway",
    "hermes_cli",
    "plugins",
    "scripts",
    "tools",
    "tui_gateway",
)
PYTHON_ROOT_FILES = ("cli.py", "hermes_constants.py", "run_agent.py")
TYPESCRIPT_SCAN_DIRS = (
    "apps/desktop/electron",
    "apps/desktop/scripts",
    "downstream",
    "scripts",
    "ui-tui",
)

PYTHON_PROCESS_CALLS = {
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "asyncio.subprocess.create_subprocess_exec",
    "asyncio.subprocess.create_subprocess_shell",
    "os.execve",
    "os.execvpe",
    "os.posix_spawn",
    "os.posix_spawnp",
    "os.spawnve",
    "os.spawnvpe",
    "ptyprocess.PtyProcess.spawn",
    "subprocess.Popen",
    "subprocess.call",
    "subprocess.check_call",
    "subprocess.check_output",
    "subprocess.run",
}
POSITIONAL_ENV_CALLS = {
    "os.execve": 2,
    "os.execvpe": 2,
    "os.posix_spawn": 2,
    "os.posix_spawnp": 2,
    "os.spawnve": 3,
    "os.spawnvpe": 3,
}
RAW_PYTHON_ENV_BUILDERS = (
    re.compile(r"\bos\.environ\.copy\s*\("),
    re.compile(r"\bdict\s*\(\s*os\.environ\s*\)"),
)
RAW_TYPESCRIPT_ENV_BUILDERS = (
    re.compile(r"\.\.\.\s*process\.env\b"),
    re.compile(r"Object\.assign\s*\(\s*\{\s*\}\s*,\s*process\.env\b"),
)

ALLOWED_RAW_ENV_OWNER_FILES = {
    "tools/environments/local.py": "central Python sanitizer snapshots the parent before filtering",
    "apps/desktop/electron/backend-env.ts": "central Electron allowlist builder filters the parent snapshot",
}

AUDITED_PYTHON_BOUNDARIES = {
    "agent/chat_completion_helpers.py": {"_run_fallback_start_command"},
    "agent/lsp/client.py": {"LSPClient._spawn"},
    "agent/lsp/install.py": {"_install_go", "_install_npm"},
    "agent/shell_hooks.py": {"_spawn"},
    "agent/skill_preprocessing.py": {"run_inline_shell"},
    "agent/transports/codex_app_server.py": {"CodexAppServerClient.__init__", "check_codex_binary"},
    "gateway/slash_commands.py": {"GatewaySlashCommandsMixin._handle_update_command"},
    "hermes_cli/mcp_catalog.py": {"_run_bootstrap"},
    "plugins/ai-partner-os/process.py": {"start_exe"},
    "plugins/sillytavern/__init__.py": {"sillytavern_proxy_start", "sillytavern_start"},
    "tools/lazy_deps.py": {"_venv_pip_install"},
    "tui_gateway/methods_tools.py": {"_"},
}
AUDITED_TYPESCRIPT_BOUNDARIES = {"apps/desktop/electron/main.ts": {"spawnUpdaterProcess"}}
LEGACY_IMPLICIT_RATIONALE = (
    "Exact pre-existing utility subprocess set outside SEC-001 through SEC-015; any hash change requires review."
)
LEGACY_RAW_ENV_RATIONALE = (
    "Exact pre-existing raw environment set outside SEC-001 through SEC-015; any hash change requires review."
)
APPROVED_IMPLICIT_SPAWN_BASELINES = {
    "agent": ("d782f1f78702bebfba47c9f3bf8e0e6756358f63747f609022eb650e6a8ff36f", LEGACY_IMPLICIT_RATIONALE),
    "apps/desktop/electron": (
        # Audited reduction: link-title fetching no longer spawns curl.
        "60f4332f15f4af885771753792fb58715e72c2a7fa28a4ab7c7dd5cdecd47d02",
        LEGACY_IMPLICIT_RATIONALE,
    ),
    "apps/desktop/scripts": (
        "e96c609717f53b2f4f1c984d9f209f0f6467883e02c31d8d16d3a4196aa65687",
        LEGACY_IMPLICIT_RATIONALE,
    ),
    "cli.py": ("b2bd458df1c719588dd62ee33336fa9aacffe54438e3eb817bbe70bbd89b6760", LEGACY_IMPLICIT_RATIONALE),
    "cron": ("e3b322c51645ed1dab6a817a4c24bc210b7ebeb5a32edfc726f55ebfc9c86ce9", LEGACY_IMPLICIT_RATIONALE),
    "downstream": ("8eb57e2d493e19d6e0e0b9c91627d3980693c6a4ec5a5dea503c3441ef139551", LEGACY_IMPLICIT_RATIONALE),
    "gateway": ("7c888db74531e5ade41e806eb9ae704b5657b00c27fbe36a00e547d5f7ca6c78", LEGACY_IMPLICIT_RATIONALE),
    # Hypura harness daemon launch switched DETACHED_PROCESS → windows_detach_flags
    # (CREATE_NO_WINDOW + explicit env=); implicit-spawn fingerprint refreshed.
    "hermes_cli": ("a77cceee55970f1d3f8ea55578e2bf52058189619324cce555a31e49b1515c05", LEGACY_IMPLICIT_RATIONALE),
    "hermes_constants.py": (
        "5b23578a51cafa9b8233e03e7bdddf96a68954014b2cfeae2b1da311ee734704",
        LEGACY_IMPLICIT_RATIONALE,
    ),
    "plugins": ("1798d998e3a7e50be65e5f7af10f30ae530cfb262efa84be89096902bc489491", LEGACY_IMPLICIT_RATIONALE),
    "scripts": ("f64ead6f1425a0a575a1cc7804e2ca8ee271a7edc8ebdbe3abaab0e9a4100f8d", LEGACY_IMPLICIT_RATIONALE),
    "tools": ("994ae77721eef4e6b519cff5882672141f42fc725e79c3d46c12067c9a14ceaf", LEGACY_IMPLICIT_RATIONALE),
    "tui_gateway": ("4de651931815b6b2a6acbb92092aaa973e738ca0e3424a7a3b66268c9c169447", LEGACY_IMPLICIT_RATIONALE),
    "ui-tui": ("88a4d1e5198da9b00a66f33915ae9908b1c80ffa0e3c5d7fba0636a4d70d4108", LEGACY_IMPLICIT_RATIONALE),
}
APPROVED_RAW_ENV_BASELINES = {
    "apps/desktop/electron": (
        # Audited reduction: runGit now uses the central Desktop env allowlist.
        "5e99cfb9d36be7b76902fd9649b00b45acb299ac3b821e89f9670a7e67087afc",
        LEGACY_RAW_ENV_RATIONALE,
    ),
    "apps/desktop/scripts": (
        "2a3c19121878dd4331bb84eeb82606ed3cbcc330700c09308e914a9e99a15199",
        LEGACY_RAW_ENV_RATIONALE,
    ),
    "cron": ("f6ef16046414a0c08cf18132190d0df8d54be0a994aa02e190dee44268b2d0df", LEGACY_RAW_ENV_RATIONALE),
    "hermes_cli": ("4f78087143e76d2ecd930fcd7df0b928b8d0e8b7516fbfaba13c961f39b24c24", LEGACY_RAW_ENV_RATIONALE),
    "plugins": ("a697e30cb6201ebfb649772c3183d77482d578fc181ccf36d5d0fe77e346d2af", LEGACY_RAW_ENV_RATIONALE),
    "scripts": ("8fe4efbc63affcc3adbe3b926bd35e6df7a49b03c79aa31d67ae515a7d66e0e6", LEGACY_RAW_ENV_RATIONALE),
    "tools": ("3f4ecb3e5f0b39a7c4766a23a5569aff5bfd1d16a581dba0773158f219dc2dbc", LEGACY_RAW_ENV_RATIONALE),
    "ui-tui": ("9b8fdcb1ea838cf26416d233911dbea3e716bc27f8b35216a61654e6b584e813", LEGACY_RAW_ENV_RATIONALE),
}


def _walk_files(root, excluded):
    # Prune dependency trees before traversal, including Windows junctions.
    for directory, children, files in os.walk(root):
        children[:] = [name for name in children if name not in excluded]
        for name in files:
            yield Path(directory) / name


def _iter_python_files():
    for directory in PYTHON_SCAN_DIRS:
        root = REPO_ROOT / directory
        if root.is_dir():
            yield from (
                path
                for path in _walk_files(root, {"tests", "node_modules", ".gitnexus"})
                if path.suffix == ".py" and "tests" not in path.relative_to(REPO_ROOT).parts
                and "node_modules" not in path.relative_to(REPO_ROOT).parts
                and ".gitnexus" not in path.relative_to(REPO_ROOT).parts
            )
    for filename in PYTHON_ROOT_FILES:
        path = REPO_ROOT / filename
        if path.is_file():
            yield path


def _iter_typescript_files():
    extensions = {".js", ".mjs", ".ts", ".tsx"}
    for directory in TYPESCRIPT_SCAN_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in _walk_files(root, {"node_modules", "dist", ".gitnexus"}):
            rel_parts = path.relative_to(REPO_ROOT).parts
            if (
                path.is_file()
                and path.suffix in extensions
                and "node_modules" not in rel_parts
                and "dist" not in rel_parts
                and ".gitnexus" not in rel_parts
                and ".test." not in path.name
                and ".node-test." not in path.name
                and ".spec." not in path.name
            ):
                yield path


def _attribute_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _python_import_aliases(tree: ast.AST) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in {"asyncio", "os", "ptyprocess", "subprocess"}:
                    aliases[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                qualified = f"{node.module}.{alias.name}"
                if qualified in PYTHON_PROCESS_CALLS or node.module == "ptyprocess":
                    aliases[alias.asname or alias.name] = qualified
    return aliases


def _python_qualnames(tree: ast.AST) -> dict[ast.AST, str]:
    names: dict[ast.AST, str] = {}

    def visit(node: ast.AST, parents: tuple[str, ...] = ()) -> None:
        current = parents
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            current = (*parents, node.name)
        names[node] = ".".join(current) or "<module>"
        for child in ast.iter_child_nodes(node):
            visit(child, current)

    visit(tree)
    return names


def _normalized_first_arg(call: ast.Call) -> str:
    if not call.args:
        return "<none>"
    return " ".join(ast.unparse(call.args[0]).split())[:120]


def _raw_python_environment_value(node: ast.AST) -> bool:
    rendered = ast.unparse(node)
    return any(pattern.search(rendered) for pattern in RAW_PYTHON_ENV_BUILDERS)


@lru_cache(maxsize=1)
def _python_spawn_sites():
    sites = []
    counters: Counter[tuple[str, str, str, str]] = Counter()
    for path in _iter_python_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError:
            continue
        aliases = _python_import_aliases(tree)
        qualnames = _python_qualnames(tree)
        raw_names: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                if not _raw_python_environment_value(node.value):
                    continue
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        raw_names.setdefault(qualnames[node], set()).add(target.id)
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = _attribute_name(node.func)
            if not called:
                continue
            root, separator, suffix = called.partition(".")
            resolved = aliases.get(root, root)
            if separator:
                resolved = f"{resolved}.{suffix}"
            if resolved not in PYTHON_PROCESS_CALLS:
                continue
            has_env = any(keyword.arg == "env" for keyword in node.keywords)
            positional_index = POSITIONAL_ENV_CALLS.get(resolved)
            if positional_index is not None and len(node.args) > positional_index:
                has_env = True
            segment = ast.get_source_segment(source, node) or ""
            raw = any(pattern.search(segment) for pattern in RAW_PYTHON_ENV_BUILDERS)
            for keyword in node.keywords:
                if keyword.arg == "env" and isinstance(keyword.value, ast.Name):
                    raw = raw or keyword.value.id in raw_names.get(qualnames[node], set())
            base = (rel, qualnames[node], resolved, _normalized_first_arg(node))
            counters[base] += 1
            key = ":".join((*base, f"#{counters[base]}"))
            sites.append((key, rel, has_env, raw))
    return tuple(sites)


def _mask_typescript(source: str) -> str:
    chars = list(source)
    index = 0
    quote: str | None = None
    while index < len(chars):
        char = chars[index]
        following = chars[index + 1] if index + 1 < len(chars) else ""
        if quote:
            if char == "\\":
                chars[index] = " "
                if index + 1 < len(chars):
                    chars[index + 1] = " "
                index += 2
                continue
            if char == quote:
                quote = None
            chars[index] = " "
        elif char in {"'", '"', "`"}:
            quote = char
            chars[index] = " "
        elif char == "/" and following == "/":
            end = source.find("\n", index)
            end = len(chars) if end == -1 else end
            chars[index:end] = " " * (end - index)
            index = end
            continue
        elif char == "/" and following == "*":
            end = source.find("*/", index + 2)
            end = len(chars) - 2 if end == -1 else end
            chars[index : end + 2] = " " * (end + 2 - index)
            index = end + 2
            continue
        index += 1
    return "".join(chars)


def _typescript_process_names(masked: str) -> set[str]:
    names = {"spawnUpdaterProcess"}
    import_re = re.compile(
        r"import\s*\{(?P<imports>[^}]*)\}\s*from\s*['\"](?:node:)?child_process['\"]"
    )
    process_exports = {
        "exec",
        "execFile",
        "execFileSync",
        "execSync",
        "fork",
        "spawn",
        "spawnSync",
    }
    for match in import_re.finditer(masked):
        for item in match.group("imports").split(","):
            parts = [part.strip() for part in item.strip().split(" as ")]
            if parts and parts[0] in process_exports:
                names.add(parts[-1])
    return names


def _balanced_typescript_call(masked: str, open_paren: int) -> int | None:
    depth = 0
    for index in range(open_paren, len(masked)):
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _typescript_first_arg(masked_call: str) -> str:
    open_paren = masked_call.find("(")
    depth = 0
    for index in range(open_paren + 1, len(masked_call)):
        char = masked_call[index]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            if depth == 0:
                return " ".join(masked_call[open_paren + 1 : index].split())[:120]
            depth -= 1
        elif char == "," and depth == 0:
            return " ".join(masked_call[open_paren + 1 : index].split())[:120]
    return "<none>"


@lru_cache(maxsize=1)
def _typescript_spawn_sites():
    sites = []
    counters: Counter[tuple[str, str, str]] = Counter()
    for path in _iter_typescript_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        masked = _mask_typescript(source)
        rel = path.relative_to(REPO_ROOT).as_posix()
        for name in _typescript_process_names(source):
            for match in re.finditer(rf"\b{re.escape(name)}\s*\(", masked):
                if re.search(r"\bfunction\s*$", masked[max(0, match.start() - 32) : match.start()]):
                    continue
                end = _balanced_typescript_call(masked, masked.find("(", match.start()))
                if end is None:
                    continue
                masked_call = masked[match.start() : end]
                source_call = source[match.start() : end]
                has_env = bool(re.search(r"\benv\s*:", masked_call))
                raw = any(pattern.search(source_call) for pattern in RAW_TYPESCRIPT_ENV_BUILDERS)
                first_arg = _typescript_first_arg(masked_call)
                base = (rel, name, first_arg)
                counters[base] += 1
                key = ":".join((*base, f"#{counters[base]}"))
                sites.append((key, rel, has_env, raw))
    return tuple(sites)


def _scope_for_path(rel: str) -> str:
    if rel.startswith("apps/desktop/electron/"):
        return "apps/desktop/electron"
    if rel.startswith("apps/desktop/scripts/"):
        return "apps/desktop/scripts"
    return rel.split("/", 1)[0]


def _fingerprints_by_scope(sites, predicate):
    grouped: dict[str, list[str]] = {}
    for key, rel, has_env, raw in sites:
        if predicate(has_env, raw):
            grouped.setdefault(_scope_for_path(rel), []).append(key)
    return {
        scope: hashlib.sha256("\n".join(sorted(keys)).encode("utf-8")).hexdigest()
        for scope, keys in grouped.items()
    }


def test_audited_python_boundaries_are_explicit_and_sanitized():
    offenders = [
        key
        for key, rel, has_env, raw in _python_spawn_sites()
        if key.split(":", 3)[1] in AUDITED_PYTHON_BOUNDARIES.get(rel, set()) and (not has_env or raw)
    ]
    assert not offenders, "Unsanitized audited Python spawn boundary(s):\n  " + "\n  ".join(offenders)


def test_audited_typescript_boundaries_are_explicit_and_sanitized():
    offenders = [
        key
        for key, rel, has_env, raw in _typescript_spawn_sites()
        if key.split(":", 2)[1] in AUDITED_TYPESCRIPT_BOUNDARIES.get(rel, set()) and (not has_env or raw)
    ]
    assert not offenders, "Unsanitized audited TypeScript spawn boundary(s):\n  " + "\n  ".join(offenders)


def test_implicit_spawn_set_matches_reviewed_baselines():
    sites = (*_python_spawn_sites(), *_typescript_spawn_sites())
    actual = _fingerprints_by_scope(sites, lambda has_env, _raw: not has_env)
    expected = {scope: digest for scope, (digest, _reason) in APPROVED_IMPLICIT_SPAWN_BASELINES.items()}
    assert actual == expected


def test_raw_environment_set_matches_reviewed_baselines():
    sites = (*_python_spawn_sites(), *_typescript_spawn_sites())
    actual = _fingerprints_by_scope(
        (site for site in sites if site[1] not in ALLOWED_RAW_ENV_OWNER_FILES),
        lambda _has_env, raw: raw,
    )
    expected = {scope: digest for scope, (digest, _reason) in APPROVED_RAW_ENV_BASELINES.items()}
    assert actual == expected


def test_security_exception_entries_are_documented():
    for scope, (_, reason) in APPROVED_IMPLICIT_SPAWN_BASELINES.items():
        assert reason.strip(), f"Missing implicit-spawn baseline rationale: {scope}"
    for scope, (_, reason) in APPROVED_RAW_ENV_BASELINES.items():
        assert reason.strip(), f"Missing raw-env baseline rationale: {scope}"
    for rel, reason in ALLOWED_RAW_ENV_OWNER_FILES.items():
        assert reason.strip(), f"Missing raw-env owner rationale: {rel}"
        assert (REPO_ROOT / rel).is_file(), f"Stale raw-env owner: {rel}"

# Familiar explicit VRChat launch integration audit (Codex)

Date: 2026-10-14

## Scope

Hermes Desktop の現在のユーザー入力が `strip()` 後に **完全一致**で
`VRChat起動` となる場合だけ、Familiar body を起動する。VRChat または
Familiar のライブ起動はこの実装・検証では行わない。

## Repository and policy review

- Root `AGENTS.md` and `apps/desktop/AGENTS.md` were reviewed.
- The core remains unchanged. The integration is a project-local standalone
  plugin under `plugins/familiar`, following the repository footprint ladder.
- Pre-existing modified/untracked files were inventoried before editing and
  left untouched.
- CodeGraph was used before broad source exploration:
  - `npx --yes @colbymchenry/codegraph status .`
  - `npx --yes @colbymchenry/codegraph sync .`
  - `npx --yes @colbymchenry/codegraph query prompt.submit`
  - `npx --yes @colbymchenry/codegraph query register_hook`
  - `npx --yes @colbymchenry/codegraph explore "desktop plugin user message submission"`
- Initial CodeGraph attempts were rejected by its Node 26 safety guard. A later
  invocation used the existing index successfully; status reported 9,089 files,
  196,190 nodes, and 608,288 edges, and sync reported `Already up to date`.
- CodeGraph and concrete source reads identified `pre_llm_call` as the plugin
  boundary that receives the current clean `original_user_message` and the
  session `platform` before any model invocation.

## Familiar provenance and execution contract

Official upstream: <https://github.com/Shoalstone/familiar>

- Added as a real git submodule at `vendor/familiar`.
- Pinned commit: `246831133ef6d9738085f370c45dc2805f8741ed` (`v0.2.0`).
- `.gitmodules` records the official URL.
- Parent index records `vendor/familiar` with gitlink mode `160000`.
- Upstream README states that clone-based commands are prefixed with `uv run`.
- Upstream `src/familiar/cli.py` defines `familiar run --print none` and
  `familiar status`.
- Upstream `src/familiar/mcp_server.py` confirms that ordinary `familiar mcp`
  auto-starts a body, while `familiar mcp --no-start` disables that behavior.
  This integration does **not** register MCP, so MCP discovery cannot bypass the
  launch gate. Any future MCP registration must use `mcp --no-start`.

## Security / intent contract

`plugins/familiar/core.py` owns the deterministic gate:

```text
source == "user"
platform == "desktop"
isinstance(raw_text, str)
raw_text.strip() == "VRChat起動"
```

The plugin registers only `pre_llm_call`; it registers no model-callable tool.
Therefore an LLM cannot fabricate a confirmation argument to reach process
creation. Assistant/tool turns do not invoke the hook as a new user turn, and
cron/other surfaces fail the platform gate. VRChat process visibility is ignored
and never acts as consent.

After the gate passes, the plugin checks the vendored checkout and `uv`, probes
Familiar through its own documented `status` command, and starts at most one body
under a lock using:

```text
uv run familiar run --print none
```

The process is created directly (no shell), hidden in a new process group on
Windows, with stderr appended to the active Hermes home's
`logs/familiar.log`.

## TDD evidence

### RED

Command:

```text
.venv/Scripts/python.exe -m pytest tests/plugins/test_familiar_plugin.py::test_launch_gate_accepts_only_stripped_exact_desktop_user_request -vv -o addopts= -p no:randomly --basetemp temp/pytest-familiar-red
```

Result: `2 failed`; expected `ModuleNotFoundError: No module named
'plugins.familiar'` before production files existed.

### GREEN

Command:

```text
.venv/Scripts/python.exe -m pytest tests/plugins/test_familiar_plugin.py -q -o addopts= -p no:randomly --basetemp temp/pytest-familiar-green
```

Result: `18 passed in 1.30s`.

Covered cases include exact text with surrounding whitespace, negative suffix,
quoted mention, topic mention, paraphrase, empty text, assistant/tool/cron
sources, non-Desktop platforms, process-detection-only input, idempotent status,
missing vendor checkout, exact upstream argv/cwd/Windows flags, and no registered
model tool.

### Related regression

```text
.venv/Scripts/python.exe -m pytest tests/hermes_cli/test_plugins.py tests/plugins/test_familiar_plugin.py -q -o addopts= -p no:randomly --basetemp temp/pytest-familiar-related
```

Result: `92 passed in 38.74s`.

### Static and discovery verification

- `python -m py_compile plugins/familiar/core.py plugins/familiar/__init__.py tests/plugins/test_familiar_plugin.py` — pass.
- `ruff check plugins/familiar tests/plugins/test_familiar_plugin.py` — pass.
- Isolated `HERMES_HOME` plugin discovery with `plugins.enabled: [familiar]` —
  `found=true`, `enabled=true`, `error=null`, hooks=`[pre_llm_call]`, tools=`[]`.
- `git submodule status vendor/familiar` — pinned clean checkout at
  `246831133ef6d9738085f370c45dc2805f8741ed` (`v0.2.0`).
- `git ls-files --stage vendor/familiar` — mode `160000` verified.
- Final post-path-normalisation rerun: plugin tests `18 passed in 0.96s`;
  plugin-manager regression tests `92 passed in 35.51s`; `py_compile` passed.
- UTF-8 without BOM, LF endings, and no trailing whitespace verified for owned
  Python/YAML/test files.
- Parent-session independent rerun after worker recovery: plugin contract tests
  `18 passed in 1.09s`; plugin-manager regression tests `92 passed in 37.59s`;
  `py_compile`, Ruff, and scoped `git diff --check` all passed.
- Parent-session isolated-profile discovery read-back: `found=true`,
  `enabled=true`, `error=null`, hooks=`[pre_llm_call]`, tools=`[]`; a negative
  near-match hook invocation returned no result and did not reach launch.

## Known limitations / non-actions

- No Familiar dependencies were installed and neither Familiar nor VRChat was
  launched; live verification is intentionally prohibited by the task.
- Standalone plugins are opt-in. After isolated discovery passed, the default
  profile was enabled with `hermes plugins enable familiar`. Read-back through
  `hermes plugins list --plain` reported `enabled bundled 0.1.0 familiar`. The
  CLI correctly reported that activation takes effect on the next session; the
  current long-lived session was not hot-mutated.
- Repository-wide `git diff --check` remains nonzero because of pre-existing
  trailing whitespace in `tools/mcp_tool.py:4032`; scoped new files are clean.
- No full repository test suite was run; focused plugin-manager coverage passed.
- No commit or push was performed.

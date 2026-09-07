# Hermes Agent - Development Guide & Architecture Manual

Instructions, design contracts, and operational standards for AI assistants and developers on `hermes-agent`.

**Never give up on the right solution.**

---

## 1. What Hermes Is & Core Philosophy

Hermes is a personal AI agent running a single core across CLI, Gateway (Telegram, Discord, Slack, LINE, WeCom, Weixin, Yuanbao, Signal, etc.), TUI, and Electron Desktop. It learns across sessions (memory + skills), delegates to subagents, schedules jobs, and drives a real terminal and browser. Capabilities are added via **plugins and skills**, not by growing the core.

### Sacred Invariants
1. **Per-conversation prompt caching is sacred**: Long-lived conversations reuse cached model prefixes. Mutating past context, mid-turn toolset swapping, or rebuilding system prompts destroys the KV cache and multiplies API cost. (Sole exception: `agent/context_compressor.py`).
2. **The core is a narrow waist; capability lives at the edges**: Core tools are transmitted on every API call. New capabilities must use the Footprint Ladder (CLI, skills, service-gated tools via `check_fn`, MCP, plugins).
3. **Surface capability is session-scoped**: UI features (desktop panes, reactions) resolve availability dynamically from `session.platform`, never from static environment variables (`os.environ["HERMES_DESKTOP"]`).
4. **Deterministic, Reversible Execution**: Destructive operations must provide recovery paths, auditability, and write approvals.

---

## 2. Contribution Rubric & Footprint Ladder

### What We Want
- **Fix real bugs thoroughly**: Reproduce on `main`, pinpoint exact manifesting lines, fix whole bug class across call paths.
- **Expand reach at edges**: Add platform adapters, providers, UI features via standard configs (`hermes tools`, `config.yaml`).
- **Refactor god-files**: Modularize `cli.py`, `run_agent.py`, `gateway/run.py` into focused mixins/helpers.
- **Extend, don't duplicate**: Formulate shared ABCs when 3+ PRs touch similar domain logic.
- **Behavior contracts over snapshots**: Assert structural invariants, not hardcoded literals or counts.
- **E2E validation**: Validate full resolution chains against isolated, temporary `HERMES_HOME`.
- **Cache- & Alternation-safe**: Byte-stable prompts, strict `system -> user -> assistant -> tool` message roles.
- **Preserve contributor credit**: Rebase-merge external contributions.

### What We Reject
- Speculative infrastructure (unused hooks/callbacks).
- New `HERMES_*` env vars for non-secret settings (`.env` is strictly for secrets; settings belong in `config.yaml`).
- New core tools when a skill, CLI command, or file tool suffices.
- Lazy-reading pagination (`offset`/`limit`) on skill or prompt tools.
- Mitigations destroying feature utility (always inspect `git log -p -S` first).
- Outbound telemetry without opt-in user config gates.
- In-tree third-party SaaS/observability connectors (belong in standalone repos under `~/.hermes/plugins/`).

### The Footprint Ladder (New Capability Decision Matrix)
1. **Extend Existing Code** (Zero new surface)
2. **CLI Command + Skill** (Zero model tool footprint; default for setup, cron, webhooks)
3. **Service-Gated Tool (`check_fn`)** (Dynamic availability when configured)
4. **Standalone Plugin** (`~/.hermes/plugins/` or pip package)
5. **MCP Server** (Catalog tool with zero core schema footprint)
6. **New Core Tool** (Universal primitive: terminal, file, web, browser)

---

## 3. Development Environment & Project Structure

### Python & Workspace Management
```bash
source .venv/bin/activate       # Linux/macOS (.venv preferred, fallback to venv)
.venv\Scripts\Activate.ps1       # Windows PowerShell
uv sync --all-extras             # Pinned via uv.lock
bash scripts/run_tests.sh       # Parity test runner
```

### Repository Layout
```
hermes-agent/
├── AGENTS.md / GEMINI.md / CLAUDE.md # Master guides & assistant mirrors
├── run_agent.py          # AIAgent class — conversation loop & execution engine
├── model_tools.py        # Tool discovery, schema compilation, handle_function_call()
├── toolsets.py           # Core toolset definitions (_HERMES_CORE_TOOLS, named sets)
├── cli.py                # HermesCLI — interactive terminal interface
├── hermes_state.py       # SessionDB — SQLite store (FTS5 search, WAL mode)
├── hermes_constants.py   # get_hermes_home(), display_hermes_home() — profile-aware paths
├── hermes_logging.py     # Multi-process logging (agent.log, errors.log, gateway.log)
├── batch_runner.py       # Multi-threaded parallel batch execution engine
├── agent/                # Conversation loop, prompt builder, memory, compression, adapters
├── hermes_cli/           # CLI subcommands, setup wizard, plugin manager, skin engine
├── tools/                # Built-in tools (file, terminal, browser, web, mcp, memory, tts, vision)
│   └── environments/     # Backends: local, docker, ssh, modal, daytona, singularity
├── gateway/              # Multi-channel gateway daemon (run.py, session.py, platforms/)
├── apps/desktop/         # Electron Desktop (React 19 + Tailwind v4 + Nanostores + Vite)
├── ui-tui/ & tui_gateway/# Ink (React) Terminal UI over stdio JSON-RPC
├── plugins/              # Extensible plugins (plugin_storage.py, memory/, model-providers/, kanban/)
├── cron/                 # Background scheduler (jobs.py, scheduler.py via croniter)
├── scripts/windows/      # Watchdog-Go, start-llama-*.ps1, Restart-*.ps1, footguns linter
├── fork/ & _docs/        # Fork overlays, harnesses, and MILSPEC implementation records
└── tests/                # Comprehensive test suite (~17k tests)
```

**Config & Logs**: `~/.hermes/config.yaml` (settings), `~/.hermes/.env` (secrets only), `~/.hermes/logs/` (`agent.log`, `errors.log`, `gateway.log`). Profile paths resolved via `get_hermes_home()`.

---

## 4. TypeScript & Frontend Architecture Style Guide

Applies to `apps/desktop/`, `ui-tui/`, `website/`, `tests-js/`:
- **Nanostores over context**: Use feature-scoped atoms (`src/store/`). Leaf components subscribe via `useStore`; non-rendering actions read via `$atom.get()`. Avoid prop-drilling across >2 layers.
- **Thin route roots**: Keep route files thin; compose views without turning roots into monolithic controllers.
- **Explicit callbacks**: Use terse void forms for side-effects: `onStateChange={st => void setGatewayState(st)}`, `onClick={() => void handleSave()}`.
- **Strict Interfaces**: Prefer `interface` over `type` for public props. Extend React primitives (`React.ComponentProps<'button'>`, `Omit<...>`, `Pick<...>`). No `any`.
- **Table-Driven Routing**: Replace verbose `switch`/`if-else` ladders with dictionary mappings.

---

## 5. Core AIAgent Architecture & Execution Loop

### AIAgent Signature (`run_agent.py`)
```python
class AIAgent:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        provider: str | None = None,
        api_mode: str | None = None,              # "chat_completions" | "codex_responses" | ...
        model: str = "",                          # Resolved from config if empty
        max_iterations: int = 500,                # Iteration budget (shared with subagents)
        enabled_toolsets: list[str] | None = None,
        disabled_toolsets: list[str] | None = None,
        quiet_mode: bool = False,
        save_trajectories: bool = False,
        platform: str | None = None,              # "cli", "telegram", "desktop", etc.
        session_id: str | None = None,
        skip_context_files: bool = False,
        skip_memory: bool = False,
        credential_pool: Any | None = None,
        reasoning_config: dict[str, Any] | None = None,
        checkpoints_enabled: bool = True,
    ) -> None: ...

    def chat(self, message: str) -> str: ...
    def run_conversation(self, user_message: str, system_message: str | None = None,
                         conversation_history: list[dict[str, Any]] | None = None,
                         task_id: str | None = None) -> dict[str, Any]: ...
```

### Synchronous Loop Invariants
1. **Interrupt Check**: Polls `self._interrupt_requested` every cycle to abort cleanly.
2. **Budget Grace Turn**: Single final grace turn granted (`self._budget_grace_call = True`) when iterations expire.
3. **OpenAI Schema**: `{"role": "system"|"user"|"assistant"|"tool", "content": "...", "tool_call_id": "..."}`.
4. **Reasoning Storage**: Thoughts and CoT blocks stored in `assistant_msg["reasoning"]`.
5. **Provider Adapters**: Native handling in `agent/*_adapter.py` for OpenAI, Anthropic, Gemini, Codex, Bedrock, Vertex, and local Llama backends.

---

## 6. CLI, TUI, Desktop & Gateway Architecture

### Slash Command Registry (`hermes_cli/commands.py`)
All commands register centrally as `CommandDef` instances in `COMMAND_REGISTRY`:
```python
@dataclass(frozen=True)
class CommandDef:
    name: str                                  # Command name without slash
    description: str                           # Short explanation
    category: str                              # Session, Configuration, Tools & Skills, Info, Exit
    aliases: tuple[str, ...] = ()              # Short aliases (e.g. ("mc",))
    args_hint: str = ""                        # Parameter hints
    cli_only: bool = False
    gateway_only: bool = False
    gateway_config_gate: str | None = None
```
- Skill slash commands (`agent/skill_commands.py`) inject as **user messages** to preserve prompt cache.

### TUI Architecture (`ui-tui` + `tui_gateway`)
Runs React/Ink in Node.js communicating with Python (`tui_gateway`) over stdio JSON-RPC:
- `prompt.submit` $\to$ `message.delta`/`complete` (text streaming)
- `tool.start`/`progress`/`complete` (tool activity)
- `approval.respond` $\leftarrow$ `approval.request` (action approvals)
- `secret.respond` $\leftarrow$ `secret.request` (masked inputs)
- `session.list`/`resume` (session picker)

### Desktop App (`apps/desktop/`)
Electron main + React renderer talking to headless backend via JSON-RPC. Curated slash commands gated in `apps/desktop/src/lib/desktop-slash-commands.ts` (`isDesktopSlashCommand`, `isDesktopSlashSuggestion`).

---

## 7. Tool Registration & Creation Standards

### Two-File Tool Registration Pattern

1. **Create `tools/your_tool.py`**:
```python
import json, os
from hermes_constants import display_hermes_home, get_hermes_home
from tools.registry import registry

def check_requirements() -> bool:
    return bool(os.getenv("EXAMPLE_API_KEY"))

def example_tool(query: str, task_id: str | None = None) -> str:
    try:
        res = {"success": True, "data": f"Processed {query}"}
        return json.dumps(res, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"success": False, "error": str(exc)}, ensure_ascii=False)

registry.register(
    name="example_tool",
    toolset="example",
    schema={
        "name": "example_tool",
        "description": f"Example tool description. Root: {display_hermes_home()}",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    handler=lambda args, **kw: example_tool(query=args.get("query", ""), task_id=kw.get("task_id")),
    check_fn=check_requirements,
    requires_env=["EXAMPLE_API_KEY"],
)
```

2. **Wire in `toolsets.py`**: Add name to `_HERMES_CORE_TOOLS` or a named set in `TOOLSETS`.

### Invariants for Tools
- Handlers MUST return a JSON string (`json.dumps(...)`).
- Descriptions referencing paths MUST use `display_hermes_home()`.
- State paths MUST use `get_hermes_home()` (never hardcode `~/.hermes`).
- Builtin meta-tools (`todo`, `memory`) are intercepted by `run_agent.py` before `handle_function_call()`.
- Tool names are injected dynamically in `model_tools.py:get_tool_definitions()`.

---

## 8. Dependency Pinning & Configuration Architecture

### Exact Supply Chain Pinning
- Core dependencies in `pyproject.toml` pinned to `>=floor,<next_major` or exact `==X.Y.Z`.
- Git URLs and GitHub Actions MUST use 40-character commit SHAs.
- Run `uv lock` whenever altering dependencies.

### Configuration Architecture
- **`config.yaml`**: Non-secret settings. Add defaults to `DEFAULT_CONFIG` in `hermes_cli/config.py`.
- **`.env`**: Secrets ONLY (API keys, tokens). Register in `OPTIONAL_ENV_VARS` in `hermes_cli/config.py`.
- **Loaders**: `load_cli_config()` (CLI), `load_config()` (CLI subcommands), direct YAML load (`gateway/run.py`).
- **Working Directory**: CLI uses `os.getcwd()`; Gateway uses `terminal.cwd` from `config.yaml`.

---

## 9. Extensible Plugin Ecosystem & Storage Isolation

### Plugin Registration (`plugins/<name>/__init__.py`)
Discovered from `~/.hermes/plugins/`, `./.hermes/plugins/`, and pip entry points:
```python
from plugins.plugin_storage import plugin_data_dir, plugin_db

def register(ctx):
    data_path = plugin_data_dir("my_plugin")
    db = plugin_db("my_plugin", "state.db") # WAL-enabled SQLite
    ctx.register_tool(name="plugin_tool", toolset="my_plugin", schema=..., handler=...)

    @ctx.hook("pre_tool_call")
    def on_pre_tool(tool_name, args, **kwargs): ...
```
- Hook callbacks use signature inspection: narrow callbacks receive declared args; `**kwargs` receives full payloads.

### Memory & Model Plugins
- **Memory Providers (`plugins/memory/`)**: Implement `MemoryProvider` ABC (`agent/memory_provider.py`). Activated via `memory.provider` in `config.yaml` (Honcho, Mem0, Supermemory, Hindsight, LMCache).
- **Model Providers (`plugins/model-providers/`)**: Register `ProviderProfile` dynamically. User plugins override bundled ones.

---

## 10. Skill Authoring Standards (Hardline)

1. **`description` $\le$ 60 chars**: Single sentence, ends with a period, zero marketing buzzwords.
2. **Native Tool References in Prose**: Reference Hermes tools in backticks (`` `terminal` ``, `` `read_file` ``, `` `patch` ``, `` `search_files` ``, `` `vision_analyze` ``), never raw shell utilities (`grep`, `sed`).
3. **Platform Gating**: Audit imports for POSIX primitives (`fcntl`, `os.kill(0)`). Provide cross-platform fallbacks or declare `platforms: [macos]`.
4. **Standard Section Layout**: `# <Skill> Skill` $\to$ Intro $\to$ `## When to Use` $\to$ `## Prerequisites` $\to$ `## How to Run` $\to$ `## Quick Reference` $\to$ `## Procedure` $\to$ `## Pitfalls` $\to$ `## Verification`.
5. **File Separation**: Python in `scripts/`, templates in `templates/`, docs in `references/`.
6. **Automated Mocks**: Unit tests in `tests/skills/test_<skill>_skill.py` using mocks (no live API calls).

---

## 11. Subsystems: Delegation, Curator, Cron, Kanban & MoA

- **Delegation (`tools/delegate_tool.py`)**: `role="leaf"` (worker cannot delegate/write memory/send messages) vs. `role="orchestrator"` (spawns workers up to `delegation.max_spawn_depth`). `background=True` returns task ID immediately.
- **Curator (`agent/curator.py`)**: Tracks agent-created skills in `~/.hermes/skills/.usage.json`. Auto-archives unused skills to `~/.hermes/skills/.archive/`. Pinned skills (`hermes curator pin`) are exempt.
- **Cron (`cron/jobs.py` + `cron/scheduler.py`)**: Schedules natural phrases (`"every 2h"`) or 5-field cron syntax. Enforces a **3-minute hard interrupt**, file locking (`~/.hermes/cron/.tick.lock`), and role alternation frames.
- **Kanban (`plugins/kanban/` + `tools/kanban_tools.py`)**: Multi-agent collaboration board with SQLite WAL backend. Gateway dispatcher claims ready tasks within `HERMES_KANBAN_BOARD` boundary.
- **MoA (`agent/moa_loop.py`)**: Multi-model routing and aggregation across heterogeneous model families with consensus synthesis.

---

## 12. Multi-Platform Messaging Gateway Architecture

- **Supported Platforms**: 20+ channels (Telegram, Discord, Slack, LINE, WeCom, Weixin, Yuanbao, Signal, WhatsApp, Matrix, Mattermost, BlueBubbles, SMS, Email).
- **Streaming Contract**: Draft frames must be prefix-stable ($N$ is exact prefix of $N+1$; no auto-closing markdown blocks). Final enhancements ride `finish(final_text)`. Ephemeral status sets `metadata["_interim_send"] = True`. Reconcile by message ID edit.
- **Fast-Path Message Guards**: Control commands (`/stop`, `/new`, `/approve`, `/deny`, `/status`) bypass queues and debounce buffers for instant execution.
- **Multiplex Secret Scope**: Secrets loaded via `_get_scoped_secret()`. A cache miss returns default, NEVER falling back to `os.environ` (prevents cross-profile credential leaks).

---

## 13. Critical Policies, Windows Footguns & Pitfalls

- **No `os.kill(0)`**: Crashes Windows Python runtimes. Use `psutil.Process().terminate()` or process trees.
- **Mandatory Explicit UTF-8**: Always open files with `encoding="utf-8"`. Never rely on Windows default ANSI/CP932 codepages.
- **Path Normalization**: Use `pathlib.Path` or convert paths via `path.as_posix()` before serializing to JSON/web.
- **ConPTY Windows Bridge**: Use `win_pty_bridge.py` for terminal emulation to prevent blocking stdio pipes.
- **Profile Isolation**: Always use `get_hermes_home()`. Never hardcode `~/.hermes`.
- **Curses & ANSI**: Pickers must use `hermes_cli/curses_ui.py`. Avoid `\033[K` in spinners; use space padding `f"\r{line}{' ' * pad}"`.

---

## 14. Testing Discipline, CI Parity & Banned Antipatterns

### Parity Test Runner (`scripts/run_tests.sh`)
- Fresh subprocess per test file (`scripts/run_tests_parallel.py`) to prevent module state pollution.
- Isolated temporary `HERMES_HOME` (`tmp_path`).
- Fixed UTC timezone, `LANG=C.UTF-8`, unset provider credentials.
- Auto-retries flaky test files once (`--file-retries=1`).

### Banned Testing Antipatterns
- **No Change-Detector Tests**: Never assert snapshots of mutable data (`assert len(MODELS) == 8`). Test invariants and schemas.
- **Never Regex Source Code in Tests**: Import functions directly and test input/output behavior.
- **Never Write to `~/.hermes/`**: Always monkeypatch `HERMES_HOME` to `tmp_path`.
- **Test Placement**: TypeScript tests belong in Vitest (`apps/desktop/`, `tests-js/`), Python in `tests/`.

---

## 15. Fork Overlay, Local Harness & Windows Automation Suite

- **Watchdog Daemon (`scripts/windows/watchdog-go/`)**: Go-based supervisor monitoring Desktop and Backend with auto-restart and crash recovery.
- **Local Llama Supercharger (`scripts/windows/start-llama-*.ps1`)**: Hot-standby runner for Qwen 3.5B / Qwen 3.8B / HuiHui Gemma with 131,072 context window support.
- **Remote Gateway Funnel**: Automated Tailscale Serve / Funnel integration for encrypted remote mobile and web access.
- **Local Scratch Policy**: Temporary probes go to `tmp/probes/` (gitignored). Implementation records go to `_docs/`.

---

## 16. CodeGraph (required navigation on this workstation)

On **zapabob/hermes-agent-windows**, CodeGraph is a **mandatory first-pass
navigation tool** before broad exploration. Prefer:

```powershell
npx --yes @colbymchenry/codegraph sync .
npx --yes @colbymchenry/codegraph query <symbol>
npx --yes @colbymchenry/codegraph impact <symbol>
```

Index: `.codegraph/` (do not commit). Prepared navigation only — not CI/merge evidence.
See root `AGENTS.md` §16–17 for the full contract and root layout policy.

## 17. Learned User Preferences, Workspace Invariants & MILSPEC Standards

1. **Hermes Restart Protocol**: Rebuild desktop via `hermes desktop --build-only --force-build` combined with `-StartLlama`. Never launch from `.worktrees/`.
2. **Canonical Desktop Target**: Packaged binary at `apps/desktop/release/win-unpacked/Hermes.exe`.
3. **Canonical Root Anchor**: `HERMES_DESKTOP_HERMES_ROOT` exclusively references `c:\Users\downl\Documents\New project\hermes-agent`.
4. **Upstream PR Cleanliness**: PRs submitted upstream must be written in King's English without referencing fork features, `_docs/`, or local scripts.
5. **High-Contrast Theme Invariant**: Desktop themes using `background_image` require high-contrast bubble overlays for readability.
6. **MILSPEC Quality Standards**:
   - **Zero `print` calls**: `logging` is mandatory across all Python files; `print` is strictly forbidden.
   - **Fixed Character Encoding**: UTF-8 without BOM across all files.
   - **Implementation Audit Logs**: Every substantive change generates a record under `_docs/yyyy-mm-dd_<feature>_<agent>.md`.
7. **CodeGraph before broad search**: See §16.

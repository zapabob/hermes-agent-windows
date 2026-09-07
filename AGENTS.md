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

### Bot Mode (`apps/desktop/src/plugins/hermes-bots/`)

The desktop "Bots" experience ships bundled in-tree. Each bot is a Hermes
agent **profile** with a persistent identity. Its design rests on one settled
invariant that has been regressed repeatedly, cost users real conversation
history each time, and is not open for re-litigation in a routine PR:

**One bot = ONE canonical forever-chat, identified by NAME.** The chat's one
and only identity is **(profile, session titled exactly "Bot Chat")** — the
state DB's UNIQUE(title) index makes that pair an exact registry of at most
one row. The full lifecycle when a bot row is clicked:

1. **Resolve the registry, every time.** Look up the profile's `Bot Chat`
   session by exact title via `session.list {title, include_hidden: true}`
   (indexed, window-free; hidden rows resolve because canonical chats are
   always hidden; compression lineages resolve to the live tip). Row exists →
   open it. That is the entire happy path.
2. **No row → create it,** titled `Bot Chat`, born hidden, kicked off with
   the bot's intro. Creation adopts-before-minting: it re-runs the registry
   lookup first, so a concurrent or pre-existing row is opened, never forked.
   (`set_session_title` silently drops conflicting titles — returns 0 rows —
   which is how the 2026-08 infinite fork loop started; adopt-before-mint is
   what kills it.)

**There is NO session-id pin.** The previous design stored a pointer in
`ui_meta['hermes-bots'].chat` and verified it per click; five hardening
waves (#88690, #90732, #90751, the #91791 revert, #92042) each guarded a new
way that pointer dangled or got stolen — rows[0] steals, `last_session`
adoptions, transient clears, drifted-title welds (a pin re-anchored onto a
cron session passed every guard). Name-as-identity removes the failure class:
a name cannot dangle, and a corrupted historical pointer simply never gets
read. Legacy `chat` keys in ui_meta are ignored and dropped from merges.

Why recency must never win (the #91791 → #92042 lesson): canonical Bot
Chats are **unconditionally hidden** from the Sessions sidebar, so the bot
row is the ONLY door to the forever-chat. A "newest visible session wins"
preference doesn't re-order two equivalent entry points — it walls the
entire relationship off behind a row that previews one session and opens
another, and any stray draft that catches a prompt captures the row.
Side-chats started via "New chat with this agent" are not plumbing-titled,
stay visible in the Sessions sidebar, and are reachable there; they are
never the bot row's target.

Corollaries for reviewers:

- There is no per-bot session browser, by explicit design (removed in
  #90732). Do not add one back.
- Reject any PR that reintroduces a stored session-id pointer as canonical
  identity — including "as a fallback tier" or "for verification". The
  registry lookup is the whole contract; pointers are how every prior
  incident started.
- Reject any PR that consults recency, visibility, or "where the user left
  off" for the bot row's target — reports that motivate such a change are
  almost always about side-chats, and the fix belongs in the Sessions
  sidebar (hide-sweep false positives), not in the bot row's target.
- The gateway reports the registry row per profile as `canonical_session`
  on `profiles.list` (resolved server-side by title); roster preview,
  activity signals, and the `/new`→`/compact` guard all read it, so preview
  identity and click identity are the same row by construction.

Regression tests encoding this contract:
`tests/canonical-chat-registry.test.mjs` (includes a tripwire asserting the
open path never reads or writes a stored pointer),
`tests/canonical-chat-creation.test.mjs`, `tests/hide-bot-chats.test.mjs`,
and `tests/tui_gateway/test_profiles_list_canonical_session.py`.

---

## Skills

Two parallel surfaces:

- **`skills/`** — built-in skills shipped and loadable by default.
  Organized by category directories (e.g. `skills/github/`, `skills/mlops/`).
- **`optional-skills/`** — heavier or niche skills shipped with the repo but
  NOT active by default. Installed explicitly via
  `hermes skills install official/<category>/<skill>`. Adapter lives in
  `tools/skills_hub.py` (`OptionalSkillSource`). Categories include
  `autonomous-ai-agents`, `blockchain`, `communication`, `creative`,
  `devops`, `email`, `health`, `mcp`, `migration`, `mlops`, `productivity`,
  `research`, `security`, `web-development`.

When reviewing skill PRs, check which directory they target — heavy-dep or
niche skills belong in `optional-skills/`.

### SKILL.md frontmatter

Standard fields: `name`, `description`, `version`, `author`, `license`,
`platforms` (OS-gating list: `[macos]`, `[linux, macos]`, ...),
`metadata.hermes.tags`, `metadata.hermes.category`,
`metadata.hermes.related_skills`, `metadata.hermes.config` (config.yaml
settings the skill needs — stored under `skills.config.<key>`, prompted
during setup, injected at load time).

Top-level `tags:` and `category:` are also accepted and mirrored from
`metadata.hermes.*` by the loader.

### Skill authoring standards (HARDLINE)

Every new or modernized skill — bundled, optional, or contributed —
must meet these standards before merge. Reviewers reject PRs that
violate them.

1. **`description` ≤ 60 characters, one sentence, ends with a period.**
   Long descriptions bloat skill listings and dilute the model's
   attention when many skills are loaded. State the capability, not
   the implementation. No marketing words ("powerful",
   "comprehensive", "seamless", "advanced"). Don't repeat the skill
   name. Verify with:
   ```python
   import re, pathlib
   m = re.search(r'^description: (.*)$',
                 pathlib.Path('skills/<cat>/<name>/SKILL.md').read_text(),
                 re.MULTILINE)
   assert len(m.group(1)) <= 60, len(m.group(1))
   ```

2. **Tools referenced in SKILL.md prose must be native Hermes tools or
   MCP servers the skill explicitly expects.** When the skill needs a
   capability, point at the proper tool by name in backticks
   (`` `terminal` ``, `` `web_extract` ``, `` `read_file` ``,
   `` `patch` ``, `` `search_files` ``, `` `vision_analyze` ``,
   `` `browser_navigate` ``, `` `delegate_task` ``, etc.). Do NOT
   name shell utilities the agent already has wrapped — `grep` →
   `search_files`, `cat`/`head`/`tail` → `read_file`, `sed`/`awk` →
   `patch`, `find`/`ls` → `search_files target='files'`. If the skill
   depends on an MCP server, name the MCP server and document the
   expected setup in `## Prerequisites`. Anything else (third-party
   CLIs, shell pipelines, etc.) is fair game inside script files but
   should not be the headline interaction surface in the prose.

3. **`platforms:` gating audited against actual script imports.**
   Skills that use POSIX-only primitives (`fcntl`, `termios`,
   `os.setsid`, `os.kill(pid, 0)` for liveness, `/proc`, `/tmp`
   hardcoded, `signal.SIGKILL`, bash heredocs, `osascript`, `apt`,
   `systemctl`) must declare their supported platforms. Default
   posture: try to fix it cross-platform first — `tempfile.gettempdir`,
   `pathlib.Path`, `psutil.pid_exists`, Python-level filtering instead
   of `grep`. Gate to a narrower set only when the dependency is
   genuinely platform-bound.

4. **`author` credits the human contributor first.** For external
   contributions, the contributor's real name + GitHub handle goes
   first; "Hermes Agent" is the secondary collaborator. If the
   contributor's commit shows "Hermes Agent" as author (because they
   used Hermes to draft the skill), replace it with their actual name
   — credit the human, not the tool.

5. **SKILL.md body uses the modern section order.** `# <Skill> Skill`
   title, 2-3 sentence intro stating what it does and doesn't do,
   `## When to Use`, `## Prerequisites`, `## How to Run`,
   `## Quick Reference`, `## Procedure`, `## Pitfalls`,
   `## Verification`. Target ~200 lines for a complex skill,
   ~100 lines for a simple one. Cut redundant intro fluff, marketing
   prose, and re-explanations of env vars already in
   `## Prerequisites`.

6. **Scripts go in `scripts/`, references in `references/`,
   templates in `templates/`.** Don't expect the model to inline-write
   parsers, XML walkers, or non-trivial logic every call — ship a
   helper script. Reference it from SKILL.md by path relative to the
   skill directory.

7. **Tests live at `tests/skills/test_<skill>_skill.py`** and use only
   stdlib + pytest + `unittest.mock`. No live network calls. Run via
   `scripts/run_tests.sh tests/skills/test_<skill>_skill.py -q`.

8. **`.env.example` additions are isolated to a clearly delimited
   block.** Don't touch the surrounding file — contributor-supplied
   `.env.example` versions are usually stale and edits outside the
   skill's own block must be dropped during salvage.

The full salvage / modernization checklist for external skill PRs
lives in the `hermes-agent-dev` skill at
`references/new-skill-pr-salvage.md` — load it before polishing
contributor skill PRs.

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

## Update Pipeline (`hermes update`)

The updater is transactional in shape (fleet-update campaign, #91277 —
Aug 2026). Every stage exists because its absence was a real field
failure; PRs that weaken a stage need to answer for the failure class it
guards:

```
plan → snapshot → apply → restart-per-kind → verify → report
```

- **Plan** (`hermes_cli/update_inventory.py`, `hermes update --plan`):
  read-only inventory — install kind, all profiles, every live gateway
  with supervisor + running code version. Deployment kinds are
  first-class: `git` updates in place; `docker`/`nix`/`apt` are NOT
  in-place-updatable and the updater reports the correct external
  command instead of fighting the deployment model.
- **Snapshot** (`hermes_cli/backup.py`): pre-update quick snapshot for
  EVERY profile (the code swap + fleet restart touch all of them), each
  into its own `state-snapshots/`, identical file set + 1 GiB per-file
  cap + keep=1. **Never add a partial/tiered snapshot set** — mixed
  coverage creates torn-restore states across schema generations. Quick
  snapshots are FILE-LOSS RECOVERY (the per-profile cron-jobs safety
  net restores from them), NOT code-rollback insurance; `--backup` full
  mode owns rollback.
- **Apply**: git pull, or the Windows ZIP fallback — which fires ONLY
  when git itself failed (`_should_zip_fallback_on_update_error`,
  argv-classified; a dependency-install failure must never trigger a
  tree-clobbering re-download), REFUSES a dirty working tree
  (`-uall`, plus a pre-swap TOCTOU re-check), and grafts the live
  `apps/desktop/release/` into the staged swap (the GitHub source ZIP
  has no built desktop app; without the graft the swap deletes it).
- **Restart-per-kind**: systemd and launchd restarts are FLEET-WIDE
  (every `hermes-gateway*` unit / `ai.hermes.gateway*` LaunchAgent),
  drain-first (SIGUSR1) with per-unit/per-label failure isolation.
  Restarting only the invoking profile's service leaves siblings on
  stale `sys.modules` until they crash — the largest dupe-PR cluster in
  the repo's history came from that bug.
- **Verify**: gateways stamp their running `code_sha`/`code_version`
  into `gateway_state.json` on every runtime-status write
  (`gateway/status.py`); after the restart phase the updater compares
  each live gateway against the fresh checkout and prints a fleet
  version matrix. A provably-stale gateway fails the update (exit 1) —
  automation must never treat a mixed-version fleet as healthy.
- **Report**: every run writes a machine-readable receipt to
  `~/.hermes/logs/update_receipts/` (`latest.json` pointer; steps,
  skips WITH reasons, restart outcome, plan, fleet snapshot).
  Finalization is owned by the `cmd_update` command boundary — early
  `sys.exit` paths (preflight refusals, fetch failures) still persist
  a receipt with the real exit code. A begun-but-unwritten receipt is
  a bug: the refused/failed runs are the ones receipts exist for.

Architecture direction: process-scan-based coordination between the
updater, serve/dashboard, and the gateway is being replaced by a
gateway-owned control socket (#92091). Do not add new scan heuristics
without checking that design; scans are the fallback layer.

### Gateway lifecycle vs. the Desktop app

`hermes serve` (control plane, desktop-spawned child) dies with the app
— by design. The messaging gateway (`gateway run`) SURVIVES the app: the
serve backend's `/api/gateway/*` endpoints spawn it detached
(`_spawn_hermes_action` — `start_new_session` / `DETACHED_PROCESS`), so
`before-quit`'s backend SIGTERM never reaches it. Bots keep running
when the user closes the app. The known breach of this contract is the
Windows shim-unlock teardown (`taskkill /T /F` on venv-shim holders,
#85265) — it exists to let updates proceed, and its replacement is
#92091's `pause-for-update`. Do not "fix" gateway-dies-with-app reports
by re-parenting the gateway under the backend, and do not "fix" update
locks by widening the tree-kill.

---

## Important Policies

### Prompt Caching Must Not Break

Hermes-Agent ensures caching remains valid throughout a conversation. **Do NOT implement changes that would:**
- Alter past context mid-conversation
- Change toolsets mid-conversation
- Reload memories or rebuild system prompts mid-conversation

Cache-breaking forces dramatically higher costs. The ONLY time we alter context is during context compression.

Slash commands that mutate system-prompt state (skills, tools, memory, etc.)
must be **cache-aware**: default to deferred invalidation (change takes
effect next session), with an opt-in `--now` flag for immediate
invalidation. See `/skills install --now` for the canonical pattern.

### Parity Test Runner (`scripts/run_tests.sh`)
- Fresh subprocess per test file (`scripts/run_tests_parallel.py`) to prevent module state pollution.
- Isolated temporary `HERMES_HOME` (`tmp_path`).
- Fixed UTC timezone, `LANG=C.UTF-8`, unset provider credentials.
- Auto-retries flaky test files once (`--file-retries=1`).

When `terminal(background=true, notify_on_complete=true)` is used, the gateway runs a watcher that
detects process completion and triggers a new agent turn. Control verbosity of background process
messages with `display.background_process_notifications`
in config.yaml (or `HERMES_BACKGROUND_NOTIFICATIONS` env var):

- `concise` — one-line status message on completion; failures append a short output tail (default)
- `all` — running-output updates + final raw-output message
- `result` — only the final raw-output completion message
- `error` — only the final raw-output message when exit code != 0
- `off` — no watcher messages at all

---

## Profiles: Multi-Instance Support

Hermes supports **profiles** — multiple fully isolated instances, each with its own
`HERMES_HOME` directory (config, API keys, memory, sessions, skills, gateway, etc.).

The core mechanism: `_apply_profile_override()` in `hermes_cli/main.py` sets
`HERMES_HOME` before any module imports. All `get_hermes_home()` references
automatically scope to the active profile.

### Rules for profile-safe code

1. **Use `get_hermes_home()` for all HERMES_HOME paths.** Import from `hermes_constants`.
   NEVER hardcode `~/.hermes` or `Path.home() / ".hermes"` in code that reads/writes state.
   ```python
   # GOOD
   from hermes_constants import get_hermes_home
   config_path = get_hermes_home() / "config.yaml"

   # BAD — breaks profiles
   config_path = Path.home() / ".hermes" / "config.yaml"
   ```

2. **Use `display_hermes_home()` for user-facing messages.** Import from `hermes_constants`.
   This returns `~/.hermes` for default or `~/.hermes/profiles/<name>` for profiles.
   ```python
   # GOOD
   from hermes_constants import display_hermes_home
   print(f"Config saved to {display_hermes_home()}/config.yaml")

   # BAD — shows wrong path for profiles
   print("Config saved to ~/.hermes/config.yaml")
   ```

3. **Module-level constants are fine** — they cache `get_hermes_home()` at import time,
   which is AFTER `_apply_profile_override()` sets the env var. Just use `get_hermes_home()`,
   not `Path.home() / ".hermes"`.

4. **Tests that mock `Path.home()` must also set `HERMES_HOME`** — since code now uses
   `get_hermes_home()` (reads env var), not `Path.home() / ".hermes"`:
   ```python
   with patch.object(Path, "home", return_value=tmp_path), \
        patch.dict(os.environ, {"HERMES_HOME": str(tmp_path / ".hermes")}):
       ...
   ```

5. **Gateway platform adapters should use token locks** — if the adapter connects with
   a unique credential (bot token, API key), call `acquire_scoped_lock()` from
   `gateway.status` in the `connect()`/`start()` method and `release_scoped_lock()` in
   `disconnect()`/`stop()`. This prevents two profiles from using the same credential.
   See `plugins/platforms/irc/adapter.py` for the canonical pattern.

6. **Profile operations are HOME-anchored, not HERMES_HOME-anchored** — `_get_profiles_root()`
   returns `Path.home() / ".hermes" / "profiles"`, NOT `get_hermes_home() / "profiles"`.
   This is intentional — it lets `hermes -p coder profile list` see all profiles regardless
   of which one is active.

7. **Multiplex profile-scoped env reads MUST fail closed — never borrow from `os.environ`**
   (`agent/secret_scope.py` contract; #72348, #86905). Under `gateway.multiplex_profiles`,
   `os.environ` holds the **default profile's** values; a secondary profile's `.env` lives
   only in its secret scope (installed per-turn by `_profile_runtime_scope`). Any
   profile-level env config — credentials (`app_secret`, tokens) AND authorization
   (`FEISHU_ALLOWED_USERS`, `{PLATFORM}_ALLOW_ALL_USERS`, `GATEWAY_ALLOW_ALL_USERS`,
   `group_policy`, `allow_bots`, ...) — must be read scope-aware:
   - Adapters: `_get_scoped_secret()` (canonical fail-closed copy in
     `plugins/platforms/feishu/adapter.py`, #86905).
   - Gateway authz: `_auth_env()` / `_platform_gate_env()` (`gateway/authz_mixin.py`).
   Rules:
   - Scope installed + multiplex active → a scoped miss returns the **default**.
     NEVER fall through to `os.environ` — that leaks another profile's value and
     silently breaks routing/admission (a leaked default allowlist skips the
     allow-all check and rejects every secondary-profile sender, #86905).
   - Unscoped default-profile path (`UnscopedSecretError`) and single-profile
     deployments keep the `os.environ` read — there it IS the profile's own value.
   - Authorization config is the sharpest edge: allowlist/allow-all leaks cause
     silent rejections (or worse, fail-open) that only show up as missing replies.
   - The `_get_scoped_secret` wrapper is copy-pasted across ~15 platform adapters —
     when touching any of them, make sure the fail-closed semantics are present;
     do not reintroduce the `except _UnscopedSecretError: val = os.getenv(...)`
     fallback-after-miss shape.

## Known Pitfalls

### DO NOT infer process identity from argv substrings
The bug class behind ~10 fleet-update issues (#90778, #87594, #78089,
#76129, #91964, ...): classifying a process by `"serve" in cmdline` or
similar. `kanban --preserve-cache` contains "serve"; a flag VALUE can
equal a subcommand (`-m dashboard serve`); truncated cmdlines hide the
real subcommand. Rules:
- Use the canonical matchers: `gateway.status.looks_like_gateway_command_line`
  (gateway run), `hermes_cli.update_cmd._hermes_holder_subcommand`
  (top-level subcommand of any Hermes argv). Never hand-roll token scans.
- Flag sets must be DERIVED from the parser
  (`_holder_value_flags()` introspects `build_top_level_parser()`), never
  hand-written lists — they drift.
- Never blanket-exclude ancestors from process scans: when `/update` runs
  as the gateway's child, a gateway ancestor must stay visible to the
  pause machinery (#87594). Exclude interactive ancestry, carve out
  gateway-shaped ancestors.
- Match on FULL cmdlines; truncate only at display time (#78089).
- Before adding any new scan heuristic, read #92091 — the gateway control
  socket replaces scans as the primary coordination mechanism; scans are
  the fallback layer for old/crashed processes.

### DO NOT hardcode `~/.hermes` paths
Use `get_hermes_home()` from `hermes_constants` for code paths. Use `display_hermes_home()`
for user-facing print/log messages. Hardcoding `~/.hermes` breaks profiles — each profile
has its own `HERMES_HOME` directory. This was the source of 5 bugs fixed in PR #3575.

### All CLI menu-pickers MUST use curses.
Interactive menus must use `hermes_cli/curses_ui.py`. See `hermes_cli/tools_config.py` for an example.

### DO NOT use `\033[K` (ANSI erase-to-EOL) in spinner/display code
Leaks as literal `?[K` text under `prompt_toolkit`'s `patch_stdout`. Use space-padding: `f"\r{line}{' ' * pad}"`.

### `_last_resolved_tool_names` is a process-global in `model_tools.py`
`_run_single_child()` in `delegate_tool.py` saves and restores this global around subagent execution. If you add new code that reads this global, be aware it may be temporarily stale during child agent runs.

### DO NOT hardcode cross-tool references in schema descriptions
Tool schema descriptions must not mention tools from other toolsets by name (e.g., `browser_navigate` saying "prefer web_search"). Those tools may be unavailable (missing API keys, disabled toolset), causing the model to hallucinate calls to non-existent tools. If a cross-reference is needed, add it dynamically in `get_tool_definitions()` in `model_tools.py` — see the `browser_navigate` / `execute_code` post-processing blocks for the pattern.

### The gateway has TWO message guards — both must bypass approval/control commands
When an agent is running, messages pass through two sequential guards:
(1) **base adapter** (`gateway/platforms/base.py`) queues messages in
`_pending_messages` when `session_key in self._active_sessions`, and
(2) **gateway runner** (`gateway/run.py`) intercepts `/stop`, `/new`,
`/queue`, `/status`, `/approve`, `/deny` before they reach
`running_agent.interrupt()`. Any new command that must reach the runner
while the agent is blocked (e.g. approval prompts) MUST bypass BOTH
guards and be dispatched inline, not via `_process_message_background()`
(which races session lifecycle).

### Streaming delivery contract (stream-is-the-message adapters) — duplicate-final class
Adapters with `draft_stream_is_message = True` (relay Slack native streaming)
keep ONE cumulative native stream per turn; the stream IS the final message.
Four invariants, each learned from a live duplicate-final incident (NS-658
canary ledger, hermes#85796 / gateway-gateway#210). Violating any of them
re-creates a duplicate or a frozen stream:

1. **Draft frames must be prefix-stable.** The connector computes append-only
   deltas: frame N must be a string prefix of frame N+1. NEVER mutate draft
   frames per-tick — no fence-closing (`ensure_closed_code_fences`), no cursor
   suffix, no segment-state resets at tool boundaries, no mrkdwn conversion.
   Any non-prefix frame triggers a whole-snapshot re-append on the platform
   ("stacked copies"). The finalize path may still transform the real final.
2. **The consumer declares the final; the adapter never guesses.**
   `finish(final_text)` carries the completed `final_response` (verifier
   footer, completion explainer included) as the authoritative finalize
   payload. New post-stream response augmentation MUST ride this payload —
   if it mutates `final_response` after the stream sealed, it re-opens the
   #11 bug (`delivered_final_matches` mismatch → corrective duplicate send).
3. **Interim sends must carry `_interim_send` metadata.** Any consumer-side
   `adapter.send()` that is NOT the turn-final (commentary, segment-tail
   flushes) must set `metadata["_interim_send"] = True`, or the relay
   adapter's seal-interception will seal the live stream with interim text.
   Seal-interception exists at BOTH egress doors (`send()` AND
   `send_for_platform()`); a new egress door needs the same two checks.
4. **Reconcile by edit, never by plain send.** Any lane that delivers a final
   beside an already-sealed stream (queued follow-ups, media-accompanied
   finals, future lanes) must first try `edit_message` on the consumer's
   `message_id`; plain `send()` is the fallback only when no editable message
   exists. A sealed native stream is a regular message — `chat.update` on it
   works (live-verified).

Contract tests: `tests/gateway/test_stream_final_contract.py` (all four
invariants, mutation-checked). Slack streaming API ground truth (live-probed,
also encoded in connector comments/tests): `chat.*Stream` speaks STANDARD
markdown, not mrkdwn; `stopStream.markdown_text` APPENDS (never replaces);
`startStream`/`stopStream` are rate-limit Tier 2 (~20/min).

Guard style note: check `draft_stream_is_message` with `is True` — MagicMock
adapters in older tests auto-create truthy attributes.

### Squash merges from stale branches silently revert recent fixes
Before squash-merging a PR, ensure the branch is up to date with `main`
(`git fetch origin main && git reset --hard origin/main` in the worktree,
then re-apply the PR's commits). A stale branch's version of an unrelated
file will silently overwrite recent fixes on main when squashed. Verify
with `git diff HEAD~1..HEAD` after merging — unexpected deletions are a
red flag.

### Don't wire in dead code without E2E validation
Unused code that was never shipped was dead for a reason. Before wiring an
unused module into a live code path, E2E test the real resolution chain
with actual imports (not mocks) against a temp `HERMES_HOME`.

### Tests must not write to `~/.hermes/`
The `_isolate_hermes_home` autouse fixture in `tests/conftest.py` redirects `HERMES_HOME` to a temp dir. Never hardcode `~/.hermes/` paths in tests.

**Profile tests**: When testing profile features, also mock `Path.home()` so that
`_get_profiles_root()` and `_get_default_hermes_home()` resolve within the temp dir.
Use the pattern from `tests/hermes_cli/test_profiles.py`:
```python
@pytest.fixture
def profile_env(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("HERMES_HOME", str(home))
    return home
```

---

## 15. Fork Overlay, Local Harness & Windows Automation Suite

- **Watchdog Daemon (`scripts/windows/watchdog-go/`)**: Go-based supervisor monitoring Desktop and Backend with auto-restart and crash recovery.
- **Local Llama Supercharger (`scripts/windows/start-llama-*.ps1`)**: Hot-standby runner for Qwen 3.5B / Qwen 3.8B / HuiHui Gemma with 131,072 context window support.
- **Remote Gateway Funnel**: Automated Tailscale Serve / Funnel integration for encrypted remote mobile and web access.
- **Local Scratch Policy**: Temporary probes go to `tmp/probes/` (gitignored). Implementation records go to `_docs/`.

The CI change classifier (`scripts/ci/classify_changes.py`) runs specific jobs based on what files changed. A Python test that asserts
about the contents of `package.json`, `package-lock.json`, `.ts`/`.tsx`
source, or any other JS-side artifact will not run on a PR that only touches
those files. This means a regression can go green on a PR and red on `main` (where the
classifier fails open and runs everything).

Any test that reads or asserts about `package.json`,
`package-lock.json`, `tsconfig.json`, `.ts`/`.tsx`/`.js`/`.mjs`/`.cjs`
source files configuration belongs in the JS (vitest) test suite, not in `tests/*.py`.

### Don't fake the host OS

Hermes supports Linux, macOS and native Windows, and plenty of its behaviour
genuinely differs per host. Those differences are tested by running on the
host, not by patching `sys.platform`.

```python
@pytest.mark.linux_only
@pytest.mark.macos_only
@pytest.mark.windows_only
```

Things that are host-independent can stay unmarked:

- **Pure functions that take a platform as data** —
  `hidden_windows_child_options(opts, is_windows=True)` is input→output, not a
  fake host. (Contrast: setting a module-level `IS_WINDOWS` flag and then
  calling `windows_detach_flags()` *is* a fake.)
- **Declaration/packaging invariants** — "pyproject declares `tzdata` with a
  `sys_platform == 'win32'` marker" asserts about a file, not about runtime.

The line: **if the test needs the interpreter to believe it is on another OS
in order to pass, it belongs on that OS.**
When one test body walks several platforms in sequence, split it.
Keep the host-native arm on the Linux lane and move the other arm into its own marked test.

**Live Windows process-topology E2E: the `wine2e` lane.** For claims about
real Windows process behavior that mocks cannot reproduce (venv-holder
scans, process-tree parentage, launcher/worker chains, detach semantics),
there is an on-demand workflow `windows-venv-e2e.yml` that runs
`tests/hermes_cli/test_venv_holder_windows_live.py` on a real
`windows-latest` runner — spawning actual processes and driving the real
detection code, no mocked psutil. It fires ONLY on pushes to `wine2e/**`
branches (inert on PRs and main; costs nothing on normal work). The proven
workflow: write probes that pin CORRECT behavior, push to a `wine2e/`
branch to reproduce the bugs live on unfixed code, build the fix, iterate
until the lane is green, then open the PR — the live receipt on the exact
head is the Windows proof reviewers ask for. Extend the live suite when
touching that subsystem; assert against the gateway ANCESTOR found by
argv, not the direct parent (the venv shim makes every spawn a
launcher/worker chain).

**Use the marker, never a bare `skipif`.** `scripts/ci/list_os_marked_tests.py`
decides which files the macOS/Windows lanes import by grepping for the marker
*name*, and the lane then filters with `-m <marker>`. A test gated with
`@pytest.mark.skipif(sys.platform != "win32")` therefore skips on Linux AND is
never imported on the Windows lane — it runs on no host at all, silently. The
same trap catches a file-local alias (`windows_only = pytest.mark.skipif(...)`):
the grep matches the name, so the file *is* listed, but `-m windows_only`
deselects every test in it and the lane reports green over zero coverage.
Equally, don't `pytest.skip()` the non-host rows of a `@parametrize` over
platforms — split it into one marked test per OS, or only the host's row ever
executes.

### Don't write change-detector tests

A test is a **change-detector** if it fails whenever data that is **expected
to change** gets updated — model catalogs, config version numbers,
enumeration counts, hardcoded lists of provider models. These tests add no
behavioral coverage; they just guarantee that routine source updates break
CI and cost engineering time to "fix."

**Do not write:**

```python
# catalog snapshot — breaks every model release
assert "gemini-2.5-pro" in _PROVIDER_MODELS["gemini"]
assert "MiniMax-M2.7" in models

# config version literal — breaks every schema bump
assert DEFAULT_CONFIG["_config_version"] == 21

# enumeration count — breaks every time a skill/provider is added
assert len(_PROVIDER_MODELS["huggingface"]) == 8
```

**Do write:**

```python
# behavior: does the catalog plumbing work at all?
assert "gemini" in _PROVIDER_MODELS
assert len(_PROVIDER_MODELS["gemini"]) >= 1

# behavior: does migration bump the user's version to current latest?
assert raw["_config_version"] == DEFAULT_CONFIG["_config_version"]

# invariant: no plan-only model leaks into the legacy list
assert not (set(moonshot_models) & coding_plan_only_models)

# invariant: every model in the catalog has a context-length entry
for m in _PROVIDER_MODELS["huggingface"]:
    assert m.lower() in DEFAULT_CONTEXT_LENGTHS_LOWER
```

The rule: if the test reads like a snapshot of current data, delete it. If
it reads like a contract about how two pieces of data must relate, keep it.
When a PR adds a new provider/model and you want a test, make the test
assert the relationship (e.g. "catalog entries all have context lengths"),
not the specific names.

Reviewers should reject new change-detector tests; authors should convert
them into invariants before re-requesting review.

### Never read source code in tests

A test that reads a source file's text is testing *the shape of the
source code*, not its behavior. This is a hard antipattern, banned outright.
Any test that reads a .py, .ts, .tsx, etc., file is suspect.

**Why it's actively harmful, not just weak:**

- It passes when the implementation is subtly broken (the regex matches a
  call site that exists but is wired wrong) and fails when a correct
  refactor changes formatting, variable names, or control flow with
  identical runtime behavior. Both directions of failure are wrong.
- It can't be run against a built/bundled/minified artifact, so it silently
  stops testing anything the moment code moves, gets renamed, or a
  dependency reformats it.
- It actively blocks refactors: reviewers see "keeps a pattern intact" tests
  fail during pure structural cleanup with no behavior change, and either
  hand-wave the failure (dangerous) or waste time updating regexes that add
  nothing (waste).
- It gives false confidence. a green suite full of source-regex tests
  looks like coverage but has never once executed the code path it claims
  to guard.

**Do not write:**

```ts
const source = fs.readFileSync(path.join(__dirname, 'main.ts'), 'utf8')

test('backend spawn hides the Windows console', () => {
  assert.match(source, /spawn\(\s*backend\.command,\s*backend\.args[\s\S]{0,300}hiddenWindowsChildOptions/)
})
```

**Do write — extract the logic into a small pure/DI-testable function and
call it for real:**

```ts
// backend-spawn.ts
export function hiddenWindowsChildOptions(options: SpawnOptionsLike = {}, isWindows = process.platform === 'win32') {
  if (!isWindows || 'windowsHide' in options) return options
  return { ...options, windowsHide: true }
}

// backend-spawn.test.ts
test('windowsHide defaults to true on Windows, is left alone elsewhere', () => {
  assert.equal(hiddenWindowsChildOptions({}, true).windowsHide, true)
  assert.equal(hiddenWindowsChildOptions({}, false).windowsHide, undefined)
  assert.equal(hiddenWindowsChildOptions({ windowsHide: false }, true).windowsHide, false)
})
```

## 16. CodeGraph (required navigation on this workstation)

On **zapabob/hermes-agent-windows**, CodeGraph is a **mandatory first-pass
navigation tool** before broad exploration, ownership surveys, or mid-size
refactors. Prefer it over grepping the whole tree when you need symbol
location, call impact, or area maps.

```powershell
npx --yes @colbymchenry/codegraph status .
npx --yes @colbymchenry/codegraph sync .
npx --yes @colbymchenry/codegraph query <symbol-or-text>
npx --yes @colbymchenry/codegraph explore <area-or-task>
npx --yes @colbymchenry/codegraph impact <symbol>
```

Index lives under `.codegraph/` (machine-local; never commit). Sync after
pulling tip if symbols look stale. CodeGraph output is **prepared local
code-intelligence context only** — it is not execution, review, CI,
merge-readiness, or merge evidence. After CodeGraph narrows the owner, open
the concrete files and run real tests for proof.

Fork-local routes that also require CodeGraph: `fork/AGENTS.md`,
`docs/windows/UPSTREAM_SEMANTIC_CARRY_2026-09-08.md`, and the local-workspace
guides under `fork/local-workspace/`.

## 17. Root layout policy (AI workstation harness)

Keep the repository **surface** (files directly under the repo root) limited to
packaging, entry modules, and product ledgers. Do **not** delete operator
scratch — **move** it into classified folders:

| Kind | Keep at root | Store under |
|------|--------------|-------------|
| Entry / packaging | `run_agent.py`, `cli.py`, `model_tools.py`, `hermes_*.py`, `toolsets.py`, `pyproject.toml`, lockfiles, `README*`, `AGENTS.md` | — |
| Product ledgers | `FEATURES.yaml`, `CARRY.yaml`, `UPSTREAM_ADOPTION.yaml`, `DOWNSTREAM_POLICY.md` | — |
| Ignored scratch | — | `output/media/`, `output/reports/`, `output/logs/`, `tmp/probes/`, `tmp/snapshots/` |
| Tracked operator archives | — | `notes/archives/` |
| Maps / handoffs | — | `docs/maps/`, `docs/windows/` |
| Fork navigation | — | `fork/` (harness, operations, local-workspace, agent-harness) |

Never relocate official root entry modules to "tidy" the tree — packaging and
upstream parity depend on them. Details:
[`fork/local-workspace/AGENTS.md`](fork/local-workspace/AGENTS.md) and
[`fork/local-workspace/README.md`](fork/local-workspace/README.md).

## 18. Learned User Preferences, Workspace Invariants & MILSPEC Standards

1. **Hermes Restart Protocol**: Rebuild desktop via `hermes desktop --build-only --force-build` combined with `-StartLlama`. Never launch from `.worktrees/`.
2. **Canonical Desktop Target**: Packaged binary at `apps/desktop/release/win-unpacked/Hermes.exe`.
3. **Canonical Root Anchor**: `HERMES_DESKTOP_HERMES_ROOT` exclusively references `c:\Users\downl\Documents\New project\hermes-agent`.
4. **Upstream PR Cleanliness**: PRs submitted upstream must be written in King's English without referencing fork features, `_docs/`, or local scripts.
5. **High-Contrast Theme Invariant**: Desktop themes using `background_image` require high-contrast bubble overlays for readability.
6. **MILSPEC Quality Standards**:
   - **Zero `print` calls**: `logging` is mandatory across all Python files; `print` is strictly forbidden.
   - **Fixed Character Encoding**: UTF-8 without BOM across all files.
   - **Implementation Audit Logs**: Every substantive change generates a record under `_docs/yyyy-mm-dd_<feature>_<agent>.md`.
7. **CodeGraph before broad search**: See §16 — sync/query/explore/impact before inventing owners.

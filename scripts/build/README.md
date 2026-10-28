# Shared product builders

Compile Hermes frontends and assemble runnable products from **prepared**
inputs. These scripts do not replace `npm`, `uv`, package managers, or Nix.

## What operators rebuild on Windows

| Product | Output | When you need it |
|---|---|---|
| Browser Webapp | `apps/desktop/dist-webapp/` | Desktop **Settings → Web access** Start serves this tree |
| Packaged Desktop | `apps/desktop/release/win-unpacked/Hermes.exe` | Local Desktop that owns Start/Stop and hosts the listener |

After tip changes that touch the browser bridge, gateway Webapp routes, or
Desktop Settings, rebuild **both**. A green unit test is not proof either
product is current.

## Layers

| Layer | Role | Entry points |
|---|---|---|
| Dependency provider | Install locked tools into a build-owned workspace | `node-deps.mjs`, `windows-deps.ps1` |
| Product builder | Compile or assemble from prepared inputs | `webapp.mjs`, `desktop.mjs`, `web.mjs`, `tui.mjs`, `agent.py` |
| App entry (npm-facing) | Mirror inputs + call the product builder | `apps/desktop/scripts/build-webapp.mjs` |

Builders refuse missing or stale inputs. They do not silently re-fetch from the
network once preparation has finished.

## Quick start (this workstation)

Run from the **repository root** (canonical main checkout, not a worktree).
Prefer Node that satisfies root `engines` (Node 26 is fine here).

```powershell
cd "C:\Users\downl\Documents\New project\hermes-agent"
$env:TEMP = 'H:\tmp'   # keep npm/Electron caches off a full C:
$env:TMP  = 'H:\tmp'
$env:HERMES_DESKTOP_HERMES_ROOT = (Resolve-Path .).Path
```

### 1. Browser Webapp (`dist-webapp`)

```powershell
node apps/desktop/scripts/build-webapp.mjs
```

What that does:

1. Mirrors Webapp inputs into `.build/webapp-workspace` (never mutates the
   Desktop `node_modules` / Electron install).
2. Runs `npm ci` in that workspace when the lock fingerprint changes.
3. Compiles the browser renderer via `scripts/build/webapp.mjs` (includes the
   browser Desktop bridge: `browser-desktop-bridge-install` in `main.tsx`).
4. Publishes to `apps/desktop/dist-webapp/` (atomic replace).

Windows notes:

- `EBUSY` on rename → something still holds the old tree (Hermes, Explorer
  preview, antivirus). Close readers and re-run, or copy
  `.dist-webapp-build-*/product` over `dist-webapp`.
- Vite config is ESM: use `import.meta.dirname` (not CommonJS `__dirname`).
- Browser bridge imports (`external-url`, `file-url`, `reconnect-backoff`,
  `session-http-mutations`) must be exported from `apps/shared` — a missing
  export fails the Webapp compile with `MISSING_EXPORT`, not a Desktop pack
  error. Re-mirror the workspace after fixing shared.
- Flags: `--prepare-only` installs without compiling; `--workspace <path>`
  overrides `.build/webapp-workspace`.

### 2. Packaged Desktop

```powershell
.\.venv\Scripts\hermes.exe desktop --build-only --force-build
```

Canonical launch binary:

`apps/desktop/release/win-unpacked/Hermes.exe`

If `hermes desktop` resolves another checkout, `HERMES_DESKTOP_HERMES_ROOT`
must point at this tree; otherwise mirror `release/win-unpacked` back here
before launching.

### 3. Smoke the connected path

1. Launch `Hermes.exe` from this tree's `release/win-unpacked/`.
2. **Settings → Web access** → Start (Nous not required; LAN needs a reachable
  address, public mode needs `https://`).
3. Gateway binds `webapp.port` (or falls back to a private listener if busy —
  it never kills the occupant) and serves `dist-webapp`.
4. Browser load installs `window.hermesDesktop` via the bridge; native Desktop
  keeps Web access / gateway management.

API: `/api/webapp-access/{status,start,stop,restart}` on the local backend.

## Module map

| File | Responsibility |
|---|---|
| `frontend-common.mjs` | Repo root discovery, product staging, atomic publish |
| `freshness.mjs` | Input hashes / receipts; refuse stale products |
| `node-deps.mjs` | Workspace `npm ci` with engines checks |
| `webapp.mjs` | Vite browser-renderer compile + `dist-webapp` publish |
| `desktop.mjs` / `desktop-reuse.mjs` | Desktop pack helpers |
| `web.mjs` / `tui.mjs` | Dashboard / TUI product builds |
| `agent.py` | Runnable agent assembly from prepared Python inputs |
| `launchers.py` / `mint_launchers.py` / `launcher_wrapper.py` | Launcher minting |
| `windows-deps.ps1` | Windows-side native / toolchain prep |

## Invariants

- **Do not** run root `npm ci` hoping to build the Webapp in-place: it fights
  the Desktop Electron / `node-pty` install. Always use the private
  `.build/webapp-workspace`.
- Product receipts bind source revision and absolute paths. Do not restore
  another machine's `.build` tree as authoritative.
- On Windows, prefer short paths / secondary-drive `TEMP` when `C:` is near full.
- Rebuild both products after bridge / Web access / `web_server` listener
  changes land on `main`.

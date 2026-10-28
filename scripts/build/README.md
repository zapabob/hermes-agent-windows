# Shared product builders

Compile Hermes frontends and assemble runnable products from **prepared**
inputs. These scripts do not replace `npm`, `uv`, package managers, or Nix.

For distribution adapters (bundles, Docker, Nix), see
[Shared bundle builds](../../docs/shared-bundle-builds.md) when that doc is
present in the tree.

## Layers

| Layer | Role | Entry points |
|---|---|---|
| Dependency provider | Install locked tools into a build-owned workspace | `node-deps.mjs`, `windows-deps.ps1` |
| Product builder | Compile or assemble from prepared inputs | `webapp.mjs`, `desktop.mjs`, `web.mjs`, `tui.mjs`, `agent.py` |
| App entry (npm-facing) | Mirror inputs + call the product builder | `apps/desktop/scripts/build-webapp.mjs` |

Builders refuse missing or stale inputs. They do not silently re-fetch from the
network once preparation has finished.

## Quick start (Windows workstation)

Run from the **repository root**. Prefer Node 22+ that satisfies root
`engines` (Node 26 is fine on this fork).

### Browser Webapp (`dist-webapp`)

Desktop **Settings → Web access** serves the gateway Webapp from
`apps/desktop/dist-webapp/`. Build it with:

```powershell
cd <repo-root>
$env:TEMP = 'H:\tmp'   # optional: keep npm/Electron caches off a full C:
node apps/desktop/scripts/build-webapp.mjs
```

What that does:

1. Mirrors Webapp inputs into `.build/webapp-workspace` (never mutates the
   Desktop `node_modules` / Electron install).
2. Runs `npm ci` in that workspace when the lock fingerprint changes.
3. Compiles the browser renderer via `scripts/build/webapp.mjs`.
4. Publishes to `apps/desktop/dist-webapp/` (atomic replace; on Windows an
   `EBUSY` rename means a process still holds the old tree — close readers and
   re-run, or copy the staging `.dist-webapp-build-*/product` folder).

Flags (see the script): `--prepare-only` installs without compiling;
`--workspace <path>` overrides `.build/webapp-workspace`.

### Packaged Desktop

```powershell
$env:HERMES_DESKTOP_HERMES_ROOT = (Resolve-Path .).Path
.\.venv\Scripts\hermes.exe desktop --build-only --force-build
```

Canonical Windows binary after pack:

`apps/desktop/release/win-unpacked/Hermes.exe`

If `hermes desktop` resolves a worktree instead of this checkout, set
`HERMES_DESKTOP_HERMES_ROOT` explicitly and mirror the `release/win-unpacked`
tree back to the path you launch from.

### Prepared JS workspace (generic)

```sh
node scripts/build/node-deps.mjs --source "$PWD" \
  --workspace apps/desktop --workspace apps/shared
```

`--source` and at least one `--workspace` are required. Prefer one complete
union per job; a later narrower `npm ci` can prune siblings.

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
  the Desktop Electron/`node-pty` install. Always use the private
  `.build/webapp-workspace`.
- **Do not** treat a green unit test as proof that `dist-webapp` or
  `Hermes.exe` is current — check the product path and build stamp.
- Product receipts bind source revision, absolute paths, and target. Do not
  restore another machine's `.build` tree as authoritative CI cache.
- On Windows, prefer short paths / secondary-drive TEMP when `C:` is near full.

## Web access (operator path)

After Desktop and `dist-webapp` are current:

1. Launch local Desktop (`Hermes.exe`).
2. **Settings → Web access** (hidden on remote connections).
3. **Start** — Nous is not required; LAN needs a reachable address, public mode
   needs an `https://` URL.
4. Gateway restarts onto the saved `webapp:` config and serves the browser UI.

API surface (Desktop → local backend): `/api/webapp-access/{status,start,stop,restart}`.

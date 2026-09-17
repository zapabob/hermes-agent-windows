# Hermes Go Watchdog（Windows）

Hermes Agent Windows Workstation Edition の **Windows-native auxiliary supervisor** です。
Hermes Python/Electron とは別プロセスで動作し、Hermes Agent の plugin / tool /
skill / MCP / cron には登録しません。

この文書の正本となる前提は、`.codex/WINDOWS_PLATFORM_CONTRACT.md` と
`CARRY.yaml` の single-authority contract です。

## Supported authority contract

同一 `HERMES_HOME`・同一 runtime role に対して、destructive lifecycle authority
を持つ component は一つだけです。

| Runtime role | Supported owner / authority |
| --- | --- |
| Desktop Python backend | **Electron main only** |
| Desktop backend claim / stop / replace / restart | **Electron main only** |
| Go watchdog process | operator / registered Windows task lifecycle |
| Watchdog-owned embedding `llama-server` | **Go watchdog only** |
| Gateway / other headless runtimes | their own canonical launcher/owner |

Go watchdog は Desktop/backend の状態を観測できますが、観測は ownership では
ありません。PID、port、health response、token、manifest、command line を知ることも
termination authority を与えません。

**Supported topologyでは、Go watchdog は Desktop Python backend を start / stop /
kill / replace / reclaim しません。** Desktop backend の lifecycle は Electron main が
保持した child ownership と identity contract の下で処理します。

### Legacy compatibility path

古い watchdog-managed backend prewarm 実装と関連フラグは互換性のためソースに
残っている場合がありますが、現在の Windows Tier-1 supported topology では
**deprecated / disabled / unqualified** です。

- `-prewarm-backend` を有効化しない
- `desktop-backend.json` を supported ownership manifest として扱わない
- watchdog-managed `:9119` serve を Desktop backend authority として扱わない
- legacy prewarm path の成功を release qualification evidence に使わない

これらを再び有効化する変更は、single-authority contract の変更として扱い、
明示的な設計変更・Windows-native negative tests・qualification が必要です。

## Isolation（AI からの変更不可）

| 項目 | 内容 |
| --- | --- |
| Process | Hermes Python/Electron とは別バイナリ |
| State | `%LOCALAPPDATA%\HermesWatchdog\` |
| Log | `%HERMES_HOME%\logs\hermes-go-watchdog.log` |
| Change API | 公開しない |
| Read API | `GET /health`, `GET /api/status`, `GET /api/v1/status` |

HTTP surface は read-only です。pause、resume、cycle、stop、restart、force-restart、
lock deletion、PID 指定 kill などの変更操作を HTTP / MCP / tool / plugin / skill /
cron へ公開しません。

Launcher は elevated operator PowerShell から起動する運用を前提とし、通常権限の
Hermes Agent と watchdog process の間に Windows process privilege boundary を置きます。

## Build

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Build-HermesGoWatchdog.ps1
```

Output:

```text
scripts\windows\watchdog-go\dist\hermes-watchdog.exe
```

## Start / stop

通常の workstation 起動では登録済み Windows Scheduled Task または operator-only
launcher から起動します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Start-HermesGoWatchdog.ps1
```

停止・明示置換も同じ launcher の operator-only path を使用します。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Start-HermesGoWatchdog.ps1 -Stop
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\windows\Start-HermesGoWatchdog.ps1 -ForceRestart
```

Watchdog 自身の ownership は `%LOCALAPPDATA%\HermesWatchdog\watchdog.lock` の
PIDだけではなく、live process identity・creation time・executable path・repository
identity を検証して扱います。

## Read-only status plane

既定 local endpoint:

```text
127.0.0.1:9920
```

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | watchdog liveness |
| GET | `/api/status` | current state |
| GET | `/api/v1/status` | versioned state |

Tailscale `tsnet` を設定した場合も status plane は read-only のままです。
認証情報を repository へ commit しないでください。

## Embedding supervision

`plugins.entries.semantic-graph.config.embedding.runtime.enabled: true` の場合、
operator launcher は readonly configuration から local embedding runtime の設定を読み、
watchdog へ渡せます。

Supported destructive authority は **watchdog が明示的に起動・所有した embedding
`llama-server` だけ**です。

原則:

- healthy な既存 embedding endpoint を理由なく置換しない
- unknown PID を停止しない
- model file を自動取得しない
- configured loopback endpoint / executable / model / arguments を使用する
- initialization timeout と ownership evidence の両方を満たす場合だけ owned child を回復する
- maintenance fence 中は recovery を行わない

代表的な embedding flags:

```text
-embedding-enabled
-embedding-endpoint
-embedding-server
-embedding-model
-embedding-args-json
-embedding-start-timeout
```

## Maintenance fence

Update、planned stop、uninstall などの計画された process mutation は、通常の
recovery と競合してはいけません。`maintenance.json` の有効な fence が存在する間、
watchdog は対象となる supported recovery を抑止します。

Maintenance fence は ownership を移譲する仕組みではありません。Electron-owned
Desktop backend の destructive authority が watchdog へ移ることはありません。

## Recovery policy

Recovery budget / backoff / circuit-breaker は watchdog 自身と、その supported owned
runtime に対する再試行嵐を防ぐためのものです。これらの状態は
`%LOCALAPPDATA%\HermesWatchdog\recovery-budget.json` に保持されます。

Recovery budget が存在すること自体は Desktop Python backend への restart authority を
意味しません。

## Security / authority invariants

次の条件を regression として扱います。

1. Go watchdog が Electron-owned Desktop backend を start / stop / kill / replace できる。
2. PID-only、port-only、command-line-only の情報が destructive authority に昇格する。
3. health/discovery path が ownership を暗黙に取得する。
4. maintenance や restart の途中で別 component が同じ runtime role の第二 owner になる。
5. embedding supervisor が自分の ownership evidence を持たない unknown process を停止する。

Authority-sensitive changesでは、unit testだけでなく Windows-native process identity、
restart/recovery、maintenance fence の negative test を残してください。

## Relationship to Desktop

Desktop と watchdog は別 lifecycle です。Desktopを閉じたこと、watchdogが生きている
こと、特定portがlistenしていることのいずれも、stack全体の世代・identity・readinessを
証明しません。

Desktop Python backend の正本 lifecycle owner は Electron main です。Watchdog status
は観測情報として利用できますが、Desktop backend ownership の根拠にはしません。

See also:

- `.codex/WINDOWS_PLATFORM_CONTRACT.md`
- `CARRY.yaml`
- `docs/windows/RELEASE_POLICY.md`
- `apps/desktop/electron/backend-claim.ts`
- `apps/desktop/electron/backend-release-gate.ts`

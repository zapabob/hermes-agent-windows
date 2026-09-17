# Windows Tier-1 platform contract

Windows 11 x64 with native Python, native Node/Electron, an interactive desktop,
and a consumer NVIDIA GPU is a Tier-1 downstream target. The workstation may
operate continuously with local LLM, local embeddings, voice, VRChat/Unity, and
remote management services.

Required compatibility covers native drive paths, MSYS `/c/...` aliases, WSL
`/mnt/c/...` aliases where supported, NTFS sharing locks, locked executable and
extension-module updates, process-tree cleanup, applicable Job Object behavior,
PowerShell argument quoting, Git Bash boundaries, CP932/UTF-8 boundaries, CRLF,
venv `Scripts\` layout, and Electron stdio pipes.

Runtime qualification covers sleep/resume, network loss and recovery, loopback
provider loss and recovery, Desktop relaunch, updater handoff, watchdog
recovery, llama restart and hot-swap, embedding restart, and profile/session
persistence. Cross-platform code expected to work on Windows must run on a
native Windows CI host; a Linux cross-compile or a marker-only lane is not
sufficient evidence.

Windows policy belongs under `downstream/platform/windows`. Existing official
Hermes helpers remain authoritative when they already own a concept; downstream
helpers delegate to them rather than creating competing process, session,
approval, profile, or registry authorities.

## Runtime authority invariant

For one resolved `HERMES_HOME` and one runtime role, exactly one component may
hold destructive lifecycle authority. Observation, health probing, discovery,
a PID, a port, a token, or a manifest never confer ownership by themselves.

For the supported Desktop topology, Electron main is the sole owner of the
Desktop Python backend lifecycle. It alone may claim, stop, replace, or restart
the backend it spawned and retained. The Go watchdog is not a second Desktop
backend owner; its supported destructive scope is limited to an embedding
`llama-server` instance that it explicitly launched and owns. The watchdog may
observe Desktop/backend health and may manage its own process lifecycle, but
must not infer Desktop-backend termination authority from observation.

Legacy watchdog backend-prewarm compatibility paths are outside the supported
single-owner topology. They must remain disabled and cannot be used as evidence
for Windows Tier-1 qualification. Any future change that gives two components
destructive authority over the same runtime role is an architecture regression
and requires an explicit platform-contract change plus Windows-native negative
tests.

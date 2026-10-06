# Windows watchdog: observe the Electron venv backend

Date: 2026-10-06. Branch: main. Base: `85072cf1cd8430f45cda32666e4c3b01594d0650`.

## Contract

Electron owns the Desktop frontend and its backend together, including their
startup, shutdown and recovery. The Go watchdog observes those surfaces. This
change adds no Desktop or backend lifecycle action to the watchdog. Existing
embedding supervision retains its separate scope.

## Reproduction

The packaged Desktop had a visible, responsive window. Its backend returned
HTTP 200 from `/api/status`. The existing watchdog nevertheless reported the
backend as down. Inspection established three causes in the observation path:

1. The WMI destination included a native `CreationTime` field that is not a
   queried `Win32_Process` property. WMI returned a missing-field error and the
   candidate list was discarded.
2. A Windows venv launches a base-Python worker outside the configured source
   root. The worker owns the listening socket; the root-scoped launcher does not.
3. uv's Python version alias is a directory junction. WMI and the native process
   image query can report different paths to the same executable file.

## Change

`getDesktopBackendCandidates` now reads WMI into a row shape containing exactly
the selected properties. Native process identity supplies creation time.

The candidate filter accepts the direct Python worker of a configured-root
backend launcher when interpreter names and full parsed argument lists match.
Both identities must have known creation times, and the parent must precede the
worker. Missing parents, reused parent PIDs, different profiles/services, other
interpreters and extra arguments fail closed.

Process image aliases are compared by file identity when their normalized paths
differ. A separate file with identical bytes is rejected. This comparison is
limited to backend observation and does not alter the watchdog lock identity or
add any process termination capability.

Implementation commits: `0bd4d4210127171bea95522458e2b485edc68393` and
`ef22faa1fd2927f903d737cf2d38d4d21a36dd7a`.

## Evidence

Native Windows `go test ./... -count=1` passed in 4.352 seconds. Coverage includes
the venv worker cases, native WMI row loading, file identity aliases and the
existing contract prohibiting Go Desktop/backend lifecycle authority.

A separately built binary ran one observation cycle against the real packaged
Desktop, using an isolated data/log directory and no HTTP listener. It reported
`desktop=up`, `backend=up`, and `backendHealth=healthy`; its observed backend PID
and port matched the live Electron-owned listener and successful HTTP probe.

The carry-surface reports were regenerated from the committed implementation.
Cloud CI, deployed watchdog status and the rebuilt Desktop install stamp are
separate delivery receipts and must be checked against the final pushed SHA.

## Recovery

The earlier executable and Desktop package are retained as local rollback
artifacts. The two implementation commits can be reverted through normal Git
history if needed. No session database, long-term memory, personality file or
model preset is modified by this observation repair.

# Dependency and policy closeout - 2026-10-06

Observed at 2026-10-06 17:05 JST.

Base: origin/main `c6cc5aaf38de41cfb377bee835cedbf85565a3ed`. Source head reviewed: `046ba2e38d438f31f8ae910ee389cfdcdd28acb1`.

This delivery carries the branch's dependency refreshes and Windows security fixes into main. It retains the Git review execution policy and its tests, updates the affected npm, pnpm, Python, and Go dependency locks, and preserves the nested-context redaction regression fix. No dependency change intentionally alters application behavior or renderer layout.

## Local evidence

- Desktop test suite: 8,681 passed, 9 skipped; 821 files passed, 1 skipped.
- Desktop typecheck and Vite/electron build completed successfully.
- Go watchdog module tests passed; the build artifact was produced separately from the repository tree.
- Root production npm audit reported zero vulnerabilities.
- Website audit still reports 45 advisories: 30 high, 13 moderate, and 2 low; zero critical. The remaining high findings are in the Docusaurus dependency chain without a safe patched graph. The offered automatic repair downgrades Docusaurus, so it was not applied. This remains an open dependency warning and is not described as fully green.
- The first Windows Tier-1 CI run for `046ba2e` failed only at carry-metrics validation; other required jobs were still pending at that observation. The reports were regenerated from committed `HEAD`, and `carry_metrics.py --check` now passes locally.

## Runtime and publication boundary

UAC-authorized stop completed with zero remaining matched processes in the helper's final inventory. A fresh process/port query also found no Hermes listener on the checked ports. No database was opened or rewritten in this step. Desktop, llama server, and Go watchdog restart plus final main-SHA CI verification are subsequent gates.

No files were deleted. The carry-surface JSON and Markdown remain at their established paths and were regenerated in place.

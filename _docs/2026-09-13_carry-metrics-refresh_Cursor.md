# 2026-09-13 Carry Metrics Refresh (Cursor)

## 概要

Tier-1 Downstream policy で失敗していた `carry_metrics.py --check`（Carry metrics are stale）を、最新 `origin/main`（SR-007b tip）上で再生成して解消した。

## 背景・要求

- CI failure on recent main pushes (`6e3f88c4`, `c878de51`)
- Evidence: `uv run --no-sync python scripts/downstream/carry_metrics.py --check` → stale
- Tip may be `e0948ff241` (SR-007b) — regenerate on latest main without reverting SR-007 work

## 前提・判断

- C: free space was 7.49 GB (`OK_SPACE`); no TEMP/`tmp/snapshots` cleanup required
- Unrelated dirty WIP left untouched (`GPTPRO_HANDOFF_REPORT.md`, `Start-HermesGoWatchdog.ps1`, `test_readme_contract.py`)
- Only `_docs/carry-surface-20260826.{json,md}` (+ this impl log) in scope

## 変更対象ファイル

- `_docs/carry-surface-20260826.json`
- `_docs/carry-surface-20260826.md`
- `_docs/2026-09-13_carry-metrics-refresh_Cursor.md`

## 実装詳細

1. `git fetch origin main` — tip already at `e0948ff241`
2. Regenerated carry surface via `carry_metrics.py` (no `--check`)
3. Verified `--check` and `validate_policy.py`

## 実行コマンド

```powershell
uv run --no-sync python scripts/downstream/carry_metrics.py
uv run --no-sync python scripts/downstream/carry_metrics.py --check
uv run --no-sync python scripts/downstream/validate_policy.py
```

## テスト・検証結果

- `carry_metrics.py --check` → `Carry metrics are current.` (exit 0)
- `validate_policy.py` → `Downstream policy validation passed.` (exit 0)

## 残留リスク

- Future main pushes that change fork/upstream delta without regenerating carry surface will re-stale the metrics
- CI confirmation depends on GitHub Actions picking up the push

## 次の推奨アクション

- Confirm Tier-1 Downstream policy job is green on the new push
- Keep regenerating carry metrics whenever CARRY/upstream snapshot or fork surface drifts

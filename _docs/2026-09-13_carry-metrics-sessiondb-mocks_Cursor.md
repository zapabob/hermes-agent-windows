# 2026-09-13 Carry Metrics + SessionDB Mock Seams (Cursor)

## 概要

CI の二系統失敗を解消した。(1) Tier-1 Downstream policy の stale carry metrics、(2) SR-003 shared SessionDB 後に壊れたモック契約に起因する Python テスト 3 件。

## 背景・要求

- `6e3f88c4` 系で Carry metrics stale + SessionDB mock failures
- Prefer updating callers/mocks to the new `db_path` / shared-acquire API (do not revert SR-003a/b)

## 前提・判断

- C: free ≈ 13.7 GB — cleanup not required
- Production opens via `hermes_state_shared.acquire` → `_open_session_db(path)` → `SessionDB(db_path=path)`
- Goals off-loop contract still valid; only the test seam was wrong (`hermes_state.SessionDB` → `hermes_state_shared._open_session_db`)
- Bare `object()` fakes cannot accept `_shared_owned` assignment from acquire

## 変更対象ファイル

- `tests/gateway/test_session_db_recovery.py`
- `tests/hermes_cli/test_goals_db_bootstrap_off_loop.py`
- `_docs/carry-surface-20260826.json`
- `_docs/carry-surface-20260826.md`
- `_docs/2026-09-13_carry-metrics-refresh_Cursor.md` (superseded context; this file is the expanded receipt)

## 実装詳細

1. Recovery reopen test: accept `db_path`, use mutable `_FakeHandle`, clear shared registry around phases
2. Goals bootstrap tests: patch `hermes_state_shared._open_session_db`, accept `db_path`, `close_all()` in fixture
3. Regenerated carry-surface reports and validated policy

## 実行コマンド

```powershell
uv run --no-sync python -m pytest tests/gateway/test_session_db_recovery.py tests/hermes_cli/test_goals_db_bootstrap_off_loop.py -q --tb=short
uv run --no-sync python scripts/downstream/carry_metrics.py
uv run --no-sync python scripts/downstream/carry_metrics.py --check
uv run --no-sync python scripts/downstream/validate_policy.py
```

## テスト・検証結果

- `tests/gateway/test_session_db_recovery.py` + `tests/hermes_cli/test_goals_db_bootstrap_off_loop.py` → **12 passed**
- `carry_metrics.py --check` → `Carry metrics are current.`
- `validate_policy.py` → `Downstream policy validation passed.`

## 残留リスク

- Other tests that still patch `hermes_state.SessionDB` without `db_path` / mutable fakes may fail similarly under shared acquire
- Full CI matrix beyond these three failures not exhaustively re-proven locally

## 次の推奨アクション

- Confirm Tier-1 Downstream policy + Python tests jobs green on the push
- Grep remaining `SessionDB` monkeypatches for no-arg constructors if CI surfaces more

# 2026-09-13 Carry Metrics CI-Stable Fix (Cursor)

## 概要

Tier-1 `carry_metrics.py --check` が「再生コミット後も stale」になる根因を特定し、
committed `HEAD` 基準の差分と `_docs/` 全体除外で CI とローカルを一致させた。

## 背景・要求

- Tip `c11161a68f` / `84e4b6399a`（再生コミット）/ `501d4e5eac` いずれも Downstream policy が
  「Carry metrics are stale」で失敗
- Python SessionDB テストは緑 — 失敗は carry metrics のみ
- 調査観点: byte-exact JSON+MD、upstream fetch、CRLF、gitignore、再生内容

## 前提・判断（CoT）

1. **gitignore ではない** — `git check-ignore` 非ヒット、両ファイルは tracked、`eol=lf`
2. **upstream fetch 不足ではない** — workflow は `UPSTREAM_SNAPSHOT` SHA を fetch、計算は例外なく完走し stale メッセージのみ
3. **再生コミット `84e4b6399a` 自体が clean checkout でも stale**
   - committed summary ≠ fresh summary（LOC/CWC 不一致）
4. **根因 A（主）**: `git diff upstream --` が **作業ツリー** を見るため、再生時の dirty WIP
   （実装ログ記載の `GPTPRO_HANDOFF_REPORT.md` 等）が数値に混入。CI は clean checkout → 不一致
5. **根因 B（副）**: 同コミットの `_docs/*_Cursor.md` 実装ログが `EXCLUDED` 外で UTR 分母を動かす自己参照

## 変更対象ファイル

- `scripts/downstream/carry_metrics.py`
- `tests/downstream/test_carry_metrics.py`
- `_docs/carry-surface-20260826.json`
- `_docs/carry-surface-20260826.md`
- `_docs/2026-09-13_carry-metrics-check-ci-stable_Cursor.md`

## 実装詳細

1. numstat を `git diff --numstat --no-renames <upstream> HEAD` に変更（dirty worktree 非依存）
2. `EXCLUDED_PREFIXES = ("_docs/",)` と `is_excluded()` で実装ログ自己無効化を遮断
3. definitions / markdown 文言を committed HEAD + `_docs/` 除外に更新
4. tip `01e3bc4b`（FI 同時進行後）上でロジック commit → regenerate → レポート commit

## 実行コマンド

```powershell
git fetch origin main
git reset --hard origin/main
py -3 scripts/downstream/carry_metrics.py
py -3 scripts/downstream/carry_metrics.py --check
py -3 -m pytest tests/downstream/test_carry_metrics.py -q
py -3 scripts/downstream/validate_policy.py
```

## テスト・検証結果

- `carry_metrics.py --check` → `Carry metrics are current.` (exit 0) after regen on post-fix HEAD
- `tests/downstream/test_carry_metrics.py` → 3 passed
- `validate_policy.py` → passed
- Clean worktree simulation: see follow-up commands in session

## 残留リスク

- `_docs/` 以外のコード変更後は従来どおり regenerate が必要
- FI 同時 push がある場合は tip 再取得後に再 regenerate が必要

## 次の推奨アクション

- Tier-1 Downstream policy が新 tip で緑になることを `gh run` で確認

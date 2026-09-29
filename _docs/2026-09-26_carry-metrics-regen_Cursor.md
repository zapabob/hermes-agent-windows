# 2026-09-26 Carry metrics regeneration (Cursor)

## Summary

Regenerated the carry-surface metrics reports so the `Downstream policy` job
(`.github/workflows/fork-cicd.yml`) passes on `main` again.

## Background

`main` at `95b96a5b` failed the step `Validate carry-surface metrics`
(`scripts/downstream/carry_metrics.py --check`) with
`Carry metrics are stale. Regenerate without --check.` Recent merges changed
upstream-owned files, so the committed reports no longer matched HEAD.

## Changed files

- `_docs/carry-surface-20260826.json`
- `_docs/carry-surface-20260826.md`
- `_docs/2026-09-26_carry-metrics-regen_Cursor.md` (this log)

## Commands

```powershell
python scripts/downstream/carry_metrics.py          # regenerate
python scripts/downstream/carry_metrics.py --check  # Carry metrics are current.
python scripts/downstream/validate_policy.py        # passed
python -m pytest tests/downstream/test_ci_contracts.py -q  # 12 passed
```

## Result

Only metric values changed (LOC 2697341 -> 2700414, carry surface 5096 -> 5103
files, CWC 86353881 -> 86364991). The `_docs/` tree is excluded from the
metrics, so committing the reports and this log does not invalidate `--check`.

## Residual risk

Any later merge touching upstream-owned paths makes the reports stale again;
rerun the generator in that PR.

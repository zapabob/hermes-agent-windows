# Semantic refresh evidence scope

This directory records bounded, evidence-backed Windows semantic-refresh family work. Keep D0, R2, U1, and historical U0 as separate frozen inputs. Record the observed current main independently; never replace a frozen SHA with a newer remote head.

Each family record must identify actual source and caller spans, the observable contract, RED and GREEN evidence, affected checks, mutation, the post-edit CodeGraph binding, independent review, and remaining gaps. A clean index, object inventory, test count, or review does not by itself prove whole-upstream parity or authorize production write. Keep Control MCP production write DISABLED until its separate authority and writer gates are satisfied.

Do not publish machine-local receipts, credentials, personal state, or generated scratch. Do not merge, rebase or cherry-pick upstream merely to make a family appear complete.

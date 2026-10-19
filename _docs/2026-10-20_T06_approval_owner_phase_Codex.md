# T06 first approval ownership phase — frozen for parent review

Baseline was 7d84b0e2a3e225a544556ce1fb5c67bdf0d7c5e0. Current HEAD observation is c1306f340898f7a0e8adab32e4d3ba5040f35338; other owners may advance it. This worker made no commit.

Only gateway/run.py, tools/approval.py and the new tests/gateway/test_approval_run_ownership.py are this phase's product/test scope. Earlier shared-input sources, all old33/31/34 tests, the old evidence manifests and paused clarify inventory remain byte-identical. All 1646 T06p manifest entries were rehashed.

Gateway run registration carries the captured state/generation/boundary owner into copied tool contexts. Admission validates under the captured state lock and then the approval lock. Callback sends validate before scheduling, when the scheduled coroutine starts, and after native delivery disposition before any text fallback. Finally removes only its exact registration and entries. A boundary deactivates registrations and wakes pending entries.

Registration replacement now removes the predecessor's own FIFO entries atomically with callback publication, then wakes those waiters outside both locks. The deterministic countercase holds A's native send ACK, displays B, issues ordinary approval without request_id, and completes B before releasing A. A receives no approval authority. This fixes lost approval without changing normal FIFO or requiring request_id.

The adjacent strict countercase inherited A's ContextVar and previously reselected B's callback. request_control_consent now captures the same producer handle before entry allocation and validates it under the same admission locks. Digest, immutable presentation, exact ticket and once-only consumption logic are unchanged. Actual source caller is HostControlCoordinator.submit; tests establish the inherited producer condition, not a native effector exploit or complete control lifecycle acceptance.

Final qualified proof: 470 unique normal cases across 35 files, including all previous 248 owner regressions and the dedicated 24 cases. 36 distinct fault variants in 37 Jobs caused 98 failed occurrences/81 unique failed nodes, every one GREEN unmutated. Accepted Jobs have zero errors, skips, recovery or bound-source drift. Every test runs offline in an owned Windows Job, isolated temporary Hermes home, with real subprocess creation and host process discovery/termination denied. Native delivery is a declared synthetic adapter; actual run/wait/queue/finally code stays active.

The process registry is concurrently edited by another owner. Its fixed import copy is recorded in t06a-evidence/declared-process-leaf, while snapshot/reapers remain explicit empty leaves. Live registry observations are retained separately. No process r3/PTY/kernel/API acceptance follows. Earlier matrices with live dependency drift were rejected.

The full exploratory approval test file has one WinError 1314 symlink skip (117 passed). That unchanged test is explicitly excluded by name in final qualified selection; it is not claimed GREEN. Initial green-1 deadlocked through an erroneous nested non-reentrant lock; its owned Job recovered three processes and reached zero active. That attempt and all setup/drift receipts are retained as nonfinal, not hidden in the zero-recovery qualification.

Fresh pinned CodeGraph 1.6.0: 16 files/1650 current matching full-method spans/2354 nodes/7038 edges. Actual DB is copied to immutable-codegraph.db and independently counted read-only. Original line numbers and exact complete run.py methods are preserved in the projection. CLI cap is unchanged. Full run.py SDK extraction retains 8157 unresolved references, so no root/full-file graph claim is made. New tests pass Ruff; selected product lint has only the unchanged baseline ActivityProvenance F821 at run.py:1298.

Parent review is required before integration or clarify expansion. Remaining scope: clarify registration/answers/finally, native adapter request_id routing, caller persistence after approval resolution, complete strict/control/native lifecycle, independent kernel/process/API proof, full graph resolution and whole-SHA CI. No production channel, installation, host security, service, external network action, delegation or commit was performed.

Canonical local receipt: tmp/continuation-20261020/t06a-evidence/receipt.json. Final source snapshots and incremental diff are adjacent. All preliminary and earlier n/p generations are retained.

# Named-profile session resume workspace: Windows semantic adoption

Frozen upstream main `63d0b94120027d487c9a5235b9ec64b696af1b26`; relevant changes `21a9a1f0ec0491dcb837f8a399e38fba0a41ab6d` and `b23600860f82bd66d345c0a1baefd0f264605955`. Parent/restoration reference `28c8ba6b4bbe504f0805e6589f367e47d1636e98`. ADAPT behavior into existing local `tui_gateway/server.py` and `tui_gateway/methods_session.py`; no upstream split module is added.

## Accepted behavior

Named local profiles repair stale/unusable saved working directories and resolve the live directory through their own configured workspace or profile home. Valid user-selected existing directories remain valid. Cold, deferred and eager resume paths persist repaired cwd to the target profile's database. Eager initialization uses that profile's database/home. Lazy child-watch resolves the live cwd without writing the saved row. Default-profile and nonlocal backend behavior retain their existing paths. Transcript display text and roles are preserved; historical prompt prefixes/toolsets are not modified.

This unit qualifies focused resume-handler/DB behavior. It does not establish a full packaged Desktop restart, provider request routing or live inference acceptance.

## Validation and independent review

Native Windows RED: 3 passed, 10 failed before product changes, reproducing incorrect named-profile workspaces. A first post-change run reached cwd/persistence assertions but had a new-test field-name mismatch (`content` versus established display `text`); that log is retained and is not a product repair. The final new-test cohort strengthened the missing directory case and passed 13/13. Six explicitly selected existing cases in `tests/test_tui_gateway_server.py` also passed, including profile-cwd and resume-history checks. No broad server suite or live provider call was used.

Commands used existing ROOT Windows Python and H-isolated launchers, fresh process per file, sanitized credentials, UTC/UTF8, `scripts/run_tests_parallel.py --jobs 1 --file-retries 0 --file-timeout 300 -q`, explicit semicolon file lists/node IDs and H temporary paths. Existing U01 launcher remained unchanged.

CodeGraph mapped the actual resume and eager-init owners before the minimal edits. One incremental sync covered two source and two new test files; status was complete with9,175files, zero pending changes/refs and extraction25 current. `_hydrate_profile_resume_cwd` is called by the resume handler and eager initialization. Separate Luna MAX independent review returned specification and quality PASS with no blocker. No upper-model repair was used.

## Evidence and recovery

Local evidence directory `H:/Codex-v0216-archive/`: `V0217_PROFILE_RESUME_WORKSPACE_CLOSEOUT_20261013.md` pins upstream/local sources, exact commands and logs; `V0217_PROFILE_RESUME_WORKSPACE_INDEPENDENT_REVIEW_20261013.md` records the independent verdict. Logs are `V0217_PROFILE_RESUME_RED_20261013.log`, original test-only failure `V0217_PROFILE_RESUME_GREEN_20261013.log`, final `V0217_PROFILE_RESUME_GREEN2_20261013.log`, and `V0217_PROFILE_RESUME_REGRESSION_20261013.log`. Commit receipt `V0217_PROFILE_RESUME_LOCAL_COMMIT_RECEIPT_20261013.json` binds exact staged/committed files and protected state. Raw logs, databases and credentials are not committed.

Recovery is a targeted revert of this unit on the isolated branch after checking later dependencies. The parent SHA remains the exact previous source. Do not reset PRIMARY or include unrelated dirty content. Session cancellation, full model/memory/Windows/package acceptance and the0.21.7version update remain open.
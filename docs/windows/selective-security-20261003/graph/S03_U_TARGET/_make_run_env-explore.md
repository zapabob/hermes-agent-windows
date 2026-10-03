**Exploration: _make_run_env**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `run` (.github/actions/setup-pm/prune/index.mjs:7) — 3 callers in `.github/actions/setup-pm/prune/index.mjs`, `evals/desktop_bug_campaign/thread-scroll/ownership-probe.mjs`; tests: `tests-js/setup-pm-post.test.mjs`
- `make` (hermes_cli/_launchers.py:210) — 1 caller in `hermes_cli/_launchers.py`; tested via callers: `tests/e2e/core/windows/_helpers.py`, `tests/hermes_cli/test_launcher_runtime_selection.py` +4
- `make` (hermes_cli/cli_loops_mixin.py:483) — 1 caller in `hermes_cli/cli_loops_mixin.py`; no tests found within 3 caller hops
- `make` (hermes_cli/config_defaults.py:2737) — 1 caller in `hermes_cli/config_defaults.py`; no tests found within 3 caller hops

**Relationships**

**calls:**
- mint_launcher → make
- mint_launcher → _launcher_script
- mint_launcher → _is_windows
- mint_launcher → _mint_shell_launcher
- mint_launcher → _load_script_maker
- mint_launcher → encode
- mint_launcher → decode
- mint_launcher → _write_atomic
- stage_launcher → mint_launcher
- hermes_exe → mint_launcher
- test_minted_launcher_reads_current_selection_and_editable_members → mint_launcher
- test_sync_migrates_old_store_wrapper_before_python_collection → mint_launcher
- publish_fixture_launcher → mint_launcher
- test_pm_observer_accepts_ready_fixture_and_leaves_failed_fixture_untouched → mint_launcher
- test_real_delivery_launcher_imports_new_generation → mint_launcher
- ... and 115 more

**instantiates:**
- make → _PathedScriptMaker
- make → GoalManager
- interruptible_streaming_api_call → _StreamingCall
- interruptible_api_call → _NonStreamRequest

**references:**
- mint_launcher → ENTRY_POINTS
- _launcher_script → ENTRY_POINTS
- load → make
- _get_goal_manager → load
- _get_heartbeat_manager → load
- _get_loop_manager → load
- make → _OMIT
- _category → make
- _category → _OMIT
- _request → _NonStreamRequest
- _nonstream_request → _NonStreamRequest

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local.py`** — calls(calls), _make_run_env(function)

```python
713	    return next((k for k in run_env if k.upper() == "PATH"), None) if _IS_WINDOWS else "PATH"
714
715
716	def _make_run_env(env: dict) -> dict:
717	    """Build a run environment with a sane PATH and provider-var stripping. The process env is
718	    the LAUNCH profile's; under a routed home override its ``.env`` residue is dropped first
719	    (``strip_launch_profile_env``, a no-op for the launch profile) so the backend's own ``env``
720	    and the served profile's declared passthrough names are what the child sees."""
721	    run_env = _scrubbed_env(
722	        [(dict(strip_launch_profile_env(os.environ.copy()) | env), True)],
723	        frozenset(),
724	        lambda p: _prepend_git_bash_dirs(_append_missing_sane_path_entries(p)),
725	    )
726	    # While this profile's Bot Desktop is running, its DISPLAY/XAUTHORITY/DBUS ride along so GUI
727	    # apps the agent launches from the terminal open on the Bot Screen the user is watching, not
728	    # on the user's own seat (#125830). published_env() is the pure read (no activity stamp — a
729	    # plain ``ls`` must not keep the screen alive past idle_stop_minutes), and it wins over the
730	    # login snapshot's seat DISPLAY; a user who wants their own seat uses an inline
731	    # ``DISPLAY=:0 cmd`` prefix, which bash applies after this env. Empty (or module missing) →
732	    # the seat env passes through untouched.
733	    try:
734	        from tools.bot_desktop.runtime import published_env
735	        published = published_env()
736	    except Exception:
737	        published = {}
738	    if published:
739	        run_env.update(published)
740	        run_env.pop("WAYLAND_DISPLAY", None)  # X11 desktop; a leaked Wayland socket flips GTK/Chromium backends
741	    return run_env
742
743
744	# --- Hermes venv / repo-root detection (module-level, computed once) ---
```

**Not shown above — explore these names for their source**

- agent/chat_completion_helpers.py: run:2782, run:4075, _BedrockStream:2620, _check_stale_giveup:609, _with_stream_emitters:2579, interruptible_api_call:1293, +29 more
- hermes_cli/config_defaults.py: make:2737, _category:2731, _OMIT:2728
- .github/actions/setup-pm/prune/index.mjs: run:7, index.mjs:1
- hermes_cli/_launchers.py: make:210, mint_launcher:186, _PathedScriptMaker:203, _launcher_script:277, _is_windows:99, _mint_shell_launcher:324, +9 more
- agent/chat_completion_nonstream.py: run:272, _NonStreamRequest:7, _emit_wait_notice:138, _codex_watchdog_snapshot:121, _ttfb_kill:186, _pre_progress:134, +12 more
- hermes_cli/cli_loops_mixin.py: make:483, load:479, _get_goal_manager:477, _get_heartbeat_manager:493, _get_loop_manager:500
- agent/relay_llm.py: run_callback:100, invoke_async:133
- hermes_cli/models_reasoning_caps.py: get:180, _CapsSource:162, _origin:34
- hermes_cli/config.py: load_config:2123
- hermes_cli/goals.py: GoalManager:1088
- ... and 40 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

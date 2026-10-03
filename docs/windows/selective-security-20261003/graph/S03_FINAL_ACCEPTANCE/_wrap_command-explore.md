**Exploration: _wrap_command**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `Command` (apps/desktop/src/components/ui/command.tsx:8) — 23 callers in `plugins/platforms/discord/adapter.py`, `apps/desktop/src/app/chat/sidebar/projects/base-branch-picker.tsx`, `apps/desktop/src/app/chat/sidebar/projects/worktree-dialog.tsx`, `apps/desktop/src/app/command-palette/index.tsx` +7 more; tests: `apps/desktop/src/app/command-palette/highlight-watcher.test.tsx`
- `wrap` (apps/desktop/src/store/session-switcher.ts:16) — 1 caller in `apps/desktop/src/store/session-switcher.ts`; tested via callers: `apps/desktop/src/store/session-switcher.test.ts`
- `command` (scripts/ci/qualify_implementation_router.py:20) — 2 callers in `scripts/ci/qualify_implementation_router.py`; no tests found within 3 caller hops
- `command` (downstream/security/cli.py:354) — 2 callers in `hermes_cli/main.py`, `plugins/platforms/slack/adapter.py`; tested via callers: `tests/gateway/test_slack.py`, `tests/gateway/test_slack_log_noise.py` +1

**Relationships**

**calls:**
- Command → cn
- _build_auto_slash_command → Command
- _register_skill_group → Command
- BaseBranchPicker → Command
- WorktreeDialog → Command
- palette → Command
- CommandPaletteBody → Command
- ComboboxInput → Command
- SearchableSelect → Command
- useStatusbarItems → Command
- LanguageCommand → Command
- ModelPickerDialog → Command
- SessionPickerDialog → Command
- StreamLine → cn
- SubagentRow → cn
- ... and 124 more

**references:**
- openOrAdvanceSwitcher → pendingBrowse
- openOrAdvanceSwitcher → $switcherIndex
- openOrAdvanceSwitcher → $switcherSessions
- openOrAdvanceSwitcher → $switcherOpen
- git → ROOT
- main → ROOT
- _kick_daily_auto_update_if_due → _run
- setFlexWrap → Wrap
- Style → Wrap
- setFlexWrap → Wrap
- getFlexWrap → Wrap
- setFlexWrap → LayoutWrap
- Style → Direction
- Style → FlexDirection
- Style → Justify
- ... and 14 more

**instantiates:**
- command → SecurityService

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/base.py`** — calls(calls), _wrap_command(method)

```python
908	        """
909	        return shlex.quote(path)
910
911	    def _wrap_command(self, command: str, cwd: str) -> str:
912	        """Build the full bash script that sources snapshot, cd's, runs command,
913	        re-dumps env vars, and emits CWD markers."""
914	        escaped = command.replace("'", "'\\''")
915
916	        # Quote the snapshot path (see init_session — LocalEnvironment
917	        # rewrites ``C:/...`` to ``/c/...`` so MSYS doesn't mangle it).
918	        _quoted_snap = self._quote_shell_path(self._snapshot_path)
919	        # Use atomic file replacement for env snapshot updates (issue #38249).
920	        # Assemble into a per-writer-unique temp file, then mv to atomically
921	        # replace the snapshot so concurrent source() calls never read a
922	        # truncated/half-written file.  ``mktemp`` is used instead of
923	        # ``$BASHPID``/``$$`` because macOS bash 3.2 lacks ``$BASHPID`` (it
924	        # expands empty, collapsing every writer onto one temp name) and ``$$``
925	        # is shared by ``&``-launched subshells.  Template shell-quoted
926	        # (Windows/spaces); the allocated path lives in a shell variable.
927	        _snap_tmp_template = self._quote_shell_path(self._snapshot_path + ".tmp.XXXXXXXXXX")
928	        _snap_tmp = '"$__hermes_snap_tmp"'
929
930	        parts = []
931	        passthrough_names = self._snapshot_excluded_passthrough_names()
932
933	        # A shared snapshot may contain the previous profile's value. Save
934	        # the current process environment before sourcing it, then restore the
935	        # current profile's value (or unset the name) immediately afterwards.
936	        # Values stay in environment memory and never enter the shell command
937	        # string, so secrets are not exposed through process arguments/logs.
938	        saved_names: list[tuple[str, str, str]] = []
939	        for name in passthrough_names:
940	            marker = f"_HERMES_RUNTIME_PASSTHROUGH_{name}"
941	            present = f"{marker}_PRESENT"
942	            value = f"{marker}_VALUE"
943	            saved_names.append((name, present, value))
944	            parts.append(f"{present}=${{{name}+x}}")
945	            parts.append(f"{value}=${{{name}-}}")
946
947	        # Source snapshot (env vars from previous commands).
948	        # Redirect stdout to /dev/null: on macOS (bash 3.2 and certain
949	        # Homebrew bash builds) sourcing a file containing ``declare -x``
950	        # can emit the declarations to stdout, leaking ~60 lines of env
951	        # vars into every tool response (issue #15459).  Linux bash is
952	        # silent here, but the redirect is harmless.
953	        if self._snapshot_ready:
954	            parts.append(
955	                f"source {_quoted_snap} >/dev/null 2>&1 || true"
956	            )
957
958	        for name, present, value in saved_names:
959	            parts.append(
960	                f'if [ "${present}" = x ]; then export {name}="${value}"; '
961	                f'else unset {name}; fi'
962	            )
963	            parts.append(f"unset {present} {value}")
964
965	        # Harness attribution: every tool subprocess advertises that it runs
966	        # under Hermes via the cross-agent ``AI_AGENT`` standard (read by e.g.
967	        # huggingface_hub's agent detection) plus the Hermes-specific
968	        # ``HERMES_AGENT`` marker.  The value MUST equal our id in the public
969	        # agent-harness registry (``hermes-agent`` — see huggingface.js
970	        # ``agent-harnesses.ts``); standard-var matching is exact, so any other
971	        # value is reported as "unknown".  Setting it here (rather than only in
972	        # the host process env) is what carries the marker into REMOTE backends
973	        # (Docker/SSH/Modal/Daytona/Singularity/Vercel), whose exec env is not
974	        # inherited from the Hermes process.  ``${VAR:-default}`` semantics:
975	        # never clobber an outer harness value that arrived via the inherited
976	        # process env (Hermes running inside another agent's terminal).
977	        parts.append(
978	            'export AI_AGENT="${AI_AGENT:-hermes-agent}" '
979	            'HERMES_AGENT="${HERMES_AGENT:-true}"'
980	        )
981
982	        # Non-interactive pager defaults: git log/diff/branch and similar
983	        # pager-happy tools hang a captured (non-TTY writing to a pipe is
984	        # fine, but PTY mode IS a TTY) or PTY-backed command waiting for `q`.
985	        # GIT_PAGER=cat neutralizes git specifically; PAGER=cat catches the
986	        # long tail (man, systemctl, psql, ...). ${VAR:-default} semantics:
987	        # a user who exported their own pager in the session keeps it.
988	        parts.append(
989	            'export GIT_PAGER="${GIT_PAGER:-cat}" PAGER="${PAGER:-cat}"'
990	        )
991
992	        # Preserve bare ``~`` expansion, but rewrite ``~/...`` through
993	        # ``$HOME`` so suffixes with spaces remain a single shell word.
994	        quoted_cwd = self._quote_cwd_for_cd(cwd)
995	        # ``--`` keeps hyphen-prefixed directory names from being parsed as options.
996	        parts.append(f"builtin cd -- {quoted_cwd} || exit 126")
997
998	        # Run the actual command
999	        parts.append(f"eval '{escaped}'")
1000	        parts.append("__hermes_ec=$?")
1001	        # Restrict Hermes metadata files without changing the user's command
1002	        # umask. Snapshot files may contain env-carried secrets.
1003	        parts.append("umask 077")
1004
1005	        # Re-dump env vars to snapshot (atomic replacement to avoid races).
1006	        # Chain mv on the export succeeding so a failed/partial dump never
1007	        # replaces a good snapshot; drop the temp on failure so it isn't
1008	        # orphaned (cleaned up wholesale in LocalEnvironment.cleanup too).
1009	        # NOTE: the temp path is allocated with mktemp into a shell variable
1010	        # first — the redirection inside _export_dump_excluding_session_vars is
1011	        # attached to a brace group so the variable expands in the same shell
1012	        # that later expands the ``mv`` operand, keeping both consistent.
1013	        if self._snapshot_ready:
1014	            parts.append(
1015	                f"__hermes_snap_tmp=$(mktemp {_snap_tmp_template}) && "
1016	                f"{{ {_export_dump_excluding_session_vars(_snap_tmp, passthrough_names)} "
1017	                f"&& mv -f {_snap_tmp} {_quoted_snap}; }} "
1018	                f"2>/dev/null || rm -f {_snap_tmp} 2>/dev/null || true"
1019	            )
1020
1021	        # Emit the CWD stdout marker; all backends (including local, since
1022	        # PR #63255) parse it from output — no temp-file write needed.
1023	        # Use a distinct line for the marker. The leading \n ensures
1024	        # the marker starts on its own line even if the command doesn't
1025	        # end with a newline (e.g. printf 'exact'). We'll strip this
1026	        # injected newline in _extract_cwd_from_output.
1027	        parts.append(
1028	            f"printf '\\n{self._cwd_marker}%s{self._cwd_marker}\\n' \"$(pwd -P)\""
1029	        )
1030	        parts.append("exit $__hermes_ec")
1031
1032	        return "\n".join(parts)
1033
1034	    # ------------------------------------------------------------------
1035	    # Stdin heredoc embedding (for SDK backends)
```

**Not shown above — explore these names for their source**

- tools/environments/local.py: _wrap_command:2120
- ui-tui/packages/hermes-ink/src/native-ts/yoga-layout/enums.ts: Wrap:112, Wrap:107, Direction:23, FlexDirection:60, Justify:73, Align:1, +3 more
- apps/desktop/src/store/session-switcher.ts: wrap:16, openOrAdvanceSwitcher:60, clearRevealTimer:23, revealOverlay:30, scheduleReveal:35, pendingBrowse:18, +4 more
- scripts/ci/qualify_implementation_router.py: command:20, git:31, main:35, ROOT:17
- downstream/security/cli.py: command:354, _kick_daily_auto_update_if_due:313, _watch_enable:217, _watch_disable:262, _emit:59, _run:341
- apps/desktop/src/components/ui/command.tsx: Command:8
- ui-tui/packages/hermes-ink/src/native-ts/yoga-layout/index.ts: Style:82, setFlexWrap:681, getFlexWrap:808, Value:37, defaultStyle:109, resolveGap:2104, +4 more
- downstream/security/service.py: status:419, quick_paths:792, full_paths:818, scan_paths:671, update:823, watch_status:826, +2 more
- nix/moduleCommon.nix: command:42, command:187, mcpServersToConfig:182, args:187, env:188, url:190, +17 more
- downstream/security/vault.py: inspect:143, restore:155, delete:190
- ... and 51 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,025 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

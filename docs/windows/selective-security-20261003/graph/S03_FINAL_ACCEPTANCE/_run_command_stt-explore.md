**Exploration: _run_command_stt**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `Command` (apps/desktop/src/components/ui/command.tsx:8) — 23 callers in `plugins/platforms/discord/adapter.py`, `apps/desktop/src/app/chat/sidebar/projects/base-branch-picker.tsx`, `apps/desktop/src/app/chat/sidebar/projects/worktree-dialog.tsx`, `apps/desktop/src/app/command-palette/index.tsx` +7 more; tests: `apps/desktop/src/app/command-palette/highlight-watcher.test.tsx`
- `run` (apps/desktop/scripts/run-short-session-hang-repro.mjs:139) — 5 callers in `apps/desktop/scripts/run-short-session-hang-repro.mjs`; tested via callers: `apps/desktop/scripts/run-short-session-hang-repro.test.mjs`
- `run` (batch_runner.py:850) — 6 callers in `batch_runner.py`; tests: `tests/integration/test_checkpoint_resumption.py`, `tests/run_agent/test_callable_api_key.py`, `tests/test_batch_runner_discard_resume.py`, `tests/test_batch_runner_durability.py`
- `command` (scripts/ci/qualify_implementation_router.py:20) — 2 callers in `scripts/ci/qualify_implementation_router.py`; no tests found within 3 caller hops

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
- ... and 256 more

**references:**
- run → REPO_ROOT
- run → ALL_POSSIBLE_TOOLS
- run → _process_batch_worker
- git → ROOT
- main → ROOT
- _kick_daily_auto_update_if_due → _run
- resolveRef → REPO_ROOT
- main → REPO_ROOT
- test_lock_timeout_degrades_to_unserialized → _second

**instantiates:**
- run → Progress
- main → BatchRunner
- test_current_implementation → BatchRunner
- test_interruption_and_resume → BatchRunner
- get_nous_subscription_features → NousSubscriptionFeatures
- test_visible_providers_reuses_logged_out_feature_snapshot → NousSubscriptionFeatures
- test_visible_providers_reuses_pool_video_feature_snapshot → NousSubscriptionFeatures
- test_toolsets_resolve_subscription_features_once → NousSubscriptionFeatures
- command → SecurityService
- __init__ → _BackgroundLoop
- _run_sequential_tool_execution_middleware → _ConcurrentToolAuthorizationGate
- execute_tool_calls_concurrent → _ConcurrentToolAuthorizationGate
- _make_gate → _ConcurrentToolAuthorizationGate

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/transcription_tools.py`** — calls(calls), Thread(calls), _run_command_stt(function), references(references)

```python
707	    return [str(item).strip() for item in raw if str(item).strip()]
708
709
710	def _run_command_stt(
711	    command: str,
712	    timeout: float,
713	    env_passthrough: Optional[list] = None,
714	) -> subprocess.CompletedProcess:
715	    """Run a command-provider shell command with process-tree idle cleanup.
716
717	    Mirrors ``tools.tts_tool._run_command_tts``: ``timeout`` is an IDLE
718	    timeout, reset whenever the command emits output on stdout/stderr —
719	    a slow-but-alive provider survives, a silently stalled one is killed
720	    (same progress-based stuck detection as the TTS runner, #50081).
721	    Child env is scrubbed of Hermes secrets (salvage of #56332) while still
722	    propagating delegated-child lineage markers when applicable.
723	    """
724	    from agent.delegation_context import delegated_child_subprocess_env
725	    from tools.environments.local import hermes_subprocess_env
726
727	    scrubbed = hermes_subprocess_env(credential_keys=env_passthrough or ())
728	    popen_kwargs: Dict[str, Any] = {
729	        "shell": True,
730	        "stdout": subprocess.PIPE,
731	        "stderr": subprocess.PIPE,
732	        "text": True,
733	        # Lossy UTF-8 decode — locale-mismatched bytes from the STT command
734	        # must not raise in the reader threads on non-UTF-8 Windows (#45099).
735	        "encoding": "utf-8",
736	        "errors": "replace",
737	        "env": delegated_child_subprocess_env(scrubbed, allowed_provider_credentials=env_passthrough or ()),
738	    }
739	    if os.name == "nt":
740	        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
741	    else:
742	        popen_kwargs["start_new_session"] = True
743
744	    proc = subprocess.Popen(command, **popen_kwargs, stdin=subprocess.DEVNULL)
745	    output_queue: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
746	    chunks: Dict[str, list] = {"stdout": [], "stderr": []}
747	    open_streams = {"stdout", "stderr"}
748
749	    def read_stream(name: str, stream: Any) -> None:
750	        encoding = getattr(stream, "encoding", None) or "utf-8"
751	        read1 = getattr(getattr(stream, "buffer", None), "read1", None)
752	        try:
753	            while True:
754	                if read1 is None:
755	                    chunk = stream.read(65536)
756	                else:
757	                    data = read1(65536)
758	                    chunk = data.decode(encoding, errors="replace")
759	                if not chunk:
760	                    break
761	                output_queue.put((name, chunk))
762	        finally:
763	            output_queue.put((name, None))
764
765	    readers = [
766	        threading.Thread(
767	            target=read_stream,
768	            args=("stdout", proc.stdout),
769	            daemon=True,
770	        ),
771	        threading.Thread(
772	            target=read_stream,
773	            args=("stderr", proc.stderr),
774	            daemon=True,
775	        ),
776	    ]
777	    for reader in readers:
778	        reader.start()
779
780	    deadline = time.monotonic() + timeout
781	    timed_out = False
782	    while open_streams:
783	        remaining = deadline - time.monotonic()
784	        if remaining <= 0:
785	            timed_out = True
786	            break
787	        try:
788	            name, chunk = output_queue.get(timeout=min(0.05, remaining))
789	        except queue.Empty:
790	            continue
791	        if chunk is None:
792	            open_streams.discard(name)
793	            continue
794	        chunks[name].append(chunk)
795	        deadline = time.monotonic() + timeout
796
797	    if not timed_out:
798	        try:
799	            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
800	        except subprocess.TimeoutExpired:
801	            timed_out = True
802
803	    if timed_out:
804	        _terminate_command_stt_process_tree(proc)
805	        for reader in readers:
806	            reader.join(timeout=0.5)
807	        while True:
808	            try:
809	                name, chunk = output_queue.get_nowait()
810	            except queue.Empty:
811	                break
812	            if chunk:
813	                chunks[name].append(chunk)
814	        stdout = "".join(chunks["stdout"])
815	        stderr = "".join(chunks["stderr"])
816	        try:
817	            raise subprocess.TimeoutExpired(command, timeout)
818	        except subprocess.TimeoutExpired as exc:
819	            raise subprocess.TimeoutExpired(
820	                command,
821	                timeout,
822	                output=stdout,
823	                stderr=stderr,
824	            ) from exc
825
826	    stdout = "".join(chunks["stdout"])
827	    stderr = "".join(chunks["stderr"])
828
829	    if proc.returncode:
830	        raise subprocess.CalledProcessError(
831	            proc.returncode,
832	            command,
833	            output=stdout,
834	            stderr=stderr,
835	        )
836	    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
837
838
839	def _read_command_stt_output(output_path: Path, stdout: str, fmt: str) -> str:
```

**Not shown above — explore these names for their source**

- hermes_cli/nous_subscription.py: stt:113, items:128, NousSubscriptionFeatures:93, web:101, image_gen:105, tts:109, +4 more
- apps/desktop/scripts/run-short-session-hang-repro.mjs: run:139, resolveRef:190, readTargetMetadata:226, readJournalContract:241, prepareTarget:280, main:1556, +1 more
- agent/lsp/manager.py: run:101, _BackgroundLoop:65, __init__:147, snapshot_baseline:297, get_diagnostics_sync:321, _mark_broken_for_file:416, +5 more
- batch_runner.py: run:850, BatchRunner:569, _scan_completed_prompts_by_content:774, _filter_dataset_by_completed:816, _load_checkpoint:730, _save_checkpoint:757, +4 more
- scripts/ci/qualify_implementation_router.py: command:20, git:31, main:35, ROOT:17
- downstream/security/cli.py: command:354, _kick_daily_auto_update_if_due:313, _watch_enable:217, _watch_disable:262, _emit:59, _run:341
- agent/tool_executor.py: run:536, _ConcurrentToolAuthorizationGate:477, _authorized_dispatch:643, __init__:499, _human_wait_seconds:528, excluded_seconds:551, +2 more
- apps/desktop/src/components/ui/command.tsx: Command:8
- downstream/security/service.py: status:419, quick_paths:792, full_paths:818, scan_paths:671, update:823, watch_status:826, +2 more
- agent/relay_runtime.py: acquire:271, release:251, _ProcessRelayPluginConfiguration:260, _clear_active:410, _remember:374, _configured_plugin_inputs:1984, +1 more
- ... and 90 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,025 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

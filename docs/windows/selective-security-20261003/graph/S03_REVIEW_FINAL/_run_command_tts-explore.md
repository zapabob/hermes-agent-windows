**Exploration: _run_command_tts**

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

**`tools/tts_tool.py`** — calls(calls), Thread(calls), _run_command_tts(function), references(references)

```python
1185	    return [str(item).strip() for item in raw if str(item).strip()]
1186
1187
1188	def _run_command_tts(
1189	    command: str,
1190	    timeout: float,
1191	    env_passthrough: Optional[list] = None,
1192	) -> subprocess.CompletedProcess:
1193	    """Run a command-provider shell command with process-tree idle cleanup.
1194
1195	    Child env is scrubbed of Hermes secrets (salvage of #56332) while still
1196	    propagating delegated-child lineage markers when applicable.
1197	    """
1198	    from agent.delegation_context import delegated_child_subprocess_env
1199	    from tools.environments.local import hermes_subprocess_env
1200
1201	    scrubbed = hermes_subprocess_env(credential_keys=env_passthrough or ())
1202	    popen_kwargs: Dict[str, Any] = {
1203	        "shell": True,
1204	        "stdout": subprocess.PIPE,
1205	        "stderr": subprocess.PIPE,
1206	        "text": True,
1207	        # Lossy UTF-8 decode — locale-mismatched bytes from the TTS command
1208	        # must not raise in the reader threads on non-UTF-8 Windows (#45099).
1209	        "encoding": "utf-8",
1210	        "errors": "replace",
1211	        "env": delegated_child_subprocess_env(scrubbed, allowed_provider_credentials=env_passthrough or ()),
1212	    }
1213	    if os.name == "nt":
1214	        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
1215	    else:
1216	        popen_kwargs["start_new_session"] = True
1217
1218	    proc = subprocess.Popen(command, **popen_kwargs, stdin=subprocess.DEVNULL)
1219	    output_queue: "queue.Queue[tuple[str, Optional[str]]]" = queue.Queue()
1220	    chunks: Dict[str, list[str]] = {"stdout": [], "stderr": []}
1221	    open_streams = {"stdout", "stderr"}
1222
1223	    def read_stream(name: str, stream: Any) -> None:
1224	        encoding = getattr(stream, "encoding", None) or "utf-8"
1225	        read1 = getattr(getattr(stream, "buffer", None), "read1", None)
1226	        try:
1227	            while True:
1228	                if read1 is None:
1229	                    chunk = stream.read(65536)
1230	                else:
1231	                    data = read1(65536)
1232	                    chunk = data.decode(encoding, errors="replace")
1233	                if not chunk:
1234	                    break
1235	                output_queue.put((name, chunk))
1236	        finally:
1237	            output_queue.put((name, None))
1238
1239	    readers = [
1240	        threading.Thread(
1241	            target=read_stream,
1242	            args=("stdout", proc.stdout),
1243	            daemon=True,
1244	        ),
1245	        threading.Thread(
1246	            target=read_stream,
1247	            args=("stderr", proc.stderr),
1248	            daemon=True,
1249	        ),
1250	    ]
1251	    for reader in readers:
1252	        reader.start()
1253
1254	    deadline = time.monotonic() + timeout
1255	    timed_out = False
1256	    while open_streams:
1257	        remaining = deadline - time.monotonic()
1258	        if remaining <= 0:
1259	            timed_out = True
1260	            break
1261	        try:
1262	            name, chunk = output_queue.get(timeout=min(0.05, remaining))
1263	        except queue.Empty:
1264	            continue
1265	        if chunk is None:
1266	            open_streams.discard(name)
1267	            continue
1268	        chunks[name].append(chunk)
1269	        deadline = time.monotonic() + timeout
1270
1271	    if not timed_out:
1272	        try:
1273	            proc.wait(timeout=max(0.0, deadline - time.monotonic()))
1274	        except subprocess.TimeoutExpired:
1275	            timed_out = True
1276
1277	    if timed_out:
1278	        _terminate_command_tts_process_tree(proc)
1279	        for reader in readers:
1280	            reader.join(timeout=0.5)
1281	        while True:
1282	            try:
1283	                name, chunk = output_queue.get_nowait()
1284	            except queue.Empty:
1285	                break
1286	            if chunk:
1287	                chunks[name].append(chunk)
1288	        stdout = "".join(chunks["stdout"])
1289	        stderr = "".join(chunks["stderr"])
1290	        try:
1291	            raise subprocess.TimeoutExpired(command, timeout)
1292	        except subprocess.TimeoutExpired as exc:
1293	            raise subprocess.TimeoutExpired(
1294	                command,
1295	                timeout,
1296	                output=stdout,
1297	                stderr=stderr,
1298	            ) from exc
1299
1300	    stdout = "".join(chunks["stdout"])
1301	    stderr = "".join(chunks["stderr"])
1302
1303	    if proc.returncode:
1304	        raise subprocess.CalledProcessError(
1305	            proc.returncode,
1306	            command,
1307	            output=stdout,
1308	            stderr=stderr,
1309	        )
1310	    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
1311
1312
1313	def _configured_command_tts_output_path(path: Path, config: Dict[str, Any]) -> Path:
```

**Not shown above — explore these names for their source**

- hermes_cli/nous_subscription.py: tts:109, items:128, NousSubscriptionFeatures:93, web:101, image_gen:105, stt:113, +4 more
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

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

**Exploration: tools/environments/base.py**

Found 70 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/base.py`** — calls(calls), append(calls), _quote_shell_path(calls), _kill_process(calls), render(calls), _run_bash(calls), _wait_for_process(calls), _finalize_wait_result(calls), _quote_cwd_for_cd(calls), _snapshot_excluded_passthrough_names(calls), _export_dump_excluding_session_vars(calls), _update_cwd(calls), get_activity_callback(calls), cleanup(calls), get_temp_dir(method), +38 more

```python
673	    # snapshot semantics until they implement the same resolver contract.
674	    _profile_scoped_passthrough: bool = False
675
676	    def get_temp_dir(self) -> str:
677	        """Return the backend temp directory used for session artifacts.
678
679	        Most sandboxed backends use ``/tmp`` inside the target environment.
680	        LocalEnvironment overrides this on platforms like Termux where ``/tmp``
681	        may be missing and ``TMPDIR`` is the portable writable location.
682	        """
683	        return "/tmp"
684
685	    def __init__(self, cwd: str, timeout: int, env: dict = None):
686	        self.cwd = cwd
687	        self.timeout = timeout
688	        self.env = env or {}
689
690	        self._session_id = uuid.uuid4().hex[:12]
691	        temp_dir = self.get_temp_dir().rstrip("/") or "/"
692	        self._snapshot_path = f"{temp_dir}/hermes-snap-{self._session_id}.sh"
693	        self._cwd_file = f"{temp_dir}/hermes-cwd-{self._session_id}.txt"
694	        self._cwd_marker = _cwd_marker(self._session_id)
695	        self._snapshot_ready = False
696	        self._snapshot_passthrough_names: set[str] = set()
697	        # When True, login bash is unusable (e.g. broken Git-for-Windows
698	        # ``Directory \\drivers\\etc`` startup) so execute() must not fall
699	        # back to ``bash -l`` per command — use non-login ``bash -c`` instead.
700	        self._prefer_nonlogin = False
701
702	    # ------------------------------------------------------------------
703	    # Abstract methods
704	    # ------------------------------------------------------------------
705
706	    def _run_bash(
707	        self,
708	        cmd_string: str,
709	        *,
710	        login: bool = False,
711	        timeout: int = 120,
712	        stdin_data: str | None = None,
713	    ) -> ProcessHandle:
714	        """Spawn a bash process to run *cmd_string*.
715
716	        Returns a ProcessHandle (subprocess.Popen or _ThreadedProcessHandle).
717	        Must be overridden by every backend.
718	        """
719	        raise NotImplementedError(f"{type(self).__name__} must implement _run_bash()")
720
721	    @abstractmethod
722	    def cleanup(self):
723	        """Release backend resources (container, instance, connection)."""
724	        ...
725
726	    # ------------------------------------------------------------------
727	    # Session snapshot (init_session)
728	    # ------------------------------------------------------------------
729
730	    def _additional_profile_scoped_passthrough_names(self) -> Iterable[str]:
731	        """Return backend-specific names that must not persist in snapshots."""
732	        return ()
733
734	    def _snapshot_excluded_passthrough_names(self) -> tuple[str, ...]:
735	        """Return profile-scoped names that must not persist in the snapshot.
736
737	        The set is monotonic for the environment lifetime. A skill/config
738	        allowlist can be cleared after a value was captured; retaining the
739	        exclusion prevents that old value from becoming visible to a later
740	        profile through the shared snapshot.
741	        """
742	        if not self._profile_scoped_passthrough:
743	            return ()
744	        try:
745	            from agent.secret_scope import is_multiplex_active
746	            if is_multiplex_active():
747	                from tools.env_passthrough import get_all_passthrough
748	                names = (
749	                    *get_all_passthrough(),
750	                    *self._additional_profile_scoped_passthrough_names(),
751	                )
752	                self._snapshot_passthrough_names.update(
753	                    name
754	                    for name in names
755	                    if isinstance(name, str) and _SHELL_ENV_NAME_RE.fullmatch(name)
756	                )
757	        except Exception:
758	            logger.debug(
759	                "Could not refresh profile-scoped snapshot exclusions",
760	                exc_info=True,
761	            )
762	        return tuple(sorted(self._snapshot_passthrough_names))
763
764	    def init_session(self):
765	        """Capture login shell environment into a snapshot file.

... (gap) ...

777	        # the Git-Bash ``/c/Users/x`` form the bootstrap ``cd`` can resolve.
778	        # Without this the snapshot bootstrap ``cd`` below fails on Windows and
779	        # ``pwd -P`` captures the login shell's directory, not ``terminal.cwd``.
780	        _quoted_cwd = self._quote_cwd_for_cd(self.cwd)
781	        # Quote snapshot / cwd-file paths via ``_quote_shell_path`` so the
782	        # LocalEnvironment override can rewrite ``C:/...`` (and mixed
783	        # ``/c/Users\\...``) to ``/c/...`` before quoting — bare drive paths
784	        # in the bootstrap script trip MSYS into the
785	        # ``Directory \\drivers\\etc does not exist`` failure class.
786	        # On POSIX this is plain ``shlex.quote``.
787	        _quoted_snap = self._quote_shell_path(self._snapshot_path)
788	        # Use atomic file replacement: assemble the snapshot in a temp file,
789	        # then mv it over the final path.  This prevents concurrent source()
790	        # calls from reading a half-written snapshot when another terminal

... (gap) ...

805	        # bash versions.  The template is shell-quoted (Windows/Git-Bash drive
806	        # letters, spaces) and the resulting path lives in a shell variable so
807	        # every later expansion is consistent.
808	        _snap_tmp_template = self._quote_shell_path(self._snapshot_path + ".tmp.XXXXXXXXXX")
809	        _snap_tmp = '"$__hermes_snap_tmp"'
810	        snapshot_excluded = self._snapshot_excluded_passthrough_names()
811	        bootstrap = (
812	            f"umask 077\n"
813	            f"__hermes_snap_tmp=$(mktemp {_snap_tmp_template}) || exit 1\n"
814	            f"{_export_dump_excluding_session_vars(_snap_tmp, snapshot_excluded)}\n"
815	            # Dump function definitions, filtering out private (``_``-prefixed)
816	            # helpers — mainly bash-completion internals (``_git``, ``_make``…)
817	            # — by NAME, not by line.  A naive ``declare -f | grep -vE '^_[^_]'``

... (gap) ...

838	            f"printf '\\n{self._cwd_marker}%s{self._cwd_marker}\\n' \"$(pwd -P)\"\n"
839	        )
840	        try:
841	            proc = self._run_bash(bootstrap, login=True, timeout=self._snapshot_timeout)
842	            result = self._wait_for_process(proc, timeout=self._snapshot_timeout)
843	            if int(result.get("returncode") or 0) != 0:
844	                raise RuntimeError(
845	                    f"snapshot bootstrap failed with exit code {result.get('returncode')}"
846	                )
847	            self._snapshot_ready = True
848	            self._update_cwd(result)
849	            logger.info(
850	                "Session snapshot created (session=%s, cwd=%s)",
851	                self._session_id,
852	                self.cwd,
853	            )
854	        except Exception as exc:
855	            self._snapshot_ready = False
856	            # Default fallback is bash -l per command so PATH/nvm/etc still
857	            # load.  If login itself is dead (classic Windows Git Bash
858	            # ``Directory \\drivers\\etc does not exist``), that fallback
859	            # would brick every tool — prefer non-login bash -c instead.
860	            detail = str(exc)
861	            prefer_nonlogin = False
862	            try:
863	                probe = self._run_bash("true", login=False, timeout=min(15, self._snapshot_timeout))
864	                probe_result = self._wait_for_process(probe, timeout=min(15, self._snapshot_timeout))
865	                prefer_nonlogin = int(probe_result.get("returncode") or 0) == 0
866	                if not prefer_nonlogin:
867	                    detail = (probe_result.get("stdout") or detail).strip() or detail
868	            except Exception as probe_exc:
869	                detail = f"{detail}; non-login probe: {probe_exc}"
870
871	            self._prefer_nonlogin = prefer_nonlogin
872	            if prefer_nonlogin:
873	                logger.warning(
874	                    "init_session failed (session=%s): %s — "
875	                    "login bash unusable; falling back to non-login bash -c",
876	                    self._session_id,
877	                    exc,
878	                )
879	            else:
880	                logger.warning(
881	                    "init_session failed (session=%s): %s — "
882	                    "falling back to bash -l per command",
883	                    self._session_id,
884	                    detail,
885	                )
886
887	    # ------------------------------------------------------------------
888	    # Command wrapping
889	    # ------------------------------------------------------------------
890
891	    @staticmethod
892	    def _quote_cwd_for_cd(cwd: str) -> str:
893	        """Quote a ``cd`` target while preserving ``~`` expansion."""
894	        if cwd == "~":
895	            return cwd
896	        if cwd == "~/":
897	            return "$HOME"
898	        if cwd.startswith("~/"):
899	            return f"$HOME/{shlex.quote(cwd[2:])}"
900	        return shlex.quote(cwd)
901
902	    def _quote_shell_path(self, path: str) -> str:
903	        """Quote *path* for interpolation into a bash script.
904
905	        LocalEnvironment overrides this to rewrite native/mixed Windows
906	        paths to ``/c/...`` before quoting. Remote backends leave paths
907	        as-is (they already speak POSIX).
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

... (gap) ...

991
992	        # Preserve bare ``~`` expansion, but rewrite ``~/...`` through
993	        # ``$HOME`` so suffixes with spaces remain a single shell word.
994	        quoted_cwd = self._quote_cwd_for_cd(cwd)
995	        # ``--`` keeps hyphen-prefixed directory names from being parsed as options.
996	        parts.append(f"builtin cd -- {quoted_cwd} || exit 126")
997

... (gap) ...

1013	        if self._snapshot_ready:
1014	            parts.append(
1015	                f"__hermes_snap_tmp=$(mktemp {_snap_tmp_template}) && "
1016	                f"{{ {_export_dump_excluding_session_vars(_snap_tmp, passthrough_names)} "
1017	                f"&& mv -f {_snap_tmp} {_quoted_snap}; }} "
1018	                f"2>/dev/null || rm -f {_snap_tmp} 2>/dev/null || true"
1019	            )

... (gap) ...

1036	    # ------------------------------------------------------------------
1037
1038	    @staticmethod
1039	    def _embed_stdin_heredoc(command: str, stdin_data: str) -> str:
1040	        """Append stdin_data as a shell heredoc to the command string."""
1041	        delimiter = f"HERMES_STDIN_{uuid.uuid4().hex[:12]}"
1042	        return f"{command} << '{delimiter}'\n{stdin_data}\n{delimiter}"
1043
1044	    # ------------------------------------------------------------------
1045	    # Process lifecycle

... (gap) ...

1075	            try:
1076	                from tools.tool_output_limits import get_max_bytes
1077
1078	                capture_limit = get_max_bytes()
1079	            except Exception:
1080	                capture_limit = 50_000
1081	        else:
1082	            # Full fidelity: effectively unbounded collector (single head
1083	            # segment, no eviction) so behavior matches the historical
1084	            # accumulate-everything semantics.
1085	            capture_limit = _UNBOUNDED_CAPTURE_CHARS
1086	        spill_path = None
1087	        if bounded_capture:
1088	            # Foreground terminal path: tee overflow to a spill file so a
1089	            # truncated result is recoverable without re-running (the file
1090	            # only gets created if output actually exceeds the cap).
1091	            try:
1092	                spill_dir = get_hermes_home() / "cache" / "terminal-output"
1093	                spill_path = spill_dir / f"out-{int(time.time())}-{os.getpid()}-{id(proc) & 0xffff:x}.log"
1094	                # Opportunistic cleanup of spills older than 7 days.
1095	                if spill_dir.is_dir():
1096	                    cutoff = time.time() - 7 * 86400
1097	                    for old in spill_dir.glob("out-*.log"):
1098	                        try:
1099	                            if old.stat().st_mtime < cutoff:
1100	                                old.unlink()
1101	                        except OSError:
1102	                            pass
1103	            except Exception:
1104	                spill_path = None
1105	        output = _BoundedOutputCollector(capture_limit, spill_path=spill_path)
1106
1107	        # Non-blocking drain via select().
1108	        #

... (gap) ...

1130	        # U+FFFD substitution rather than clobbering the whole buffer.
1131	        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
1132
1133	        def _drain_iterable(stream):
1134	            # Fallback path: ``stream`` is not backed by a real OS file
1135	            # descriptor (no usable ``fileno()``).  This covers in-memory
1136	            # ProcessHandle adapters that expose stdout as a plain iterator of
1137	            # already-collected output (the legacy ``for line in proc.stdout``
1138	            # contract) rather than a live pipe.  Iterate it to EOF.  Without
1139	            # this, the drain thread would raise an unhandled exception and die
1140	            # silently, losing all of the process's output.
1141	            try:
1142	                for piece in stream:
1143	                    if piece is None:
1144	                        continue
1145	                    if isinstance(piece, bytes):
1146	                        output.append(decoder.decode(piece))
1147	                    else:
1148	                        output.append(str(piece))
1149	            except Exception:
1150	                pass
1151	            finally:
1152	                try:
1153	                    tail = decoder.decode(b"", final=True)
1154	                    if tail:
1155	                        output.append(tail)
1156	                except Exception:
1157	                    pass
1158
1159	        def _drain():
1160	            # Resolve a real OS file descriptor up front.  Real subprocesses and
1161	            # the SDK ``_ThreadedProcessHandle`` (os.pipe-backed) both return an
1162	            # integer fd here.  Mocks / iterator-style stdout streams either lack
1163	            # ``fileno()`` entirely or return a non-integer — in that case fall
1164	            # back to draining the stream as an iterable instead of crashing the
1165	            # thread (issue: 'list_iterator' object has no attribute 'fileno').
1166	            stream = proc.stdout
1167	            if stream is None:
1168	                return
1169	            fileno = getattr(stream, "fileno", None)
1170	            try:
1171	                fd = fileno() if callable(fileno) else None
1172	            except Exception:
1173	                fd = None
1174	            if not isinstance(fd, int) or fd < 0:
1175	                _drain_iterable(stream)
1176	                return
1177	            # select.select does NOT work on pipe fds on Windows (only sockets).
1178	            # Use blocking os.read in a daemon thread instead — safe because
1179	            # EOF arrives promptly when bash exits.
1180	            if os.name == "nt":
1181	                try:
1182	                    while True:
1183	                        chunk = os.read(fd, 4096)
1184	                        if not chunk:
1185	                            break
1186	                        output.append(decoder.decode(chunk))
1187	                except (ValueError, OSError):
1188	                    pass
1189	                finally:
1190	                    try:
1191	                        tail = decoder.decode(b"", final=True)
1192	                        if tail:
1193	                            output.append(tail)
1194	                    except Exception:
1195	                        pass
1196	                return
1197	            idle_after_exit = 0
1198	            try:
1199	                while True:
1200	                    try:
1201	                        ready, _, _ = select.select([fd], [], [], 0.1)
1202	                    except (ValueError, OSError):
1203	                        break  # fd already closed
1204	                    if ready:
1205	                        try:
1206	                            chunk = os.read(fd, 4096)
1207	                        except (ValueError, OSError):
1208	                            break
1209	                        if not chunk:
1210	                            break  # true EOF — all writers closed
1211	                        output.append(decoder.decode(chunk))
1212	                        idle_after_exit = 0
1213	                    elif proc.poll() is not None:
1214	                        # bash is gone and the pipe was idle for ~100ms.  Give
1215	                        # it two more cycles to catch any buffered tail, then
1216	                        # stop — otherwise we wait forever on a grandchild pipe.
1217	                        idle_after_exit += 1
1218	                        if idle_after_exit >= 3:
1219	                            break
1220	            finally:
1221	                # Flush any bytes buffered mid-sequence.  With ``errors="replace"``
1222	                # this emits U+FFFD for any final incomplete sequence rather than
1223	                # raising.
1224	                try:
1225	                    tail = decoder.decode(b"", final=True)
1226	                    if tail:
1227	                        output.append(tail)
1228	                except Exception:
1229	                    pass
1230
1231	        drain_thread = threading.Thread(target=_drain, daemon=True)
1232	        drain_thread.start()
1233	        deadline = time.monotonic() + timeout
1234	        _now = time.monotonic()
1235	        _activity_state = {
1236	            "last_touch": _now,
1237	            "start": _now,
1238	        }
1239
1240	        # --- Debug tracing (opt-in via HERMES_DEBUG_INTERRUPT=1) -------------
1241	        # Captures loop entry/exit, interrupt state changes, and periodic
1242	        # heartbeats so we can diagnose "agent never sees the interrupt"
1243	        # reports without reproducing locally.
1244	        _tid = threading.current_thread().ident
1245	        _pid = getattr(proc, "pid", None)
1246	        _iter_count = 0
1247	        _last_heartbeat = _now
1248	        _last_interrupt_state = False
1249	        _cb_was_none = get_activity_callback() is None
1250	        if _DEBUG_INTERRUPT:
1251	            logger.info(
1252	                "[interrupt-debug] _wait_for_process ENTER tid=%s pid=%s "
1253	                "timeout=%ss activity_cb=%s initial_interrupt=%s",
1254	                _tid, _pid, timeout,
1255	                "set" if not _cb_was_none else "MISSING",
1256	                is_interrupted(),
1257	            )
1258
1259	        try:
1260	            _poll_sleep = 0.005
1261	            while proc.poll() is None:
1262	                _iter_count += 1
1263	                if is_interrupted():
1264	                    if _DEBUG_INTERRUPT:
1265	                        logger.info(
1266	                            "[interrupt-debug] _wait_for_process INTERRUPT DETECTED "
1267	                            "tid=%s pid=%s iter=%d elapsed=%.1fs — killing process group",
1268	                            _tid, _pid, _iter_count, time.monotonic() - _activity_state["start"],
1269	                        )
1270	                    self._kill_process(proc)
1271	                    drain_thread.join(timeout=2)
1272	                    return self._finalize_wait_result(
1273	                        output,
1274	                        output.render(suffix="\n[Command interrupted]"),
1275	                        130,
1276	                    )
1277	                if time.monotonic() > deadline:
1278	                    if _DEBUG_INTERRUPT:
1279	                        logger.info(
1280	                            "[interrupt-debug] _wait_for_process TIMEOUT "
1281	                            "tid=%s pid=%s iter=%d timeout=%ss",
1282	                            _tid, _pid, _iter_count, timeout,
1283	                        )
1284	                    self._kill_process(proc)
1285	                    drain_thread.join(timeout=2)
1286	                    timeout_msg = f"\n[Command timed out after {timeout}s]"
1287	                    return self._finalize_wait_result(
1288	                        output,
1289	                        output.render(suffix=timeout_msg).lstrip()
1290	                        if output.total_chars == 0
1291	                        else output.render(suffix=timeout_msg),
1292	                        124,
1293	                    )
1294	                # Periodic activity touch so the gateway knows we're alive
1295	                touch_activity_if_due(_activity_state, "terminal command running")
1296
1297	                # Heartbeat every ~30s: proves the loop is alive and reports
1298	                # the activity-callback state (thread-local, can get clobbered
1299	                # by nested tool calls or executor thread reuse).
1300	                if _DEBUG_INTERRUPT and time.monotonic() - _last_heartbeat >= 30.0:
1301	                    _cb_now_none = get_activity_callback() is None
1302	                    logger.info(
1303	                        "[interrupt-debug] _wait_for_process HEARTBEAT "
1304	                        "tid=%s pid=%s iter=%d elapsed=%.0fs "
1305	                        "interrupt=%s activity_cb=%s%s",
1306	                        _tid, _pid, _iter_count,
1307	                        time.monotonic() - _activity_state["start"],
1308	                        is_interrupted(),
1309	                        "set" if not _cb_now_none else "MISSING",
1310	                        " (LOST during run)" if _cb_now_none and not _cb_was_none else "",
1311	                    )
1312	                    _last_heartbeat = time.monotonic()
1313	                    _cb_was_none = _cb_now_none
1314
1315	                # Adaptive poll: start at 5ms so fast commands (echo, pwd,
```

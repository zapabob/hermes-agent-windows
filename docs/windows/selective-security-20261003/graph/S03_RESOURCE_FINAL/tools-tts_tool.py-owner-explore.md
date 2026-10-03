**Exploration: tools/tts_tool.py**

Found 191 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/tts_tool.py`** — calls(calls), _resolve_provider_key(calls), _load_tts_config(calls), _get_command_tts_output_format(calls), _resolve_max_text_length(calls), _get_provider(calls), _check_neutts_available(calls), _get_provider_section(calls), _is_command_provider_config(calls), _import_edge_tts(calls), _import_elevenlabs(calls), _import_openai_client(calls), _import_mistral_client(calls), _resolve_command_provider_config(calls), _convert_to_opus(calls), +206 more

```python
60	from hermes_cli._subprocess_compat import windows_hide_flags
61	from hermes_constants import display_hermes_home
62
63	logger = logging.getLogger(__name__)
64	def get_env_value(name, default=None):
65	    """Read env values through the live config module.
66
67	    Tests may monkeypatch and later restore ``hermes_cli.config.get_env_value``
68	    before this module is imported. Resolve the helper at call time so TTS does
69	    not keep a stale imported function for the rest of the test process.
70	    """
71	    try:
72	        from hermes_cli.config import get_env_value as _get_env_value
73	    except ImportError:
74	        return os.getenv(name, default)
75	    value = _get_env_value(name)
76	    return default if value is None else value
77
78
79	def _resolve_provider_key(env_var: str, provider_id: str) -> str:
80	    """Resolve a TTS provider API key via the shared voice-key resolver.
81
82	    Delegates to ``tools.tool_backend_helpers.resolve_provider_secret`` —
83	    the single owner of STT/TTS key resolution (config > env/.env > the
84	    credential pool populated by ``hermes auth add <provider_id>``).
85	    Resolved at call time so tests that reload the helpers module see the
86	    live function.
87	    """
88	    try:
89	        from tools.tool_backend_helpers import resolve_provider_secret
90	    except ImportError:  # pragma: no cover — helpers are in-repo
91	        return str(get_env_value(env_var) or "").strip()
92	    return resolve_provider_secret(env_var, provider_id, env_getter=get_env_value)
93
94	from tools.managed_tool_gateway import resolve_managed_tool_gateway
95	from tools.tool_backend_helpers import (

... (gap) ...

829	    falls back to ``tts.<name>`` so users who followed the built-in layout
830	    still work. Returns an empty dict when the provider is not declared.
831	    """
832	    providers = _get_provider_section(tts_config, "providers")
833	    section = providers.get(name) if isinstance(providers, dict) else None
834	    if isinstance(section, dict):
835	        return section
836	    # Back-compat: allow ``tts.<name>`` for user-declared providers too,
837	    # but only when the name is not a built-in (so a user's ``tts.openai``
838	    # block still means the OpenAI provider, not a custom command).
839	    if name.lower() not in BUILTIN_TTS_PROVIDERS:
840	        legacy = _get_provider_section(tts_config, name)
841	        if legacy:
842	            return legacy
843	    return {}
844
845
846	def _is_command_provider_config(config: Dict[str, Any]) -> bool:
847	    """Return True when *config* declares a command-type provider."""
848	    if not isinstance(config, dict):
849	        return False
850	    ptype = str(config.get("type") or "").strip().lower()
851	    if ptype and ptype != "command":
852	        return False
853	    command = config.get("command")

... (gap) ...

866	    """
867	    if not provider:
868	        return None
869	    key = provider.lower().strip()
870	    if key in BUILTIN_TTS_PROVIDERS:
871	        return None
872	    config = _get_named_provider_config(tts_config, key)
873	    if _is_command_provider_config(config):
874	        return config
875	    return None
876

... (gap) ...

908	    """
909	    if not provider:
910	        return None
911	    key = provider.lower().strip()
912	    if key in BUILTIN_TTS_PROVIDERS:
913	        return None
914	    # Defense in depth: command-provider check should already have
915	    # short-circuited the caller. If a same-name command config exists,
916	    # bail so the command path wins.
917	    if _is_command_provider_config(_get_named_provider_config(tts_config, key)):
918	        return None
919	    try:
920	        from agent.tts_registry import get_provider
921	        from hermes_cli.plugins import _ensure_plugins_discovered
922
923	        _ensure_plugins_discovered()
924	        plugin_provider = get_provider(key)
925	        if plugin_provider is None:
926	            # Long-lived sessions may have discovered plugins before the
927	            # bundled backend was patched in or before config changed.
928	            # Retry once with a forced refresh before surfacing fall-
929	            # through. Mirrors the image_gen / browser dispatcher
930	            # recovery pattern.
931	            _ensure_plugins_discovered(force=True)
932	            plugin_provider = get_provider(key)
933	    except Exception as exc:  # noqa: BLE001 — discovery failure is non-fatal
934	        logger.debug("tts plugin dispatch skipped (discovery failed): %s", exc)
935	        return None

... (gap) ...

952	    logger.info(
953	        "Generating speech with plugin TTS provider '%s'...", key,
954	    )
955	    written = plugin_provider.synthesize(
956	        text,
957	        output_path,
958	        voice=voice if isinstance(voice, str) and voice else None,

... (gap) ...

975	    """
976	    if not provider:
977	        return False
978	    key = provider.lower().strip()
979	    if key in BUILTIN_TTS_PROVIDERS:
980	        return False
981	    try:
982	        from agent.tts_registry import get_provider
983
984	        plugin_provider = get_provider(key)
985	        if plugin_provider is None:
986	            return False
987	        return bool(plugin_provider.voice_compatible)
988	    except Exception as exc:  # noqa: BLE001
989	        logger.debug(
990	            "tts plugin voice_compatible check failed for '%s': %s", key, exc,
991	        )
992	        return False
993
994
995	def _iter_command_providers(tts_config: Dict[str, Any]):
996	    """Yield (name, config) pairs for every declared command-type provider."""
997	    if not isinstance(tts_config, dict):
998	        return
999	    providers = _get_provider_section(tts_config, "providers")
1000	    for name, cfg in (providers or {}).items():
1001	        if isinstance(name, str) and name.lower() not in BUILTIN_TTS_PROVIDERS:
1002	            if _is_command_provider_config(cfg):
1003	                yield name, cfg
1004
1005

... (gap) ...

1021	) -> str:
1022	    """Return the validated output format (mp3/wav/ogg/flac)."""
1023	    if output_path:
1024	        suffix = Path(output_path).suffix.lower().strip().lstrip(".")
1025	        if suffix in COMMAND_TTS_OUTPUT_FORMATS:
1026	            return suffix
1027	    raw = (
1028	        config.get("format")
1029	        or config.get("output_format")
1030	        or DEFAULT_COMMAND_TTS_OUTPUT_FORMAT
1031	    )
1032	    fmt = str(raw).lower().strip().lstrip(".")
1033	    return fmt if fmt in COMMAND_TTS_OUTPUT_FORMATS else DEFAULT_COMMAND_TTS_OUTPUT_FORMAT
1034
1035

... (gap) ...

1075	def _quote_command_tts_placeholder(value: str, quote_context: Optional[str]) -> str:
1076	    """Quote a placeholder value for its position in a shell command template."""
1077	    if quote_context == "'":
1078	        return value.replace("'", r"'\''")
1079	    if quote_context == '"':
1080	        return (
1081	            value
1082	            .replace("\\", "\\\\")
1083	            .replace('"', r'\"')
1084	            .replace("$", r"\$")

... (gap) ...

1095	) -> str:
1096	    """Replace supported placeholders while preserving ``{{`` / ``}}``."""
1097	    names = "|".join(re.escape(name) for name in placeholders)
1098	    pattern = re.compile(
1099	        rf"(?<!\$)(?:\{{\{{(?P<double>{names})\}}\}}|\{{(?P<single>{names})\}})"
1100	    )
1101	    replacements: list[tuple[str, str]] = []
1102
1103	    def replace_match(match: re.Match[str]) -> str:
1104	        name = match.group("double") or match.group("single")
1105	        token = f"__HERMES_TTS_PLACEHOLDER_{len(replacements)}__"
1106	        replacements.append((
1107	            token,
1108	            _quote_command_tts_placeholder(
1109	                placeholders[name],
1110	                _shell_quote_context(command_template, match.start()),
1111	            ),
1112	        ))
1113	        return token
1114
1115	    rendered = pattern.sub(replace_match, command_template)
1116	    rendered = rendered.replace("{{", "{").replace("}}", "}")
1117	    for token, value in replacements:
1118	        rendered = rendered.replace(token, value)
1119	    return rendered
1120
1121
1122	def _terminate_command_tts_process_tree(proc: subprocess.Popen) -> None:
1123	    """Best-effort termination of a shell process and all of its children."""
1124	    if proc.poll() is not None:
1125	        return
1126
1127	    if os.name == "nt":
1128	        try:
1129	            subprocess.run(
1130	                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
1131	                stdout=subprocess.DEVNULL,
1132	                stderr=subprocess.DEVNULL,
1133	                timeout=5,
1134	                stdin=subprocess.DEVNULL,
1135	            )
1136	        except Exception:
1137	            proc.kill()
1138	        return
1139
1140	    import psutil
1141	    try:
1142	        parent = psutil.Process(proc.pid)
1143	        for child in parent.children(recursive=True):
1144	            try:
1145	                child.terminate()
1146	            except psutil.NoSuchProcess:
1147	                pass
1148	        parent.terminate()
1149	    except psutil.NoSuchProcess:
1150	        return
1151	    except Exception:
1152	        proc.terminate()
1153
1154	    try:
1155	        proc.wait(timeout=2)
1156	        return
1157	    except subprocess.TimeoutExpired:
1158	        pass
1159
1160	    try:
1161	        parent = psutil.Process(proc.pid)
1162	        for child in parent.children(recursive=True):
1163	            try:
1164	                child.kill()
1165	            except psutil.NoSuchProcess:
1166	                pass
1167	        parent.kill()
1168	    except psutil.NoSuchProcess:
1169	        return
1170	    except Exception:
1171	        proc.kill()
1172
1173
1174	def _command_provider_env_passthrough(config: Dict[str, Any]) -> list:
1175	    """Return the provider's ``env_passthrough`` allowlist (opt-out of scrub).
1176
1177	    Command providers legitimately reference their own API keys in the shell
1178	    template (curl one-liners). The child env is scrubbed of Hermes secrets by
1179	    default; ``env_passthrough: [MY_API_KEY, ...]`` copies the named variables
1180	    back from the parent environment so a trusted template keeps working.
1181	    """
1182	    raw = config.get("env_passthrough")
1183	    if not isinstance(raw, (list, tuple)):
1184	        return []
1185	    return [str(item).strip() for item in raw if str(item).strip()]
1186
1187
1188	def _run_command_tts(

... (gap) ...

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

... (gap) ...

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

... (gap) ...

1312
1313	def _configured_command_tts_output_path(path: Path, config: Dict[str, Any]) -> Path:
1314	    """Return an output path whose extension matches the provider's output_format."""
1315	    fmt = _get_command_tts_output_format(config)
1316	    return path.with_suffix(f".{fmt}")
1317
1318

... (gap) ...

1329	    Raises ``ValueError`` when the provider config is invalid, and
1330	    ``RuntimeError`` for timeouts / non-zero exits / empty output.
1331	    """
1332	    command_template = str(config.get("command") or "").strip()
1333	    if not command_template:
1334	        raise ValueError(
1335	            f"tts.providers.{provider_name}.command is not configured"
1336	        )
1337
1338	    output = Path(output_path).expanduser()
1339	    output.parent.mkdir(parents=True, exist_ok=True)
1340	    if output.exists():
1341	        output.unlink()
1342
1343	    timeout = _get_command_tts_timeout(config)
1344	    output_format = _get_command_tts_output_format(config, str(output))
1345	    speed = config.get("speed", tts_config.get("speed", ""))
1346
1347	    with tempfile.TemporaryDirectory() as tmpdir:
1348	        text_path = Path(tmpdir) / "input.txt"
1349	        text_path.write_text(text, encoding="utf-8")
1350
1351	        placeholders = {
1352	            "input_path": str(text_path),
1353	            "text_path": str(text_path),
1354	            "output_path": str(output),
1355	            "format": output_format,
1356	            "voice": str(config.get("voice", "")),
1357	            "model": str(config.get("model", "")),
1358	            "speed": str(speed),
1359	        }
1360	        command = _render_command_tts_template(command_template, placeholders)
1361
1362	        try:
1363	            _run_command_tts(
1364	                command,
1365	                timeout,
1366	                env_passthrough=_command_provider_env_passthrough(config),
1367	            )
1368	        except subprocess.TimeoutExpired as exc:
1369	            raise RuntimeError(
1370	                f"TTS provider '{provider_name}' timed out after {timeout:g}s"
1371	            ) from exc
1372	        except subprocess.CalledProcessError as exc:
1373	            detail_parts = []
1374	            if exc.stderr:
1375	                detail_parts.append(f"stderr: {exc.stderr.strip()}")
1376	            if exc.stdout:
1377	                detail_parts.append(f"stdout: {exc.stdout.strip()}")
1378	            detail = "; ".join(detail_parts) or "no command output"
1379	            raise RuntimeError(
1380	                f"TTS provider '{provider_name}' exited with code "

... (gap) ...

1391	def _has_any_command_tts_provider(tts_config: Optional[Dict[str, Any]] = None) -> bool:
1392	    """Return True when any command-type TTS provider is configured."""
1393	    if tts_config is None:
1394	        tts_config = _load_tts_config()
1395	    for _name, _cfg in _iter_command_providers(tts_config):
1396	        return True
1397	    return False
1398
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,021 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

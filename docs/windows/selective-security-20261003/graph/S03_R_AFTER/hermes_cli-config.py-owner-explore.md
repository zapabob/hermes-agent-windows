**Exploration: hermes_cli/config.py**

Found 257 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/config.py`** — calls(calls), get_env_value(calls), get_config_path(calls), _issue(calls), _section(calls), _model_assignment_text(calls), _split_key_path(calls), load_config(calls), read_raw_config(calls), get_env_path(calls), _exit_invalid(calls), _expand_env_vars(calls), _warn_config_parse_failure(calls), load_env(calls), is_managed(calls), +330 more

```python
730	        {"name": var_name, **info, "is_required": is_required}
731	        for table, is_required in groups
732	        for var_name, info in table.items()
733	        if not get_env_value(var_name)]
734
735
736	def _split_key_path(key: str) -> list[str]:

... (gap) ...

773	    """
774	    if not isinstance(container, dict) or not parts:
775	        return None
776	    return next(
777	        ((".".join(parts[:n]), n) for n in range(len(parts), 0, -1) if ".".join(parts[:n]) in container),
778	        None)
779
780
781	def _phantom_sibling(container: dict, part: str) -> Optional[str]:
782	    """Existing literal dotted key that creating an intermediate mapping ``part`` would shadow
783	    (``grok-4`` beside ``grok-4.5``) — the write would produce a phantom sibling the runtime never
784	    reads, so callers fail loudly instead.
785
786	    Called when a write is about to CREATE a new intermediate mapping named ``part``. See #84064.
787	    """
788	    if not isinstance(container, dict):
789	        return None
790	    prefix = part + "."
791	    return next((k for k in container if isinstance(k, str) and k.startswith(prefix)), None)
792
793
794	def _set_nested(config, dotted_key: str, value):

... (gap) ...

804	    create a new intermediate mapping that shadows an existing dotted sibling (``grok-4`` beside
805	    ``grok-4.5``), it raises ``ValueError`` instead of silently writing a phantom the runtime never reads.
806	    """
807	    parts = _split_key_path(dotted_key)
808	    current = config
809	    i = 0
810	    while i < len(parts):

... (gap) ...

823	                    f"segment {part!r} is not a numeric index")
824	            i += 1
825	        elif isinstance(current, dict):
826	            match = _greedy_literal_match(current, remaining)
827	            if match is not None:
828	                key, consumed = match
829	                if i + consumed == len(parts):

... (gap) ...

839	            if at_leaf:
840	                current[part] = value
841	                return
842	            shadowed = _phantom_sibling(current, part)
843	            if shadowed is not None:
844	                escaped = shadowed.replace(".", "\\.")
845	                raise ValueError(

... (gap) ...

892	                return None
893	            consumed = 1
894	        elif isinstance(current, dict):
895	            match = _greedy_literal_match(current, remaining)
896	            if match is None:
897	                return None
898	            key, consumed = match

... (gap) ...

913	    dotted key over blind splitting, so ``config get providers.p.models.grok-4.6.context_length`` reads the
914	    real ``grok-4.6`` entry instead of reporting the key unset (#84064).
915	    """
916	    loc = _locate_nested(config, _split_key_path(dotted_key))
917	    if loc is None:
918	        return _MISSING
919	    _, container, key = loc
920	    return container[key]
921
922
923	def _unset_nested(config, dotted_key: str) -> bool:
924	    """Remove a dotted-path value; True if it existed. Empty dict containers left behind are
925	    dropped, while user-authored empty lists and non-empty sibling branches are preserved.
926
927	    Same escape-aware, greedy-literal navigation as ``_set_nested`` / ``_get_nested`` (#84064): unsetting an
928	    unescaped dotted key removes the real literal entry rather than a phantom sibling.
929	    """
930	    loc = _locate_nested(config, _split_key_path(dotted_key))
931	    if loc is None:
932	        return False
933	    parents, current, key = loc

... (gap) ...

990	                missing.append({"key": full_key, "default": default_value,
991	                                "description": f"New config option: {full_key}"})
992	            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
993	                _check(default_value, current[key], full_key)
994
995	    _check(DEFAULT_CONFIG, load_config())
996	    return missing
997
998
999	def get_missing_skill_config_vars() -> List[Dict[str, Any]]:
1000	    """Return skill-declared config vars (``skills.config.<key>``) that are missing or empty."""
1001	    try:
1002	        from agent.skill_utils import discover_all_skill_config_vars, SKILL_CONFIG_PREFIX
1003	    except Exception:
1004	        return []
1005
1006	    try:
1007	        all_vars = discover_all_skill_config_vars()
1008	    except Exception as e:
1009	        # A malformed SKILL.md must never break `hermes update`; this prompting is a nicety.
1010	        logger.debug("discover_all_skill_config_vars failed: %s", e)
1011	        return []
1012	    if not all_vars:
1013	        return []
1014
1015	    config = load_config()
1016	    values = ((var, cfg_get(config, *f"{SKILL_CONFIG_PREFIX}.{var['key']}".split("."))) for var in all_vars)
1017	    return [var for var, v in values if v is None or (isinstance(v, str) and not v.strip())]
1018
1019
1020	def _coerce_config_version(value: Any) -> int:
1021	    """Return a safe integer config version, treating invalid values as legacy."""
1022	    if isinstance(value, bool):
1023	        return 0
1024	    try:
1025	        version = int(value)
1026	    except (TypeError, ValueError):
1027	        return 0
1028	    return max(version, 0)
1029
1030
1031	def check_config_version(*, raise_on_parse_error: bool = False) -> Tuple[int, int]:
1032	    """Return ``(current_version, latest_version)`` from the raw on-disk config.
1033	    Reads the raw file rather than ``load_config()``: the deep-merge would make a file lacking
1034	    ``_config_version`` inherit the latest version, hiding that the schema was never migrated.
1035	    Invalid YAML gets a parse warning, not an automatic schema rewrite. Tolerant runtime status
1036	    callers keep the historical latest/latest fallback for malformed YAML; mutation and explicit
1037	    validation paths set ``raise_on_parse_error`` so a parse failure or a non-mapping root cannot
1038	    be mistaken for an up-to-date config."""
1039	    latest = _coerce_config_version(DEFAULT_CONFIG.get("_config_version", 1)) or 1
1040	    config_path = get_config_path()
1041	    if not config_path.exists():
1042	        return latest, latest
1043
1044	    try:
1045	        with open(config_path, encoding="utf-8") as f:
1046	            config = fast_safe_load(f)
1047	    except Exception as e:
1048	        _warn_config_parse_failure(config_path, e)
1049	        if raise_on_parse_error:
1050	            raise InvalidUserConfigError(
1051	                f"Cannot inspect {config_path}: config.yaml is not valid YAML ({e})"
1052	            ) from e
1053	        return latest, latest
1054
1055	    if config is None:
1056	        config = {}  # empty file / bare document: valid first-run state
1057	    if not isinstance(config, dict):
1058	        # A list/scalar root parses fine but is just as unusable as broken YAML: save_config()
1059	        # would refuse it later, after .env was already rewritten. Strict callers see it up front.
1060	        if raise_on_parse_error:
1061	            raise InvalidUserConfigError(
1062	                f"Cannot inspect {config_path}: config.yaml top-level value must be "
1063	                f"a mapping, got {type(config).__name__}"
1064	            )
1065	        config = {}
1066	    return _coerce_config_version(config.get("_config_version")), latest
1067
1068
1069	# ---- Config structure validation ----

... (gap) ...

1112
1113
1114	def _issue(issues: List["ConfigIssue"], severity: str, message: str, hint: str) -> None:
1115	    issues.append(ConfigIssue(severity, message, hint))
1116
1117
1118	def _require_fields(
1119	    issues: List["ConfigIssue"], entry: Dict[str, Any], label: str,
1120	    fields: Tuple[Tuple[str, str], ...], suffix: str = "") -> None:
1121	    """Append a warning for every falsy ``field`` of *entry* (message: ``<label> is missing '<f>' field``)."""
1122	    for field, hint in fields:
1123	        if not entry.get(field):
1124	            _issue(issues, "warning", f"{label} is missing '{field}' field{suffix}", hint)
1125
1126
1127	_CP_REQUIRED_FIELDS = (

... (gap) ...

1142	    submit_mode = voice_cfg.get("submit_mode")
1143	    normalized = submit_mode.strip().lower() if isinstance(submit_mode, str) else None
1144	    if normalized not in {"direct", "draft"}:
1145	        _issue(issues, "error", f"voice.submit_mode must be 'direct' or 'draft', got {submit_mode!r}",
1146	               "Set voice.submit_mode to direct (submit immediately) or draft (edit before sending)")
1147
1148
1149	def _validate_entry_list(
1150	    entries: list, label: str, issues: List[ConfigIssue], fields, *, non_dict: Tuple[str, str, str],
1151	) -> None:
1152	    """Validate each list entry: ``non_dict`` = (severity, message-with-{i}-and-{type}, hint) for
1153	    non-dict items; dict items get ``_require_fields`` with *fields*."""
1154	    severity, message, hint = non_dict
1155	    for i, entry in enumerate(entries):
1156	        if not isinstance(entry, dict):
1157	            _issue(issues, severity, message.format(i=i, type=type(entry).__name__), hint)
1158	        else:
1159	            _require_fields(issues, entry, f"{label}[{i}]", fields)
1160
1161
1162	def _validate_custom_providers(cp: Any, issues: List[ConfigIssue]) -> None:
1163	    """custom_providers must be a list of dicts, not a dict."""
1164	    if isinstance(cp, dict):
1165	        _issue(issues, "error",
1166	               "custom_providers is a dict — it must be a YAML list (items prefixed with '-')",
1167	               "Change to:\n  custom_providers:\n    - name: my-provider\n      base_url: https://...\n"
1168	               "      api_key: ...")
1169	        suspicious = set(cp.keys()) & _CUSTOM_PROVIDER_LIKE_FIELDS
1170	        if suspicious:
1171	            _issue(issues, "warning",
1172	                   f"Root-level keys {sorted(suspicious)} look like custom_providers entry fields",
1173	                   "These should be indented under a '- name: ...' list entry, not at root level")
1174	    elif isinstance(cp, list):
1175	        _validate_entry_list(cp, "custom_providers", issues, _CP_REQUIRED_FIELDS, non_dict=(
1176	            "warning", "custom_providers[{i}] is not a dict (got {type})",
1177	            "Each entry should have at minimum: name, base_url"))
1178
1179
1180	def _validate_fallback_model(fb: Any, issues: List[ConfigIssue]) -> None:
1181	    """fallback_model: single dict OR list of dicts (chain)."""
1182	    if isinstance(fb, list):
1183	        _validate_entry_list(fb, "fallback_model", issues, _FB_REQUIRED_FIELDS, non_dict=(
1184	            "error", "fallback_model[{i}] should be a dict, got {type}", "Each entry needs provider + model"))
1185	    elif not isinstance(fb, dict):
1186	        _issue(issues, "error",
1187	               f"fallback_model should be a dict with 'provider' and 'model', got {type(fb).__name__}",
1188	               "Change to:\n  fallback_model:\n    provider: openrouter\n    model: anthropic/claude-sonnet-4")
1189	    elif fb:
1190	        _require_fields(issues, fb, "fallback_model", _FB_SINGLE_REQUIRED_FIELDS,
1191	                        suffix=" — fallback will be disabled")
1192
1193

... (gap) ...

1204	        return
1205	    seen: set = set()
1206	    for _key in ("backend", "search_backend", "extract_backend"):
1207	        _val = str(web_cfg.get(_key) or "").strip().lower()
1208	        if not _val or _val in seen:
1209	            continue
1210	        seen.add(_val)
1211	        note = removed_backend_note("web", _val)
1212	        if note:
1213	            _issue(issues, "warning",
1214	                   f"web.{_key} is set to '{_val}', but {note} — "
1215	                   "web_search/web_extract will fail until it is changed",
1216	                   "Run 'hermes tools' and pick a different Web Search & Extract provider")
1217
1218
1219	def validate_config_structure(config: Optional[Dict[str, Any]] = None) -> List["ConfigIssue"]:
1220	    """Validate config.yaml structure and return detected issues (accepts a pre-loaded dict).
1221	    Catches common YAML mistakes that otherwise surface as confusing runtime errors."""
1222	    if config is None:
1223	        try:
1224	            config = load_config()
1225	        except Exception:
1226	            return [ConfigIssue("error", "Could not load config.yaml", "Run 'hermes setup' to create a valid config")]
1227
1228	    issues: List[ConfigIssue] = []
1229	    _validate_voice(config, issues)
1230	    cp = config.get("custom_providers")
1231	    fb = config.get("fallback_model")
1232	    for value, validator in ((cp, _validate_custom_providers), (fb, _validate_fallback_model)):
1233	        if value is not None:
1234	            validator(value, issues)
1235
1236	    if isinstance(cp, dict) and "fallback_model" not in config and "fallback_model" in (cp or {}):
1237	        _issue(issues, "error", "fallback_model appears inside custom_providers instead of at root level",
1238	               "Move fallback_model to the top level of config.yaml (no indentation)")
1239
1240	    if cp and not config.get("model"):
1241	        _issue(issues, "warning",
1242	               "custom_providers defined but no 'model' section — Hermes won't know which provider to use",
1243	               "Add a model section:\n  model:\n    provider: custom\n    default: your-model-name\n"
1244	               "    base_url: https://...")
1245
1246	    # Only provider-like fields are flagged as misplaced roots. Arbitrary unknown top-level keys
1247	    # are deliberately NOT warned about: top-level scalars are bridged into os.environ so users
1248	    # can feed skills/external apps env-style keys — a closed-world allowlist cannot enumerate those.
1249	    for key in config:
1250	        if not key.startswith("_") and key not in _KNOWN_ROOT_KEYS and key in _CUSTOM_PROVIDER_LIKE_FIELDS:
1251	            _issue(issues, "warning",
1252	                   f"Root-level key '{key}' looks misplaced — should it be under 'model:' or inside a 'custom_providers' entry?",
1253	                   f"Move '{key}' under the appropriate section")
1254
1255	    _validate_web_backends(config, issues)
1256	    return issues
1257
1258
1259	def print_config_warnings(config: Optional[Dict[str, Any]] = None) -> None:
1260	    """Print config structure warnings to stderr at startup; nothing if config is healthy."""
1261	    try:
1262	        issues = validate_config_structure(config)
1263	    except Exception:
1264	        issues = []
1265	    if not issues:
1266	        return
1267
1268	    lines = ["\033[33m⚠ Config issues detected in config.yaml:\033[0m"]
1269	    for ci in issues:
1270	        marker = "\033[31m✗\033[0m" if ci.severity == "error" else "\033[33m⚠\033[0m"
1271	        lines.append(f"  {marker} {ci.message}")
1272	    lines.append("  \033[2mRun 'hermes doctor' for fix suggestions.\033[0m")
1273	    sys.stderr.write("\n".join(lines) + "\n\n")
1274
1275
1276	def warn_deprecated_cwd_env_vars() -> None:
1277	    """Warn if MESSAGING_CWD / TERMINAL_CWD is set in .env (canonical: terminal.cwd in config.yaml).
1278	    Reads the file rather than ``os.environ`` because runtime bridges and session restoration
1279	    legitimately set ``TERMINAL_CWD``."""
1280	    try:
1281	        env_map = load_env()
1282	    except Exception:
1283	        return
1284
1285	    lines: list[str] = []
1286	    for name in ("MESSAGING_CWD", "TERMINAL_CWD"):
1287	        val = str(env_map.get(name) or "").strip()
1288	        if val:
1289	            lines.append(f"  \033[33m⚠\033[0m {name}={val} found in .env — this is deprecated.")
1290	    if lines:
1291	        from hermes_constants import display_hermes_home
1292
1293	        hint_path = display_hermes_home()
1294	        lines.insert(0, "\033[33m⚠ Deprecated .env settings detected:\033[0m")
1295	        lines.append(
1296	            "  \033[2mMove to config.yaml instead:  "
1297	            "terminal:\\n    cwd: /your/project/path\033[0m")
1298	        lines.append(f"  \033[2mThen remove the old entries from {hint_path}/.env\033[0m")
1299	        sys.stderr.write("\n".join(lines) + "\n\n")
1300
1301
1302	def _persist_migration(config: Dict[str, Any]) -> None:
1303	    """Persist a migrated config under THE migration write invariant: a migration may only
1304	    persist values that DIFFER from the schema default, plus explicit removals/renames of user
1305	    data. Every migration step MUST write through here (``save_config`` with default-stripping
1306	    ON, no ``merge_existing``) so the invariant cannot regress one migration at a time."""
1307	    save_config(config)
1308
1309
1310	def _prompt_and_save_env(name: str, info: Dict[str, Any], prompt: str, results: Dict[str, Any]) -> bool:
1311	    """Prompt for one env var (masked when ``info['password']``), save it, record it; False if skipped."""
1312	    value = masked_secret_prompt(prompt) if info.get("password") else line_input(prompt).strip()
1313	    if not value:
1314	        return False
1315	    save_env_value(name, value)
1316	    results["env_added"].append(name)
1317	    print(f"  ✓ Saved {name}")
1318	    return True
1319
1320
1321	def _ask_yes_no(prompt: str) -> bool:
1322	    try:
1323	        answer = input(prompt).strip().lower()
1324	    except (EOFError, KeyboardInterrupt):
1325	        answer = "n"
1326	    return answer in {"y", "yes"}
1327
1328
1329	def migrate_config(interactive: bool = True, quiet: bool = False) -> Dict[str, Any]:
1330	    """Migrate config to latest version, prompting for new required fields."""
1331	    results = {"env_added": [], "config_added": [], "warnings": []}
1332
1333	    # Validate config.yaml before any migration side effect: sanitize_env_file() rewrites .env,
1334	    # which must not happen when the migration will be refused for malformed YAML.
1335	    current_ver, latest_ver = check_config_version(raise_on_parse_error=True)
1336
1337	    try:
1338	        fixes = sanitize_env_file()
1339	        if fixes and not quiet:
1340	            print(f"  ✓ Normalized .env line formatting ({fixes} line(s) changed)")
1341	    except Exception:

... (gap) ...

1351	        SUPPORT_FLOOR_VERSION, run_migrations, support_floor_message)
1352
1353	    try:
1354	        has_explicit_version = "_config_version" in read_user_config_raw()
1355	    except Exception:
1356	        has_explicit_version = False
1357	    floor_refused = (
1358	        has_explicit_version and current_ver < SUPPORT_FLOOR_VERSION and current_ver < latest_ver)
1359	    if floor_refused:
1360	        msg = support_floor_message()
1361	        results["warnings"].append(msg)
1362	        # stderr so it is visible even on quiet startup paths.
1363	        sys.stderr.write(f"⚠ hermes config: {msg}\n")
1364	        if not quiet:
1365	            print(f"  ⚠ {msg}")
1366	    else:
1367	        run_migrations(current_ver, results, quiet)
1368
1369	    _disable_suspicious_mcp_servers(results, quiet)
1370	    _warn_invalid_platform_toolsets(results, quiet)
1371
1372	    if current_ver < latest_ver and not quiet and not floor_refused:
1373	        print(f"Config version: {current_ver} → {latest_ver}")
1374
1375	    missing_env = get_missing_env_vars(required_only=True)
1376	    if missing_env and not quiet:
1377	        print("\n⚠️  Missing required environment variables:")
1378	        for var in missing_env:
1379	            print(f"   • {var['name']}: {var['description']}")
1380	    if interactive and missing_env:
1381	        print("\nLet's configure them now:\n")
1382	        for var in missing_env:
1383	            if var.get("url"):
1384	                print(f"  Get your key at: {var['url']}")
1385	            if not _prompt_and_save_env(var["name"], var, f"  {var['prompt']}: ", results):
1386	                results["warnings"].append(f"Skipped {var['name']} - some features may not work")
1387	            print()
1388
1389	    if interactive and not quiet:
1390	        _offer_new_optional_env_vars(current_ver, latest_ver, results)
1391
1392	    # New default keys are NOT materialised to disk (load_config() deep-merges DEFAULT_CONFIG at
1393	    # read time); this list only feeds the "N new config option(s)" display.
1394	    results["config_added"].extend(field["key"] for field in get_missing_config_fields())
1395
1396	    if current_ver < latest_ver and not floor_refused:
1397	        config = read_raw_config()
1398	        config["_config_version"] = latest_ver
1399	        _persist_migration(config)
1400
1401	    missing_skill_config = get_missing_skill_config_vars()
1402	    if missing_skill_config and interactive and not quiet:
1403	        _offer_skill_config_vars(missing_skill_config, results)
1404
1405	    return results
1406
1407
1408	def _disable_suspicious_mcp_servers(results: Dict[str, Any], quiet: bool) -> None:
1409	    """Post-migration: disable exfiltration-shaped MCP stdio entries (hand-edited or from older
1410	    installs). The stanza is preserved for auditability but marked disabled."""
1411	    config = read_raw_config()
1412	    # Preserve the stanza for auditability but mark it disabled so the next startup will not spawn it.
1413	    # (#45620)
1414	    raw_mcp_servers = config.get("mcp_servers")
1415	    if not isinstance(raw_mcp_servers, dict):
1416	        return
1417	    try:
1418	        from hermes_cli.mcp_security import validate_mcp_server_entry
1419	    except Exception:
1420	        return
1421	    mcp_touched = False
1422	    for server_name, entry in raw_mcp_servers.items():
1423	        issues = validate_mcp_server_entry(server_name, entry) if isinstance(entry, dict) else None
1424	        if not issues:
1425	            continue
1426	        entry["enabled"] = False
1427	        mcp_touched = True
1428	        results["warnings"].append(f"Disabled suspicious MCP server '{server_name}'")
1429	        if not quiet:
1430	            for issue in issues:
1431	                print(f"  ⚠ {issue}")
1432	            print(f"  ⚠ Disabled MCP server '{server_name}' pending review")
1433	    if mcp_touched:
1434	        config["mcp_servers"] = raw_mcp_servers
1435	        _persist_migration(config)
1436
1437
1438	def _warn_invalid_platform_toolsets(results: Dict[str, Any], quiet: bool) -> None:
1439	    """Surface invalid toolset names in platform_toolsets: ``resolve_toolset()`` returns [] for an
1440	    unknown name, silently disabling the affected tools. Best-effort; never blocks migration."""
1441	    try:
1442	        from toolsets import validate_toolset
1443	        from hermes_cli.toolset_validation import validate_platform_toolsets
1444	        from hermes_cli.toolset_scope import toolset_allowed_for_platform
1445
1446	        for w in validate_platform_toolsets(
1447	                read_raw_config().get("platform_toolsets"), validate_toolset, toolset_allowed_for_platform):
1448	            results["warnings"].append(w)
1449	            if not quiet:
1450	                print(f"  ⚠ {w}")
1451	    except Exception as _ts_val_err:
1452	        logger.debug("platform_toolsets validation skipped: %s", _ts_val_err)
1453
1454
1455	def _offer_list(heading: str, items: List[str], question: str) -> bool:
1456	    """Print a bulleted offer list and ask; False (with the "set later" hint) when declined."""
1457	    print(heading)
1458	    for item in items:
1459	        print(f"    • {item}")
1460	    print()
1461	    if not _ask_yes_no(question):
1462	        print("  Set later with: hermes config set <key> <value>")
1463	        return False
1464	    print()
1465	    return True
1466
1467
1468	def _offer_new_optional_env_vars(current_ver: int, latest_ver: int, results: Dict[str, Any]) -> None:
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

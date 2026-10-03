**Exploration: hermes_cli/config.py**

Found 258 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/config.py`** — calls(calls), _exit_invalid(calls), _split_key_path(calls), _issue(calls), get_config_path(calls), get_env_value(calls), _section(calls), get_env_path(calls), _expand_env_vars(calls), load_config(calls), read_raw_config(calls), cfg_get(calls), load_env(calls), _deep_merge(calls), instantiates(instantiates), +352 more

```python
635	        {"name": var_name, **info, "is_required": is_required}
636	        for table, is_required in groups
637	        for var_name, info in table.items()
638	        if not get_env_value(var_name)]
639
640
641	def _split_key_path(key: str) -> list[str]:

... (gap) ...

709	    create a new intermediate mapping that shadows an existing dotted sibling (``grok-4`` beside
710	    ``grok-4.5``), it raises ``ValueError`` instead of silently writing a phantom the runtime never reads.
711	    """
712	    parts = _split_key_path(dotted_key)
713	    current = config
714	    i = 0
715	    while i < len(parts):

... (gap) ...

728	                    f"segment {part!r} is not a numeric index")
729	            i += 1
730	        elif isinstance(current, dict):
731	            match = _greedy_literal_match(current, remaining)
732	            if match is not None:
733	                key, consumed = match
734	                if i + consumed == len(parts):

... (gap) ...

744	            if at_leaf:
745	                current[part] = value
746	                return
747	            shadowed = _phantom_sibling(current, part)
748	            if shadowed is not None:
749	                escaped = shadowed.replace(".", "\\.")
750	                raise ValueError(

... (gap) ...

804	                return None
805	            consumed = 1
806	        elif isinstance(current, dict):
807	            match = _greedy_literal_match(current, remaining)
808	            if match is None:
809	                return None
810	            key, consumed = match

... (gap) ...

825	    dotted key over blind splitting, so ``config get providers.p.models.grok-4.6.context_length`` reads the
826	    real ``grok-4.6`` entry instead of reporting the key unset (#84064).
827	    """
828	    loc = _locate_nested(config, _split_key_path(dotted_key))
829	    if loc is None:
830	        return _MISSING
831	    _, container, key = loc
832	    return container[key]
833
834
835	def _unset_nested(config, dotted_key: str) -> bool:
836	    """Remove a dotted-path value; True if it existed. Empty dict containers left behind are
837	    dropped, while user-authored empty lists and non-empty sibling branches are preserved.
838
839	    Same escape-aware, greedy-literal navigation as ``_set_nested`` / ``_get_nested`` (#84064): unsetting an
840	    unescaped dotted key removes the real literal entry rather than a phantom sibling.
841	    """
842	    loc = _locate_nested(config, _split_key_path(dotted_key))
843	    if loc is None:
844	        return False
845	    parents, current, key = loc

... (gap) ...

888	    if value is None:
889	        return "null"
890	    if isinstance(value, (dict, list)):
891	        return yaml.safe_dump(value, sort_keys=False).rstrip()  # config-writer: ok — renders a value for display, never written to disk
892	    return str(value)
893
894

... (gap) ...

905	                missing.append({"key": full_key, "default": default_value,
906	                                "description": f"New config option: {full_key}"})
907	            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
908	                _check(default_value, current[key], full_key)
909
910	    _check(DEFAULT_CONFIG, load_config())
911	    return missing
912
913
914	def get_missing_skill_config_vars() -> List[Dict[str, Any]]:
915	    """Return skill-declared config vars (``skills.config.<key>``) that are missing or empty."""
916	    try:
917	        from agent.skill_utils import discover_all_skill_config_vars, SKILL_CONFIG_PREFIX
918	    except Exception:
919	        return []
920
921	    try:
922	        all_vars = discover_all_skill_config_vars()
923	    except Exception as e:
924	        # A malformed SKILL.md must never break `hermes update`; this prompting is a nicety.
925	        logger.debug("discover_all_skill_config_vars failed: %s", e)
926	        return []
927	    if not all_vars:
928	        return []
929
930	    config = load_config()
931	    values = ((var, cfg_get(config, *f"{SKILL_CONFIG_PREFIX}.{var['key']}".split("."))) for var in all_vars)
932	    return [var for var, v in values if v is None or (isinstance(v, str) and not v.strip())]
933
934
935	def _coerce_config_version(value: Any) -> int:
936	    """Return a safe integer config version, treating invalid values as legacy."""
937	    if isinstance(value, bool):
938	        return 0
939	    try:
940	        version = int(value)
941	    except (TypeError, ValueError):
942	        return 0
943	    return max(version, 0)
944
945
946	def _read_config_version_stamp(*, raise_on_parse_error: bool = False) -> Tuple[Optional[int], int]:
947	    """Single raw read behind ``check_config_version()``: ``(stamp, latest_version)`` where
948	    *stamp* is ``None`` when config.yaml parsed but carries no ``_config_version`` key (a
949	    never-stamped current-schema file, not an ancient install — ``migrate_config()`` gives it only
950	    the legacy-key steps). A missing file, or malformed YAML under a tolerant caller, reads as
951	    ``latest`` exactly as ``check_config_version()`` always reported it."""
952	    latest = _coerce_config_version(DEFAULT_CONFIG.get("_config_version", 1)) or 1
953	    config_path = get_config_path()
954	    if not config_path.exists():
955	        return latest, latest
956
957	    try:
958	        with open(config_path, encoding="utf-8-sig") as f:
959	            config = fast_safe_load(f)
960	    except Exception as e:
961	        _warn_config_parse_failure(config_path, e)
962	        if raise_on_parse_error:
963	            raise InvalidUserConfigError(
964	                f"Cannot inspect {config_path}: config.yaml is not valid YAML ({e})"
965	            ) from e
966	        return latest, latest
967
968	    if config is None:
969	        config = {}  # empty file / bare document: valid first-run state
970	    if not isinstance(config, dict):
971	        # A list/scalar root parses fine but is just as unusable as broken YAML: save_config()
972	        # would refuse it later, after .env was already rewritten. Strict callers see it up front.
973	        if raise_on_parse_error:
974	            raise InvalidUserConfigError(
975	                f"Cannot inspect {config_path}: config.yaml top-level value must be "
976	                f"a mapping, got {type(config).__name__}"
977	            )
978	        config = {}
979	    if "_config_version" not in config:
980	        return None, latest
981	    return _coerce_config_version(config.get("_config_version")), latest
982
983
984	def check_config_version(*, raise_on_parse_error: bool = False) -> Tuple[int, int]:
985	    """Return ``(current_version, latest_version)`` from the raw on-disk config.
986	    Reads the raw file rather than ``load_config()``: the deep-merge would make a file lacking
987	    ``_config_version`` inherit the latest version, hiding that the schema was never migrated.
988	    Invalid YAML gets a parse warning, not an automatic schema rewrite. Tolerant runtime status
989	    callers keep the historical latest/latest fallback for malformed YAML; mutation and explicit
990	    validation paths set ``raise_on_parse_error`` so a parse failure or a non-mapping root cannot
991	    be mistaken for an up-to-date config. A file with no version key reads as 0."""
992	    stamp, latest = _read_config_version_stamp(raise_on_parse_error=raise_on_parse_error)
993	    return (0 if stamp is None else stamp), latest
994
995

... (gap) ...

1039
1040
1041	def _issue(issues: List["ConfigIssue"], severity: str, message: str, hint: str) -> None:
1042	    issues.append(ConfigIssue(severity, message, hint))
1043
1044
1045	def _require_fields(
1046	    issues: List["ConfigIssue"], entry: Dict[str, Any], label: str,
1047	    fields: Tuple[Tuple[str, str], ...], suffix: str = "") -> None:
1048	    """Append a warning for every falsy ``field`` of *entry* (message: ``<label> is missing '<f>' field``)."""
1049	    for field, hint in fields:
1050	        if not entry.get(field):
1051	            _issue(issues, "warning", f"{label} is missing '{field}' field{suffix}", hint)
1052
1053
1054	_CP_REQUIRED_FIELDS = (

... (gap) ...

1069	    submit_mode = voice_cfg.get("submit_mode")
1070	    normalized = submit_mode.strip().lower() if isinstance(submit_mode, str) else None
1071	    if normalized not in {"direct", "draft"}:
1072	        _issue(issues, "error", f"voice.submit_mode must be 'direct' or 'draft', got {submit_mode!r}",
1073	               "Set voice.submit_mode to direct (submit immediately) or draft (edit before sending)")
1074
1075

... (gap) ...

1090	            "schedules silently fall back to server-local time. HERMES_TIMEZONE overrides "
1091	            "this key when set.")
1092	    if tz is not None and not isinstance(tz, str):
1093	        _issue(issues, "error", f"timezone must be an IANA zone name string, got {tz!r}", hint)
1094	        return
1095	    if not (isinstance(tz, str) and tz.strip()):
1096	        return
1097	    name = tz.strip()
1098	    try:
1099	        import zoneinfo
1100	        zoneinfo.ZoneInfo("UTC")  # is a tz database available at all?
1101	    except Exception:
1102	        return
1103	    try:
1104	        zoneinfo.ZoneInfo(name)
1105	    except Exception:
1106	        _issue(issues, "error", f"timezone {name!r} is not a valid IANA zone name", hint)
1107
1108
1109	def _validate_entry_list(
1110	    entries: list, label: str, issues: List[ConfigIssue], fields, *, non_dict: Tuple[str, str, str],
1111	) -> None:
1112	    """Validate each list entry: ``non_dict`` = (severity, message-with-{i}-and-{type}, hint) for
1113	    non-dict items; dict items get ``_require_fields`` with *fields*."""
1114	    severity, message, hint = non_dict
1115	    for i, entry in enumerate(entries):
1116	        if not isinstance(entry, dict):
1117	            _issue(issues, severity, message.format(i=i, type=type(entry).__name__), hint)
1118	        else:
1119	            _require_fields(issues, entry, f"{label}[{i}]", fields)
1120
1121
1122	_CP_LIST_HINT = "Change to:\n  custom_providers:\n    - name: my-provider\n      base_url: https://...\n      api_key: ..."
1123
1124
1125	def _validate_custom_providers(cp: Any, issues: List[ConfigIssue]) -> None:
1126	    """custom_providers must be a list of dicts — a dict or a scalar is silently dropped by the runtime."""
1127	    if isinstance(cp, dict):
1128	        _issue(issues, "error",
1129	               "custom_providers is a dict — it must be a YAML list (items prefixed with '-')", _CP_LIST_HINT)
1130	        suspicious = set(cp.keys()) & _CUSTOM_PROVIDER_LIKE_FIELDS
1131	        if suspicious:
1132	            _issue(issues, "warning",
1133	                   f"Root-level keys {sorted(suspicious)} look like custom_providers entry fields",
1134	                   "These should be indented under a '- name: ...' list entry, not at root level")
1135	    elif isinstance(cp, list):
1136	        _validate_entry_list(cp, "custom_providers", issues, _CP_REQUIRED_FIELDS, non_dict=(
1137	            "warning", "custom_providers[{i}] is not a dict (got {type})",
1138	            "Each entry should have at minimum: name, base_url"))
1139	    else:
1140	        # get_compatible_custom_providers() returns [] for any non-list: the legacy entries vanish
1141	        # ("0 endpoints") with nothing naming the cause.
1142	        _issue(issues, "error",
1143	               f"custom_providers is a {type(cp).__name__} — it must be a YAML list (items prefixed with '-'); "
1144	               "legacy custom_providers entries are ignored until it is", _CP_LIST_HINT)
1145
1146
1147	def _validate_fallback_model(fb: Any, issues: List[ConfigIssue]) -> None:
1148	    """fallback_model: single dict OR list of dicts (chain)."""
1149	    if isinstance(fb, list):
1150	        _validate_entry_list(fb, "fallback_model", issues, _FB_REQUIRED_FIELDS, non_dict=(
1151	            "error", "fallback_model[{i}] should be a dict, got {type}", "Each entry needs provider + model"))
1152	    elif not isinstance(fb, dict):
1153	        _issue(issues, "error",
1154	               f"fallback_model should be a dict with 'provider' and 'model', got {type(fb).__name__}",
1155	               "Change to:\n  fallback_model:\n    provider: openrouter\n    model: anthropic/claude-sonnet-4")
1156	    elif fb:
1157	        _require_fields(issues, fb, "fallback_model", _FB_SINGLE_REQUIRED_FIELDS,
1158	                        suffix=" — fallback will be disabled")
1159
1160

... (gap) ...

1175	        if not _val or _val in seen:
1176	            continue
1177	        seen.add(_val)
1178	        note = removed_backend_note("web", _val)
1179	        if note:
1180	            _issue(issues, "warning",
1181	                   f"web.{_key} is set to '{_val}', but {note} — "
1182	                   "web_search/web_extract will fail until it is changed",
1183	                   "Run 'hermes tools' and pick a different Web Search & Extract provider")

... (gap) ...

1193	            path = f"{prefix}.{key}" if prefix else key
1194	            if isinstance(value, dict):
1195	                slots[path] = "mapping"
1196	                walk(value, path)
1197	            elif isinstance(value, list):
1198	                slots[path] = "list"
1199
1200	    walk(DEFAULT_CONFIG, "")
1201	    slots.update(_KNOWN_CONTAINER_TYPES)
1202	    return slots
1203
1204
1205	def _validate_quoted_containers(config: Dict[str, Any], issues: List[ConfigIssue]) -> None:
1206	    """A container slot holding ONE quoted string (``enabled: '["a","b"]'``) is skipped by every
1207	    isinstance-gated reader while ``config get`` echoes it back, so plugins silently unmount and
1208	    exclusions silently lapse (#83308, #105706). Finding only — the file is never rewritten."""
1209	    for key, kind in _container_slots().items():
1210	        # ``parse_config_string_list`` readers accept the quoted form; nothing is ignored there.
1211	        if key in _SCALAR_AS_ONE_ITEM_LIST_KEYS:
1212	            continue
1213	        value = cfg_get(config, *key.split("."))
1214	        if not isinstance(value, str) or not _looks_structured_value(value):
1215	            continue
1216	        try:
1217	            parsed = yaml.safe_load(value)
1218	        except yaml.YAMLError:
1219	            continue
1220	        if isinstance(parsed, (list, dict)):
1221	            _issue(issues, "warning",
1222	                   f"{key} is the quoted string {value!r} — Hermes expects a YAML {kind} here "
1223	                   "and every reader ignores the string",
1224	                   f"Run: hermes config set {key} {shlex.quote(value)}  (stores a real {kind}), "
1225	                   "or remove the quotes in config.yaml")
1226
1227
1228	def validate_config_structure(config: Optional[Dict[str, Any]] = None) -> List["ConfigIssue"]:
1229	    """Validate config.yaml structure and return detected issues (accepts a pre-loaded dict).
1230	    Catches common YAML mistakes that otherwise surface as confusing runtime errors."""
1231	    if config is None:
1232	        try:
1233	            config = load_config()
1234	        except Exception as exc:
1235	            from hermes_cli.config_home import config_load_issue
1236	            return [config_load_issue(exc)]
1237
1238	    issues: List[ConfigIssue] = []
1239	    _validate_voice(config, issues)
1240	    _validate_timezone(config, issues)
1241	    cp = config.get("custom_providers")
1242	    fb = config.get("fallback_model")
1243	    for value, validator in ((cp, _validate_custom_providers), (fb, _validate_fallback_model)):
1244	        if value is not None:
1245	            validator(value, issues)
1246
1247	    if isinstance(cp, dict) and "fallback_model" not in config and "fallback_model" in (cp or {}):
1248	        _issue(issues, "error", "fallback_model appears inside custom_providers instead of at root level",
1249	               "Move fallback_model to the top level of config.yaml (no indentation)")
1250
1251	    if cp and not config.get("model"):
1252	        _issue(issues, "warning",
1253	               "custom_providers defined but no 'model' section — Hermes won't know which provider to use",
1254	               "Add a model section:\n  model:\n    provider: custom\n    default: your-model-name\n"
1255	               "    base_url: https://...")
1256
1257	    # Only provider-like fields are flagged as misplaced roots. Arbitrary unknown top-level keys
1258	    # are deliberately NOT warned about: top-level scalars are bridged into os.environ so users
1259	    # can feed skills/external apps env-style keys — a closed-world allowlist cannot enumerate those.
1260	    for key in config:
1261	        if not key.startswith("_") and key not in _KNOWN_ROOT_KEYS and key in _CUSTOM_PROVIDER_LIKE_FIELDS:
1262	            _issue(issues, "warning",
1263	                   f"Root-level key '{key}' looks misplaced — should it be under 'model:' or inside a 'custom_providers' entry?",
1264	                   f"Move '{key}' under the appropriate section")
1265
1266	    _validate_web_backends(config, issues)
1267	    _validate_quoted_containers(config, issues)
1268	    return issues
1269
1270
1271	def print_config_warnings(config: Optional[Dict[str, Any]] = None) -> None:
1272	    """Print config structure warnings to stderr at startup; nothing if config is healthy."""
1273	    try:
1274	        issues = validate_config_structure(config)
1275	    except Exception:
1276	        issues = []
1277	    if not issues:
1278	        return
1279
1280	    lines = ["\033[33m⚠ Config issues detected in config.yaml:\033[0m"]
1281	    for ci in issues:
1282	        marker = "\033[31m✗\033[0m" if ci.severity == "error" else "\033[33m⚠\033[0m"
1283	        lines.append(f"  {marker} {ci.message}")
1284	    lines.append("  \033[2mRun 'hermes doctor' for fix suggestions.\033[0m")
1285	    sys.stderr.write("\n".join(lines) + "\n\n")
1286
1287
1288	def warn_deprecated_cwd_env_vars() -> None:
1289	    """Warn if MESSAGING_CWD / TERMINAL_CWD is set in .env (canonical: terminal.cwd in config.yaml).
1290	    Reads the file rather than ``os.environ`` because runtime bridges and session restoration
1291	    legitimately set ``TERMINAL_CWD``."""
1292	    try:
1293	        env_map = load_env()
1294	    except Exception:
1295	        return
1296
1297	    lines: list[str] = []
1298	    for name in ("MESSAGING_CWD", "TERMINAL_CWD"):
1299	        val = str(env_map.get(name) or "").strip()
1300	        if val:
1301	            lines.append(f"  \033[33m⚠\033[0m {name}={val} found in .env — this is deprecated.")
1302	    if lines:
1303	        from hermes_constants import display_hermes_home
1304
1305	        hint_path = display_hermes_home()
1306	        lines.insert(0, "\033[33m⚠ Deprecated .env settings detected:\033[0m")
1307	        lines.append(
1308	            "  \033[2mMove to config.yaml instead:  "
1309	            "terminal:\\n    cwd: /your/project/path\033[0m")
1310	        lines.append(f"  \033[2mThen remove the old entries from {hint_path}/.env\033[0m")
1311	        sys.stderr.write("\n".join(lines) + "\n\n")
1312
1313
1314	def _persist_migration(config: Dict[str, Any]) -> None:
1315	    """Persist a migrated config under THE migration write invariant: a migration may only
1316	    persist values that DIFFER from the schema default, plus explicit removals/renames of user
1317	    data. Every migration step MUST write through here (``save_config`` with default-stripping
1318	    ON, no ``merge_existing``) so the invariant cannot regress one migration at a time. A migration
1319	    is Hermes' own write, never a user turning a feature off."""
1320	    from hermes_cli.observability.shared_metrics_disabled import hermes_applied_write
1321
1322	    with hermes_applied_write():
1323	        save_config(config)
1324
1325
1326	def _prompt_and_save_env(name: str, info: Dict[str, Any], prompt: str, results: Dict[str, Any]) -> bool:
1327	    """Prompt for one env var (masked when ``info['password']``), save it, record it; False if skipped."""
1328	    value = masked_secret_prompt(prompt) if info.get("password") else line_input(prompt).strip()
1329	    if not value:
1330	        return False
1331	    save_env_value(name, value)
1332	    results["env_added"].append(name)
1333	    print(f"  ✓ Saved {name}")
1334	    return True
1335

... (gap) ...

1348
1349	    # Validate config.yaml before any migration side effect: sanitize_env_file() rewrites .env,
1350	    # which must not happen when the migration will be refused for malformed YAML.
1351	    stamp, latest_ver = _read_config_version_stamp(raise_on_parse_error=True)
1352	    current_ver = 0 if stamp is None else stamp
1353
1354	    try:
1355	        fixes = sanitize_env_file()
1356	        if fixes and not quiet:
1357	            print(f"  ✓ Normalized .env line formatting ({fixes} line(s) changed)")
1358	    except Exception:

... (gap) ...

1371	    floor_refused = (
1372	        has_explicit_version and current_ver < SUPPORT_FLOOR_VERSION and current_ver < latest_ver)
1373	    if floor_refused:
1374	        msg = support_floor_message()
1375	        results["warnings"].append(msg)
1376	        # stderr so it is visible even on quiet startup paths.
1377	        sys.stderr.write(f"⚠ hermes config: {msg}\n")
1378	        if not quiet:
1379	            print(f"  ⚠ {msg}")
1380	    else:
1381	        run_migrations(current_ver, results, quiet, unversioned=not has_explicit_version)
1382
1383	    _disable_suspicious_mcp_servers(results, quiet)
1384	    _warn_invalid_platform_toolsets(results, quiet)
1385
1386	    if current_ver < latest_ver and not quiet and not floor_refused:
1387	        print(f"Config version: {current_ver} → {latest_ver}")
1388
1389	    missing_env = get_missing_env_vars(required_only=True)
1390	    if missing_env and not quiet:
1391	        print("\n⚠️  Missing required environment variables:")
1392	        for var in missing_env:
1393	            print(f"   • {var['name']}: {var['description']}")
1394	    if interactive and missing_env:
1395	        print("\nLet's configure them now:\n")
1396	        for var in missing_env:
1397	            if var.get("url"):
1398	                print(f"  Get your key at: {var['url']}")
1399	            if not _prompt_and_save_env(var["name"], var, f"  {var['prompt']}: ", results):
1400	                results["warnings"].append(f"Skipped {var['name']} - some features may not work")
1401	            print()
1402
1403	    if interactive and not quiet:
1404	        _offer_new_optional_env_vars(current_ver, latest_ver, results)
1405
1406	    # New default keys are NOT materialised to disk (load_config() deep-merges DEFAULT_CONFIG at
1407	    # read time); this list only feeds the "N new config option(s)" display.
1408	    results["config_added"].extend(field["key"] for field in get_missing_config_fields())
1409
1410	    if current_ver < latest_ver and not floor_refused:
1411	        config = read_raw_config()
1412	        config["_config_version"] = latest_ver
1413	        _persist_migration(config)
1414
1415	    missing_skill_config = get_missing_skill_config_vars()
1416	    if missing_skill_config and interactive and not quiet:
1417	        _offer_skill_config_vars(missing_skill_config, results)
1418
1419	    return results
1420
1421
1422	def _disable_suspicious_mcp_servers(results: Dict[str, Any], quiet: bool) -> None:
1423	    """Post-migration: disable exfiltration-shaped MCP stdio entries (hand-edited or from older
1424	    installs). The stanza is preserved for auditability but marked disabled."""
1425	    config = read_raw_config()
1426	    # Preserve the stanza for auditability but mark it disabled so the next startup will not spawn it.
```


> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

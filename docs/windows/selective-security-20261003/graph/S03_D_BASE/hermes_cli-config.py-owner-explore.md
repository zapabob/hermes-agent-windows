**Exploration: hermes_cli/config.py**

Found 199 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/config.py`** — calls(calls), ConfigIssue(instantiates), get_env_value(calls), get_config_path(calls), is_managed(calls), load_config(calls), get_env_path(calls), _model_assignment_text(calls), read_raw_config(calls), coerce_provider_id(calls), _warn_config_parse_failure(calls), load_env(calls), _expand_env_vars(calls), managed_error(calls), _secure_file(calls), +261 more

```python
693
694	def format_managed_message(action: str = "modify this Hermes installation") -> str:
695	    """Build a user-facing error for managed installs."""
696	    managed_system = get_managed_system() or "a package manager"
697	    return (
698	        f"Cannot {action}: this Hermes installation is managed by {managed_system}.\n"
699	        "Use your package manager to upgrade or reinstall Hermes."
700	    )
701
702	def managed_error(action: str = "modify configuration"):
703	    """Print user-friendly error for managed mode."""
704	    print(format_managed_message(action), file=sys.stderr)
705
706
707	# =============================================================================

... (gap) ...

719	    container.enable = true. It tells the host CLI to exec into the container
720	    instead of running locally.
721	    """
722	    if os.environ.get("HERMES_DEV") == "1":
723	        return None
724
725	    from hermes_constants import is_container
726	    if is_container():
727	        return None
728
729	    container_mode_file = get_hermes_home() / ".container-mode"
730
731	    try:
732	        info = {}

... (gap) ...

763
764	def get_config_path() -> Path:
765	    """Get the main config file path."""
766	    return get_hermes_home() / "config.yaml"
767
768	def get_env_path() -> Path:
769	    """Get the .env file path (for API keys)."""
770	    return get_hermes_home() / ".env"
771
772	def get_project_root() -> Path:
773	    """Get the project installation directory."""
774	    return Path(__file__).parent.parent.resolve()
775
776	def _resolve_hermes_uid_gid() -> tuple[Optional[int], Optional[int]]:
777	    """Read the HERMES_UID / HERMES_GID env vars set by Docker deployments.

... (gap) ...

790	    """
791	    if sys.platform == "win32":
792	        return None, None
793	    uid_str = os.environ.get("HERMES_UID", "").strip()
794	    gid_str = os.environ.get("HERMES_GID", "").strip()
795	    try:
796	        uid = int(uid_str) if uid_str else None
797	    except ValueError:

... (gap) ...

815	    directories created by :func:`ensure_hermes_home` on Docker deployments.
816	    See #34107.
817	    """
818	    uid, gid = _resolve_hermes_uid_gid()
819	    if uid is None and gid is None:
820	        return
821	    try:

... (gap) ...

850	    created at runtime by kanban workers don't land as root:root and block
851	    subsequent uid-mapped workers).
852	    """
853	    if is_managed():
854	        return
855	    try:
856	        mode_str = os.environ.get("HERMES_HOME_MODE", "").strip()
857	        mode = int(mode_str, 8) if mode_str else 0o700
858	    except ValueError:
859	        mode = 0o700
860	    try:
861	        os.chmod(path, mode)
862	    except (OSError, NotImplementedError):
863	        pass
864	    _chown_to_hermes_uid(path)
865
866
867	def _is_container() -> bool:
868	    """Detect if we're running inside a Docker/Podman/LXC container.
869
870	    When Hermes runs in a container with volume-mounted config files, forcing
871	    0o600 permissions breaks multi-process setups where the gateway and
872	    dashboard run as different UIDs or the volume mount requires broader
873	    permissions.
874	    """
875	    # Explicit opt-out
876	    if os.environ.get("HERMES_CONTAINER") or os.environ.get("HERMES_SKIP_CHMOD"):
877	        return True
878	    # Docker / Podman marker file
879	    if os.path.exists("/.dockerenv"):
880	        return True
881	    # LXC / cgroup-based detection
882	    try:

... (gap) ...

898	    Skipped in containers — Docker/Podman volume mounts often need broader
899	    permissions.  Set HERMES_SKIP_CHMOD=1 to force-skip on other systems.
900	    """
901	    if is_managed() or _is_container():
902	        return
903	    try:
904	        if os.path.exists(str(path)):
905	            os.chmod(path, 0o600)
906	    except (OSError, NotImplementedError):
907	        pass
908
909
910	def _ensure_default_soul_md(home: Path) -> None:
911	    """Seed a default SOUL.md into HERMES_HOME, upgrading legacy empty templates.
912
913	    First run: write DEFAULT_SOUL_MD. Existing installs whose SOUL.md is still
914	    the old comment-only scaffold (seeded by older install.sh / install.ps1 /
915	    docker images, which shadowed the runtime default) get upgraded in place to
916	    DEFAULT_SOUL_MD. A SOUL.md the user actually customized is never touched.
917	    """
918	    soul_path = home / "SOUL.md"
919	    if soul_path.exists():
920	        try:
921	            existing = soul_path.read_text(encoding="utf-8")
922	        except (OSError, UnicodeDecodeError):
923	            return
924	        if not is_legacy_template_soul(existing):
925	            return
926	        # Legacy empty template -> upgrade to the real default in place.
927	    soul_path.write_text(DEFAULT_SOUL_MD, encoding="utf-8")
928	    _secure_file(soul_path)
929
930
931	# Home paths whose directory skeleton has been created this process — see

... (gap) ...

949	    recreated on the next load, as before). Profile switches change
950	    ``get_hermes_home()`` and therefore re-run for the new path.
951	    """
952	    home = get_hermes_home()
953	    key = str(home)
954
955	    if key in _HERMES_HOME_ENSURED and home.is_dir():
956	        return
957	    # Named profiles must be created explicitly (e.g. ``hermes profile create``).
958	    # If a stale process keeps running after the profile was renamed/deleted,
959	    # silently mkdir-ing the old HERMES_HOME would resurrect an empty skeleton
960	    # and make the deleted profile reappear in Desktop/profile lists.
961	    if home.parent.name == "profiles" and not home.exists():
962	        raise FileNotFoundError(
963	            f"Named profile home does not exist: {home}. "
964	            "Create the profile explicitly before using it."
965	        )
966	    if is_managed():
967	        old_umask = os.umask(0o007)
968	        try:
969	            _ensure_hermes_home_managed(home)
970	        finally:
971	            os.umask(old_umask)
972	    else:
973	        home.mkdir(parents=True, exist_ok=True)
974	        _secure_dir(home)
975	        for subdir in (
976	            "cron", "sessions", "logs", "logs/curator", "memories",
977	            "pairing", "hooks", "image_cache", "audio_cache", "skills",
978	        ):
979	            d = home / subdir
980	            d.mkdir(parents=True, exist_ok=True)
981	            _secure_dir(d)
982	        _ensure_default_soul_md(home)
983
984	    _HERMES_HOME_ENSURED.add(key)
985
986
987	def _ensure_hermes_home_managed(home: Path):
988	    """Managed-mode variant: verify dirs exist (activation creates them), seed SOUL.md."""
989	    if not home.is_dir():
990	        raise RuntimeError(
991	            f"HERMES_HOME {home} does not exist."
992	        )
993	    for subdir in ("cron", "sessions", "logs", "memories"):
994	        d = home / subdir
995	        if not d.is_dir():
996	            raise RuntimeError(f"{d} does not exist.")
997	    # Curator reports dir is a sub-path of logs/; create it if missing.
998	    # In managed mode the activation script may not know about this subdir,
999	    # so we mkdir it ourselves (it's inside an already-secured logs/ dir).
1000	    (home / "logs" / "curator").mkdir(parents=True, exist_ok=True)
1001	    # Inside umask(0o007) scope — SOUL.md will be created as 0660
1002	    _ensure_default_soul_md(home)
1003
1004
1005	# =============================================================================

... (gap) ...

1044
1045	    # Check required vars
1046	    for var_name, info in REQUIRED_ENV_VARS.items():
1047	        if not get_env_value(var_name):
1048	            missing.append({"name": var_name, **info, "is_required": True})
1049
1050	    # Check optional vars (if not required_only)
1051	    if not required_only:
1052	        for var_name, info in OPTIONAL_ENV_VARS.items():
1053	            if not get_env_value(var_name):
1054	                missing.append({"name": var_name, **info, "is_required": False})
1055
1056	    return missing

... (gap) ...

1274	    Walks the DEFAULT_CONFIG tree at arbitrary depth and reports any keys
1275	    present in defaults but absent from the user's loaded config.
1276	    """
1277	    config = load_config()
1278	    missing = []
1279
1280	    def _check(defaults: dict, current: dict, prefix: str = ""):
1281	        for key, default_value in defaults.items():
1282	            if key.startswith('_'):
1283	                continue
1284	            full_key = key if not prefix else f"{prefix}.{key}"
1285	            if key not in current:
1286	                missing.append({
1287	                    "key": full_key,
1288	                    "default": default_value,
1289	                    "description": f"New config option: {full_key}",
1290	                })
1291	            elif isinstance(default_value, dict) and isinstance(current.get(key), dict):
1292	                _check(default_value, current[key], full_key)
1293
1294	    _check(DEFAULT_CONFIG, config)
1295	    return missing
1296
1297

... (gap) ...

1308	        return []
1309
1310	    try:
1311	        all_vars = discover_all_skill_config_vars()
1312	    except Exception as e:
1313	        # A malformed SKILL.md, unreadable external skill dir, or similar
1314	        # should never break `hermes update`.  Skill-config prompting is a
1315	        # post-migration nicety, not a blocker.
1316	        import logging
1317	        logging.getLogger(__name__).debug(
1318	            "discover_all_skill_config_vars failed: %s", e
1319	        )
1320	        return []
1321	    if not all_vars:
1322	        return []
1323
1324	    config = load_config()
1325	    missing: List[Dict[str, Any]] = []
1326	    for var in all_vars:
1327	        # Skill config is stored under skills.config.<logical_key>

... (gap) ...

1359	    if dedup_key in _PROVIDER_NORMALIZE_WARNED:
1360	        return
1361	    _PROVIDER_NORMALIZE_WARNED.add(dedup_key)
1362	    logger.warning(msg, *args)
1363
1364
1365	_API_MODE_ALIASES = {

... (gap) ...

1395	    see a canonical name instead of silently discarding the user's intent.
1396	    """
1397	    cleaned = api_mode.strip()
1398	    return _API_MODE_ALIASES.get(cleaned.lower(), cleaned)
1399
1400
1401	def coerce_provider_id(value: Any) -> str:
1402	    """Provider identity fields are strings.
1403
1404	    PyYAML loads unquoted scalars like ``provider: 2070`` / ``2070:`` as int,
1405	    and later ``.strip()`` / ``.lower()`` on that value 500s the Model tab.
1406	    """
1407	    if value is None:
1408	        return ""
1409	    return str(value).strip()
1410
1411
1412	def stringify_provider_map(providers: Any) -> dict:
1413	    """Copy a ``providers:`` mapping so keys are strings.
1414
1415	    Desktop Custom Endpoints store the name as the dict key. An unquoted
1416	    YAML key ``2070:`` loads as int; picker code then calls ``ep_name.lower()``
1417	    and CRUD looks up ``"2070"`` and misses.
1418	    """
1419	    if not isinstance(providers, dict):
1420	        return {}
1421	    out: Dict[str, Any] = {}
1422	    for stored, value in providers.items():
1423	        key = coerce_provider_id(stored)
1424	        if key:
1425	            out[key] = value
1426	    return out
1427
1428
1429	def find_provider_entry(providers: Any, key: Any) -> Tuple[Any, Optional[Dict[str, Any]]]:
1430	    """Return ``(stored_key, entry)`` matching *key* by string identity.
1431
1432	    Needed because PyYAML may have stored the key as ``2070`` (int) while
1433	    Desktop looks up ``"2070"``. Prefer an exact string hit, then scan.
1434	    """
1435	    if not isinstance(providers, dict):
1436	        return None, None
1437	    want = coerce_provider_id(key)
1438	    if not want:
1439	        return None, None
1440	    exact = providers.get(want)
1441	    if isinstance(exact, dict):
1442	        return want, exact
1443	    for stored, entry in providers.items():
1444	        if coerce_provider_id(stored) == want and isinstance(entry, dict):
1445	            return stored, entry
1446	    return None, None
1447

... (gap) ...

1463	    # alias keys back into config.yaml through any later
1464	    # save_config(load_config()) round-trip.
1465	    entry = dict(entry)
1466	    provider_key = coerce_provider_id(provider_key)
1467
1468	    # Accept camelCase aliases commonly used in hand-written configs.
1469	    _CAMEL_ALIASES: Dict[str, str] = {

... (gap) ...

1498	    }
1499	    for camel, snake in _CAMEL_ALIASES.items():
1500	        if camel in entry and snake not in entry:
1501	            _warn_once_per_provider(
1502	                provider_key, f"camel:{camel}",
1503	                "providers.%s: camelCase key '%s' auto-mapped to '%s' "
1504	                "(use snake_case to avoid this warning)",
1505	                provider_key or "?", camel, snake,
1506	            )
1507	            entry[snake] = entry[camel]
1508	    unknown = set(entry.keys()) - _KNOWN_KEYS - set(_CAMEL_ALIASES.keys())
1509	    if unknown:
1510	        _warn_once_per_provider(
1511	            provider_key, "unknown:" + ",".join(sorted(unknown)),
1512	            "providers.%s: unknown config keys ignored: %s",
1513	            provider_key or "?", ", ".join(sorted(unknown)),

... (gap) ...

1533	                base_url = candidate
1534	                break
1535	            else:
1536	                logger.warning(
1537	                    "providers.%s: '%s' value '%s' is not a valid URL "
1538	                    "(no scheme or host) — skipped",
1539	                    provider_key or "?", url_key, candidate,
1540	                )
1541	    if not base_url:
1542	        return None
1543
1544	    name = coerce_provider_id(entry.get("name")) or provider_key
1545	    if not name:
1546	        return None
1547

... (gap) ...

1566
1567	    api_mode = entry.get("api_mode") or entry.get("transport")
1568	    if isinstance(api_mode, str) and api_mode.strip():
1569	        normalized["api_mode"] = _canonical_api_mode(api_mode)
1570
1571	    model_name = entry.get("model") or entry.get("default_model")
1572	    if isinstance(model_name, str) and model_name.strip():

... (gap) ...

1647	    # Per-provider extra HTTP headers (proxies, gateways, custom auth).
1648	    # Values may carry credentials (e.g. CF-Access-Client-Secret) — never
1649	    # log them anywhere downstream.
1650	    normalized_headers = normalize_extra_headers(entry.get("extra_headers"))
1651	    if normalized_headers:
1652	        normalized["extra_headers"] = normalized_headers
1653

... (gap) ...

1670	    provider_key: str = "",
1671	) -> Optional[Dict[str, Any]]:
1672	    """Translate a legacy custom provider entry to the v12 providers shape."""
1673	    normalized = _normalize_custom_provider_entry(
1674	        dict(entry) if isinstance(entry, dict) else entry,
1675	        provider_key=provider_key,
1676	    )

... (gap) ...

1711
1712	    custom_providers: List[Dict[str, Any]] = []
1713	    for key, entry in providers_dict.items():
1714	        if isinstance(entry, dict) and not is_provider_enabled(entry):
1715	            continue
1716	        normalized = _normalize_custom_provider_entry(
1717	            entry, provider_key=coerce_provider_id(key)
1718	        )
1719	        if normalized is not None:
1720	            custom_providers.append(normalized)

... (gap) ...

1733	    back into config.yaml because it duplicates entries in UIs.
1734	    """
1735	    if config is None:
1736	        config = load_config()
1737
1738	    compatible: List[Dict[str, Any]] = []
1739	    seen_provider_keys: set = set()
1740	    seen_name_url_pairs: set = set()
1741
1742	    def _append_if_new(entry: Optional[Dict[str, Any]]) -> None:
1743	        if entry is None:
1744	            return
1745	        provider_key = str(entry.get("provider_key", "") or "").strip().lower()
1746	        name = str(entry.get("name", "") or "").strip().lower()
1747	        base_url = str(entry.get("base_url", "") or "").strip().rstrip("/").lower()
1748	        model = str(entry.get("model", "") or "").strip().lower()
1749	        pair = (name, base_url, model)
1750
1751	        if provider_key and provider_key in seen_provider_keys:

... (gap) ...

1764	        if not isinstance(custom_providers, list):
1765	            return []
1766	        for entry in custom_providers:
1767	            _append_if_new(_normalize_custom_provider_entry(entry))
1768
1769	    for entry in providers_dict_to_custom_providers(config.get("providers")):
1770	        _append_if_new(entry)
1771
1772	    return compatible
1773

... (gap) ...

1794	    """Return TLS settings from a matching ``custom_providers`` / ``providers`` entry."""
1795	    if custom_providers is None:
1796	        try:
1797	            custom_providers = get_compatible_custom_providers(config)
1798	        except Exception:
1799	            custom_providers = []
1800	    if not base_url or not isinstance(custom_providers, list):
1801	        return {}
1802
1803	    target_url = normalize_route_base_url(base_url)
1804	    for entry in custom_providers:
1805	        if not isinstance(entry, dict):
1806	            continue
1807	        entry_url = normalize_route_base_url(entry.get("base_url"))
1808	        if not entry_url or entry_url != target_url:
1809	            continue
1810	        out: Dict[str, Any] = {}
1811	        ca = entry.get("ssl_ca_cert")
1812	        if isinstance(ca, str) and ca.strip():
1813	            out["ssl_ca_cert"] = ca.strip()
1814	        verify = _coerce_ssl_verify(entry.get("ssl_verify"))
1815	        if verify is not None:
1816	            out["ssl_verify"] = verify
1817	        return out
1818	    return {}
1819
1820
1821	def apply_custom_provider_tls_to_client_kwargs(
1822	    client_kwargs: Dict[str, Any],
1823	    base_url: str,
1824	    custom_providers: Optional[List[Dict[str, Any]]] = None,
1825	    config: Optional[Dict[str, Any]] = None,
1826	) -> None:
1827	    """Attach per-provider TLS knobs to OpenAI client kwargs when matched."""
1828	    tls = get_custom_provider_tls_settings(base_url, custom_providers, config)
1829	    if tls.get("ssl_ca_cert"):
1830	        client_kwargs["ssl_ca_cert"] = tls["ssl_ca_cert"]
1831	    if "ssl_verify" in tls:

... (gap) ...

1866	    """
1867	    if custom_providers is None:
1868	        try:
1869	            custom_providers = get_compatible_custom_providers(config)
1870	        except Exception:
1871	            custom_providers = []
1872	    if not base_url or not isinstance(custom_providers, list):
1873	        return {}
1874
1875	    target_url = normalize_route_base_url(base_url)
1876	    for entry in custom_providers:
1877	        if not isinstance(entry, dict):
1878	            continue
1879	        entry_url = normalize_route_base_url(entry.get("base_url"))
1880	        if not entry_url or entry_url != target_url:
1881	            continue
1882	        headers = normalize_extra_headers(entry.get("extra_headers"))
1883	        if headers:
1884	            return headers
1885	    return {}

... (gap) ...

1900
1901	    SECURITY: values may carry credentials — never log them.
1902	    """
1903	    extra_headers = get_custom_provider_extra_headers(base_url, custom_providers, config)
1904	    if not extra_headers:
1905	        return
1906	    merged = dict(client_kwargs.get("default_headers") or {})

... (gap) ...

1936	        return None
1937	    if custom_providers is None:
1938	        try:
1939	            custom_providers = get_compatible_custom_providers(config)
1940	        except Exception:
1941	            if config is None:
1942	                return None
1943	            raw = config.get("custom_providers")
1944	            custom_providers = raw if isinstance(raw, list) else []
1945	    if not isinstance(custom_providers, list):
1946	        return None
1947
1948	    target_url = normalize_route_base_url(base_url)
1949	    if not target_url:
1950	        return None
1951
1952	    for entry in custom_providers:
1953	        if not isinstance(entry, dict):
1954	            continue
1955	        entry_url = normalize_route_base_url(entry.get("base_url"))
1956	        if not entry_url or entry_url != target_url:
1957	            continue
1958	        models = entry.get("models")

... (gap) ...

1995	                # scans, and get_compatible_custom_providers shallow-copies
1996	                # each entry before normalizing, so the no-deepcopy cache is
1997	                # safe here (~135us saved per call on the blank-stub paths).
1998	                config = load_config_readonly()
1999	            custom_providers = get_compatible_custom_providers(config)
2000	        except Exception:
2001	            return None
2002	    if not isinstance(custom_providers, list):
2003	        return None
2004
2005	    target_url = normalize_route_base_url(base_url)
2006	    if not target_url:
2007	        return None
2008
2009	    for entry in custom_providers:
2010	        if not isinstance(entry, dict):
2011	            continue
2012	        entry_url = normalize_route_base_url(entry.get("base_url"))
2013	        if not entry_url or entry_url != target_url:
2014	            continue
2015	        models = entry.get("models")

... (gap) ...

2032	        version = int(value)
2033	    except (TypeError, ValueError):
2034	        return 0
2035	    return max(version, 0)
2036
2037
2038	def _raw_config_has_explicit_version() -> bool:
2039	    """True when config.yaml exists, parses, and carries a ``_config_version`` key.
2040
2041	    Distinguishes an ANCIENT config (explicit old version → refused by the
2042	    v12 support floor) from a fresh minimal/hand-written/cloned config with
2043	    no version key at all (→ migrated + stamped normally). Missing or
2044	    unparseable files return False so they never trip the floor gate.
2045	    """
2046	    config_path = get_config_path()
2047	    if not config_path.exists():
2048	        return False
2049	    try:
2050	        with open(config_path, encoding="utf-8") as f:
2051	            raw = fast_safe_load(f) or {}
2052	    except Exception:
2053	        return False
2054	    return isinstance(raw, dict) and "_config_version" in raw

... (gap) ...

2066
2067	    Returns (current_version, latest_version).
2068	    """
2069	    latest = _coerce_config_version(DEFAULT_CONFIG.get("_config_version", 1)) or 1
2070	    config_path = get_config_path()
2071	    if not config_path.exists():
2072	        return latest, latest
2073
2074	    try:
2075	        with open(config_path, encoding="utf-8") as f:
2076	            config = fast_safe_load(f) or {}
2077	    except Exception as e:
2078	        # Invalid YAML needs a parse warning, not an automatic schema rewrite
2079	        # that could replace the user's broken file with defaults.
2080	        _warn_config_parse_failure(config_path, e)
2081	        return latest, latest
2082
2083	    if not isinstance(config, dict):
2084	        config = {}
2085	    current = _coerce_config_version(config.get("_config_version"))
2086	    return current, latest
2087
2088

... (gap) ...

2159	    """
2160	    if config is None:
2161	        try:
2162	            config = load_config()
2163	        except Exception:
2164	            return [ConfigIssue("error", "Could not load config.yaml", "Run 'hermes setup' to create a valid config")]
2165
2166	    issues: List[ConfigIssue] = []
2167
2168	    # ── voice.submit_mode: direct | draft ────────────────────────────────
2169	    voice_cfg = config.get("voice")
2170	    if isinstance(voice_cfg, dict) and "submit_mode" in voice_cfg:
2171	        submit_mode = voice_cfg.get("submit_mode")
2172	        normalized_submit_mode = (
2173	            submit_mode.strip().lower() if isinstance(submit_mode, str) else None
2174	        )
```


> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

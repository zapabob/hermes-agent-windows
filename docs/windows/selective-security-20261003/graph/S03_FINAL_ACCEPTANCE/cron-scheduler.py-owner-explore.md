**Exploration: cron/scheduler.py**

Found 197 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`cron/scheduler.py`** — calls(calls), instantiates(instantiates), _get_hermes_home(calls), _get_home_target_chat_id(calls), _normalize_deliver_value(calls), _interpreter_shutting_down(calls), _get_home_target_thread_id(calls), _resolve_delivery_targets(calls), _run_job_script(calls), _abort_if_fire_claim_lost(calls), _teardown_cron_agent(calls), _fire_claim_ownership_lost(calls), _execution_home_for_job(calls), _resolve_origin(calls), _resolve_home_env_var(calls), +239 more

```python
1435	    the two sites cannot drift apart — the lock bound must stay at or above
1436	    the inactivity limit or waiters would fail while a healthy holder runs.
1437	    """
1438	    raw = os.getenv("HERMES_CRON_TIMEOUT", "").strip()
1439	    if not raw:
1440	        return 600.0
1441	    try:
1442	        return float(raw)
1443	    except (ValueError, TypeError):
1444	        logger.warning("Invalid HERMES_CRON_TIMEOUT=%r; using default 600s", raw)
1445	        return 600.0
1446
1447
1448	def _cwd_lock_timeout_seconds() -> float:
1449	    """Bound for the TERMINAL_CWD lock wait: inactivity limit + margin."""
1450	    inactivity = _cron_inactivity_seconds()
1451	    if inactivity <= 0:  # 0 = unlimited job runtime; keep the wait bounded.
1452	        inactivity = 600.0
1453	    return (
1454	        max(inactivity, _CWD_LOCK_TIMEOUT_FLOOR_SECONDS)
1455	        + _CWD_LOCK_TIMEOUT_MARGIN_SECONDS
1456	    )
1457
1458
1459	def _get_parallel_pool(max_workers: Optional[int]) -> concurrent.futures.ThreadPoolExecutor:
1460	    """Return (or create) the persistent parallel pool."""
1461	    global _parallel_pool, _parallel_pool_max_workers
1462	    if _parallel_pool is None or _parallel_pool_max_workers != max_workers:
1463	        if _parallel_pool is not None:
1464	            _parallel_pool.shutdown(wait=False, cancel_futures=False)
1465	        _parallel_pool = concurrent.futures.ThreadPoolExecutor(
1466	            max_workers=max_workers,
1467	            thread_name_prefix="cron-parallel",

... (gap) ...

1491	    """Shut down the persistent pools on process exit."""
1492	    global _parallel_pool, _parallel_pool_max_workers, _sequential_pool
1493	    if _parallel_pool is not None:
1494	        _parallel_pool.shutdown(wait=True, cancel_futures=False)
1495	        _parallel_pool = None
1496	        _parallel_pool_max_workers = None
1497	    if _sequential_pool is not None:
1498	        _sequential_pool.shutdown(wait=True, cancel_futures=False)
1499	        _sequential_pool = None
1500
1501
1502	atexit.register(_shutdown_parallel_pool)
1503	# Per-fire usage audit log for cron token spend instrumentation.
1504	# Resolves through _get_hermes_home() so profile-scoped paths work correctly.
1505	def _usage_audit_path() -> Path:
1506	    return _get_hermes_home() / "cron" / "usage_audit.jsonl"
1507
1508
1509	def _utcnow_iso_ms() -> str:
1510	    """RFC3339 UTC timestamp with millisecond precision and 'Z' suffix."""
1511	    now = datetime.now(timezone.utc)
1512	    # %f gives microseconds; trim to milliseconds.
1513	    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
1514
1515
1516	def _write_usage_audit(record: dict) -> None:
1517	    """Append a single JSONL line to ~/.hermes/cron/usage_audit.jsonl.
1518
1519	    NEVER raises — a logger bug must not break cron jobs. Wraps the entire
1520	    write (path resolve, mkdir, json.dumps, file append) in a single try.
1521	    """
1522	    try:
1523	        path = _usage_audit_path()
1524	        path.parent.mkdir(parents=True, exist_ok=True)
1525	        line = json.dumps(record, ensure_ascii=False)
1526	        with open(path, "a", encoding="utf-8") as f:
1527	            f.write(line + "\n")
1528	    except Exception as e:
1529	        logger.warning("usage_audit write failed: %s", e)
1530
1531
1532	def _interpreter_shutting_down(exc: Optional[BaseException] = None) -> bool:

... (gap) ...

1555	    """
1556	    from tools.interpreter_shutdown import interpreter_shutting_down
1557
1558	    return interpreter_shutting_down(exc)
1559
1560
1561	# Backward-compatible module override used by tests and emergency monkeypatches.

... (gap) ...

1571	    (its .env, config.yaml, scripts, skills). Do not freeze this at import or
1572	    anchor it at the shared default root — either re-breaks profile isolation.
1573	    """
1574	    return _hermes_home or get_hermes_home()
1575
1576
1577	def _job_needs_sequential_tick(job: dict) -> bool:
1578	    """Return True when a due job mutates process-global Hermes state."""
1579	    if (job.get("workdir") or "").strip():
1580	        return True
1581	    profile = str(job.get("profile") or "").strip()
1582	    return bool(profile)
1583
1584
1585	def _execution_home_for_job(job: dict | None) -> Path:
1586	    """Resolve the Hermes home a job must execute under.
1587
1588	    A missing profile follows the scheduler's active home. Explicit
1589	    ``default`` selects the canonical default root. Any other name must
1590	    resolve to a real profile directory under the profiles root.
1591	    """
1592	    profile = str((job or {}).get("profile") or "").strip()
1593	    if not profile:
1594	        return _get_hermes_home()
1595	    if profile.lower() == "default":
1596	        return get_default_hermes_root()
1597
1598	    from hermes_cli.profiles import (
1599	        get_profile_dir,
1600	        normalize_profile_name,
1601	        profile_exists,
1602	        validate_profile_name,
1603	    )
1604
1605	    canonical_profile = normalize_profile_name(profile)
1606	    validate_profile_name(canonical_profile)
1607	    if not profile_exists(canonical_profile):
1608	        raise ValueError(f"Cron profile {canonical_profile!r} does not exist")
1609
1610	    profiles_root = (get_default_hermes_root() / "profiles").resolve()
1611	    profile_home = get_profile_dir(canonical_profile).resolve()
1612	    try:
1613	        profile_home.relative_to(profiles_root)
1614	    except ValueError as exc:

... (gap) ...

1630	            _profile_home_guard_depth.reset(token)
1631	        return
1632
1633	    profile = str(job.get("profile") or "").strip()
1634	    holds_write = bool(profile)
1635	    if holds_write:
1636	        _profile_home_lock.acquire_write()
1637	    else:
1638	        _profile_home_lock.acquire_read()
1639	    token = _profile_home_guard_depth.set(1)
1640	    try:
1641	        yield
1642	    finally:
1643	        _profile_home_guard_depth.reset(token)
1644	        if holds_write:
1645	            _profile_home_lock.release_write()
1646	        else:
1647	            _profile_home_lock.release_read()
1648
1649
1650	@contextlib.contextmanager
1651	def _cron_profile_context(job: dict):
1652	    """Temporarily switch HERMES_HOME for profile-pinned cron jobs."""
1653	    global _hermes_home
1654
1655	    profile_name = str(job.get("profile") or "").strip()
1656	    if not profile_name:
1657	        yield
1658	        return
1659
1660	    try:
1661	        from hermes_cli.profiles import normalize_profile_name
1662
1663	        canon = normalize_profile_name(profile_name)
1664	        home = _execution_home_for_job(job)
1665	    except ValueError as exc:
1666	        logger.error(
1667	            "Job '%s': refusing invalid or missing profile %r (%s)",
1668	            job.get("id"),
1669	            profile_name,
1670	            exc,
1671	        )
1672	        raise
1673
1674	    prior_home = _hermes_home
1675	    prior_env = os.environ.get("HERMES_HOME")
1676	    from hermes_cli.env_loader import remember_launch_profile_home
1677	    from hermes_constants import get_process_hermes_home
1678	    remember_launch_profile_home(get_process_hermes_home())
1679	    home_override_token = set_hermes_home_override(home)
1680	    _hermes_home = home
1681	    os.environ["HERMES_HOME"] = str(home)
1682	    logger.info(
1683	        "Job '%s': switched to profile %r (%s)",
1684	        job.get("id"),
1685	        canon,
1686	        home,
1687	    )
1688	    try:
1689	        yield
1690	    finally:
1691	        _hermes_home = prior_home
1692	        if prior_env is None:
1693	            os.environ.pop("HERMES_HOME", None)
1694	        else:
1695	            os.environ["HERMES_HOME"] = prior_env
1696	        reset_hermes_home_override(home_override_token)
1697
1698
1699	def _scripts_dir_for_job(job: dict | None) -> Path:
1700	    """Resolve the scripts directory for a cron job.
1701
1702	    A named profile selects its validated profile home, explicit ``default``
1703	    selects the canonical default root, and a missing profile follows the
1704	    scheduler's active home. Named resolution is derived from the immutable
1705	    job field rather than mutable process-global profile context.
1706	    """
1707	    scripts_dir = _execution_home_for_job(job) / "scripts"
1708	    scripts_dir.mkdir(parents=True, exist_ok=True)
1709	    return scripts_dir
1710
1711
1712	def _get_lock_paths() -> tuple[Path, Path]:
1713	    """Resolve cron lock paths at call time so profile/env changes are honored."""
1714	    hermes_home = _get_hermes_home()
1715	    lock_dir = hermes_home / "cron"
1716	    return lock_dir, lock_dir / ".tick.lock"
1717

... (gap) ...

1751	    """
1752	    if isinstance(exc, OSError) and exc.errno in (errno.EMFILE, errno.ENFILE):
1753	        return True
1754	    return _is_fd_exhaustion_text(str(exc))
1755
1756
1757	def _reclaim_fds_best_effort() -> None:

... (gap) ...

1772	    try:
1773	        import gc
1774
1775	        gc.collect()
1776	    except Exception:
1777	        pass
1778	    try:
1779	        from hermes_cli.resource_limits import apply_nofile_soft_limit
1780
1781	        apply_nofile_soft_limit(None)
1782	    except Exception:
1783	        pass
1784

... (gap) ...

1818	            raw = sub.get("cron_continuable_surface")
1819	        else:
1820	            raw = extra.get("cron_continuable_surface")
1821	        if raw is not None and str(raw).strip().lower() == "in_channel":
1822	            return "in_channel"
1823	    except Exception:
1824	        pass

... (gap) ...

1881	        return per_job
1882	    try:
1883	        if cfg is None:
1884	            cfg = load_config() or {}
1885	        return bool((cfg.get("cron", {}) or {}).get("mirror_delivery", False))
1886	    except Exception:
1887	        return False
1888

... (gap) ...

1967	    future callers stay self-contained.
1968	    """
1969	    if origin_match is None:
1970	        origin = _resolve_origin(job) or {}
1971	        origin_match = _target_matches_origin(
1972	            origin, target.get("platform", ""), target.get("chat_id", ""),
1973	            target.get("thread_id"),
1974	        )

... (gap) ...

2035	    """
2036	    if not enabled:
2037	        return
2038	    text = (mirror_text or "").strip()
2039	    if not text:
2040	        return
2041	    try:
2042	        from gateway.mirror import mirror_to_session
2043
2044	        # Mirror as a USER turn with a labelled prefix, NOT an assistant turn.
2045	        # The brief is not the agent speaking; an assistant-role mirror lands as
2046	        # assistant→assistant after the agent's last turn and breaks strict
2047	        # alternation (issue #2221, the exact failure #2313 removed). A
2048	        # user-role turn collapses safely via repair_message_sequence's
2049	        # consecutive-user merge on every provider, and the prefix preserves the
2050	        # "this came from cron" context that the dropped SQLite mirror metadata
2051	        # would otherwise lose on replay.
2052	        ok = mirror_to_session(
2053	            platform_name,
2054	            str(chat_id),
2055	            f"[Cron delivery: {job.get('name') or job.get('id', 'cron')}]\n{text}",

... (gap) ...

2099	        from agent.async_utils import safe_schedule_threadsafe
2100
2101	        coro = create_thread(str(chat_id), thread_name)
2102	        future = safe_schedule_threadsafe(coro, loop)  # type: ignore[arg-type]
2103	        if future is None:
2104	            return None
2105	        new_thread_id = future.result(timeout=30)
2106	        return str(new_thread_id) if new_thread_id else None
2107	    except Exception as e:
2108	        logger.debug(

... (gap) ...

2154	    ``_session_store`` handle rather than the gateway object. Best-effort — a
2155	    delivery that already succeeded is never failed by a seeding problem.
2156	    """
2157	    text = (mirror_text or "").strip()
2158	    if not text:
2159	        return
2160	    try:
2161	        from gateway.config import Platform
2162	        from gateway.session import SessionSource
2163
2164	        seeded_session_id: Optional[str] = None
2165	        session_store = getattr(adapter, "_session_store", None)
2166	        if session_store is not None:
2167	            try:
2168	                platform_enum = Platform(platform_name.lower())
2169	            except (ValueError, KeyError):
2170	                platform_enum = None
2171	            if platform_enum is not None:
2172	                # Discord thread destinations must key on the thread's OWN id
2173	                # to match how the Discord adapter keys organic in-thread
2174	                # messages (chat_id == thread_id). Other platforms (Slack,
2175	                # Telegram) use chat_id == parent_channel for thread messages,
2176	                # so the parent chat_id is correct for them. See the matching
2177	                # guard in GatewayRunner._process_handoff.
2178	                if platform_enum == Platform.DISCORD:
2179	                    seed_chat_id = str(thread_id)
2180	                else:
2181	                    seed_chat_id = str(chat_id)
2182	                dest_source = SessionSource(
2183	                    platform=platform_enum,
2184	                    chat_id=seed_chat_id,
2185	                    chat_name=chat_name,

... (gap) ...

2196	                # Capture the exact id — the mirror writes into THIS row, not
2197	                # an origin-heuristic rediscovery (which bails on populated
2198	                # chats; same class as the flat-seed live failure 2026-08-19).
2199	                _entry = session_store.get_or_create_session(dest_source)
2200	                seeded_session_id = getattr(_entry, "session_id", None)
2201
2202	        from gateway.mirror import mirror_to_session
2203
2204	        # User-role + labelled prefix (see _maybe_mirror_cron_delivery): the
2205	        # seeded brief must not read as an assistant turn, or the user's first
2206	        # in-thread reply produces assistant→user→... off a phantom assistant
2207	        # message. Pass the seed user_id so the mirror resolves the exact
2208	        # thread-keyed session row we just created.
2209	        ok = mirror_to_session(
2210	            platform_name,
2211	            str(chat_id),
2212	            f"[Cron delivery: {job.get('name') or job.get('id', 'cron')}]\n{text}",

... (gap) ...

2222	                job.get("id", "?"), thread_id, platform_name, chat_id,
2223	            )
2224	        else:
2225	            logger.warning(
2226	                "Job '%s': thread seed did NOT land on %s:%s thread=%s — an "
2227	                "in-thread reply will not see this brief",
2228	                job.get("id", "?"), platform_name, chat_id, thread_id,
2229	            )
2230	    except Exception as e:
2231	        # WARNING, not debug: a silent seed failure IS the continuation-
2232	        # amnesia bug (Alice 2026-08-19) — it must be visible in production.
2233	        logger.warning(
2234	            "Job '%s': seeding cron thread session failed for %s:%s:%s: %s",
2235	            job.get("id", "?"), platform_name, chat_id, thread_id, e,
2236	        )

... (gap) ...

2281	    (caller falls back to the plain mirror). Best-effort — a delivery that
2282	    already succeeded is never failed by a seeding problem.
2283	    """
2284	    text = (mirror_text or "").strip()
2285	    if not text:
2286	        return False
2287	    try:
2288	        from gateway.config import Platform
2289	        from gateway.session import SessionSource
2290
2291	        chat_type = "dm" if is_dm else "group"
2292	        session_store = getattr(adapter, "_session_store", None)
2293	        seeded_session_id: Optional[str] = None
2294	        if session_store is not None:
2295	            try:
2296	                platform_enum = Platform(platform_name.lower())
2297	            except (ValueError, KeyError):
2298	                platform_enum = None
2299	            if platform_enum is not None:
2300	                dest_source = SessionSource(
2301	                    platform=platform_enum,
2302	                    chat_id=str(chat_id),
2303	                    chat_name=chat_name,

... (gap) ...

2315	                # re-discover it via origin heuristics (which bail out on
2316	                # populated chats where the flat session coexists with
2317	                # per-message thread sessions — live failure, Alice 2026-08-19).
2318	                _entry = session_store.get_or_create_session(dest_source)
2319	                seeded_session_id = getattr(_entry, "session_id", None)
2320
2321	        from gateway.mirror import mirror_to_session
2322
2323	        ok = mirror_to_session(
2324	            platform_name,
2325	            str(chat_id),
2326	            f"[Cron delivery: {job.get('name') or job.get('id', 'cron')}]\n{text}",

... (gap) ...

2340	        # WARNING, not debug: a silent seed failure IS the "agent has no idea
2341	        # about its own brief" bug (Alice 2026-08-19) — it must be visible in
2342	        # production logs.
2343	        logger.warning(
2344	            "Job '%s': seeding in_channel session failed for %s:%s: %s",
2345	            job.get("id", "?"), platform_name, chat_id, e,
2346	        )

... (gap) ...

2365	        value = origin.get(key)
2366	        if value is None:
2367	            continue
2368	        text = str(value).replace("\r", " ").replace("\n", " ").strip()
2369	        if text:
2370	            fields.append(f"origin_{key}={text[:200]!r}")
2371	    return " " + " ".join(fields) if fields else ""
2372
2373
2374	def _plugin_cron_env_var(platform_name: str) -> str:
2375	    """Return the cron home-channel env var registered by a plugin platform.
2376
2377	    Falls through the platform registry so plugins that set
2378	    ``cron_deliver_env_var`` on their ``PlatformEntry`` get cron delivery
2379	    support without editing this module.
2380	    """
2381	    try:
2382	        from hermes_cli.plugins import discover_plugins
2383	        discover_plugins()  # idempotent
2384	        from gateway.platform_registry import platform_registry
2385	        entry = platform_registry.get(platform_name.lower())
2386	        if entry and entry.cron_deliver_env_var:

... (gap) ...

2400	    name = platform_name.lower()
2401	    if name in _KNOWN_DELIVERY_PLATFORMS:
2402	        return True
2403	    return bool(_plugin_cron_env_var(name))
2404
2405
2406	def _resolve_home_env_var(platform_name: str) -> str:
2407	    """Return the env var name for a platform's cron home channel.
2408
2409	    Built-in platforms are in ``_HOME_TARGET_ENV_VARS``; plugin platforms are
2410	    resolved from the platform registry.
2411	    """
2412	    name = platform_name.lower()
2413	    env_var = _HOME_TARGET_ENV_VARS.get(name)
2414	    if env_var:
2415	        return env_var
2416	    return _plugin_cron_env_var(name)
2417
2418
2419	def _get_config_home_channel(platform_name: str):

... (gap) ...

2432	    try:
2433	        from gateway.config import load_gateway_config, Platform
2434
2435	        config = load_gateway_config()
2436	        platform = Platform(platform_name.lower())
2437	        return config.get_home_channel(platform)
2438	    except Exception:
2439	        logger.debug(
2440	            "config home_channel lookup failed for platform %r",
2441	            platform_name, exc_info=True,
2442	        )
2443	        return None
2444
2445
2446	def _env_home_target_chat_id(platform_name: str) -> str:
2447	    """Return the home chat id from the legacy env mirror only (no config)."""
2448	    env_var = _resolve_home_env_var(platform_name)
2449	    if not env_var:
2450	        return ""
2451	    value = os.getenv(env_var, "")
2452	    if not value:
2453	        legacy = _LEGACY_HOME_TARGET_ENV_VARS.get(env_var)
2454	        if legacy:
2455	            value = os.getenv(legacy, "")
2456	    return value
2457
2458
2459	def _get_home_target_chat_id(platform_name: str) -> str:
2460	    """Return the configured home target chat/room ID for a delivery platform.
2461
2462	    Resolution order: platform env var (legacy mirror, kept first so an
2463	    operator override keeps winning) → legacy env var name → the canonical
2464	    ``home_channel`` block persisted in config.yaml by ``/sethome``.
2465	    """
2466	    value = _env_home_target_chat_id(platform_name)
2467	    if value:
2468	        return value
2469	    home = _get_config_home_channel(platform_name)
2470	    if home is not None and home.chat_id:
2471	        return str(home.chat_id)
2472	    return ""

... (gap) ...

2483	    cron at a dedicated topic via this env var lets replies work as expected
2484	    without changing the lobby invariant.
2485	    """
2486	    env_var = _resolve_home_env_var(platform_name)
2487	    if platform_name.lower() == "telegram":
2488	        cron_thread = os.getenv("TELEGRAM_CRON_THREAD_ID", "").strip()
2489	        if cron_thread:
2490	            return cron_thread
2491	    value = os.getenv(f"{env_var}_THREAD_ID", "").strip() if env_var else ""
2492	    if not value and env_var:
2493	        legacy = _LEGACY_HOME_TARGET_ENV_VARS.get(env_var)
2494	        if legacy:
2495	            value = os.getenv(f"{legacy}_THREAD_ID", "").strip()
2496	    if value:
2497	        return value
2498	    # Canonical config.yaml fallback — same rationale as
2499	    # _get_home_target_chat_id, and thread affinity only applies when the
2500	    # chat itself resolved from the same config block (an env-provided chat
2501	    # id keeps its env-provided thread semantics).
2502	    if not _env_home_target_chat_id(platform_name):
2503	        home = _get_config_home_channel(platform_name)
2504	        if home is not None and home.thread_id:
2505	            return str(home.thread_id)
2506	    return None
2507
2508
2509	def _iter_home_target_platforms():
2510	    """Iterate built-in + plugin platform names that expose a home channel.
2511
2512	    Used by the ``deliver=origin`` fallback when the job has no origin.
2513	    """
2514	    for name in _HOME_TARGET_ENV_VARS:
2515	        yield name
2516	    try:
2517	        from hermes_cli.plugins import discover_plugins
2518	        discover_plugins()  # idempotent
2519	        from gateway.platform_registry import platform_registry
2520	        for entry in platform_registry.plugin_entries():
2521	            if entry.cron_deliver_env_var and entry.name not in _HOME_TARGET_ENV_VARS:
2522	                yield entry.name
2523	    except Exception:

... (gap) ...

2542	    try:
2543	        from gateway.relay import relay_fronted_platforms
2544
2545	        return relay_fronted_platforms()
2546	    except Exception:
2547	        logger.debug("relay fronted-platform lookup failed", exc_info=True)
2548	        return set()

... (gap) ...

2566	    try:
2567	        from gateway.config import load_gateway_config
2568
2569	        gateway_config = load_gateway_config()
2570	        connected = {p.value for p in gateway_config.get_connected_platforms()}
2571	        connected |= _relay_fronted_delivery_platforms(connected)
2572	    except Exception:
2573	        logger.debug("cron_delivery_targets: gateway config unavailable", exc_info=True)
2574	        connected = set()
2575
2576	    for name in _iter_home_target_platforms():
2577	        if name not in connected:
2578	            continue
2579	        if not _is_known_delivery_platform(name):
2580	            continue
2581	        env_var = _resolve_home_env_var(name)
2582	        targets.append(
2583	            {
2584	                "id": name,
2585	                "name": name.replace("_", " ").title(),
```


> **Explore budget: 3 calls for this project (9,025 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

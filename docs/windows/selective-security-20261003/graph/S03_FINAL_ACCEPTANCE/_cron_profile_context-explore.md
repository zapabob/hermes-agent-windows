**Exploration: _cron_profile_context**

Found 1 symbol across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `ProfileContext` (web/src/contexts/profile-context.ts:14) — 2 callers in `web/src/contexts/ProfileProvider.tsx`, `web/src/contexts/useProfileScope.ts`; no tests found within 3 caller hops
- `_cron_profile_home` (hermes_cli/web_server.py:13223) — 10 callers in `hermes_cli/web_server.py`; tested via callers: `tests/hermes_cli/test_web_server.py`, `tests/hermes_cli/test_web_server_cron_profiles.py` +1
- `_cron_profile_dicts` (hermes_cli/web_server.py:13177) — 4 callers in `hermes_cli/web_server.py`; tests: `tests/hermes_cli/test_cron_profile_enumeration_lightweight.py`
- `profile` (gateway/pairing.py:484) — 1 caller in `plugins/memory/supermemory/__init__.py`; tested via callers: `tests/plugins/memory/test_supermemory_provider.py`

**Relationships**

**calls:**
- _cron_profile_home → strip
- _cron_profile_home → _cron_default_profile
- _fs_download_path → _cron_profile_home
- _open_session_db_for_profile → _cron_profile_home
- _prune_sessions → _cron_profile_home
- _call_cron_for_profile → _cron_profile_home
- _notify_cron_provider_for_profile → _cron_profile_home
- _create_cron_job_sync → _cron_profile_home
- _update_cron_job_sync → _cron_profile_home
- _fire_cron_job_for_profile → _cron_profile_home
- _forward_cron_fire_to_gateway → _cron_profile_home
- _gateway_intentionally_stopped → _cron_profile_home
- _extract_v4a_patch_paths → strip
- should_auto_approve_edit → strip
- _run_setup → strip
- ... and 105 more

**references:**
- _cron_profile_dicts → _log
- _notify_cron_provider_for_profile → _log
- _list_cron_jobs_sync → _log
- _create_cron_job_sync → _log
- _forward_cron_fire_to_gateway → _log

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`cron/scheduler.py`** — calls(calls), _cron_profile_context(function), strip(calls), set_hermes_home_override(calls), reset_hermes_home_override(calls)

```python
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
```

**Not shown above — explore these names for their source**

- web/src/contexts/profile-context.ts: ProfileContext:14, ProfileContextValue:3
- hermes_cli/web_server.py: _cron_profile_home:13223, _cron_profile_dicts:13177, _cron_default_profile:13203, _fs_download_path:2946, _open_session_db_for_profile:12805, _prune_sessions:12899, +16 more
- apps/desktop/src/app/contrib/surfaces.tsx: cron:177
- gateway/pairing.py: profile:484, PairingStore:435, __init__:451, _pending_path:488, _approved_path:491, _rate_limit_path:494, +18 more
- acp_adapter/server.py: _named_custom_provider_catalogs:90, _resource_display_name:258, _is_text_resource:273, _is_image_resource:280, _path_from_file_uri:307, _resource_link_to_parts:378, +1 more
- plugins/memory/supermemory/__init__.py: get_profile:368
- acp_adapter/edit_approval.py: _extract_v4a_patch_paths:131, should_auto_approve_edit:200
- acp_adapter/entry.py: _run_setup:165, main:220
- hermes_constants.py: set_hermes_home_override:30, reset_hermes_home_override:40
- apps/desktop/src/components/ui/glyph-spinner.test.tsx: strip:33
- ... and 12 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,025 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

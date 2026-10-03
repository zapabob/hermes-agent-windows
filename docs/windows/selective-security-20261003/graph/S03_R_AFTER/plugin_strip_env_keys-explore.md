**Exploration: plugin_strip_env_keys**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `plugin_strip_env_keys` (agent/terminal_env_registry.py:69) — 1 caller in `tools/environments/local_env_policy.py`; tested via callers: `tests/test_subprocess_home_isolation.py`, `tests/tools/test_env_passthrough.py` +37
- `keys` (apps/desktop/src/lib/lru-cache.ts:64) — 221 callers in `acp_adapter/session.py`, `apps/desktop/electron/backend-env.ts`, `apps/desktop/electron/connection-config.ts`, `apps/desktop/electron/connection-registry.ts` +99 more; tests: `apps/desktop/electron/connection-registry.test.ts`, `apps/desktop/electron/crash-forensics.test.ts`, `apps/desktop/electron/native-token-store.test.ts`, `apps/desktop/electron/profile-migration.test.ts` +60

**Relationships**

**calls:**
- plugin_strip_env_keys → values
- _plugin_terminal_env_strip_keys → plugin_strip_env_keys
- list_sessions → values
- _iter_httpx_pools_with_owner → values
- _resolve_nous_branch → values
- shutdown_cached_clients → values
- _flush_current → values
- _contains_image → values
- _settled_output → values
- _accepts_keyword → values
- _reader_loop → values
- get_status → values
- _shutdown_async → values
- _has_var_kwargs → values
- _provider_memory_write_metadata_mode → values
- ... and 130 more

**references:**
- plugin_strip_env_keys → _registry
- plugin → HermesPlugin
- HermesPlugin → PluginContext
- loadRuntimePlugin → HermesPlugin
- plugin → HermesPlugin
- _strip_ref_siblings → strip
- strip → attachRead
- run_once → KEYS
- main → KEYS
- run_once → DEFAULT_STATE_DB
- main → DEFAULT_LOG
- main → DEFAULT_TUI_DIR

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`agent/terminal_env_registry.py`** — plugin_strip_env_keys(function), _registry(variable)

```python
1	"""Terminal Environment Registry.
2
3	Central map of registered pluggable terminal backends, populated by plugins via
4	:meth:`PluginContext.register_terminal_environment_provider` and consumed by
5	:func:`tools.terminal_tool_backends._create_environment` plus the classification helpers across the
6	terminal/file/approval/prompt surfaces. Unlike the image/video/web/browser registries there
7	is **no active-provider resolution**: the active backend is whatever ``TERMINAL_ENV`` /
8	``terminal.backend`` names. Built-in names are reserved (registration raises) so a plugin can
9	never shadow the in-tree docker/modal/... implementations. Scope semantics mirror
10	:mod:`agent.browser_registry` (per-profile scope or the global base map).
11	"""
12
13	from __future__ import annotations
14
15	import logging
16	from typing import List, Optional
17
18	from agent.provider_registry import ProviderRegistry, lower_key
19	from agent.terminal_env_provider import TerminalEnvironmentProvider
20
21	logger = logging.getLogger(__name__)
22
23
24	#: Names owned by in-tree backends in tools/environments/ — never
25	#: registrable by plugins. Includes internal-mode aliases (managed_modal).
26	BUILTIN_BACKEND_NAMES = frozenset({
27	    "local", "docker", "singularity", "modal", "managed_modal",
28	    "daytona", "vercel_sandbox", "ssh",
29	})
30
31
32	def _reject_builtin_collision(name: str) -> None:
33	    raise ValueError(f"Terminal backend name '{name}' is reserved for the built-in {name} backend "
34	                     "and cannot be registered by a plugin")
35
36
37	_registry: ProviderRegistry[TerminalEnvironmentProvider] = ProviderRegistry(
38	    label="Terminal environment",
39	    provider_cls=TerminalEnvironmentProvider,
40	    logger=logger,
41	    normalize=lower_key,
42	    builtin_names=BUILTIN_BACKEND_NAMES,
43	    on_builtin_collision=_reject_builtin_collision,
44	)
45	_registry.export(globals())
46
47
48	def plugin_backend_names(*, scope: Optional[str] = None) -> List[str]:
49	    """Names of all registered plugin backends (sorted)."""
50	    return [p.name.strip().lower() for p in _registry.list_providers(scope=scope)]
51
52
53	def provider_flag(name: str, attr: str, default=False):
54	    """Read a classification attribute off the provider for *name*.
55
56	    Fail-soft: unknown backend or a raising property returns *default* so a misbehaving
57	    plugin degrades to built-in-equivalent behavior instead of taking the terminal tool down.
58	    """
59	    provider = _registry.get_provider(name)
60	    if provider is None:
61	        return default
62	    try:
63	        return getattr(provider, attr, default)
64	    except Exception:
65	        logger.debug("Terminal environment provider '%s' attribute '%s' raised", name, attr, exc_info=True)
66	        return default
67
68
69	def plugin_strip_env_keys() -> frozenset:
70	    """Union of every registered provider's ``strip_env_keys`` — across ALL scopes, not
71	    just the active backend: a token in the process environment is strippable regardless of
72	    which backend is selected (as MODAL_*/DAYTONA_API_KEY sit in the static tier-1 set)."""
73	    keys: set = set()
74	    with _registry._lock:
75	        all_providers = list(_registry._providers.values())
76	        for scoped in _registry._scoped_providers.values():
77	            all_providers.extend(scoped.values())
78	    for provider in all_providers:
79	        try:
80	            keys.update(provider.strip_env_keys)
81	        except Exception:
82	            logger.debug("Terminal environment provider strip_env_keys raised", exc_info=True)
83	    return frozenset(keys)
84
85
86	# ---- BEGIN PLUGIN-COMPAT (revert-scheduled; see COMPAT_MANIFEST.md) ----
87	# Names external plugins imported from this module before the Sep 2026 decomposition.
88	# Internal code MUST NOT use these (scripts/check_compat_pointers.py fails CI if it does).
89	# The whole block is removed by reverting the commit that added it.
90	from typing import Dict  # noqa: F401,E402
91	import threading  # noqa: F401,E402
92
93
94	_PLUGIN_COMPAT_LAZY = {
95	    'hermes_home_key': ('hermes_constants', 'hermes_home_key'),
96	}
97
98
99	def __getattr__(name):  # PEP 562 — lazy so no import cycles
100	    target = _PLUGIN_COMPAT_LAZY.get(name)
101	    if target is None:
102	        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
103	    import importlib
104	    from hermes_cli.plugin_compat import warn_once
105	    warn_once(__name__, name, *target)
106	    return getattr(importlib.import_module(target[0]), target[1])
107	# ---- END PLUGIN-COMPAT ----
```

**Not shown above — explore these names for their source**

- scripts/profile-tui.py: KEYS:56, run_once:405, main:476, pick_longest_session:65, drain:76, hold_key:94, +8 more
- apps/desktop/src/lib/lru-cache.ts: keys:64, LruCache:11, set:46
- tools/schema_sanitizer.py: strip:112, _strip_ref_siblings:110
- apps/desktop/electron/main.ts: cacheTitle:5639, resolveFaviconCached:5985, closePreviewWatchers:6320, headersForRemoteRequest:9149, sanitizeConnectionProfiles:9183, sanitizeRegistryConnection:9489, +6 more
- acp_adapter/model_catalog.py: _named_custom_provider_catalogs:19, _entry_catalog:52, _semantic_provider:99, _empty_catalog_applies:108, encode_model_choice:146, add_inventory_rows:189, +2 more
- acp_adapter/server.py: _flatten_history_text:51, _history_replay_updates:124, _build_model_state:291, _rewrite_prompt_for_interrupt:667, prompt:776, set_session_mode:941
- apps/desktop/electron/connection-registry.ts: normalizeConnectionInput:839, normalizeRegistry:1068, migrateV1ToRegistry:1236
- apps/desktop/electron/plugin-compat-notice.ts: reportKey:36, readReport:44, pendingNotice:102
- agent/auxiliary_client.py: _resolve_nous_branch:4426, shutdown_cached_clients:5286, _normalize_aux_provider:555, _bare_model:578, _codex_route_bare_model:619, _fast_model_from_catalog:683, +26 more
- acp_adapter/session.py: list_sessions:193, _normalize_cwd_for_compare:33, _build_session_title:57, _updated_at_sort_key:71, _first_user_preview:126
- ... and 49 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

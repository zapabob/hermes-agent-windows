**Exploration: plugin_strip_env_keys**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `plugin_strip_env_keys` (agent/terminal_env_registry.py:69) — 1 caller in `tools/environments/local_env_policy.py`; tested via callers: `tests/tools/test_env_passthrough.py`, `tests/tools/test_local_env_blocklist.py` +48
- `strip` (tools/schema_sanitizer.py:116) — 1 caller in `tools/schema_sanitizer.py`; no tests found within 3 caller hops

**Relationships**

**calls:**
- plugin_strip_env_keys → values
- _plugin_terminal_env_strip_keys → plugin_strip_env_keys
- list_sessions → values
- _iter_httpx_pools_with_owner → values
- _settled_output → values
- _accepts_keyword → values
- _reader_loop → values
- get_status → values
- _release_async → values
- _detach_roots → values
- _shutdown_async → values
- enable_happy_eyeballs_on_client → values
- list_providers → values
- shutdown_all → values
- _pop_dispatchable → values
- ... and 145 more

**references:**
- plugin_strip_env_keys → _registry
- plugin → HermesPlugin
- HermesPlugin → PluginContext
- loadRuntimePlugin → HermesPlugin
- strip → _REF_FORBIDDEN_SIBLINGS
- _strip_ref_siblings → strip
- _strip_ref_siblings → _REF_FORBIDDEN_SIBLINGS
- object → Fields
- identity → Fields
- request → Fields
- decodeChannelManifest → packageEntry
- collapse_const_unions → collapse
- strip_nullable_unions → collapse

**instantiates:**
- object → Fields
- head → Fields
- decodeChannelRecord → Fields
- packageEntry → Fields
- decodeChannelManifest → Fields

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
```

**Not shown above — explore these names for their source**

- tools/schema_sanitizer.py: strip:116, _strip_ref_siblings:114, _REF_FORBIDDEN_SIBLINGS:111, _rewrite:29, _sanitize_single_tool:86, collapse:158, +7 more
- apps/desktop/src/lib/lru-cache.ts: keys:64, LruCache:11, set:46, constructor:15
- scripts/releases/channels.py: keys:75, R2ChannelStore:29, list:324
- apps/desktop/electron/updater/channel-protocol.ts: keys:150, Fields:138, constructor:140, get:147, text:153, integer:166, +9 more
- scripts/releases/r2.py: canonical_query:59, signed_request:222, amz_timestamp:152, parse_list_xml:724, text:168
- scripts/releases/r2_scope.py: listing_prefix:48, bucket_url:58, logical_key:53
- cron/scheduler.py: get_running_job_ids:695, get_running_job_details:707, get_restart_wait_cron_counts:766
- acp_adapter/session.py: list_sessions:210, end_all_sessions:276
- ui-tui/src/hooks/useVirtualHistory.ts: useVirtualHistory:138, pruneVirtualHeightCache:65
- apps/desktop/electron/link-metadata.ts: cacheTitle:53, resolveFaviconCached:431
- ... and 74 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

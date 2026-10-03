**Exploration: plugin_strip_env_keys**

Found 4 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `plugin_strip_env_keys` (agent/terminal_env_registry.py:148) — 1 caller in `tools/environments/local.py`; tested via callers: `tests/test_subprocess_home_isolation.py`, `tests/tools/test_env_passthrough.py` +5
- `PLUGIN` (plugins/airi/core.py:30) — 2 callers in `plugins/airi/core.py`; tested via callers: `tests/plugins/test_airi_sync.py`

**Relationships**

**calls:**
- plugin_strip_env_keys → values
- _plugin_terminal_env_strip_keys → plugin_strip_env_keys
- list_sessions → values
- resolve_provider_client → values
- shutdown_cached_clients → values
- _accepts_keyword → values
- _reader_loop → values
- _shutdown_async → values
- _provider_sync_accepts_messages → values
- _provider_memory_write_metadata_mode → values
- _iter_nested_dicts → values
- shutdown_plugin_stream_hook_dispatcher → values
- _plugin_patterns → values
- shutdown_all → values
- total_tools → values
- ... and 107 more

**references:**
- plugin_strip_env_keys → _scoped_providers
- plugin_strip_env_keys → _providers
- plugin_strip_env_keys → _lock
- plugin → HermesPlugin
- HermesPlugin → PluginContext
- loadRuntimePlugin → HermesPlugin
- plugin → HermesPlugin
- _cfg → PLUGIN
- status → PLUGIN
- status → HERMES_AIRI_HOME
- _probe_hermes → status
- strip → attachRead
- run_once → KEYS
- main → KEYS
- run_once → DEFAULT_STATE_DB
- ... and 4 more

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`agent/terminal_env_registry.py`** — plugin_strip_env_keys(function), _scoped_providers(variable), _providers(variable), _lock(variable)

```python
1	"""
2	Terminal Environment Registry
3	=============================
4
5	Central map of registered pluggable terminal backends. Populated by plugins
6	at load time via :meth:`PluginContext.register_terminal_environment_provider`;
7	consumed by :func:`tools.terminal_tool._create_environment` and the
8	classification helpers spread across the terminal/file/approval/prompt
9	surfaces.
10
11	Unlike the image/video/web/browser registries there is **no active-provider
12	resolution here**: the active backend is whatever ``TERMINAL_ENV`` /
13	``terminal.backend`` names, exactly as for built-in backends. The registry's
14	only job is mapping that name to a provider instance (and answering the
15	classification questions the core historically answered with frozensets of
16	built-in names).
17
18	Built-in backend names are reserved — :func:`register_provider` rejects a
19	provider whose ``name`` collides with one, so a plugin can never shadow the
20	in-tree docker/modal/... implementations.
21
22	Mirrors :mod:`agent.browser_registry` scope semantics: providers register
23	into a per-profile scope (multiplexed gateways) or the global base map.
24	"""
25
26	from __future__ import annotations
27
28	import logging
29	import threading
30	from typing import Dict, List, Optional
31
32	from agent.terminal_env_provider import TerminalEnvironmentProvider
33	from hermes_constants import hermes_home_key
34
35	logger = logging.getLogger(__name__)
36
37
38	#: Names owned by in-tree backends in tools/environments/ — never
39	#: registrable by plugins. Includes internal-mode aliases (managed_modal).
40	BUILTIN_BACKEND_NAMES = frozenset({
41	    "local", "docker", "singularity", "modal", "managed_modal",
42	    "daytona", "vercel_sandbox", "ssh",
43	})
44
45
46	_providers: Dict[str, TerminalEnvironmentProvider] = {}
47	_scoped_providers: Dict[str, Dict[str, TerminalEnvironmentProvider]] = {}
48	_generation = 0
49	_scoped_generations: Dict[str, int] = {}
50	_lock = threading.Lock()
51
52
53	def register_provider(
54	    provider: TerminalEnvironmentProvider, *, scope: Optional[str] = None
55	) -> None:
56	    """Register a terminal environment provider.
57
58	    Re-registration (same ``name``) overwrites the previous entry — makes
59	    hot-reload scenarios (tests, dev loops) behave predictably.
60
61	    Raises:
62	        TypeError: not a TerminalEnvironmentProvider instance.
63	        ValueError: empty name or collision with a built-in backend name.
64	    """
65	    if not isinstance(provider, TerminalEnvironmentProvider):
66	        raise TypeError(
67	            f"register_provider() expects a TerminalEnvironmentProvider "
68	            f"instance, got {type(provider).__name__}"
69	        )
70	    raw_name = provider.name
71	    if not isinstance(raw_name, str) or not raw_name.strip():
72	        raise ValueError("Terminal environment provider .name must be a non-empty string")
73	    name = raw_name.strip().lower()
74	    if name in BUILTIN_BACKEND_NAMES:
75	        raise ValueError(
76	            f"Terminal backend name '{name}' is reserved for the built-in "
77	            f"{name} backend and cannot be registered by a plugin"
78	        )
79	    global _generation
80	    with _lock:
81	        target = _providers if scope is None else _scoped_providers.setdefault(scope, {})
82	        existing = target.get(name)
83	        target[name] = provider
84	        if scope is None:
85	            _generation += 1
86	        else:
87	            _scoped_generations[scope] = _scoped_generations.get(scope, 0) + 1
88	    if existing is not None:
89	        logger.debug(
90	            "Terminal environment provider '%s' re-registered (was %r)",
91	            name, type(existing).__name__,
92	        )
93	    else:
94	        logger.debug(
95	            "Registered terminal environment provider '%s' (%s)",
96	            name, type(provider).__name__,
97	        )
98
99
100	def list_providers(*, scope: Optional[str] = None) -> List[TerminalEnvironmentProvider]:
101	    """Return all registered providers, sorted by name."""
102	    with _lock:
103	        merged = dict(_providers)
104	        merged.update(_scoped_providers.get(scope or hermes_home_key(), {}))
105	        items = list(merged.values())
106	    return sorted(items, key=lambda p: p.name)
107
108
109	def get_provider(
110	    name: str, *, scope: Optional[str] = None
111	) -> Optional[TerminalEnvironmentProvider]:
112	    """Return the provider registered under *name*, or None."""
113	    if not isinstance(name, str):
114	        return None
115	    key = name.strip().lower()
116	    with _lock:
117	        return (
118	            _scoped_providers.get(scope or hermes_home_key(), {}).get(key)
119	            or _providers.get(key)
120	        )
121
122
123	def plugin_backend_names(*, scope: Optional[str] = None) -> List[str]:
124	    """Names of all registered plugin backends (sorted)."""
125	    return [p.name.strip().lower() for p in list_providers(scope=scope)]
126
127
128	def provider_flag(name: str, attr: str, default=False):
129	    """Read a classification attribute off the provider for *name*.
130
131	    Fail-soft: unknown backend or a raising property returns *default* so a
132	    misbehaving plugin degrades to built-in-equivalent behavior instead of
133	    taking the terminal tool down.
134	    """
135	    provider = get_provider(name)
136	    if provider is None:
137	        return default
138	    try:
139	        return getattr(provider, attr, default)
140	    except Exception:
141	        logger.debug(
142	            "Terminal environment provider '%s' attribute '%s' raised",
143	            name, attr, exc_info=True,
144	        )
145	        return default
146
147
148	def plugin_strip_env_keys() -> frozenset:
149	    """Union of every registered provider's ``strip_env_keys``.
150
151	    Secrets are stripped for ALL registered backends, not just the active
152	    one — a token in the process environment is strippable regardless of
153	    which backend is selected (mirrors how MODAL_*/DAYTONA_API_KEY sit in
154	    the static tier-1 set unconditionally).
155	    """
156	    keys: set = set()
157	    with _lock:
158	        all_providers = list(_providers.values())
159	        for scoped in _scoped_providers.values():
160	            all_providers.extend(scoped.values())
161	    for provider in all_providers:
162	        try:
163	            keys.update(provider.strip_env_keys)
164	        except Exception:
165	            logger.debug(
166	                "Terminal environment provider strip_env_keys raised",
167	                exc_info=True,
168	            )
169	    return frozenset(keys)
170
171
172	def snapshot_registration(
173	    name: str, *, scope: Optional[str] = None
174	) -> Optional[TerminalEnvironmentProvider]:
175	    with _lock:
176	        target = _providers if scope is None else _scoped_providers.get(scope, {})
177	        return target.get(name.strip().lower())
178
179
180	def registry_generation(*, scope: Optional[str] = None) -> tuple:
181	    """Return a cache fingerprint for the global base and one profile."""
182	    active_scope = scope or hermes_home_key()
183	    with _lock:
184	        return _generation, _scoped_generations.get(active_scope, 0)
185
186
187	def restore_registration(
188	    name: str,
189	    current: TerminalEnvironmentProvider,
190	    previous: Optional[TerminalEnvironmentProvider],
191	    *,
192	    scope: Optional[str] = None,
193	) -> bool:
194	    """Restore a plugin registration only when *current* is still installed."""
195	    key = name.strip().lower()
196	    global _generation
197	    with _lock:
198	        target = _providers if scope is None else _scoped_providers.setdefault(scope, {})
199	        if target.get(key) is not current:
200	            return False
201	        if previous is None:
202	            target.pop(key, None)
203	        else:
204	            target[key] = previous
205	        if scope is None:
206	            _generation += 1
207	        else:
208	            _scoped_generations[scope] = _scoped_generations.get(scope, 0) + 1
209	            if not target:
210	                _scoped_providers.pop(scope, None)
211	    return True
212
213
214	def _reset_for_tests() -> None:
215	    """Clear all registrations. Test hook — mirrors sibling registries."""
216	    global _generation
217	    with _lock:
218	        _providers.clear()
219	        _scoped_providers.clear()
220	        _scoped_generations.clear()
221	        _generation = 0
```

**Not shown above — explore these names for their source**

- plugins/airi/core.py: PLUGIN:30, _cfg:58, status:1173, _repo:68, _candidate_base_urls:82, _model:106, +10 more
- scripts/profile-tui.py: KEYS:56, run_once:405, main:476, pick_longest_session:65, drain:76, hold_key:94, +8 more
- apps/desktop/scripts/perf/image-attach-bench.mjs: strip:252, attachRead:248
- apps/desktop/src/contrib/plugin.ts: HermesPlugin:94, PluginContext:62
- apps/desktop/src/plugins/accent/plugin.tsx: plugin:37
- apps/desktop/src/plugins/kanban/plugin.tsx: plugin:80
- tools/environments/local.py: _plugin_terminal_env_strip_keys:445
- hermes_cli/plugins.py: _register_deferred_platform_tools:5105, _load_plugin_scoped:5311, _load_portable_plugin:5470
- agent/agent_runtime_helpers.py: _raw_cache_ttl_from_config:2190, switch_model:2915, _heal_escalation_threshold:3957
- tests/test_tui_gateway_server.py: values:14234, _ExplodingDict:14233
- ... and 44 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,016 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

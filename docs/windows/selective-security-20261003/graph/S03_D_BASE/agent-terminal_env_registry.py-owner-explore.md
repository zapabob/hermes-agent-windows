**Exploration: agent/terminal_env_registry.py**

Found 17 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`agent/terminal_env_registry.py`** — calls(calls), logger(variable), BUILTIN_BACKEND_NAMES(variable), _providers(variable), _scoped_providers(variable), _generation(variable), _scoped_generations(variable), _lock(variable), register_provider(function), references(references), list_providers(function), get_provider(function), plugin_backend_names(function), list_providers(calls), provider_flag(function), +5 more

```python
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
222
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

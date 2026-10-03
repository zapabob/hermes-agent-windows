**Exploration: tools/env_passthrough.py**

Found 11 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/env_passthrough.py`** — calls(calls), _is_hermes_provider_credential(calls), _get_allowed(calls), _load_config_passthrough(calls), logger(variable), _allowed_env_vars_var(variable), _get_allowed(function), _config_passthrough(variable), _is_hermes_provider_credential(function), register_env_passthrough(function), _load_config_passthrough(function), is_env_passthrough(function), get_all_passthrough(function), resolve_passthrough_value(function), clear_env_passthrough(function)

```python
26	from typing import Iterable
27	from hermes_cli.config import cfg_get
28
29	logger = logging.getLogger(__name__)
30
31	# Session-scoped set of env var names that should pass through to sandboxes.
32	# Backed by ContextVar to prevent cross-session data bleed in the gateway pipeline.
33	_allowed_env_vars_var: ContextVar[set[str]] = ContextVar("_allowed_env_vars")
34
35
36	def _get_allowed() -> set[str]:
37	    """Get or create the allowed env vars set for the current context/session."""
38	    try:
39	        return _allowed_env_vars_var.get()
40	    except LookupError:
41	        val: set[str] = set()
42	        _allowed_env_vars_var.set(val)
43	        return val
44
45
46	# Cache for the config-based allowlist (loaded once per process).
47	_config_passthrough: frozenset[str] | None = None
48
49
50	def _is_hermes_provider_credential(name: str) -> bool:
51	    """True if ``name`` is a Hermes-managed provider credential (API key,
52	    token, or similar) per ``_HERMES_PROVIDER_ENV_BLOCKLIST``.
53
54	    Skill-declared ``required_environment_variables`` frontmatter must
55	    not be able to override this list — that was the bypass in
56	    GHSA-rhgp-j443-p4rf where a malicious skill registered
57	    ``ANTHROPIC_TOKEN`` / ``OPENAI_API_KEY`` as passthrough and received
58	    the credential in the ``execute_code`` child process, defeating the
59	    sandbox's scrubbing guarantee.
60
61	    Non-Hermes API keys (TENOR_API_KEY, NOTION_TOKEN, etc.) are NOT
62	    in the blocklist and remain legitimately registerable — skills that
63	    wrap third-party APIs still work.
64
65	    Fail closed: if the authoritative blocklist cannot be imported (partial
66	    install, import-time error, etc.) we treat the name as a protected
67	    provider credential and refuse passthrough, rather than fall open and
68	    let a skill tunnel a Hermes credential into the execute_code child.
69	    """
70	    try:
71	        from tools.environments.local import (
72	            _provider_secret_env,
73	            _is_hermes_internal_secret,
74	            _plugin_terminal_env_strip_keys,
75	            _registered_adapter_secret_env,
76	        )
77	        protected = set(_provider_secret_env())
78	        protected.update(key.upper() for key in _plugin_terminal_env_strip_keys())
79	        protected.update(_registered_adapter_secret_env())
80	    except Exception as e:
81	        logger.warning(
82	            "env passthrough: provider credential blocklist import failed; "
83	            "failing closed and refusing passthrough registration for %r: %s",
84	            name,
85	            e,
86	        )
87	        return True
88	    # Dynamically-generated Hermes-internal secrets (AUXILIARY_*_API_KEY /
89	    # _BASE_URL side-LLM credentials, GATEWAY_RELAY_* relay-auth) are provider
90	    # credentials the static blocklist can't enumerate — they're injected per
91	    # task/relay at gateway startup. A skill must not be able to register them
92	    # as passthrough and tunnel them into an execute_code / terminal child.
93	    if _is_hermes_internal_secret(name):
94	        return True
95	    return name.upper() in protected
96
97
98	def register_env_passthrough(var_names: Iterable[str]) -> None:
99	    """Register environment variable names as allowed in sandboxed environments.
100
101	    Typically called when a skill declares ``required_environment_variables``.
102
103	    Variables that are Hermes-managed provider credentials (from
104	    ``_HERMES_PROVIDER_ENV_BLOCKLIST``) are rejected here to preserve
105	    the ``execute_code`` sandbox's credential-scrubbing guarantee per
106	    GHSA-rhgp-j443-p4rf. A skill that needs to talk to a Hermes-managed
107	    provider should do so via the agent's main-process tools (web_search,
108	    web_extract, etc.) where the credential remains safely in the main
109	    process.
110
111	    Non-Hermes third-party API keys (TENOR_API_KEY, NOTION_TOKEN, etc.)
112	    pass through normally — they were never in the sandbox scrub list.
113	    """
114	    for name in var_names:
115	        name = name.strip()
116	        if not name:
117	            continue
118	        if _is_hermes_provider_credential(name):
119	            logger.warning(
120	                "env passthrough: refusing to register Hermes provider "
121	                "credential %r (blocked by _HERMES_PROVIDER_ENV_BLOCKLIST). "
122	                "Skills must not override the execute_code sandbox's "
123	                "credential scrubbing; see GHSA-rhgp-j443-p4rf.",
124	                name,
125	            )
126	            continue
127	        _get_allowed().add(name)
128	        logger.debug("env passthrough: registered %s", name)
129
130
131	def _load_config_passthrough() -> frozenset[str]:
132	    """Load ``tools.env_passthrough`` from config.yaml (cached)."""
133	    global _config_passthrough
134	    if _config_passthrough is not None:
135	        return _config_passthrough
136
137	    result: set[str] = set()
138	    try:
139	        from hermes_cli.config import read_raw_config
140	        cfg = read_raw_config()
141	        passthrough = cfg_get(cfg, "terminal", "env_passthrough")
142	        if isinstance(passthrough, list):
143	            for item in passthrough:
144	                if not isinstance(item, str) or not item.strip():
145	                    continue
146	                name = item.strip()
147	                # Mirror the skill-path filter in register_env_passthrough:
148	                # Hermes-managed provider credentials must not be passed
149	                # through to execute_code / terminal children, regardless of
150	                # whether the request came from a skill or from config.yaml.
151	                # See GHSA-rhgp-j443-p4rf.
152	                if _is_hermes_provider_credential(name):
153	                    logger.warning(
154	                        "env passthrough: refusing to register Hermes "
155	                        "provider credential %r from config.yaml (blocked "
156	                        "by _HERMES_PROVIDER_ENV_BLOCKLIST). Operator "
157	                        "configuration must not override the execute_code "
158	                        "sandbox's credential scrubbing; see "
159	                        "GHSA-rhgp-j443-p4rf.",
160	                        name,
161	                    )
162	                    continue
163	                result.add(name)
164	    except Exception as e:
165	        logger.debug("Could not read tools.env_passthrough from config: %s", e)
166
167	    _config_passthrough = frozenset(result)
168	    return _config_passthrough
169
170
171	def is_env_passthrough(var_name: str) -> bool:
172	    """Check whether *var_name* is allowed to pass through to sandboxes.
173
174	    Returns ``True`` if the variable was registered by a skill or listed in
175	    the user's ``tools.env_passthrough`` config.
176	    """
177	    registered = var_name in _get_allowed() or var_name in _load_config_passthrough()
178	    return registered and not _is_hermes_provider_credential(var_name)
179
180
181	def get_all_passthrough() -> frozenset[str]:
182	    """Return the union of skill-registered and config-based passthrough vars."""
183	    return frozenset(name for name in frozenset(_get_allowed()) | _load_config_passthrough()
184	                     if not _is_hermes_provider_credential(name))
185
186
187	def resolve_passthrough_value(
188	    name: str,
189	    fallback: str | None = None,
190	) -> str | None:
191	    """Resolve an allowlisted variable without crossing profile boundaries.
192
193	    ``fallback`` is the value the caller would have forwarded before profile
194	    secret scopes existed (typically a snapshot of ``os.environ`` or the
195	    current profile's ``.env``).  An active multiplex scope is authoritative:
196	    a missing key returns ``None`` and never falls back to the process-global
197	    environment.  An unscoped read while multiplexing is active raises the
198	    fail-closed ``UnscopedSecretError`` from :mod:`agent.secret_scope`.
199
200	    Outside multiplexing, an installed scope keeps the existing overlay
201	    semantics and an unscoped caller keeps its already-resolved fallback.
202	    """
203	    from agent.secret_scope import (
204	        _is_global_env,
205	        current_secret_scope,
206	        get_secret,
207	        is_multiplex_active,
208	    )
209
210	    # Global terminal/runtime settings are not profile secrets.  ``fallback``
211	    # is already the caller's effective value (including an explicit per-call
212	    # override), so preserve it instead of replacing it with the process-wide
213	    # value while a multiplex scope is active.
214	    if _is_global_env(name) and fallback is not None:
215	        return fallback
216
217	    scope = current_secret_scope()
218	    multiplex_active = is_multiplex_active()
219	    if scope is None:
220	        if multiplex_active:
221	            return get_secret(name)
222	        return fallback
223	    return get_secret(name, None if multiplex_active else fallback)
224
225
226	def clear_env_passthrough() -> None:
227	    """Reset the skill-scoped allowlist (e.g. on session reset)."""
228	    _get_allowed().clear()
229
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,019 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

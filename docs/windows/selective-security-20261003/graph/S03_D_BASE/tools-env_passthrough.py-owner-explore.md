**Exploration: tools/env_passthrough.py**

Found 11 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/env_passthrough.py`** — calls(calls), _get_allowed(calls), _is_hermes_provider_credential(calls), _load_config_passthrough(calls), logger(variable), _allowed_env_vars_var(variable), _get_allowed(function), _config_passthrough(variable), _is_hermes_provider_credential(function), register_env_passthrough(function), _load_config_passthrough(function), is_env_passthrough(function), get_all_passthrough(function), resolve_passthrough_value(function), clear_env_passthrough(function)

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
72	            _HERMES_PROVIDER_ENV_BLOCKLIST,
73	            _is_hermes_internal_secret,
74	        )
75	    except Exception as e:
76	        logger.warning(
77	            "env passthrough: provider credential blocklist import failed; "
78	            "failing closed and refusing passthrough registration for %r: %s",
79	            name,
80	            e,
81	        )
82	        return True
83	    # Dynamically-generated Hermes-internal secrets (AUXILIARY_*_API_KEY /
84	    # _BASE_URL side-LLM credentials, GATEWAY_RELAY_* relay-auth) are provider
85	    # credentials the static blocklist can't enumerate — they're injected per
86	    # task/relay at gateway startup. A skill must not be able to register them
87	    # as passthrough and tunnel them into an execute_code / terminal child.
88	    if _is_hermes_internal_secret(name):
89	        return True
90	    return name in _HERMES_PROVIDER_ENV_BLOCKLIST
91
92
93	def register_env_passthrough(var_names: Iterable[str]) -> None:
94	    """Register environment variable names as allowed in sandboxed environments.
95
96	    Typically called when a skill declares ``required_environment_variables``.
97
98	    Variables that are Hermes-managed provider credentials (from
99	    ``_HERMES_PROVIDER_ENV_BLOCKLIST``) are rejected here to preserve
100	    the ``execute_code`` sandbox's credential-scrubbing guarantee per
101	    GHSA-rhgp-j443-p4rf. A skill that needs to talk to a Hermes-managed
102	    provider should do so via the agent's main-process tools (web_search,
103	    web_extract, etc.) where the credential remains safely in the main
104	    process.
105
106	    Non-Hermes third-party API keys (TENOR_API_KEY, NOTION_TOKEN, etc.)
107	    pass through normally — they were never in the sandbox scrub list.
108	    """
109	    for name in var_names:
110	        name = name.strip()
111	        if not name:
112	            continue
113	        if _is_hermes_provider_credential(name):
114	            logger.warning(
115	                "env passthrough: refusing to register Hermes provider "
116	                "credential %r (blocked by _HERMES_PROVIDER_ENV_BLOCKLIST). "
117	                "Skills must not override the execute_code sandbox's "
118	                "credential scrubbing; see GHSA-rhgp-j443-p4rf.",
119	                name,
120	            )
121	            continue
122	        _get_allowed().add(name)
123	        logger.debug("env passthrough: registered %s", name)
124
125
126	def _load_config_passthrough() -> frozenset[str]:
127	    """Load ``tools.env_passthrough`` from config.yaml (cached)."""
128	    global _config_passthrough
129	    if _config_passthrough is not None:
130	        return _config_passthrough
131
132	    result: set[str] = set()
133	    try:
134	        from hermes_cli.config import read_raw_config
135	        cfg = read_raw_config()
136	        passthrough = cfg_get(cfg, "terminal", "env_passthrough")
137	        if isinstance(passthrough, list):
138	            for item in passthrough:
139	                if not isinstance(item, str) or not item.strip():
140	                    continue
141	                name = item.strip()
142	                # Mirror the skill-path filter in register_env_passthrough:
143	                # Hermes-managed provider credentials must not be passed
144	                # through to execute_code / terminal children, regardless of
145	                # whether the request came from a skill or from config.yaml.
146	                # See GHSA-rhgp-j443-p4rf.
147	                if _is_hermes_provider_credential(name):
148	                    logger.warning(
149	                        "env passthrough: refusing to register Hermes "
150	                        "provider credential %r from config.yaml (blocked "
151	                        "by _HERMES_PROVIDER_ENV_BLOCKLIST). Operator "
152	                        "configuration must not override the execute_code "
153	                        "sandbox's credential scrubbing; see "
154	                        "GHSA-rhgp-j443-p4rf.",
155	                        name,
156	                    )
157	                    continue
158	                result.add(name)
159	    except Exception as e:
160	        logger.debug("Could not read tools.env_passthrough from config: %s", e)
161
162	    _config_passthrough = frozenset(result)
163	    return _config_passthrough
164
165
166	def is_env_passthrough(var_name: str) -> bool:
167	    """Check whether *var_name* is allowed to pass through to sandboxes.
168
169	    Returns ``True`` if the variable was registered by a skill or listed in
170	    the user's ``tools.env_passthrough`` config.
171	    """
172	    if var_name in _get_allowed():
173	        return True
174	    return var_name in _load_config_passthrough()
175
176
177	def get_all_passthrough() -> frozenset[str]:
178	    """Return the union of skill-registered and config-based passthrough vars."""
179	    return frozenset(_get_allowed()) | _load_config_passthrough()
180
181
182	def resolve_passthrough_value(
183	    name: str,
184	    fallback: str | None = None,
185	) -> str | None:
186	    """Resolve an allowlisted variable without crossing profile boundaries.
187
188	    ``fallback`` is the value the caller would have forwarded before profile
189	    secret scopes existed (typically a snapshot of ``os.environ`` or the
190	    current profile's ``.env``).  An active multiplex scope is authoritative:
191	    a missing key returns ``None`` and never falls back to the process-global
192	    environment.  An unscoped read while multiplexing is active raises the
193	    fail-closed ``UnscopedSecretError`` from :mod:`agent.secret_scope`.
194
195	    Outside multiplexing, an installed scope keeps the existing overlay
196	    semantics and an unscoped caller keeps its already-resolved fallback.
197	    """
198	    from agent.secret_scope import (
199	        _is_global_env,
200	        current_secret_scope,
201	        get_secret,
202	        is_multiplex_active,
203	    )
204
205	    # Global terminal/runtime settings are not profile secrets.  ``fallback``
206	    # is already the caller's effective value (including an explicit per-call
207	    # override), so preserve it instead of replacing it with the process-wide
208	    # value while a multiplex scope is active.
209	    if _is_global_env(name) and fallback is not None:
210	        return fallback
211
212	    scope = current_secret_scope()
213	    multiplex_active = is_multiplex_active()
214	    if scope is None:
215	        if multiplex_active:
216	            return get_secret(name)
217	        return fallback
218	    return get_secret(name, None if multiplex_active else fallback)
219
220
221	def clear_env_passthrough() -> None:
222	    """Reset the skill-scoped allowlist (e.g. on session reset)."""
223	    _get_allowed().clear()
224
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,014 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

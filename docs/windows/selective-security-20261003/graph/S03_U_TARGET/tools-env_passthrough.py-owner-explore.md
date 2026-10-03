**Exploration: tools/env_passthrough.py**

Found 13 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/env_passthrough.py`** — logger(variable), _allowed_env_vars_var(variable), _get_allowed(function), _config_passthrough(variable), _is_hermes_provider_credential(function), register_env_passthrough(function), _accepted(function), _load_config_passthrough(function), is_env_passthrough(function), get_all_passthrough(function), resolve_passthrough_value(function), scoped_passthrough_additions(function), clear_env_passthrough(function)

```python
1	"""Environment variable passthrough registry: the session-scoped allowlist of vars a
2	skill's ``required_environment_variables`` (registered by ``skill_view``) or
3	``terminal.env_passthrough`` in config.yaml may forward into sandboxed children
4	(execute_code, terminal), which strip secrets by default. Under profile multiplexing,
5	forwarded values resolve through the profile's secret scope, not the process env."""
6
7	from __future__ import annotations
8
9	import logging
10	from contextvars import ContextVar
11	from typing import Iterable
12	from hermes_cli.config import cfg_get, read_raw_config
13
14	logger = logging.getLogger(__name__)
15
16	# Session-scoped allowlist; ContextVar-backed to prevent cross-session bleed
17	# in the gateway pipeline.
18	_allowed_env_vars_var: ContextVar[set[str]] = ContextVar("_allowed_env_vars")
19
20
21	def _get_allowed() -> set[str]:
22	    """Get or create the allowed env vars set for the current context/session."""
23	    try:
24	        return _allowed_env_vars_var.get()
25	    except LookupError:
26	        val: set[str] = set()
27	        _allowed_env_vars_var.set(val)
28	        return val
29
30
31	# Config-based allowlist, keyed by Hermes home: under gateway.multiplex_profiles one process serves
32	# many profiles, and a single slot would let the first profile's operator allowlist decide which env
33	# vars tunnel into every other profile's sandbox children.
34	_config_passthrough: dict[str, frozenset[str]] = {}
35
36
37	def _is_hermes_provider_credential(name: str) -> bool:
38	    """True if ``name`` is a Hermes-managed provider credential per
39	    ``_HERMES_PROVIDER_ENV_BLOCKLIST`` or a dynamic Hermes-internal secret
40	    (AUXILIARY_*_API_KEY / _BASE_URL, GATEWAY_RELAY_*). Skill-declared
41	    ``required_environment_variables`` must not override this — that was the
42	    GHSA-rhgp-j443-p4rf bypass (a skill registered ``OPENAI_API_KEY`` and received it
43	    in the ``execute_code`` child); non-Hermes keys (TENOR_API_KEY, …) stay
44	    registerable. Fails closed when the blocklist cannot be imported."""
45	    try:
46	        from tools.environments.local_env_policy import (
47	            _is_hermes_internal_secret, _is_provider_env_blocklisted)
48	    except Exception as e:
49	        logger.warning(
50	            "env passthrough: provider credential blocklist import failed; "
51	            "failing closed and refusing passthrough registration for %r: %s", name, e)
52	        return True
53	    # Case-folded membership too: the remote-exec env builder resolves each
54	    # registered name via os.getenv(), which is case-insensitive on Windows, so
55	    # ``openai_api_key`` would tunnel the real OPENAI_API_KEY into children.
56	    return _is_hermes_internal_secret(name) or _is_provider_env_blocklisted(name)
57
58
59	def register_env_passthrough(var_names: Iterable[str]) -> None:
60	    """Register env var names as allowed in sandboxed environments (typically a
61	    skill's ``required_environment_variables``). Hermes-managed provider credentials
62	    are rejected (GHSA-rhgp-j443-p4rf) — such skills should use the main-process tools
63	    (web_search, web_extract, …); third-party keys pass normally."""
64	    for name in _accepted((n.strip() for n in var_names), (
65	        "env passthrough: refusing to register Hermes provider "
66	        "credential %r (blocked by _HERMES_PROVIDER_ENV_BLOCKLIST). "
67	        "Skills must not override the execute_code sandbox's "
68	        "credential scrubbing; see GHSA-rhgp-j443-p4rf."
69	    )):
70	        _get_allowed().add(name)
71	        logger.debug("env passthrough: registered %s", name)
72
73
74	def _accepted(names, refusal_msg: str):
75	    """Yield non-empty *names* that are not Hermes provider credentials; refused
76	    names are logged with *refusal_msg* (``%r`` = name)."""
77	    for name in names:
78	        if not name:
79	            continue
80	        if _is_hermes_provider_credential(name):
81	            logger.warning(refusal_msg, name)
82	            continue
83	        yield name
84
85
86	def _load_config_passthrough() -> frozenset[str]:
87	    """Load ``tools.env_passthrough`` from config.yaml (cached). Same credential
88	    filter as register_env_passthrough: operator config must not tunnel provider
89	    credentials into sandbox children either (GHSA-rhgp-j443-p4rf)."""
90	    from hermes_constants import hermes_home_key
91
92	    try:
93	        home_key = hermes_home_key()
94	    except (RuntimeError, OSError):
95	        # No resolvable home (stripped environ in a sandbox child): nothing to scope by.
96	        home_key = ""
97	    cached = _config_passthrough.get(home_key)
98	    if cached is not None:
99	        return cached
100	    result: set[str] = set()
101	    try:
102	        passthrough = cfg_get(read_raw_config(), "terminal", "env_passthrough")
103	        items = passthrough if isinstance(passthrough, list) else ()
104	        result.update(_accepted((i.strip() for i in items if isinstance(i, str)), (
105	            "env passthrough: refusing to register Hermes "
106	            "provider credential %r from config.yaml (blocked "
107	            "by _HERMES_PROVIDER_ENV_BLOCKLIST). Operator "
108	            "configuration must not override the execute_code "
109	            "sandbox's credential scrubbing; see "
110	            "GHSA-rhgp-j443-p4rf."
111	        )))
112	    except Exception as e:
113	        logger.debug("Could not read tools.env_passthrough from config: %s", e)
114	    _config_passthrough[home_key] = frozenset(result)
115	    return _config_passthrough[home_key]
116
117
118	def is_env_passthrough(var_name: str) -> bool:
119	    """True if *var_name* was registered by a skill or listed in config and is not a
120	    Hermes-managed credential NOW. Ownership changes after acceptance (a platform plugin
121	    registered later declares the name in its ``required_env`` or manifest), so the refusal applied at registration
122	    is re-applied here, where every child builder consumes the allowlist."""
123	    return ((var_name in _get_allowed() or var_name in _load_config_passthrough())
124	            and not _is_hermes_provider_credential(var_name))
125
126
127	def get_all_passthrough() -> frozenset[str]:
128	    """Return the union of skill-registered and config-based passthrough vars, minus names
129	    that have become Hermes-managed credentials since they were accepted."""
130	    return frozenset(name for name in frozenset(_get_allowed()) | _load_config_passthrough()
131	                     if not _is_hermes_provider_credential(name))
132
133
134	def resolve_passthrough_value(name: str, fallback: str | None = None) -> str | None:
135	    """Resolve an allowlisted variable without crossing profile boundaries. ``fallback``
136	    is what the caller would have forwarded before secret scopes existed (a snapshot of
137	    ``os.environ`` / the profile ``.env``). An active multiplex scope is authoritative:
138	    a missing key returns ``None``, never the process-global env, and an unscoped read
139	    raises the fail-closed ``UnscopedSecretError``. Outside multiplexing an installed
140	    scope keeps overlay semantics and an unscoped caller keeps its fallback."""
141	    from agent.secret_scope import (
142	        _is_global_env, current_secret_scope, get_secret, is_multiplex_active)
143	    # Global terminal/runtime settings are not profile secrets; ``fallback`` is
144	    # already the caller's effective value (incl. an explicit per-call override).
145	    if _is_global_env(name) and fallback is not None:
146	        return fallback
147	    multiplex_active = is_multiplex_active()
148	    if current_secret_scope() is None:
149	        return get_secret(name) if multiplex_active else fallback
150	    return get_secret(name, None if multiplex_active else fallback)
151
152
153	def scoped_passthrough_additions(present: Iterable[str]) -> dict[str, str]:
154	    """Declared passthrough names the bound profile secret scope supplies but the env being
155	    filtered (*present*) lacks. A routed profile's ``.env`` and hydrated sources never enter
156	    ``os.environ`` (``load_hermes_dotenv`` skips the process-global load for a routed home), so a
157	    name-by-name filter over the process env can only forward a declared name the LAUNCH profile
158	    also happens to define — the served profile's own value has no way in (#114209). Reads the
159	    bound scope alone: never ``os.environ``, never another profile. Empty without a scope, so
160	    single-profile spawns are byte-identical."""
161	    from agent.secret_scope import _is_global_env, current_secret_scope
162	    scope = current_secret_scope()
163	    if not scope:
164	        return {}
165	    present = set(present)
166	    additions: dict[str, str] = {}
167	    for name in get_all_passthrough():
168	        if name in present or _is_global_env(name):
169	            continue
170	        value = scope.get(name)
171	        if value is not None:
172	            additions[name] = value
173	    return additions
174
175
176	def clear_env_passthrough() -> None:
177	    """Reset the skill-scoped allowlist (e.g. on session reset)."""
178	    _get_allowed().clear()
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

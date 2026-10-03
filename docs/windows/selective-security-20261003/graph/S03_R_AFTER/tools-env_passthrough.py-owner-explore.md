**Exploration: tools/env_passthrough.py**

Found 12 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/env_passthrough.py`** — logger(variable), _allowed_env_vars_var(variable), _get_allowed(function), _config_passthrough(variable), _is_hermes_provider_credential(function), register_env_passthrough(function), _accepted(function), _load_config_passthrough(function), is_env_passthrough(function), get_all_passthrough(function), resolve_passthrough_value(function), clear_env_passthrough(function)

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
31	# Cache for the config-based allowlist (loaded once per process).
32	_config_passthrough: frozenset[str] | None = None
33
34
35	def _is_hermes_provider_credential(name: str) -> bool:
36	    """True if ``name`` is a Hermes-managed provider credential per
37	    ``_HERMES_PROVIDER_ENV_BLOCKLIST`` or a dynamic Hermes-internal secret
38	    (AUXILIARY_*_API_KEY / _BASE_URL, GATEWAY_RELAY_*). Skill-declared
39	    ``required_environment_variables`` must not override this — that was the
40	    GHSA-rhgp-j443-p4rf bypass (a skill registered ``OPENAI_API_KEY`` and received it
41	    in the ``execute_code`` child); non-Hermes keys (TENOR_API_KEY, …) stay
42	    registerable. Fails closed when the blocklist cannot be imported."""
43	    try:
44	        from tools.environments.local_env_policy import (
45	            _HERMES_PROVIDER_ENV_BLOCKLIST, _is_hermes_internal_secret)
46	    except Exception as e:
47	        logger.warning(
48	            "env passthrough: provider credential blocklist import failed; "
49	            "failing closed and refusing passthrough registration for %r: %s", name, e)
50	        return True
51	    return _is_hermes_internal_secret(name) or name in _HERMES_PROVIDER_ENV_BLOCKLIST
52
53
54	def register_env_passthrough(var_names: Iterable[str]) -> None:
55	    """Register env var names as allowed in sandboxed environments (typically a
56	    skill's ``required_environment_variables``). Hermes-managed provider credentials
57	    are rejected (GHSA-rhgp-j443-p4rf) — such skills should use the main-process tools
58	    (web_search, web_extract, …); third-party keys pass normally."""
59	    for name in _accepted((n.strip() for n in var_names), (
60	        "env passthrough: refusing to register Hermes provider "
61	        "credential %r (blocked by _HERMES_PROVIDER_ENV_BLOCKLIST). "
62	        "Skills must not override the execute_code sandbox's "
63	        "credential scrubbing; see GHSA-rhgp-j443-p4rf."
64	    )):
65	        _get_allowed().add(name)
66	        logger.debug("env passthrough: registered %s", name)
67
68
69	def _accepted(names, refusal_msg: str):
70	    """Yield non-empty *names* that are not Hermes provider credentials; refused
71	    names are logged with *refusal_msg* (``%r`` = name)."""
72	    for name in names:
73	        if not name:
74	            continue
75	        if _is_hermes_provider_credential(name):
76	            logger.warning(refusal_msg, name)
77	            continue
78	        yield name
79
80
81	def _load_config_passthrough() -> frozenset[str]:
82	    """Load ``tools.env_passthrough`` from config.yaml (cached). Same credential
83	    filter as register_env_passthrough: operator config must not tunnel provider
84	    credentials into sandbox children either (GHSA-rhgp-j443-p4rf)."""
85	    global _config_passthrough
86	    if _config_passthrough is not None:
87	        return _config_passthrough
88	    result: set[str] = set()
89	    try:
90	        passthrough = cfg_get(read_raw_config(), "terminal", "env_passthrough")
91	        items = passthrough if isinstance(passthrough, list) else ()
92	        result.update(_accepted((i.strip() for i in items if isinstance(i, str)), (
93	            "env passthrough: refusing to register Hermes "
94	            "provider credential %r from config.yaml (blocked "
95	            "by _HERMES_PROVIDER_ENV_BLOCKLIST). Operator "
96	            "configuration must not override the execute_code "
97	            "sandbox's credential scrubbing; see "
98	            "GHSA-rhgp-j443-p4rf."
99	        )))
100	    except Exception as e:
101	        logger.debug("Could not read tools.env_passthrough from config: %s", e)
102	    _config_passthrough = frozenset(result)
103	    return _config_passthrough
104
105
106	def is_env_passthrough(var_name: str) -> bool:
107	    """True if *var_name* was registered by a skill or listed in config."""
108	    return var_name in _get_allowed() or var_name in _load_config_passthrough()
109
110
111	def get_all_passthrough() -> frozenset[str]:
112	    """Return the union of skill-registered and config-based passthrough vars."""
113	    return frozenset(_get_allowed()) | _load_config_passthrough()
114
115
116	def resolve_passthrough_value(name: str, fallback: str | None = None) -> str | None:
117	    """Resolve an allowlisted variable without crossing profile boundaries. ``fallback``
118	    is what the caller would have forwarded before secret scopes existed (a snapshot of
119	    ``os.environ`` / the profile ``.env``). An active multiplex scope is authoritative:
120	    a missing key returns ``None``, never the process-global env, and an unscoped read
121	    raises the fail-closed ``UnscopedSecretError``. Outside multiplexing an installed
122	    scope keeps overlay semantics and an unscoped caller keeps its fallback."""
123	    from agent.secret_scope import (
124	        _is_global_env, current_secret_scope, get_secret, is_multiplex_active)
125	    # Global terminal/runtime settings are not profile secrets; ``fallback`` is
126	    # already the caller's effective value (incl. an explicit per-call override).
127	    if _is_global_env(name) and fallback is not None:
128	        return fallback
129	    multiplex_active = is_multiplex_active()
130	    if current_secret_scope() is None:
131	        return get_secret(name) if multiplex_active else fallback
132	    return get_secret(name, None if multiplex_active else fallback)
133
134
135	def clear_env_passthrough() -> None:
136	    """Reset the skill-scoped allowlist (e.g. on session reset)."""
137	    _get_allowed().clear()
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

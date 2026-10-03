**Exploration: tools/environments/local_env_policy.py**

Found 13 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local_env_policy.py`** — _HERMES_PROVIDER_ENV_FORCE_PREFIX(variable), _AWS_SDK_CREDENTIAL_ENV_VARS(variable), _STATIC_PROVIDER_ENV_BLOCKLIST(variable), _build_provider_env_blocklist(function), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _TERMINAL_FIRST_PARTY_ENV_PREFIXES(variable), _matches_terminal_first_party_prefix(function), _buzz_terminal_context_active(function), _is_terminal_first_party_env(function), _ACTIVE_VENV_MARKER_VARS(variable), _is_hermes_internal_secret(function), _plugin_terminal_env_strip_keys(function), _ALWAYS_STRIP_KEYS(variable)

```python
1	"""Secret-scrub policy for Hermes child processes: pure data + predicates for which env
2	names are Hermes-managed credentials. The env *builders* applying it (``_make_run_env``,
3	``_sanitize_subprocess_env``, ``hermes_subprocess_env``) live in ``tools.environments.local``."""
4
5	import os
6
7	# Prefix a caller uses in ``extra_env`` to force a blocklisted var through.
8	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
9
10	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"`` (Bedrock):
11	# only the Bedrock bearer token, which no aws/terraform/boto3 toolchain uses. The
12	# general AWS chain stays inheritable on purpose — the local terminal is the user's
13	# trusted operator shell (SECURITY.md §3.2) and env_passthrough can never re-allow a
14	# blocklisted name (GHSA-rhgp-j443-p4rf), so blocking it would be unrecoverable.
15	_AWS_SDK_CREDENTIAL_ENV_VARS = frozenset({"AWS_BEARER_TOKEN_BEDROCK"})
16
17	_STATIC_PROVIDER_ENV_BLOCKLIST = frozenset({
18	    "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_ORG_ID",
19	    "OPENAI_ORGANIZATION", "OPENROUTER_API_KEY", "ANTHROPIC_BASE_URL",
20	    "ANTHROPIC_API_KEY", "ANTHROPIC_TOKEN", "LLM_MODEL", "GOOGLE_API_KEY",
21	    # Path to a GCP service-account JSON, not a bare key, so OPTIONAL_ENV_VARS
22	    # marks it password=False and the registry loop skips it.
23	    "VERTEX_CREDENTIALS_PATH", "GOOGLE_APPLICATION_CREDENTIALS", "DEEPSEEK_API_KEY",
24	    "MISTRAL_API_KEY", "GROQ_API_KEY", "TOGETHER_API_KEY", "PERPLEXITY_API_KEY",
25	    "COHERE_API_KEY", "FIREWORKS_API_KEY", "XAI_API_KEY", "HELICONE_API_KEY",
26	    "PARALLEL_API_KEY", "FIRECRAWL_API_KEY", "FIRECRAWL_API_URL",
27	    "TELEGRAM_HOME_CHANNEL", "TELEGRAM_HOME_CHANNEL_NAME", "DISCORD_HOME_CHANNEL",
28	    "DISCORD_HOME_CHANNEL_NAME", "DISCORD_REQUIRE_MENTION",
29	    "DISCORD_FREE_RESPONSE_CHANNELS", "DISCORD_AUTO_THREAD", "SLACK_HOME_CHANNEL",
30	    "SLACK_HOME_CHANNEL_NAME", "SLACK_ALLOWED_USERS", "WHATSAPP_ENABLED",
31	    "WHATSAPP_MODE", "WHATSAPP_ALLOWED_USERS", "SIGNAL_HTTP_URL", "SIGNAL_ACCOUNT",
32	    "SIGNAL_ALLOWED_USERS", "SIGNAL_GROUP_ALLOWED_USERS", "SIGNAL_HOME_CHANNEL",
33	    "SIGNAL_HOME_CHANNEL_NAME", "SIGNAL_IGNORE_STORIES", "HASS_TOKEN", "HASS_URL",
34	    "EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST", "EMAIL_SMTP_HOST",
35	    "EMAIL_HOME_ADDRESS", "EMAIL_HOME_ADDRESS_NAME", "HERMES_DASHBOARD_SESSION_TOKEN",
36	    "GATEWAY_ALLOWED_USERS", "GH_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH",
37	    "GITHUB_APP_INSTALLATION_ID", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
38	    "DAYTONA_API_KEY", "GATEWAY_RELAY_ID", "GATEWAY_RELAY_SECRET",
39	    "GATEWAY_RELAY_DELIVERY_KEY", "VERCEL_OIDC_TOKEN", "VERCEL_TOKEN",
40	    "VERCEL_PROJECT_ID", "VERCEL_TEAM_ID",
41	})
42
43
44	def _build_provider_env_blocklist() -> frozenset:
45	    """Derive the blocklist from provider, tool, and gateway config."""
46	    blocked: set[str] = set(_STATIC_PROVIDER_ENV_BLOCKLIST)
47	    try:
48	        from hermes_cli.auth import PROVIDER_REGISTRY
49	        for pconfig in PROVIDER_REGISTRY.values():
50	            blocked.update(pconfig.api_key_env_vars)
51	            if pconfig.auth_type == "aws_sdk":
52	                blocked.update(_AWS_SDK_CREDENTIAL_ENV_VARS)
53	            if pconfig.base_url_env_var:
54	                blocked.add(pconfig.base_url_env_var)
55	    except ImportError:
56	        pass
57	    try:
58	        from hermes_cli.config import OPTIONAL_ENV_VARS
59	        for name, metadata in OPTIONAL_ENV_VARS.items():
60	            category = metadata.get("category")
61	            if category in {"tool", "messaging"} or (
62	                    category == "setting" and metadata.get("password")):
63	                blocked.add(name)
64	    except ImportError:
65	        pass
66	    # CLAUDE_CODE_OAUTH_TOKEN (via the anthropic registry entry) belongs to the user's
67	    # Claude Code install, not Hermes: stripping it made agent-spawned ``claude`` CLIs
68	    # fall through to the shared Keychain / ~/.claude store and, on auth failure, wipe
69	    # it — logging the user out. BUZZ_* is deliberately NOT discarded: this list feeds
70	    # every scrub surface, so an import-time discard would leak BUZZ_PRIVATE_KEY into
71	    # non-terminal children; the Buzz carve-out is terminal-only and context-gated
72	    # (``_is_terminal_first_party_env``).
73	    # It is set and owned by the user's Claude Code install (subscription OAuth), not a Hermes-managed
74	    # inference credential — Claude subscription auth is not a working Hermes provider path. It arrives via
75	    # the registry loop above (anthropic api_key_env_vars), so remove it explicitly. See #55878.
76	    blocked.discard("CLAUDE_CODE_OAUTH_TOKEN")
77	    # BUZZ_* is deliberately NOT discarded here, even for Buzz-managed agents (BUZZ_MANAGED_AGENT set by the
78	    # buzz-acp harness). See #76243, #78026, #78065, #78511.
79	    return frozenset(blocked)
80
81
82	_HERMES_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
83
84	# First-party platform credentials (``BUZZ_*``, driving the platform-mandated ``buzz``
85	# CLI) carved out of the TERMINAL scrub only (``_make_run_env``,
86	# ``_sanitize_subprocess_env``); execute_code, hermes_subprocess_env, docker and
87	# env_passthrough registration stay sealed (GHSA-rhgp-j443-p4rf). CONTEXT-GATED via
88	# ``_buzz_terminal_context_active``: a Telegram/CLI/cron session on a host that also
89	# runs a Buzz gateway must not get the signing key. Values are used directly, never
90	# scope-resolved (UnscopedSecretError under multiplex); the snapshot treats them as
91	# profile-scoped. Prefix-based so future BUZZ_* names need no code change.
92	# First-party platform credentials the agent's own platform adapters need in terminal children (e.g. the
93	# ``BUZZ_*`` vars for the Buzz messaging platform, which drive the platform-mandated ``buzz`` CLI:
94	# BUZZ_PRIVATE_KEY, BUZZ_AUTH_TAG, BUZZ_RELAY_URL, and the other BUZZ_* names). These are the agent's OWN
95	# credentials — a Buzz community agent is expected to operate the ``buzz`` CLI — so they are carved out of
96	# the terminal scrub. CONTEXT-GATED: the carve-out applies ONLY when this process/session is actually
97	# operating as a Buzz agent — either the process is a Buzz-ACP managed agent (``BUZZ_MANAGED_AGENT`` is set,
98	# only by Buzz Desktop's buzz-acp harness; see #76243 / #78511) or the current session's platform is
99	# ``buzz`` (the gateway's ``HERMES_SESSION_PLATFORM`` ContextVar; concurrency safe under a multi-session
100	# host). A Telegram/CLI/cron session on a host that also runs a Buzz gateway does NOT get BUZZ_PRIVATE_KEY
101	# in its terminal children — blanket passthrough of a signing key to every terminal child on the host would
102	# be wrong (maintainer triage note on #76243: don't expose the key to unrelated shell commands).
103	# ``_sanitize_subprocess_env`` is also consumed by search workers (e.g. the ddgs web-search subprocess), the
104	# computer-use driver binary, and user-script runners (bang ``!`` commands, quick commands, cron scripts,
105	# webhook-filter scripts), so those children receive the vars too — matching the approved background/PTY
106	# scope. Every other surface stays sealed — execute_code scrubbing, :func:`hermes_subprocess_env` (browser /
107	# TUI host / copilot-executor spawns), docker children, and ``env_passthrough`` registration (skills/config
108	# still cannot register these names). The GHSA-rhgp-j443-p4rf seal is preserved because no registration path
109	# is opened; this is a scrub-path exemption, not an allowlist addition. First-party matches use the merged
110	# env value directly — they are the process's own env values and are never scope-resolved (a profile secret
111	# scope under multiplex would otherwise raise UnscopedSecretError at passthrough-resolution call sites);
112	# only skill/config passthrough names resolve through the profile secret scope. The snapshot mechanism
113	# treats these names like profile-scoped passthrough names (see
114	# ``LocalEnvironment._additional_profile_scoped_passthrough_names``) so they never persist in the shared
115	# terminal snapshot across profiles. Contrast with CLAUDE_CODE_OAUTH_TOKEN above, which is discarded from
116	# the blocklist entirely because it is NOT a Hermes credential; these ARE Hermes-managed first-party
117	# platform credentials, so they stay IN the blocklist for every non-terminal surface. See issue #78026 (Buzz
118	# agents could not use ``buzz`` from the terminal tool) and #76243 (Buzz Desktop managed agent wakes but
119	# cannot reply).
120	_TERMINAL_FIRST_PARTY_ENV_PREFIXES = ("BUZZ_",)
121
122
123	def _matches_terminal_first_party_prefix(name: str) -> bool:
124	    """Pure name check (``BUZZ_*``), regardless of session context — the snapshot
125	    exclusion must stay conservative even when the carve-out is inactive."""
126	    return name.startswith(_TERMINAL_FIRST_PARTY_ENV_PREFIXES)
127
128
129	def _buzz_terminal_context_active() -> bool:
130	    """True when this process/session operates as a Buzz agent: ``BUZZ_MANAGED_AGENT`` in
131	    the process env (set only by Buzz Desktop's buzz-acp harness), or the live session's
132	    platform is ``buzz`` via the gateway ContextVar — authoritative under a concurrent
133	    multi-session host, so a sibling Telegram session resolves its OWN platform.
134
135	    Gateway / CLI / cron / kanban processes never carry it. See #76243.
136	    """
137	    if os.environ.get("BUZZ_MANAGED_AGENT"):
138	        return True
139	    try:
140	        from gateway.session_context import get_session_env
141
142	        return get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower() == "buzz"
143	    except Exception:
144	        return False
145
146
147	def _is_terminal_first_party_env(name: str) -> bool:
148	    """``name`` is a first-party platform credential (``BUZZ_*``) AND the current
149	    process/session context entitles it to reach terminal children."""
150	    return _matches_terminal_first_party_prefix(name) and _buzz_terminal_context_active()
151
152
153	# Active-venv markers that must NOT leak: VIRTUAL_ENV/CONDA_PREFIX make uv/poetry sync
154	# ANOTHER project's deps into the Hermes venv (still reachable via PATH, so stripping
155	# is safe); PYTHONHOME redirects a child interpreter's stdlib to the Hermes venv
156	# (version-mismatch crashes). PYTHONPATH is handled separately (Hermes-owned entries only).
157	# The gateway runs inside its own venv, so its process environment carries VIRTUAL_ENV (and possibly
158	# CONDA_PREFIX). If those leak into commands the agent runs against OTHER Python projects, tools like
159	# ``uv``/``poetry`` treat the inherited value as the active environment and build/sync that other project's
160	# dependencies into the Hermes venv path instead of the project's own ``.venv`` — silently clobbering the
161	# Hermes environment (e.g. a project pinned to a different Python version overwrites it and breaks the
162	# gateway). PYTHONHOME is included because a gateway-inherited value redirects the standard-library search
163	# of ANY child interpreter — including unrelated system/venv Pythons — to the Hermes venv's stdlib, which
164	# crashes with version-mismatch errors before a child script even imports a package (#75018). Hermes itself
165	# treats PYTHONHOME as contamination in its own child processes (managed_uv.py, sqlite_runtime.py), so
166	# stripping it from subprocess envs is consistent. Users who need PYTHONHOME for a specific child can set it
167	# explicitly in the command. PYTHONPATH is NOT included here — it's handled by
168	# _strip_hermes_owned_pythonpath() which removes only Hermes-owned entries, preserving user-set paths.
169	_ACTIVE_VENV_MARKER_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")
170
171
172	def _is_hermes_internal_secret(key: str) -> bool:
173	    """True for Hermes-internal secrets injected under *dynamic* names the static
174	    blocklist cannot enumerate: ``AUXILIARY_<TASK>_API_KEY``/``_BASE_URL`` (per-task
175	    side-LLM credentials) and ``GATEWAY_RELAY_*_SECRET``/``_KEY``/``_TOKEN`` (relay
176	    auth; non-secret routing hints stay visible). Stripped on every spawn path
177	    regardless of env_passthrough registration or ``inherit_credentials``."""
178	    upper = key.upper()
179	    if upper.startswith("AUXILIARY_") and upper.endswith(("_API_KEY", "_BASE_URL")):
180	        return True
181	    return upper.startswith("GATEWAY_RELAY_") and upper.endswith(("_SECRET", "_KEY", "_TOKEN"))
182
183
184	def _plugin_terminal_env_strip_keys() -> frozenset:
185	    """Credential env keys owned by plugin-registered terminal backends (Tier-1:
186	    stripped from every spawned subprocess). Computed at call time because plugins
187	    register after import; fail-soft to empty."""
188	    try:
189	        from agent.terminal_env_registry import plugin_strip_env_keys
190
191	        return plugin_strip_env_keys()
192	    except Exception:
193	        return frozenset()
194
195
196	# Tier-1 secrets: stripped from EVERY spawned subprocess even under inherit_credentials
197	# (claude/codex/gemini). Not provider credentials — no child needs them and they are the
198	# highest-value secrets to keep from a compromised dependency. Provider keys = Tier 2.
199	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
200	    # GitHub auth
201	    "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH",
202	    "GITHUB_APP_INSTALLATION_ID",
203	    # Gateway / messaging bot tokens and access control
204	    "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
205	    "SLACK_SIGNING_SECRET", "GATEWAY_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS",
206	    # Gateway relay auth triplet. _SECRET/_DELIVERY_KEY are also matched by
207	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
208	    # enumerated here to stay stripped on the inherit_credentials=True path.
209	    "GATEWAY_RELAY_ID", "GATEWAY_RELAY_SECRET", "GATEWAY_RELAY_DELIVERY_KEY",
210	    "HASS_TOKEN", "EMAIL_PASSWORD", "HERMES_DASHBOARD_SESSION_TOKEN",
211	    # Remote-compute / infrastructure secrets
212	    "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "DAYTONA_API_KEY",
213	})
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

**Exploration: tools/environments/local_env_policy.py**

Found 28 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`tools/environments/local_env_policy.py`** — calls(calls), _platform_gate_env_prefixes(calls), _HERMES_PROVIDER_ENV_FORCE_PREFIX(variable), _AWS_SDK_CREDENTIAL_ENV_VARS(variable), _STATIC_PROVIDER_ENV_BLOCKLIST(variable), _build_provider_env_blocklist(function), _build_adapter_secret_env(function), _PROVIDER_ENV_BLOCKLIST(variable), _ADAPTER_SECRET_ENV(variable), _HERMES_PROVIDER_ENV_BLOCKLIST(variable), _HOME_ADAPTER_SECRET_CACHE(variable), _home_adapter_secret_env(function), _registry_adapter_secret_env(function), _registered_adapter_secret_env(function), _registry_adapter_secret_env(calls), +22 more

```python
7	from typing import Optional
8
9	# Prefix a caller uses in ``extra_env`` to force a blocklisted var through.
10	_HERMES_PROVIDER_ENV_FORCE_PREFIX = "_HERMES_FORCE_"
11
12	# Hermes-managed AWS *inference* credentials for ``auth_type="aws_sdk"`` (Bedrock):
13	# only the Bedrock bearer token, which no aws/terraform/boto3 toolchain uses. The
14	# general AWS chain stays inheritable on purpose — the local terminal is the user's
15	# trusted operator shell (SECURITY.md §3.2) and env_passthrough can never re-allow a
16	# blocklisted name (GHSA-rhgp-j443-p4rf), so blocking it would be unrecoverable.
17	_AWS_SDK_CREDENTIAL_ENV_VARS = frozenset({"AWS_BEARER_TOKEN_BEDROCK"})
18
19	_STATIC_PROVIDER_ENV_BLOCKLIST = frozenset({
20	    "OPENAI_BASE_URL", "OPENAI_API_KEY", "OPENAI_API_BASE", "OPENAI_ORG_ID",

... (gap) ...

90	    return frozenset(blocked)
91
92
93	def _build_adapter_secret_env() -> frozenset:
94	    """Secrets the messaging adapters declare, process-wide: core ``password`` messaging entries
95	    of OPTIONAL_ENV_VARS, the bundled platform plugin manifests' secret entries, and the
96	    secret-named keys the gateway env-override table reads (WEIXIN_TOKEN, FEISHU_ENCRYPT_KEY, ...).
97	    Declared names only: a user's own ``SLACK_USER_TOKEN`` or ``LOCAL_LLM_API_KEY`` is not Hermes's.
98	    A profile's user-installed platform plugins are per home: :func:`_home_adapter_secret_env`.
99	    Nothing here fails soft: an unreadable bundled manifest or env table fails the import rather
100	    than dropping its secrets from the policy."""
101	    from hermes_cli.config import (
102	        CORE_DECLARED_ENV_NAMES, OPTIONAL_ENV_VARS, PLATFORM_SECRET_ENV_SUFFIXES, platform_manifest_secret_envs)
103	    from hermes_cli.profile_channels import config_env_table_keys
104	    # Read in code only, declared nowhere else: the Microsoft Graph app secret and webhook
105	    # clientState, and the QQ bot's speech-to-text key.
106	    names: set[str] = {"MSGRAPH_CLIENT_SECRET", "MSGRAPH_WEBHOOK_CLIENT_STATE", "QQ_STT_API_KEY"}
107	    names.update(name.upper() for name, meta in OPTIONAL_ENV_VARS.items()
108	                 if name in CORE_DECLARED_ENV_NAMES
109	                 and meta.get("category") == "messaging" and meta.get("password"))
110	    names |= platform_manifest_secret_envs(source="bundled", strict=True)
111	    names.update(n.upper() for n in config_env_table_keys() if n.upper().endswith(PLATFORM_SECRET_ENV_SUFFIXES))
112	    return frozenset(names)
113
114
115	# Provider blocklist first: it imports hermes_cli.auth before hermes_cli.config, whose import
116	# discovers provider plugins that expect a fully initialized auth registry.
117	_PROVIDER_ENV_BLOCKLIST = _build_provider_env_blocklist()
118	_ADAPTER_SECRET_ENV = _build_adapter_secret_env()
119	_HERMES_PROVIDER_ENV_BLOCKLIST = _PROVIDER_ENV_BLOCKLIST | _ADAPTER_SECRET_ENV
120
121	_HOME_ADAPTER_SECRET_CACHE: dict[str, tuple] = {}
122
123
124	def _home_adapter_secret_env() -> frozenset:
125	    """Secrets declared by the bound profile's own user-installed platform plugins. Per home, not
126	    process-wide: under multiplex profile A's plugin must neither strip a same-named value from
127	    profile B's children nor be missing from A's. Cached per home and keyed on every manifest's
128	    file signature, so an edit, replacement or deletion takes effect on the next spawn. A plugin
129	    manifest under ``plugins/platforms/`` that cannot be read raises. A partial scan (a plugin dir
130	    or flat manifest unreadable or unparsable) keeps the names this home already had and is not
131	    cached, so a failed discovery never releases a known denial and recovery is seen at once."""
132	    from hermes_cli.config import platform_manifest_secret_scan, platform_manifest_stamp
133	    from hermes_constants import get_hermes_home, hermes_home_key
134	    home = get_hermes_home()
135	    key, stamp = hermes_home_key(home), platform_manifest_stamp(home)
136	    cached = _HOME_ADAPTER_SECRET_CACHE.get(key)
137	    if cached is None or cached[0] is None or cached[0] != stamp:
138	        names, complete = platform_manifest_secret_scan(home)
139	        names -= _ADAPTER_SECRET_ENV
140	        if not complete and cached is not None:
141	            names |= cached[1]
142	        cached = (stamp if complete else None, names)
143	        _HOME_ADAPTER_SECRET_CACHE[key] = cached
144	    return cached[1]
145
146
147	def _registry_adapter_secret_env() -> frozenset:
148	    """Secret-named ``required_env`` of the adapters registered in the current profile scope.
149	    Tier 2 only: ``required_env`` is an unchecked setup list, so a plugin naming OPENAI_API_KEY
150	    must not strip it from credentialed children. No blanket fallback: a registry error surfaces
151	    instead of an empty (fail-open) set."""
152	    from gateway.platform_registry import platform_registry
153	    from hermes_cli.config import PLATFORM_SECRET_ENV_SUFFIXES
154	    return frozenset(n.upper() for n in platform_registry.required_env_names()
155	                     if n.upper().endswith(PLATFORM_SECRET_ENV_SUFFIXES))
156
157
158	def _registered_adapter_secret_env() -> frozenset:
159	    """Per-call adapter secrets: the bound profile's user-plugin declarations (Tier 1, see
160	    :func:`_home_adapter_secret_env`) plus the registered adapters' (Tier 2,
161	    :func:`_registry_adapter_secret_env`)."""
162	    return _registry_adapter_secret_env() | _home_adapter_secret_env()
163
164
165	def _is_provider_env_blocklisted(name: str, _registered: "frozenset | None" = None) -> bool:
166	    """``name`` is a blocklisted provider/tool credential or adapter secret, matched the way the
167	    platform's environment resolves names: exact plus case-folded. On Windows the environment
168	    block is case-insensitive, so ``openai_api_key`` IS ``OPENAI_API_KEY``; consistent with
169	    ``_is_hermes_internal_secret``, which already folds (``key.upper()``). Loops pass
170	    ``_registered`` so the registry is read once per env, not once per key."""
171	    upper = name.upper()
172	    if name in _HERMES_PROVIDER_ENV_BLOCKLIST or upper in _HERMES_PROVIDER_ENV_BLOCKLIST:
173	        return True
174	    return upper in (_registered_adapter_secret_env() if _registered is None else _registered)
175
176
177	# First-party platform credentials (``BUZZ_*``, driving the platform-mandated ``buzz``

... (gap) ...

210	# platform credentials, so they stay IN the blocklist for every non-terminal surface. See issue #78026 (Buzz
211	# agents could not use ``buzz`` from the terminal tool) and #76243 (Buzz Desktop managed agent wakes but
212	# cannot reply).
213	_TERMINAL_FIRST_PARTY_ENV_PREFIXES = ("BUZZ_",)
214
215
216	def _matches_terminal_first_party_prefix(name: str) -> bool:
217	    """Pure name check (``BUZZ_*``), regardless of session context — the snapshot
218	    exclusion must stay conservative even when the carve-out is inactive.
219	    Case-folded: on Windows the env block is case-insensitive, so a
220	    lowercase-stored ``buzz_private_key`` IS the credential; it needs the
221	    carve-out (and the snapshot exclusion) just like the canonical name."""
222	    return name.upper().startswith(_TERMINAL_FIRST_PARTY_ENV_PREFIXES)
223
224
225	def _buzz_terminal_context_active() -> bool:
226	    """True when this process/session operates as a Buzz agent: ``BUZZ_MANAGED_AGENT`` in
227	    the process env (set only by Buzz Desktop's buzz-acp harness), or the live session's
228	    platform is ``buzz`` via the gateway ContextVar — authoritative under a concurrent
229	    multi-session host, so a sibling Telegram session resolves its OWN platform.
230
231	    Gateway / CLI / cron / kanban processes never carry it. See #76243.
232	    """
233	    if os.environ.get("BUZZ_MANAGED_AGENT"):
234	        return True
235	    try:
236	        from gateway.session_context import get_session_env
237
238	        return get_session_env("HERMES_SESSION_PLATFORM", "").strip().lower() == "buzz"
239	    except Exception:
240	        return False
241
242
243	def _is_terminal_first_party_env(name: str) -> bool:
244	    """``name`` is a first-party platform credential (``BUZZ_*``) AND the current
245	    process/session context entitles it to reach terminal children."""
246	    return _matches_terminal_first_party_prefix(name) and _buzz_terminal_context_active()
247
248
249	# Active-venv markers that must NOT leak: VIRTUAL_ENV/CONDA_PREFIX make uv/poetry sync

... (gap) ...

262	# stripping it from subprocess envs is consistent. Users who need PYTHONHOME for a specific child can set it
263	# explicitly in the command. PYTHONPATH is NOT included here — it's handled by
264	# _strip_hermes_owned_pythonpath() which removes only Hermes-owned entries, preserving user-set paths.
265	_ACTIVE_VENV_MARKER_VARS = ("VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME")
266
267
268	def _is_hermes_internal_secret(key: str) -> bool:
269	    """True for Hermes-internal secrets injected under *dynamic* names the static
270	    blocklist cannot enumerate: ``AUXILIARY_<TASK>_API_KEY``/``_BASE_URL`` (per-task
271	    side-LLM credentials) and ``GATEWAY_RELAY_*_SECRET``/``_KEY``/``_TOKEN`` (relay
272	    auth; non-secret routing hints stay visible). Stripped on every spawn path
273	    regardless of env_passthrough registration or ``inherit_credentials``."""
274	    upper = key.upper()
275	    if upper.startswith("AUXILIARY_") and upper.endswith(("_API_KEY", "_BASE_URL")):
276	        return True
277	    return upper.startswith("GATEWAY_RELAY_") and upper.endswith(("_SECRET", "_KEY", "_TOKEN"))
278
279
280	# Authorization gates: the env names platform adapters read to decide WHO may talk to the
281	# agent (allow/deny lists, allow-all opt-ins, bot policy, channel scoping). Not credentials, so
282	# no secret scrub touches them, and most profiles' ``.env`` files do not define them, so the
283	# child's own dotenv load never overwrites an inherited value: a child spawned FOR profile B
284	# from a process that loaded profile A's gates (or a unit-file ``Environment=``) would enforce
285	# A's channel/user/role list as its own (#113270). The suffix is matched by shape so a gate
286	# added to any adapter is covered without a second edit, but ONLY under a platform prefix
287	# (``DISCORD_``, ``GATEWAY_``, a plugin adapter's name): an operator's own ``DEMO_ALLOWED_SENDER``
288	# is script data, not a Hermes gate, and deleting it by name shape broke routed ``no_agent``
289	# cron scripts (#119539). ``HERMES_*`` never counts (``HERMES_MEDIA_ALLOW_DIRS``,
290	# ``HERMES_ALLOW_PRIVATE_URLS`` are process settings, not adapter gates).
291	_PROFILE_GATE_ENV_MARKERS = (
292	    "_ALLOWED_", "_ALLOW_ALL_", "_ALLOW_FROM", "_ALLOW_BOTS", "_ALLOW_PUBLIC_", "_IGNORED_CHANNELS",
293	    "_NO_THREAD_CHANNELS", "_FREE_RESPONSE_CHANNELS", "_BACKFILL_CHANNELS", "_GROUP_ALLOWED",
294	)
295	# Gate owners that are not a ``Platform`` value: the cross-platform pairing gate and adapters whose
296	# env prefix differs from their platform name (``qqbot`` reads ``QQ_*``).
297	_EXTRA_GATE_ENV_PREFIXES = frozenset({"GATEWAY", "QQ"})
298
299
300	@functools.lru_cache(maxsize=1)
301	def _static_gate_env_prefixes() -> frozenset:
302	    """Built-in ``Platform`` values plus bundled platform plugins (directory names and manifest
303	    aliases) — fixed for the life of the process, so scanned once."""
304	    names = set(_EXTRA_GATE_ENV_PREFIXES)
305	    try:
306	        from gateway.config import Platform
307	        names.update(m.value for m in Platform.__members__.values())
308	        bundled, aliases = Platform._scan_bundled_plugin_platforms()
309	        names.update(bundled)
310	        names.update(aliases)
311	    except Exception:  # noqa: BLE001 — a broken gateway import must not disable the gate strip
312	        pass
313	    return frozenset(str(n).upper().replace("-", "_") for n in names if n)
314
315
316	def _platform_gate_env_prefixes() -> frozenset:
317	    """Upper-cased owners of authorization gates: the static set plus runtime-registered plugin
318	    adapters (``platform_registry``, dynamic and profile-scoped, so read per call — a cheap set
319	    union under the registry lock)."""
320	    names = set(_static_gate_env_prefixes())
321	    try:
322	        from gateway.platform_registry import platform_registry
323	        names.update(str(n).upper().replace("-", "_") for n in platform_registry.registered_names() if n)
324	    except Exception:  # noqa: BLE001
325	        pass
326	    return frozenset(names)
327
328
329	def is_profile_gate_env(name: str, _prefixes: Optional[frozenset] = None) -> bool:
330	    """True for a platform authorization gate (``DISCORD_ALLOWED_CHANNELS``, ``TELEGRAM_ALLOW_ALL_USERS``,
331	    ``GATEWAY_ALLOWED_USERS``, ``WHATSAPP_GROUP_ALLOW_FROM`` ...) — profile-scoped policy a child acting
332	    for ANOTHER profile must never inherit. A gate is a platform prefix AND a gate-shaped suffix;
333	    an operator variable that merely contains ``_ALLOWED_`` is not one."""
334	    upper = name.upper()
335	    if upper.startswith("HERMES_") or upper.startswith("_"):
336	        return False
337	    if not any(marker in upper for marker in _PROFILE_GATE_ENV_MARKERS):
338	        return False
339	    prefixes = _prefixes if _prefixes is not None else _platform_gate_env_prefixes()
340	    return any(upper.startswith(prefix + "_") for prefix in prefixes)
341
342
343	def strip_profile_gate_env(env: dict) -> dict:
344	    """Drop every authorization gate from *env* in place (see :func:`is_profile_gate_env`)."""
345	    prefixes = _platform_gate_env_prefixes()
346	    for key in [k for k in env if is_profile_gate_env(k, prefixes)]:
347	        del env[key]
348	    return env
349
350
351	def _plugin_terminal_env_strip_keys() -> frozenset:
352	    """Credential env keys owned by plugin-registered terminal backends (Tier-1:
353	    stripped from every spawned subprocess). Computed at call time because plugins
354	    register after import; fail-soft to empty."""
355	    try:
356	        from agent.terminal_env_registry import plugin_strip_env_keys
357
358	        return plugin_strip_env_keys()
359	    except Exception:
360	        return frozenset()
361
362
363	# Tier-1 secrets: stripped from EVERY spawned subprocess even under inherit_credentials
364	# (claude/codex/gemini). Not provider credentials — no child needs them and they are the
365	# highest-value secrets to keep from a compromised dependency. Provider keys = Tier 2.
366	_ALWAYS_STRIP_KEYS: frozenset[str] = frozenset({
367	    # GitHub auth
368	    "GH_TOKEN", "GITHUB_TOKEN", "GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY_PATH",
369	    "GITHUB_APP_INSTALLATION_ID",
370	    # Gateway / messaging bot tokens and access control
371	    "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN",
372	    "SLACK_SIGNING_SECRET", "GATEWAY_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS",
373	    # Gateway relay auth triplet. _SECRET/_DELIVERY_KEY are also matched by
374	    # _is_hermes_internal_secret, but _ID has no secret suffix, so it must be
375	    # enumerated here to stay stripped on the inherit_credentials=True path.
376	    "GATEWAY_RELAY_ID", "GATEWAY_RELAY_SECRET", "GATEWAY_RELAY_DELIVERY_KEY",
377	    "HASS_TOKEN", "EMAIL_PASSWORD", "HERMES_DASHBOARD_SESSION_TOKEN",
378	    # Dashboard auth: the basic-auth password and session-signing secret, the OIDC client
379	    # secret and the drain bearer. They let a holder mint or forge dashboard sessions, and no
380	    # child (credentialed CLIs included) consumes them.
381	    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD", "HERMES_DASHBOARD_BASIC_AUTH_SECRET",
382	    "HERMES_DASHBOARD_OIDC_CLIENT_SECRET", "HERMES_DASHBOARD_DRAIN_SECRET",
383	    # Remote-compute / infrastructure secrets
384	    "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET", "DAYTONA_API_KEY",
385	}) | _ADAPTER_SECRET_ENV  # every declared adapter secret is Tier 1, like the bot tokens above
386	_ALWAYS_STRIP_FOLDED: frozenset[str] = frozenset(k.upper() for k in _ALWAYS_STRIP_KEYS)
387
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

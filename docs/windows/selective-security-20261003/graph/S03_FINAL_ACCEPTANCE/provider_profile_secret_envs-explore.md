**Exploration: provider_profile_secret_envs**

Found 3 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `provider_profile_secret_envs` (hermes_cli/config.py:6217) — 2 callers in `hermes_cli/config.py`, `tools/environments/local.py`; tested via callers: `tests/tools/test_env_passthrough.py`, `tests/test_subprocess_home_isolation.py` +11
- `PROVIDER` (scripts/master-heartbeat.py:23) — 3 callers in `scripts/master-heartbeat.py`; no tests found within 3 caller hops
- `profile` (gateway/pairing.py:484) — 1 caller in `plugins/memory/supermemory/__init__.py`; tested via callers: `tests/plugins/memory/test_supermemory_provider.py`

**Relationships**

**calls:**
- provider_profile_secret_envs → list_providers
- platform_manifest_secret_envs → provider_profile_secret_envs
- _provider_secret_env → provider_profile_secret_envs
- list_providers → values
- list_providers → _merged
- list_token_providers → list_providers
- list_session_providers → list_providers
- auth_logout → list_providers
- _build_apikey_providers_list → list_providers
- _maybe_setup_dashboard_auth_interactively → list_providers
- provider_catalog → list_providers
- _print_setup_summary → list_providers
- setup_terminal_backend → list_providers
- _plugin_image_gen_providers → list_providers
- _plugin_video_gen_providers → list_providers
- ... and 97 more

**references:**
- list_providers → _lock
- run_hermes_task → PROVIDER
- persist_results → PROVIDER
- print_report → PROVIDER
- run_hermes_task → MODEL
- run_hermes_task → HERMES_CMD
- persist_results → MODEL
- persist_results → A2A_RESULTS_DIR
- print_report → HERMES_CMD
- print_report → MODEL
- _subprocess_env → CERT_BUNDLE
- provider → codex_plugin
- test_unavailable_without_codex_token → codex_plugin
- test_available_with_codex_token → codex_plugin
- test_openai_api_key_alone_is_not_enough → codex_plugin
- ... and 21 more

**instantiates:**
- provider → OpenAIImageGenProvider
- register → OpenAIImageGenProvider
- provider → NousDashboardAuthProvider
- provider → HindsightMemoryProvider

**extends:**
- OpenAIImageGenProvider → ImageGenProvider

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`hermes_cli/config.py`** — list_providers(calls), _inject_profile_env_vars(function), provider_profile_secret_envs(function), platform_manifest_secret_envs(function), resolve(calls), provider_profile_secret_envs(calls), is_dir(calls), fast_safe_load(calls), calls(calls)

```python
6151	_profile_env_vars_injected = False
6152
6153
6154	def _inject_profile_env_vars() -> None:
6155	    """Populate OPTIONAL_ENV_VARS from provider profiles not already listed.
6156
6157	    Called once at module load time. Idempotent — repeated calls are no-ops.
6158	    """
6159	    global _profile_env_vars_injected
6160	    if _profile_env_vars_injected:
6161	        return
6162	    _profile_env_vars_injected = True
6163	    try:
6164	        from providers import list_providers
6165	        for _pp in list_providers():
6166	            # SDK credentials also serve unrelated child tools; they are not
6167	            # Hermes-owned provider keys or password prompts.
6168	            if _pp.auth_type == "aws_sdk":
6169	                continue
6170	            for _var in _pp.env_vars:
6171	                if _var in OPTIONAL_ENV_VARS:
6172	                    continue
6173	                _is_key = not _var.endswith("_BASE_URL") and not _var.endswith("_URL")
6174	                OPTIONAL_ENV_VARS[_var] = {
6175	                    "description": f"{_pp.display_name or _pp.name} {'API key' if _is_key else 'base URL override'}",
6176	                    "prompt": f"{_pp.display_name or _pp.name} {'API key' if _is_key else 'base URL (leave empty for default)'}",
6177	                    "url": _pp.signup_url or None,
6178	                    "password": _is_key,
6179	                    "category": "provider",
6180	                    "advanced": True,
6181	                }
6182	    except Exception:
6183	        pass
6184
6185
6186	# Eagerly inject so that OPTIONAL_ENV_VARS is fully populated at import time.

... (gap) ...

6214	PLATFORM_SECRET_ENV_SUFFIXES = ("_TOKEN", "_SECRET", "_KEY", "_PASSWORD", "_JSON")
6215
6216
6217	def provider_profile_secret_envs() -> frozenset[str]:
6218	    """Resolve current provider declarations for UI-independent security policy."""
6219	    names: set[str] = set()
6220	    try:
6221	        from providers import list_providers
6222	        for profile in list_providers():
6223	            declared = profile.env_vars
6224	            if not isinstance(declared, (tuple, list, set, frozenset)) or any(
6225	                not isinstance(name, str) or not name for name in declared
6226	            ):
6227	                raise ValueError("provider environment declaration is invalid")
6228	            if profile.auth_type != "aws_sdk":
6229	                names.update(name.upper() for name in declared if not name.upper().endswith("_URL"))
6230	    except Exception as exc:
6231	        raise RuntimeError("Cannot resolve provider credential declaration") from exc
6232	    names.discard("CLAUDE_CODE_OAUTH_TOKEN")
6233	    return frozenset(names)
6234
6235
6236	def platform_manifest_secret_envs(home: Path | None) -> frozenset[str]:
6237	    """Read platform security declarations without importing plugin code.
6238
6239	    A known manifest that cannot be read or parsed cannot authorize a spawn.
6240	    User declarations stay home-scoped and cannot demote core credentials.
6241	    """
6242	    roots = [(Path(__file__).resolve().parents[1] / "plugins" / "platforms", True)]
6243	    if home is not None:
6244	        roots.extend(((Path(home) / "plugins" / "platforms", True), (Path(home) / "plugins", False)))
6245	    keys: set[str] = set()
6246	    try:
6247	        provider_names = provider_profile_secret_envs()
6248	        for root, platform_directory in roots:
6249	            if not root.exists():
6250	                if os.path.lexists(root):
6251	                    raise ValueError("platform manifest root is unreadable")
6252	                continue
6253	            for child in root.iterdir():
6254	                if not child.is_dir():
6255	                    if os.path.lexists(child) and not child.exists():
6256	                        raise ValueError("platform directory link is unreadable")
6257	                    continue
6258	                path = child / "plugin.yaml"
6259	                if not os.path.lexists(path):
6260	                    path = child / "plugin.yml"
6261	                if not os.path.lexists(path):
6262	                    continue
6263	                with path.open("r", encoding="utf-8") as stream:
6264	                    manifest = fast_safe_load(stream)
6265	                if not isinstance(manifest, dict):
6266	                    raise ValueError("platform manifest must be a mapping")
6267	                if not platform_directory and manifest.get("kind") != "platform":
6268	                    continue
6269	                for field in ("requires_env", "optional_env"):
6270	                    entries = manifest.get(field, [])
6271	                    if entries is None:
6272	                        entries = []
6273	                    if not isinstance(entries, list):
6274	                        raise ValueError("platform env declaration must be a list")
6275	                    for entry in entries:
6276	                        meta = entry if isinstance(entry, dict) else {}
6277	                        name = meta.get("name") if meta else entry
6278	                        if not isinstance(name, str) or not name:
6279	                            raise ValueError("platform env declaration requires a name")
6280	                        for flag in ("password", "secret"):
6281	                            if meta.get(flag) is not None and not isinstance(meta[flag], bool):
6282	                                raise ValueError("platform security flag must be boolean")
6283	                        upper = name.upper()
6284	                        core = OPTIONAL_ENV_VARS.get(upper, {})
6285	                        if upper in _CORE_DECLARED_ENV_NAMES:
6286	                            if core.get("category") == "messaging" and core.get("password"):
6287	                                keys.add(upper)
6288	                            continue
6289	                        if upper in provider_names:
6290	                            continue
6291	                        if meta.get("password") or meta.get("secret") or (
6292	                            meta.get("password") is not False
6293	                            and upper.endswith(PLATFORM_SECRET_ENV_SUFFIXES)
6294	                        ):
6295	                            keys.add(upper)
6296	    except Exception as exc:
6297	        raise RuntimeError("Cannot resolve platform manifest secret declaration") from exc
6298	    return frozenset(keys)
6299
6300
6301	def _inject_platform_plugin_env_vars() -> None:
```

**Not shown above — explore these names for their source**

- scripts/master-heartbeat.py: PROVIDER:23, run_hermes_task:143, persist_results:220, print_report:243, _subprocess_env:114, classify_output:124, +7 more
- gateway/pairing.py: profile:484, PairingStore:435, __init__:451, _pending_path:488, _approved_path:491, _rate_limit_path:494, +18 more
- plugins/image_gen/openai/__init__.py: OpenAIImageGenProvider:165, name:169, display_name:173, is_available:176, list_models:185, default_model:197, +8 more
- tests/plugins/image_gen/test_openai_codex_provider.py: provider:43, codex_plugin:20, test_unavailable_without_codex_token:76, test_available_with_codex_token:81, test_openai_api_key_alone_is_not_enough:86, test_returns_auth_error_without_codex_token:98, +14 more
- tests/plugins/memory/test_hindsight_provider.py: provider:166, _provider_for_mode:97, test_local_embedded_recall_reconnects_after_idle_shutdown:533, _make_mock_client:63
- hermes_cli/dashboard_auth/registry.py: list_providers:98, _merged:25, list_token_providers:104, list_session_providers:117, _lock:20
- plugins/memory/hindsight/__init__.py: initialize:1603, HindsightMemoryProvider:754
- tests/plugins/image_gen/test_openai_provider.py: provider:39
- tests/plugins/dashboard_auth/test_nous_provider.py: provider:306
- hermes_cli/tools_config.py: _plugin_image_gen_providers:3273, _plugin_video_gen_providers:3313, _plugin_tts_providers:3502, _toolset_needs_configuration_prompt:3881, _reap_after_timeout:1835, _run_cua_driver_installer:1619
- ... and 40 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (9,025 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

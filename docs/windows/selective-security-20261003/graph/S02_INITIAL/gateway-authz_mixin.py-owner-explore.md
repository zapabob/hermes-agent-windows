**Exploration: gateway/authz_mixin.py**

Found 23 symbols across 1 file. 1 file pinned from the query.

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`gateway/authz_mixin.py`** — calls(calls), _authorization_adapter(calls), _platform_gate_env(calls), _auth_env(calls), _primary_adapters(calls), _adapter_for_source(calls), _owning_profile(calls), _transport_owner(calls), _coerce_allow_set(calls), _adapter_dm_policy(calls), _platform_gate_env(function), _auth_env(function), _coerce_allow_set(function), _primary_adapters(method), _profile_adapters_map(method), +27 more

```python
30	)
31
32
33	def _platform_gate_env(name: str, default: str = "") -> str:
34	    """Read a platform allow/deny gate env var with per-profile isolation.
35
36	    When a profile secret scope is installed AND multiplexing is active, a
37	    key absent from the scope returns ``default`` instead of falling through
38	    to ``os.environ``. Under multiplex the process env may hold ANOTHER
39	    profile's first-writer-bridged value (the YAML→env bridges in the
40	    Discord/Telegram adapters' ``_apply_yaml_config`` are first-writer-wins),
41	    so falling through would leak profile A's allowlist into profile B
42	    (issue #72348). Single-profile deployments — no scope installed, or
43	    multiplex off — behave exactly like the legacy ``os.getenv`` read.
44	    """
45	    if not name:
46	        return default
47	    try:
48	        from agent.secret_scope import current_secret_scope, is_multiplex_active
49
50	        scope = current_secret_scope()
51	        if scope is not None and is_multiplex_active():
52	            val = scope.get(name)
53	            if val is None:
54	                return default
55	            return str(val).strip()
56	    except Exception:
57	        pass
58	    return (os.getenv(name) or default).strip()
59
60
61	def _auth_env(name: str, default: str = "") -> str:
62	    """Read allowlist/auth env with per-profile isolation under multiplex.
63
64	    Same rules as ``_platform_gate_env``: a scoped miss under multiplex
65	    returns ``default`` and does not fall through to ``os.environ``. The
66	    process env may hold another profile's first-writer-bridged value, so
67	    a fallthrough would leak allowlists and allow-all flags across profiles
68	    (issue #72348). Single-profile deployments keep the legacy
69	    ``os.getenv`` read.
70	    """
71	    return _platform_gate_env(name, default)
72
73
74	def _coerce_allow_set(raw) -> set[str]:
75	    """Parse allowlist values from config or env var into a set of strings.
76
77	    Handles both list inputs (YAML sequences) and comma-separated string
78	    inputs (env vars or scalar YAML values).  A scalar string is split on
79	    commas so ``allow_from: "123,456"`` yields ``{"123", "456"}``, not
80	    ``{"1", "2", "3", ",", ...}``.
81	    """
82	    if raw is None:
83	        return set()
84	    if isinstance(raw, list):
85	        return {str(part).strip() for part in raw if str(part).strip()}
86	    return {part.strip() for part in str(raw).split(",") if part.strip()}
87
88
89	class GatewayAuthorizationMixin:
90	    """User/chat authorization methods for ``GatewayRunner``."""
91
92	    def _primary_adapters(self) -> dict:
93	        return getattr(self, "adapters", None) or {}
94
95	    def _profile_adapters_map(self) -> dict:
96	        return getattr(self, "_profile_adapters", None) or {}
97
98	    def _authorization_adapter(
99	        self,
100	        platform: Optional[Platform],
101	        profile: Optional[str] = None,
102	    ):
103	        """Live adapter whose intake policy gates authorization.
104
105	        Resolves through ``_adapters_for_profile`` so shared-bot satellites keep
106	        the primary transport and disconnected secondaries stay fail-closed.
107	        """
108	        if not platform:
109	            return None
110	        return self._adapters_for_profile(profile).get(platform)
111
112	    def _adapters_for_profile(self, profile: Optional[str]) -> dict:
113	        """Adapter map *profile* may deliver through.
114
115	        Consult ``_profile_adapters`` before the active profile name: multiplex
116	        turns override ``HERMES_HOME`` so ``_active_profile_name()`` reports the
117	        secondary mid-turn, and treating it as primary would hand it the default
118	        bot. A named profile with an empty map borrows the primary only when it
119	        is a shared-bot satellite; otherwise ``{}`` (fail closed).
120	        """
121	        profile_name = (profile or "").strip() or None
122	        if not profile_name or profile_name == "default":
123	            return self._primary_adapters()
124	        profile_adapters = self._profile_adapters_map()
125	        if profile_name in profile_adapters:
126	            adapters = profile_adapters[profile_name]
127	            if adapters or not self._is_shared_bot_satellite(profile_name):
128	                return adapters
129	            return self._primary_adapters()
130	        primary_profile = getattr(self, "_primary_profile_name", None)
131	        if not primary_profile:
132	            with contextlib.suppress(Exception):
133	                primary_profile = self._active_profile_name()
134	        return self._primary_adapters() if profile_name == primary_profile else {}
135
136	    def _is_shared_bot_satellite(self, profile_name: str) -> bool:
137	        """Served profile with no bot of its own, targeted by a default-bot route.
138
139	        Its ``_profile_adapters`` entry is the ``{}`` startup placeholder; a
140	        secondary connected on ANY platform (or queued for reconnect) is its own
141	        credential boundary and never borrows the primary.
142	        """
143	        config = getattr(self, "config", None)
144	        if not getattr(config, "multiplex_profiles", False):
145	            return False
146	        if (getattr(self, "_profile_failed_platforms", None) or {}).get(profile_name):
147	            return False
148	        routes = getattr(config, "profile_routes", None) or []
149	        if not any(
150	            getattr(r, "enabled", True)
151	            and r.profile == profile_name
152	            and getattr(r, "bot_profile", None) is None
153	            for r in routes
154	        ):
155	            return False
156	        from gateway.run import _multiplex_profile_homes
157
158	        try:
159	            return profile_name in {name for name, _home in _multiplex_profile_homes(config)}
160	        except Exception:
161	            return False
162
163	    def _adapter_for_source(self, source: Optional[SessionSource]):
164	        """Resolve the live adapter for an inbound ``SessionSource``."""
165	        if source is None:
166	            return None
167	        transport_adapter = self._registered_transport_adapter(source)
168	        if transport_adapter is not None:
169	            return transport_adapter
170	        # Relay ingress deliberately keeps the underlying platform on the

... (gap) ...

182	            return adapters.get(Platform.RELAY)
183	        # ``getattr`` guards test fixtures that build a bare source via
184	        # SimpleNamespace and omit ``profile`` (see AGENTS.md pitfall #17).
185	        return self._authorization_adapter(
186	            getattr(source, "platform", None),
187	            getattr(source, "profile", None),
188	        )
189
190	    def _owning_profile(self, adapter, platform):
191	        """Return (registered, profile) for a live adapter: profile is None for primary."""
192	        if adapter is (getattr(self, "adapters", None) or {}).get(platform):
193	            return True, None
194	        profile_maps = getattr(self, "_profile_adapters", None) or {}
195	        for profile, profile_adapters in profile_maps.items():
196	            if adapter is profile_adapters.get(platform):
197	                return True, profile
198	        return False, None
199
200	    def _transport_owner(self, source: SessionSource):
201	        """``(adapter, profile)`` of the registered adapter that created *source*, if retained; else None.
202
203	        ``source.profile`` may differ from the adapter profile when one shared credential serves
204	        several routed runtimes; ``build_source`` keeps the receiving adapter as provenance so replies
205	        stay on that transport. Restored/hand-built sources fall back (fail-closed) to profile lookup.
206	        """
207	        adapter_ref = getattr(source, "_transport_adapter_ref", None)
208	        adapter = adapter_ref() if callable(adapter_ref) else None
209	        platform = getattr(source, "platform", None)
210	        if adapter is None or platform is None:
211	            return None
212	        registered, profile = self._owning_profile(adapter, platform)
213	        return (adapter, profile) if registered else None
214
215	    def _registered_transport_adapter(self, source: SessionSource):
216	        """Return the registered adapter that created *source*, if retained.
217
218	        ``source.profile`` is the runtime/session namespace. A chat-based
219	        profile route can therefore differ from the adapter profile when one
220	        shared credential serves several routed runtimes. ``build_source``
221	        keeps the receiving adapter as in-process provenance so replies and
222	        intake-policy checks stay on that transport without weakening the
223	        fail-closed fallback for restored or hand-built sources.
224	        """
225	        owner = self._transport_owner(source)
226	        return owner[0] if owner is not None else None
227
228	    def _authorization_home_for_source(self, source: SessionSource):
229	        """HERMES_HOME whose allowlist admits *source*.

... (gap) ...

241	            return Path(stamped)
242	        if not getattr(getattr(self, "config", None), "multiplex_profiles", False):
243	            return None
244	        adapter = self._adapter_for_source(source)
245	        if adapter is None:
246	            return None
247	        _registered, profile = self._owning_profile(adapter, getattr(source, "platform", None))
248	        if profile is None:
249	            from hermes_constants import get_process_hermes_home
250
251	            return get_process_hermes_home()
252	        from hermes_cli.profiles import get_profile_dir
253
254	        return get_profile_dir(profile)
255
256	    def _adapter_profile_for_source(self, source: SessionSource) -> Optional[str]:
257	        """Resolve the transport-owning profile for adapter policy lookups."""
258	        owner = self._transport_owner(source)
259	        return owner[1] if owner is not None else getattr(source, "profile", None)
260
261	    def _adapter_authorization_is_upstream(
262	        self,
263	        platform: Optional[Platform],
264	        *,
265	        profile: Optional[str] = None,
266	    ) -> bool:
267	        """Whether the adapter for *platform* delegates authz to a trusted upstream.
268
269	        Mirrors ``BasePlatformAdapter.authorization_is_upstream``. The relay
270	        adapter sets this True: the Team Gateway connector authenticates the
271	        gateway's WS and resolves owner-only author bindings before delivering,
272	        so an inbound relay event is already authorized as this instance's bound
273	        user. Unlike ``_adapter_enforces_own_access_policy`` (a LOCAL config
274	        policy the gateway mirrors only when it's an allowlist), this is an
275	        UPSTREAM decision the gateway honors directly. Defaults to ``False`` when
276	        the adapter is unknown or doesn't expose the flag.
277	        """
278	        if not platform:
279	            return False
280	        adapter = self._authorization_adapter(platform, profile)
281	        if adapter is None:
282	            return False
283	        return bool(getattr(adapter, "authorization_is_upstream", False))
284
285	    def _adapter_enforces_own_access_policy(
286	        self,

... (gap) ...

305	        # Some test helpers build a bare GatewayRunner via object.__new__ and
306	        # never set ``adapters``; treat a missing/empty map as "no adapter"
307	        # rather than raising (see pitfalls.md #17).
308	        adapter = self._authorization_adapter(platform, profile)
309	        if adapter is None:
310	            return False
311	        return bool(getattr(adapter, "enforces_own_access_policy", False))

... (gap) ...

333	        """
334	        if not platform:
335	            return ""
336	        adapter = self._authorization_adapter(platform, profile)
337	        policy = getattr(adapter, "_dm_policy", None) if adapter is not None else None
338	        if policy is None:
339	            config = getattr(self, "config", None)
340	            platform_cfg = (
341	                config.platforms.get(platform)
342	                if config is not None and hasattr(config, "platforms")
343	                else None
344	            )
345	            extra = getattr(platform_cfg, "extra", None) if platform_cfg else None
346	            if isinstance(extra, dict):
347	                policy = extra.get("dm_policy")
348	        return str(policy or "").strip().lower()
349
350	    def _adapter_group_policy(
351	        self,

... (gap) ...

368	        """
369	        if not platform:
370	            return ""
371	        adapter = self._authorization_adapter(platform, profile)
372	        policy = getattr(adapter, "_group_policy", None) if adapter is not None else None
373	        if policy is None:
374	            config = getattr(self, "config", None)
375	            platform_cfg = (
376	                config.platforms.get(platform)
377	                if config is not None and hasattr(config, "platforms")
378	                else None
379	            )
380	            extra = getattr(platform_cfg, "extra", None) if platform_cfg else None
381	            if isinstance(extra, dict):
382	                policy = extra.get("group_policy")
383	        return str(policy or "").strip().lower()
384
385	    def _adapter_group_has_sender_allowlist(
386	        self,

... (gap) ...

400	        """
401	        if not platform or not chat_id:
402	            return False
403	        adapter = self._authorization_adapter(platform, profile)
404	        groups = getattr(adapter, "_groups", None) if adapter is not None else None
405	        if groups is None:
406	            config = getattr(self, "config", None)
407	            platform_cfg = (
408	                config.platforms.get(platform)
409	                if config is not None and hasattr(config, "platforms")
410	                else None
411	            )

... (gap) ...

432	        if isinstance(sender_allow, str):
433	            return bool(sender_allow.strip())
434	        if isinstance(sender_allow, (list, tuple, set)):
435	            return any(str(item).strip() for item in sender_allow)
436	        return False
437
438	    def _pairing_store_for(self, source: "SessionSource"):
439	        """Pick the per-profile PairingStore for a source, falling back to global.
440
441	        In a multiplexing gateway, each profile owns its own pairing whitelist
442	        so isolation is preserved. When the source has no profile (single-
443	        profile gateway, or a path that hasn't stamped profile yet) or the
444	        profile isn't registered, fall back to ``self.pairing_store`` (the
445	        global default) so existing behavior is preserved.
446	        """
447	        per_profile = getattr(self, "pairing_stores", None) or {}
448	        profile = getattr(source, "profile", None)
449	        if profile and profile in per_profile:
450	            return per_profile[profile]
451	        return getattr(self, "pairing_store", None)
452
453	    def _is_user_authorized(
454	        self,

... (gap) ...

475	        if source.platform in {Platform.HOMEASSISTANT, Platform.WEBHOOK}:
476	            return True
477
478	        adapter_profile = self._adapter_profile_for_source(source)
479
480	        # Relay (and any adapter whose authorization is enforced by a trusted
481	        # authenticated upstream): the Team Gateway connector authenticates this

... (gap) ...

506	        # tests) — defensive against accidental fail-open.
507	        if allow_adapter_delegation and (
508	            source.delivered_via_upstream_relay is True
509	            or self._adapter_authorization_is_upstream(
510	                source.platform,
511	                profile=adapter_profile,
512	            )

... (gap) ...

531	                Platform.QQBOT: "QQ_GROUP_ALLOWED_USERS",
532	            }.get(source.platform, "")
533	            if chat_allowlist_env:
534	                raw_chat_allowlist = _platform_gate_env(chat_allowlist_env)
535	                if raw_chat_allowlist:
536	                    allowed_group_ids = {
537	                        cid.strip()

... (gap) ...

548	            # so the env-var-only check above misses config.yaml-configured
549	            # allowlists.  Read the live adapter's config.extra as a fallback.
550	            try:
551	                adapter = self._adapter_for_source(source)
552	                if adapter is not None:
553	                    extra = getattr(getattr(adapter, "config", None), "extra", None) or {}
554	                    adapter_group_allowed = extra.get("group_allowed_chats")
555	                    if adapter_group_allowed:
556	                        allowed = _coerce_allow_set(adapter_group_allowed)
557	                        if "*" in allowed or source.chat_id in allowed:
558	                            return True
559	            except Exception:

... (gap) ...

573	        }
574	        if getattr(source, "is_bot", False):
575	            allow_bots_var = platform_allow_bots_map.get(source.platform)
576	            if allow_bots_var and _platform_gate_env(allow_bots_var, "none").lower().strip() in {"mentions", "all"}:
577	                return True
578
579	        if not user_id:

... (gap) ...

643
644	        # Per-platform allow-all flag (e.g., DISCORD_ALLOW_ALL_USERS=true)
645	        platform_allow_all_var = platform_allow_all_map.get(source.platform, "")
646	        if platform_allow_all_var and _auth_env(platform_allow_all_var).lower() in {"true", "1", "yes"}:
647	            return True
648
649	        # Adapter-verified role auth: the Discord adapter already confirmed the

... (gap) ...

672	        # profile's whitelist is isolated; falls back to the global store when
673	        # the source has no profile or the profile isn't registered.
674	        platform_name = source.platform.value if source.platform else ""
675	        pairing_store = self._pairing_store_for(source)
676	        if pairing_store is not None and pairing_store.is_approved(platform_name, user_id):
677	            return True
678
679	        # Check platform-specific and global allowlists
680	        platform_allowlist = _auth_env(platform_env_map.get(source.platform, ""))
681	        group_user_allowlist = ""
682	        group_chat_allowlist = ""
683	        if source.chat_type in {"group", "forum"}:
684	            group_user_allowlist = _auth_env(platform_group_user_env_map.get(source.platform, ""))
685	            group_chat_allowlist = _auth_env(platform_group_chat_env_map.get(source.platform, ""))
686	        global_allowlist = _auth_env("GATEWAY_ALLOWED_USERS")
687
688	        if not platform_allowlist and not group_user_allowlist and not group_chat_allowlist and not global_allowlist:
689	            # No env allowlist configured. Adapters that own their own

... (gap) ...

709	            # flag (checked above), and the pairing flow remain the explicit
710	            # opt-ins to broader access. (#34515 follow-up: trusting "open" was a
711	            # fail-open.)
712	            if allow_adapter_delegation and self._adapter_enforces_own_access_policy(
713	                source.platform,
714	                profile=adapter_profile,
715	            ):
716	                if source.chat_type in {"group", "forum", "channel"}:
717	                    effective_policy = self._adapter_group_policy(
718	                        source.platform,
719	                        profile=adapter_profile,
720	                    )
721	                    if self._adapter_group_has_sender_allowlist(
722	                        source.platform,
723	                        source.chat_id,
724	                        profile=adapter_profile,
725	                    ):
726	                        return True
727	                else:
728	                    effective_policy = self._adapter_dm_policy(
729	                        source.platform,
730	                        profile=adapter_profile,
731	                    )
732	                if effective_policy == "allowlist":
733	                    # Trust allowlist intake only when the live adapter still
734	                    # allowlists this sender. Pairing revoke can clear
735	                    # WHATSAPP_ALLOWED_USERS while a construction-time
736	                    # ``_allow_from`` snapshot would otherwise keep authorizing
737	                    # until restart; re-check when the adapter exposes a DM
738	                    # allowlist helper. Adapters without that helper keep the
739	                    # historical "reached the gateway under allowlist policy"
740	                    # rubber-stamp (#34515).
741	                    if source.chat_type not in {"group", "forum", "channel"}:
742	                        adapter = self._authorization_adapter(
743	                            source.platform,
744	                            profile=adapter_profile,
745	                        )

... (gap) ...

755	            # group_allow_from at intake but do not override enforces_own_access_policy.
756	            # Check their allowlist here so config.yaml-configured allow_from works
757	            # without requiring a separate {PLATFORM}_ALLOWED_USERS env var.
758	            adapter = self._adapter_for_source(source)
759	            if adapter is not None:
760	                extra = getattr(getattr(adapter, "config", None), "extra", None) or {}
761	                if source.chat_type in {"group", "forum", "channel"}:
762	                    adapter_allow = extra.get("group_allow_from")
763	                else:
764	                    adapter_allow = extra.get("allow_from")
765	                if adapter_allow:
766	                    allowed = _coerce_allow_set(adapter_allow)
767	                    if user_id in allowed or "*" in allowed:
768	                        return True
769	            # No allowlists configured -- check global allow-all flag
770	            return _auth_env("GATEWAY_ALLOW_ALL_USERS").lower() in {"true", "1", "yes"}
771
772	        # Telegram can optionally authorize group traffic by chat ID.
773	        # Keep this separate from TELEGRAM_GROUP_ALLOWED_USERS, which gates

... (gap) ...

798	            }
799	            if legacy_chat_ids:
800	                if not getattr(self, "_warned_telegram_group_users_legacy", False):
801	                    logger.warning(
802	                        "TELEGRAM_GROUP_ALLOWED_USERS contains chat-ID-shaped values "
803	                        "(%s). Treating them as chat IDs for backward compatibility. "
804	                        "Move chat IDs to TELEGRAM_GROUP_ALLOWED_CHATS — the _USERS var "

... (gap) ...

889
890	        # Check for an explicit per-platform override first.
891	        if config and hasattr(config, "get_unauthorized_dm_behavior") and platform:
892	            platform_cfg = config.platforms.get(platform) if hasattr(config, "platforms") else None
893	            if platform_cfg and "unauthorized_dm_behavior" in getattr(platform_cfg, "extra", {}):
894	                # Operator explicitly configured behavior for this platform — respect it.
895	                return config.get_unauthorized_dm_behavior(platform)
896
897	        # Email is inbox-shaped, not chat-shaped: an agent mailbox may contain
898	        # unrelated unread human email. Require an explicit per-platform
```


---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

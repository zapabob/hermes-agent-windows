**Exploration: _is_user_authorized**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `_is_callback_user_authorized` (plugins/platforms/telegram/adapter.py:744) — 7 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_multiplex_interactive_auth.py`, `tests/gateway/test_telegram_callback_auth_fail_closed.py`
- `_is_user_authorized_from_message` (plugins/platforms/telegram/adapter.py:855) — 13 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_multiplex_interactive_auth.py`, `tests/gateway/test_telegram_auth_check.py`

**Relationships**

**calls:**
- _is_callback_user_authorized → strip
- _is_callback_user_authorized → _normalize_chat_type
- _is_callback_user_authorized → _is_sender_authorized
- _is_callback_user_authorized → _legacy_runner_auth_fn
- _is_callback_user_authorized → _env_allowlist_decision
- _is_callback_user_authorized → _scoped_gate_env
- _handle_inline_query → _is_callback_user_authorized
- _callback_authorized → _is_callback_user_authorized
- test_routed_primary_callback_uses_routed_pairing_store_and_transport_allowlist → _is_callback_user_authorized
- test_no_allowlist_no_allow_all_denies → _is_callback_user_authorized
- test_allowlist_with_matching_user_permits → _is_callback_user_authorized
- test_injected_check_used_when_handler_is_a_closure → _is_callback_user_authorized
- test_injected_check_deny_wins_over_env_allowlist → _is_callback_user_authorized
- _is_user_authorized_from_message → _source_from_message_for_auth
- _is_user_authorized_from_message → get
- ... and 137 more

**instantiates:**
- _is_callback_user_authorized → SessionSource

**references:**
- UserMessage → USER_ACTION_ICON_BUTTON_CLASS
- UserMessage → StopGlyph
- UserMessage → USER_BUBBLE_BASE_CLASS
- UserMessage → AGENT_MESSAGE_RE
- splitFences → FENCE_RE
- splitFences → TopSegment
- AgentMessageNote → AGENT_MESSAGE_RE

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`gateway/authz_mixin.py`** — calls(calls), _coerce_allow_set(calls), _coerce_allow_set(function), strip(calls), _is_user_authorized(method)

```python
82	    return None
83
84
85	def _coerce_allow_set(raw) -> set[str]:
86	    """Parse an allowlist (YAML list or comma-separated scalar) into a set of strings."""
87	    if raw is None:
88	        return set()
89	    if isinstance(raw, list):
90	        return {str(part).strip() for part in raw if str(part).strip()}
91	    return {part.strip() for part in str(raw).split(",") if part.strip()}
92
93
94	def _allows(allowed: set[str], candidate: Optional[str]) -> bool:

... (gap) ...

470	            self._warned_telegram_group_users_legacy = True
471	        return source.chat_id in legacy_chat_ids
472
473	    def _is_user_authorized(self, source: SessionSource, *, allow_adapter_delegation: bool = True) -> bool:
474	        """Whether a user may use the bot.
475
476	        Order: trusted-upstream delegation, chat-scoped group allowlists, ``{PLATFORM}_ALLOW_BOTS``,
477	        per-platform allow-all, adapter role auth, pairing store, env/config allowlists,
478	        ``GATEWAY_ALLOW_ALL_USERS``, default deny.
479	        """
480	        # HA events are system-generated (HASS_TOKEN); webhook events are HMAC-verified.
481	        if source.platform in {Platform.HOMEASSISTANT, Platform.WEBHOOK}:
482	            return True
483
484	        adapter_profile = self._adapter_profile_for_source(source)
485	        is_group = source.chat_type in _GROUP_CHAT_TYPES
486	        is_group_or_forum = source.chat_type in _GROUP_FORUM_TYPES
487	        if self._chat_scoped_grant(source, adapter_profile, is_group, allow_adapter_delegation):
488	            return True
489	        user_id = source.user_id
490	        if not user_id:
491	            return False
492
493	        platform_allow_env = _ALLOWED_USERS_ENV.get(source.platform, "")
494	        platform_allow_all_var = _ALLOW_ALL_ENV.get(source.platform, "")
495	        if source.platform not in _ALLOWED_USERS_ENV:
496	            entry = _registry_entry(source.platform)
497	            with contextlib.suppress(Exception):
498	                platform_allow_env = getattr(entry, "allowed_users_env", "") or platform_allow_env
499	                platform_allow_all_var = getattr(entry, "allow_all_env", "") or platform_allow_all_var
500	        if platform_allow_all_var and _env_truthy(platform_allow_all_var):
501	            return True
502	        # Adapter-verified role auth (Discord DISCORD_ALLOWED_ROLES). ``is True``: no MagicMock pass.
503	        if allow_adapter_delegation and getattr(source, "role_authorized", False) is True:
504	            return True
505	        # Pairing store: a first-class grant created only by an operator approving a code. Honored as
506	        # a UNION with the allowlist (approval also mirrors into it).
507	        pairing_store = self._pairing_store_for(source)
508	        if pairing_store is not None and pairing_store.is_approved(source.platform.value if source.platform else "", user_id):
509	            return True
510
511	        platform_allowlist = _auth_env(platform_allow_env)
512	        group_user_allowlist = _auth_env(_GROUP_USER_ENV.get(source.platform, "")) if is_group_or_forum else ""
513	        group_chat_allowlist = _auth_env(_GROUP_CHAT_ENV.get(source.platform, "")) if is_group_or_forum else ""
514	        global_allowlist = _auth_env("GATEWAY_ALLOWED_USERS")
515
516	        if not (platform_allowlist or group_user_allowlist or group_chat_allowlist or global_allowlist):
517	            # No env allowlist: own-policy adapters gate at intake (see _own_policy_authorizes).
518	            if allow_adapter_delegation and self._adapter_flag(source.platform, "enforces_own_access_policy", adapter_profile):
519	                verdict = self._own_policy_authorizes(source, user_id, is_group, adapter_profile)
520	                if verdict is not None:
521	                    return verdict
522	            if self._adapter_extra_allowlist_authorizes(source, user_id, is_group):
523	                return True
524	            return _env_truthy("GATEWAY_ALLOW_ALL_USERS")
525
526	        if is_group_or_forum and source.chat_id:
527	            # Telegram group traffic authorized by chat ID (TELEGRAM_GROUP_ALLOWED_USERS gates the sender).
528	            if group_chat_allowlist and _allows(_coerce_allow_set(group_chat_allowlist), source.chat_id):
529	                return True
530	            if (
531	                source.platform == Platform.TELEGRAM and group_user_allowlist
532	                and self._legacy_telegram_chat_grant(source, group_user_allowlist)
533	            ):
534	                return True
535
536	        # TELEGRAM_GROUP_ALLOWED_USERS is group-scoped (no DM access); TELEGRAM_ALLOWED_USERS is platform-wide.
537	        allowed_ids = (
538	            _coerce_allow_set(platform_allowlist)
539	            | _coerce_allow_set(group_user_allowlist)
540	            | _coerce_allow_set(global_allowlist)
541	        )
542	        if platform_allowlist:
543	            allowed_ids |= self._adapter_resolved_allowlist_ids(source)
544	        return "*" in allowed_ids or _principal_matches_allowlist(source, user_id, allowed_ids)
545
546	    def _get_unauthorized_dm_behavior(self, platform: Optional[Platform], *, profile: Optional[str] = None) -> str:
547	        """How unauthorized DMs are handled ("pair" / "ignore") for a platform.
```

**Not shown above — explore these names for their source**

- plugins/platforms/telegram/adapter.py: _is_callback_user_authorized:744, _is_user_authorized_from_message:855, TelegramAdapter:368, _normalize_chat_type:712, _legacy_runner_auth_fn:721, _env_allowlist_decision:736, +19 more
- plugins/platforms/matrix/adapter.py: _is_authorized_user:2350, MatrixAdapter:738, _env_truthy:476, _on_invite:2127, _validate_matrix_prompt_reactor:2355, _resolve_store_dir:748, +19 more
- ui-tui/src/domain/roles.ts: user:8
- apps/desktop/src/components/assistant-ui/thread/user-message.tsx: UserMessage:266, hasTextSelection:22, ProcessNotificationNote:234, AgentMessageNote:179, StickyHumanMessageContainer:28, USER_ACTION_ICON_BUTTON_CLASS:69, +5 more
- apps/desktop/src/components/assistant-ui/thread/user-message-text.tsx: UserMessageText:121, splitFences:68, InlineSegmentView:149, FENCE_RE:41, TopSegment:38
- nix/nixosModules.nix: user:256, User:214, flake.nixosModules.default:34, cfg:44, common:45, lib:45, +20 more
- tests/gateway/test_telegram_callback_auth_fail_closed.py: test_no_allowlist_no_allow_all_denies:72, test_allowlist_with_matching_user_permits:82, test_injected_check_used_when_handler_is_a_closure:103, test_injected_check_deny_wins_over_env_allowlist:124
- apps/desktop/src/components/assistant-ui/thread/content.ts: messageContentText:17, messageAttachmentRefs:47
- apps/desktop/src/components/assistant-ui/thread/message-reactions.tsx: ReactionPicker:99, ReactionBadge:166
- apps/desktop/src/app/artifacts/index.tsx: ArtifactsPagination:416, ArtifactImageCard:467, PrimaryCell:583, LocationCell:607, ArtifactTable:677
- ... and 23 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (8,774 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

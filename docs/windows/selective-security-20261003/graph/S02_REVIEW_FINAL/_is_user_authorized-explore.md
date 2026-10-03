**Exploration: _is_user_authorized**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `_is_callback_user_authorized` (plugins/platforms/telegram/adapter.py:1173) — 5 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_telegram_callback_auth_fail_closed.py`
- `_is_user_authorized_from_message` (plugins/platforms/telegram/adapter.py:1385) — 12 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_telegram_auth_check.py`

**Relationships**

**calls:**
- _is_callback_user_authorized → strip
- _is_callback_user_authorized → _scoped_gate_env
- _handle_choice_picker_callback → _is_callback_user_authorized
- _handle_callback_query → _is_callback_user_authorized
- _handle_gmail_triage_callback → _is_callback_user_authorized
- test_no_allowlist_no_allow_all_denies → _is_callback_user_authorized
- test_allowlist_with_matching_user_permits → _is_callback_user_authorized
- _is_user_authorized_from_message → _source_from_message_for_auth
- _is_user_authorized_from_message → get
- _is_user_authorized_from_message → _telegram_auth_env_configured
- _is_user_authorized_from_message → _is_sender_authorized
- _is_user_authorized_from_message → strip
- _is_user_authorized_from_message → _scoped_gate_env
- _is_user_authorized_from_message → _should_pass_unauthorized_dm_for_pairing
- _is_user_authorized_from_message → _coerce_allow_set
- ... and 152 more

**instantiates:**
- _is_callback_user_authorized → SessionSource

**references:**
- _is_user_authorized_from_message → Message
- UserMessage → USER_ACTION_ICON_BUTTON_CLASS
- UserMessage → StopGlyph
- UserMessage → USER_BUBBLE_BASE_CLASS
- splitFences → FENCE_RE
- splitFences → TopSegment
- _source_from_message_for_auth → Message

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`gateway/authz_mixin.py`** — calls(calls), _coerce_allow_set(calls), _is_user_authorized(method), strip(calls)

```python
450	            return per_profile[profile]
451	        return getattr(self, "pairing_store", None)
452
453	    def _is_user_authorized(
454	        self,
455	        source: SessionSource,
456	        *,
457	        allow_adapter_delegation: bool = True,
458	    ) -> bool:
459	        """
460	        Check if a user is authorized to use the bot.
461
462	        Checks in order:
463	        1. Per-platform allow-all flag (e.g., DISCORD_ALLOW_ALL_USERS=true)
464	        2. Environment variable allowlists (TELEGRAM_ALLOWED_USERS, etc.)
465	        3. DM pairing approved list
466	        4. Global allow-all (GATEWAY_ALLOW_ALL_USERS=true)
467	        5. Default: deny
468	        """
469	        from gateway.run import logger
470	        # Home Assistant events are system-generated (state changes), not
471	        # user-initiated messages.  The HASS_TOKEN already authenticates the
472	        # connection, so HA events are always authorized.
473	        # Webhook events are authenticated via HMAC signature validation in
474	        # the adapter itself — no user allowlist applies.
475	        if source.platform in {Platform.HOMEASSISTANT, Platform.WEBHOOK}:
476	            return True
477
478	        adapter_profile = self._adapter_profile_for_source(source)
479
480	        # Relay (and any adapter whose authorization is enforced by a trusted
481	        # authenticated upstream): the Team Gateway connector authenticates this
482	        # gateway's WS with a per-instance secret and resolves owner-only author
483	        # bindings BEFORE delivering, so an inbound relay event was already
484	        # authorized as this instance's bound user (the author id is the one the
485	        # connector observed, never gateway-asserted). There is no local
486	        # RELAY_ALLOWED_USERS env allowlist to consult, and default-denying for
487	        # its absence is the bug this branch fixes. This is delegation to a
488	        # trusted upstream, NOT a fail-open: it fires only for an event that was
489	        # actually delivered over the authenticated relay WS (the transport
490	        # stamps ``delivered_via_upstream_relay``), or whose platform's adapter
491	        # explicitly declares ``authorization_is_upstream=True``; every direct
492	        # network-exposed adapter leaves the flag False and its events unmarked,
493	        # so the env-allowlist default-deny below still applies unchanged.
494	        #
495	        # The delivery marker is the PRIMARY signal: a relay *message* inbound
496	        # carries the UNDERLYING platform (``source.platform`` == discord/…),
497	        # NOT ``Platform.RELAY``, because that's what session-keying and egress
498	        # need — so keying authz off ``source.platform`` would miss (the relay
499	        # adapter is registered under ``Platform.RELAY``) and default-deny the
500	        # user ("Unauthorized user <id> on discord"). The adapter-flag check is
501	        # retained for events whose ``source.platform`` IS ``Platform.RELAY``
502	        # (e.g. the interaction-passthrough path).
503	        # ``is True`` (not just truthiness): the marker is a real bool on a
504	        # SessionSource, and an explicit identity check refuses to authorize a
505	        # non-bool stand-in (e.g. a MagicMock attribute auto-vivifies truthy in
506	        # tests) — defensive against accidental fail-open.
507	        if allow_adapter_delegation and (
508	            source.delivered_via_upstream_relay is True
509	            or self._adapter_authorization_is_upstream(
510	                source.platform,
511	                profile=adapter_profile,
512	            )
513	        ):
514	            return True
515
516	        user_id = source.user_id
517
518	        # Telegram (and similar) authorize entire group/forum/channel chats
519	        # by chat ID via TELEGRAM_GROUP_ALLOWED_CHATS / QQ_GROUP_ALLOWED_USERS.
520	        # That allowlist is chat-scoped, so it must work even when
521	        # source.user_id is None — Telegram emits anonymous-admin posts,
522	        # sender_chat traffic, and channel broadcasts with no `from_user`,
523	        # and an operator who explicitly listed the chat expects those to
524	        # be honored. Run this check before the no-user-id guard below so
525	        # documented behavior matches reality
526	        # (website/docs/reference/environment-variables.md,
527	        # website/docs/user-guide/messaging/telegram.md).
528	        if source.chat_type in {"group", "forum", "channel"} and source.chat_id:
529	            chat_allowlist_env = {
530	                Platform.TELEGRAM: "TELEGRAM_GROUP_ALLOWED_CHATS",
531	                Platform.QQBOT: "QQ_GROUP_ALLOWED_USERS",
532	            }.get(source.platform, "")
533	            if chat_allowlist_env:
534	                raw_chat_allowlist = _platform_gate_env(chat_allowlist_env)
535	                if raw_chat_allowlist:
536	                    allowed_group_ids = {
537	                        cid.strip()
538	                        for cid in raw_chat_allowlist.split(",")
539	                        if cid.strip()
540	                    }
541	                    if "*" in allowed_group_ids or source.chat_id in allowed_group_ids:
542	                        return True
543
544	            # Fallback: also check adapter-level config (config.yaml)
545	            # for platforms.<platform>.extra.group_allowed_chats.
546	            # The Telegram observe-unmentioned mode strips user_id from
547	            # triggered group messages (_apply_telegram_group_observe_attribution),
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
560	                pass
561
562	        # Bots admitted by {PLATFORM}_ALLOW_BOTS bypass the human allowlist (#4466).
563	        # Checked before the no-user-id guard below: some platforms deliver
564	        # bot/automation traffic with no user_id at all -- e.g. Slack Workflow
565	        # Builder posts arrive as subtype=bot_message with user=None -- so
566	        # deferring past the guard would reject them outright (the same reason
567	        # the chat-scoped allowlist above runs early).
568	        platform_allow_bots_map = {
569	            Platform.DISCORD: "DISCORD_ALLOW_BOTS",
570	            Platform.FEISHU: "FEISHU_ALLOW_BOTS",
571	            Platform.TELEGRAM: "TELEGRAM_ALLOW_BOTS",
572	            Platform.SLACK: "SLACK_ALLOW_BOTS",
573	        }
574	        if getattr(source, "is_bot", False):
575	            allow_bots_var = platform_allow_bots_map.get(source.platform)
576	            if allow_bots_var and _platform_gate_env(allow_bots_var, "none").lower().strip() in {"mentions", "all"}:
577	                return True
578
579	        if not user_id:
580	            return False
581
582	        platform_env_map = {
583	            Platform.TELEGRAM: "TELEGRAM_ALLOWED_USERS",
584	            Platform.DISCORD: "DISCORD_ALLOWED_USERS",
585	            Platform.WHATSAPP: "WHATSAPP_ALLOWED_USERS",
586	            Platform.WHATSAPP_CLOUD: "WHATSAPP_CLOUD_ALLOWED_USERS",
587	            Platform.SLACK: "SLACK_ALLOWED_USERS",
588	            Platform.SIGNAL: "SIGNAL_ALLOWED_USERS",
589	            Platform.EMAIL: "EMAIL_ALLOWED_USERS",
590	            Platform.SMS: "SMS_ALLOWED_USERS",
591	            Platform.MATTERMOST: "MATTERMOST_ALLOWED_USERS",
592	            Platform.MATRIX: "MATRIX_ALLOWED_USERS",
593	            Platform.DINGTALK: "DINGTALK_ALLOWED_USERS",
594	            Platform.FEISHU: "FEISHU_ALLOWED_USERS",
595	            Platform.WECOM: "WECOM_ALLOWED_USERS",
596	            Platform.WECOM_CALLBACK: "WECOM_CALLBACK_ALLOWED_USERS",
597	            Platform.WEIXIN: "WEIXIN_ALLOWED_USERS",
598	            Platform.BLUEBUBBLES: "BLUEBUBBLES_ALLOWED_USERS",
599	            Platform.QQBOT: "QQ_ALLOWED_USERS",
600	            Platform.YUANBAO: "YUANBAO_ALLOWED_USERS",
601	        }
602	        platform_group_user_env_map = {
603	            Platform.TELEGRAM: "TELEGRAM_GROUP_ALLOWED_USERS",
604	        }
605	        platform_group_chat_env_map = {
606	            Platform.TELEGRAM: "TELEGRAM_GROUP_ALLOWED_CHATS",
607	            Platform.QQBOT: "QQ_GROUP_ALLOWED_USERS",
608	        }
609	        platform_allow_all_map = {
610	            Platform.TELEGRAM: "TELEGRAM_ALLOW_ALL_USERS",
611	            Platform.DISCORD: "DISCORD_ALLOW_ALL_USERS",
612	            Platform.WHATSAPP: "WHATSAPP_ALLOW_ALL_USERS",
613	            Platform.WHATSAPP_CLOUD: "WHATSAPP_CLOUD_ALLOW_ALL_USERS",
614	            Platform.SLACK: "SLACK_ALLOW_ALL_USERS",
615	            Platform.SIGNAL: "SIGNAL_ALLOW_ALL_USERS",
616	            Platform.EMAIL: "EMAIL_ALLOW_ALL_USERS",
617	            Platform.SMS: "SMS_ALLOW_ALL_USERS",
618	            Platform.MATTERMOST: "MATTERMOST_ALLOW_ALL_USERS",
619	            Platform.MATRIX: "MATRIX_ALLOW_ALL_USERS",
620	            Platform.DINGTALK: "DINGTALK_ALLOW_ALL_USERS",
621	            Platform.FEISHU: "FEISHU_ALLOW_ALL_USERS",
622	            Platform.WECOM: "WECOM_ALLOW_ALL_USERS",
623	            Platform.WECOM_CALLBACK: "WECOM_CALLBACK_ALLOW_ALL_USERS",
624	            Platform.WEIXIN: "WEIXIN_ALLOW_ALL_USERS",
625	            Platform.BLUEBUBBLES: "BLUEBUBBLES_ALLOW_ALL_USERS",
626	            Platform.QQBOT: "QQ_ALLOW_ALL_USERS",
627	            Platform.YUANBAO: "YUANBAO_ALLOW_ALL_USERS",
628	        }
629
630	        # Plugin platforms: check the registry for auth env var names
631	        if source.platform not in platform_env_map:
632	            try:
633	                from gateway.platform_registry import platform_registry
634
635	                entry = platform_registry.get(source.platform.value)
636	                if entry:
637	                    if entry.allowed_users_env:
638	                        platform_env_map[source.platform] = entry.allowed_users_env
639	                    if entry.allow_all_env:
640	                        platform_allow_all_map[source.platform] = entry.allow_all_env
641	            except Exception:
642	                pass
643
644	        # Per-platform allow-all flag (e.g., DISCORD_ALLOW_ALL_USERS=true)
645	        platform_allow_all_var = platform_allow_all_map.get(source.platform, "")
646	        if platform_allow_all_var and _auth_env(platform_allow_all_var).lower() in {"true", "1", "yes"}:
647	            return True
648
649	        # Adapter-verified role auth: the Discord adapter already confirmed the
650	        # user holds a role in DISCORD_ALLOWED_ROLES before dispatching the message.
651	        # Compare with ``is True`` so the real bool field authorizes while a
652	        # MagicMock source (test fixtures using ``object.__new__`` runners with
653	        # mock sources) does not auto-truthy through this gate (see pitfall #13).
654	        if (
655	            allow_adapter_delegation
656	            and getattr(source, "role_authorized", False) is True
657	        ):
658	            return True
659
660	        # Check pairing store. A pairing entry is a first-class authorization
661	        # grant, created only by a trusted operator approving a pairing code
662	        # (hermes gateway pairing approve / the authenticated dashboard) — an
663	        # inbound sender can never reach approve_code, so this is not an
664	        # attacker-controlled path. Honored as a UNION with the allowlist: a
665	        # paired user is authorized regardless of the allowlist, and when an
666	        # allowlist IS configured, operator approval also writes the user into
667	        # that allowlist (see PairingStore._approve_user), keeping a single
668	        # operator-visible source of truth. (#23778: the original bypass was the
669	        # inbound message/approval-button gate, not this gate; that gate is
670	        # fixed separately.)
671	        # In multiplex gateways, route to the per-profile PairingStore so each
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
690	            # config-driven access policy (dm_policy / group_policy /
691	            # allow_from / group_allow_from) gate access at intake, so for those
692	            # platforms we can honor the adapter's decision instead of the
693	            # env-only default-deny below -- but ONLY when that decision was an
694	            # actual allowlist restriction.
695	            #
696	            # The adapters default dm_policy / group_policy to "open", which
697	            # forwards EVERY sender. Reading "reached the gateway" as
698	            # authorization in that case would admit the whole external network
699	            # with no operator-configured allowlist -- the fail-open SECURITY.md
700	            # §2.6 forbids ("an allowlist is required for every enabled
701	            # network-exposed adapter ... code paths that fail open when no
702	            # allowlist is configured are code bugs"). "disabled" never
703	            # forwards, and "pairing" forwards unpaired DMs only so the gateway
704	            # can run its pairing handshake (the pairing-store check above
705	            # already denied this sender). So trust the adapter only when its
706	            # effective policy for THIS chat type is "allowlist"; for "open" /
707	            # "pairing" / anything else, fall through to default-deny, where
708	            # GATEWAY_ALLOW_ALL_USERS, the per-platform {PLATFORM}_ALLOW_ALL_USERS
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
746	                        dm_check = (
747	                            getattr(adapter, "_is_dm_allowed", None)
748	                            if adapter is not None
749	                            else None
750	                        )
751	                        if callable(dm_check):
752	                            return bool(dm_check(user_id))
753	                    return True
754	            # Some adapters (e.g. Telegram) gate access via config.extra.allow_from /
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
774	        # the sender user ID for group/forum messages.
775	        if group_chat_allowlist and source.chat_type in {"group", "forum"} and source.chat_id:
776	            allowed_group_ids = {
777	                chat_id.strip() for chat_id in group_chat_allowlist.split(",") if chat_id.strip()
778	            }
779	            if "*" in allowed_group_ids or source.chat_id in allowed_group_ids:
780	                return True
781
782	        # Backward-compat shim for #15027: prior to PR #17686,
783	        # TELEGRAM_GROUP_ALLOWED_USERS was (mis)used as a chat-ID allowlist.
784	        # Values starting with "-" are Telegram chat IDs, not user IDs, so if
785	        # users still have those in TELEGRAM_GROUP_ALLOWED_USERS we honor them
786	        # as chat IDs and warn once. The correct var is now
787	        # TELEGRAM_GROUP_ALLOWED_CHATS.
788	        if (
789	            source.platform == Platform.TELEGRAM
790	            and group_user_allowlist
791	            and source.chat_type in {"group", "forum"}
792	            and source.chat_id
793	        ):
794	            legacy_chat_ids = {
795	                v.strip()
796	                for v in group_user_allowlist.split(",")
797	                if v.strip().startswith("-")
798	            }
799	            if legacy_chat_ids:
800	                if not getattr(self, "_warned_telegram_group_users_legacy", False):
801	                    logger.warning(
802	                        "TELEGRAM_GROUP_ALLOWED_USERS contains chat-ID-shaped values "
803	                        "(%s). Treating them as chat IDs for backward compatibility. "
804	                        "Move chat IDs to TELEGRAM_GROUP_ALLOWED_CHATS — the _USERS var "
805	                        "is now for sender user IDs.",
806	                        ",".join(sorted(legacy_chat_ids)),
807	                    )
808	                    self._warned_telegram_group_users_legacy = True
809	                if source.chat_id in legacy_chat_ids:
810	                    return True
811
812	        # Check if user is in any allowlist. In group/forum chats,
813	        # TELEGRAM_GROUP_ALLOWED_USERS is the scoped allowlist and should not
814	        # imply DM access; TELEGRAM_ALLOWED_USERS remains the platform-wide
815	        # allowlist and still works everywhere for backward compatibility.
816	        allowed_ids = set()
817	        if platform_allowlist:
818	            allowed_ids.update(uid.strip() for uid in platform_allowlist.split(",") if uid.strip())
819	        if group_user_allowlist:
```

**Not shown above — explore these names for their source**

- plugins/platforms/telegram/adapter.py: _is_callback_user_authorized:1173, _is_user_authorized_from_message:1385, TelegramAdapter:575, _scoped_gate_env:43, _handle_choice_picker_callback:6737, _handle_callback_query:7262, +23 more
- plugins/platforms/google_chat/adapter.py: AuthorizedHttp:70, _new_authed_http:2530, GoogleChatAdapter:625, _resolve_bot_user_id:943, _do_delete:2315, _do_patch:2353, +19 more
- ui-tui/src/domain/roles.ts: user:8
- apps/desktop/src/components/assistant-ui/thread/user-message.tsx: UserMessage:266, hasTextSelection:22, ProcessNotificationNote:234, AgentMessageNote:179, StickyHumanMessageContainer:28, USER_ACTION_ICON_BUTTON_CLASS:69, +5 more
- ... and 29 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

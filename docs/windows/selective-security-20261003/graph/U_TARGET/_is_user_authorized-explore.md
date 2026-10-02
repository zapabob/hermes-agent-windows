**Exploration: _is_user_authorized**

Found 2 symbols across 1 file.

**Blast radius — what depends on these (update/verify before editing)**

- `authorize` (scripts/releases/channel_build.py:105) — 1 caller in `scripts/releases/channel_build.py`; tested via callers: `tests/scripts/test_release_channel_build.py`
- `authorize` (scripts/releases/channel_disposable.py:116) — 1 caller in `scripts/releases/channel_disposable.py`; no tests found within 3 caller hops
- `authorize` (scripts/releases/channel_publish.py:218) — 1 caller in `scripts/releases/channel_publish.py`; tested via callers: `tests/ci/test_channel_build_publication.py`
- `_is_callback_user_authorized` (plugins/platforms/telegram/adapter.py:927) — 9 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_multiplex_interactive_auth.py`, `tests/gateway/test_telegram_callback_auth_fail_closed.py`
- `_is_user_authorized_from_message` (plugins/platforms/telegram/adapter.py:1039) — 13 callers in `plugins/platforms/telegram/adapter.py`; tests: `tests/gateway/test_multiplex_interactive_auth.py`, `tests/gateway/test_telegram_auth_check.py`

**Relationships**

**calls:**
- authorize → output
- maintainer_authorizer → validate_repository
- configured_publisher → maintainer_authorizer
- configured_publisher → output
- resolve_revision → output
- authorize → admit
- allocate → get
- allocate → validate_name
- allocate → selects_all
- allocate → require_run
- allocate → admit
- allocate → require_commit
- allocate → configured
- allocate → channel_public_base
- allocate → credentials
- ... and 148 more

**instantiates:**
- authorize → ChannelError
- _match → ChannelError
- validate_name → ChannelError
- pairs → ChannelError
- decode_json → ChannelError
- public_base → ChannelError
- artifact_key → ChannelError
- _integer → ChannelError
- _schema → ChannelError
- validate_identity → ChannelError
- validate_request → ChannelError
- _head → ChannelError
- validate_record → ChannelError
- redirect_request → ChannelError
- read → ChannelError
- ... and 7 more

**references:**
- maintainer_authorizer → authorize
- allocate → authorize
- main → authorize
- main → qualified
- decode_json → pairs
- read_bytes → read

**extends:**
- ChannelNotFound → ChannelError
- ChannelConflict → ChannelError
- PublicVisibilityError → ChannelError

**Source Code**

> The code below is the **verbatim, current on-disk source** of these files — re-read from disk on this call and line-numbered, byte-for-byte identical to what the Read tool returns. It is NOT a summary, outline, or stale cache. Treat each block as a Read you have already performed: do not Read a file shown here.

**`gateway/authz_mixin.py`** — calls(calls), _coerce_allow_set(function), _is_user_authorized(method)

```python
68	    return None
69
70
71	def _coerce_allow_set(raw) -> set[str]:
72	    """Parse an allowlist (YAML list, JSON list literal string, or comma-separated scalar) into a set of strings."""
73	    if raw is None:
74	        return set()
75	    raw = _decode_json_list_literal(raw)
76	    if isinstance(raw, list):
77	        return {str(part).strip() for part in raw if str(part).strip()}
78	    return {part.strip() for part in str(raw).split(",") if part.strip()}
79
80
81	def _allows(allowed: set[str], candidate: Optional[str]) -> bool:

... (gap) ...

611	            )
612	        return allowed
613
614	    def _is_user_authorized(self, source: SessionSource, *, allow_adapter_delegation: bool = True) -> bool:
615	        """Whether a user may use the bot.
616
617	        Order: trusted-upstream delegation, chat-scoped group allowlists, ``{PLATFORM}_ALLOW_BOTS``,
618	        per-platform allow-all, adapter role auth, pairing store, env/config allowlists,
619	        ``GATEWAY_ALLOW_ALL_USERS``, default deny. A bot-authored message that any of these admits
620	        is still refused while its chat's loop guard is cooling down.
621	        """
622	        if not self._principal_authorized(source, allow_adapter_delegation=allow_adapter_delegation):
623	            return False
624	        if not getattr(source, "is_bot", False):
625	            return True
626	        # The guard judges the final verdict: a chat allowlist admits a bot before the ALLOW_BOTS block runs.
627	        return not self._bot_loop_guard_instance().blocked(self._bot_loop_guard_conversation(source))
628
629	    def _principal_authorized(self, source: SessionSource, *, allow_adapter_delegation: bool) -> bool:
630	        """The allowlist verdict alone, before the bot loop guard."""
```

**Not shown above — explore these names for their source**

- plugins/platforms/telegram/adapter.py: _is_callback_user_authorized:927, _is_user_authorized_from_message:1039, TelegramAdapter:510, _normalize_chat_type:895, _legacy_runner_auth_fn:904, _env_allowlist_decision:919, +18 more
- ui-tui/src/domain/roles.ts: user:8
- scripts/releases/channel_publish.py: authorize:218, admit:58, main:190, qualified:223, read_request:21, require_success:31, +3 more
- scripts/releases/channel_disposable.py: authorize:116, allocate:87, probe:24, allocate_receivers:58, main:139
- scripts/releases/channel_build.py: authorize:105, maintainer_authorizer:102, configured_publisher:126
- scripts/releases/commit_build.py: output:22, resolve_revision:180, admit:67, require_commit:16, _controller:46, version_at:37, +2 more
- nix/nixosModules.nix: user:263, flake.nixosModules.default:34, cfg:44, common:45, lib:45, effectivePackage:47, +19 more
- hermes_cli/release_channels.py: ChannelError:22, validate_repository:43, ChannelNotFound:26, _match:30, validate_name:36, pairs:68, +12 more
- tests/gateway/test_multiplex_interactive_auth.py: test_routed_primary_callback_uses_routed_pairing_store_and_transport_allowlist:72, test_secondary_owned_callback_reads_own_profile_allowlist:113, test_secondary_callback_allowlist_follows_env_edits:141, test_bot_sender_reaches_allow_bots_policy_through_callback:90
- tests/gateway/test_telegram_callback_auth_fail_closed.py: test_no_allowlist_no_allow_all_denies:72, test_allowlist_with_matching_user_permits:82, test_injected_check_used_when_handler_is_a_closure:103, test_injected_check_deny_wins_over_env_allowlist:124
- ... and 16 more files

---
> **Complete source for 1 files is included above — do NOT re-read them.** If your question also needs files/symbols listed under "Not shown above" (or any area this call didn't cover), make ANOTHER codegraph_explore targeting those names — it returns the same source with line numbers and is cheaper and more complete than reading. Reserve Read for a single specific line range explore can't surface.

> **Explore budget: 3 calls for this project (13,144 files indexed).** Each call covers ~6 files; if your question spans more, spend your remaining calls on the uncovered area BEFORE falling back to Read — another explore is cheaper and more complete than reading those files. Synthesize once you've used 3.

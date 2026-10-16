"""Actual SDK binding contracts: relay; separate process budget, unchanged assertions."""
import pytest

from tests.fakes.mcp_oauth_config_binding_contract import (
    homes as homes,
    owned_protocol_evidence as owned_protocol_evidence,
    test_changed_connection_cannot_adopt_actual_grant as test_changed_connection_cannot_adopt_actual_grant,
    test_changed_after_actual_token_write_discards_only_owned_bytes as test_changed_after_actual_token_write_discards_only_owned_bytes,
    test_unchanged_connection_keeps_actual_sdk_nonce_effect as test_unchanged_connection_keeps_actual_sdk_nonce_effect,
    test_wrong_state_then_real_callback_and_replay_keep_one_grant as test_wrong_state_then_real_callback_and_replay_keep_one_grant,
    test_changed_flow_settles_then_fresh_current_target_owns_grant as test_changed_flow_settles_then_fresh_current_target_owns_grant,
    test_implicit_auth_commit_preserves_template_and_reusable_provider as test_implicit_auth_commit_preserves_template_and_reusable_provider,
    test_actual_invalid_config_cannot_authorize_saved_flow as test_actual_invalid_config_cannot_authorize_saved_flow,
    test_changed_after_actual_probe_cannot_commit_old_connection as test_changed_after_actual_probe_cannot_commit_old_connection,
)


@pytest.fixture(params=("relay",))
def surface(request):
    return request.param

"""Existing one-argument native/plugin probes retain stream behavior."""

import pytest

from gateway.stream_consumer import GatewayStreamConsumer, StreamConsumerConfig
from tests.gateway.test_stream_consumer_draft import _make_draft_capable_adapter


@pytest.mark.asyncio
async def test_one_argument_probe_keeps_native_cumulative_segments():
    adapter = _make_draft_capable_adapter()
    calls = []

    def native_probe(self, chat_id):
        calls.append(chat_id)
        return chat_id == 'owned-native-chat'

    type(adapter).stream_is_message_for_chat = native_probe
    consumer = GatewayStreamConsumer(
        adapter, 'owned-native-chat',
        StreamConsumerConfig(transport='draft', chat_type='dm', edit_interval=0, cursor=''),
        metadata={'thread_id': 'owned-native-thread'},
    )
    consumer.on_delta('Native first segment.')
    consumer.on_segment_break()
    consumer.on_delta('Native second segment.')
    consumer.finish()
    await consumer.run()
    assert calls and set(calls) == {'owned-native-chat'}
    assert 'Native first segment.' in adapter.draft_calls[-1]['content']
    # This native fixture publishes the final via send; unlike RelayAdapter,
    # it does not turn that send into a final draft frame.
    adapter.send.assert_awaited_once()
    final_content = adapter.send.call_args.kwargs['content']
    assert 'Native first segment.' in final_content
    assert 'Native second segment.' in final_content
    assert consumer.final_response_sent


def test_metadata_aware_probe_body_error_does_not_retry_without_identity():
    adapter = _make_draft_capable_adapter()
    calls = []

    def broken_probe(self, chat_id, metadata=None):
        calls.append((chat_id, metadata))
        if metadata is not None:
            raise TypeError('owned probe body failure')
        return True

    type(adapter).stream_is_message_for_chat = broken_probe
    metadata = {'thread_id': 'owned-thread', 'scope_id': 'owned-scope'}
    consumer = GatewayStreamConsumer(adapter, 'owned-chat', metadata=metadata)
    assert consumer._stream_is_message() is False
    assert calls == [('owned-chat', metadata)]

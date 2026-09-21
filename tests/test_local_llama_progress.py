import json
import unittest
from unittest.mock import MagicMock, patch

from agent.chat_completion_helpers import _poll_local_llama_progress, _LlamaProgressTracker


class TestLocalLlamaProgress(unittest.TestCase):
    def test_none_or_empty_base_url(self):
        self.assertIsNone(_poll_local_llama_progress(None))
        self.assertIsNone(_poll_local_llama_progress(""))

    @patch("urllib.request.urlopen")
    def test_successful_reading_progress(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {
                "id": 0,
                "is_processing": True,
                "n_prompt_tokens": 10000,
                "n_prompt_tokens_processed": 5500,
            }
        ]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = _poll_local_llama_progress("http://127.0.0.1:8080/v1", "test-model")
        self.assertIsNotNone(res)
        self.assertEqual(res["phase"], "reading")
        self.assertEqual(res["processed"], 5500)
        self.assertEqual(res["total"], 10000)
        self.assertAlmostEqual(res["pct"], 55.0)

    @patch("urllib.request.urlopen")
    def test_successful_generating_progress(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {
                "id": 0,
                "is_processing": True,
                "n_prompt_tokens": 10000,
                "n_prompt_tokens_processed": 10000,
                "next_token": [{"n_decoded": 42}],
            }
        ]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = _poll_local_llama_progress("http://127.0.0.1:8080/v1", "test-model")
        self.assertIsNotNone(res)
        self.assertEqual(res["phase"], "generating")
        self.assertEqual(res["decoded"], 42)

    @patch("urllib.request.urlopen")
    def test_idle_slot_returns_none(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {
                "id": 0,
                "is_processing": False,
                "n_prompt_tokens": 10000,
                "n_prompt_tokens_processed": 10000,
            }
        ]).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        res = _poll_local_llama_progress("http://127.0.0.1:8080/v1")
        self.assertIsNone(res)

    @patch("urllib.request.urlopen")
    def test_connection_error_fails_silently(self, mock_urlopen):
        mock_urlopen.side_effect = ConnectionRefusedError("Connection refused")
        res = _poll_local_llama_progress("http://127.0.0.1:8080/v1")
        self.assertIsNone(res)

    def test_tracker_lifecycle_non_local(self):
        agent = MagicMock()
        tracker = _LlamaProgressTracker(agent, "https://api.openai.com/v1")
        tracker.start()
        self.assertIsNone(tracker.thread)
        tracker.stop()

    @patch("http.client.HTTPConnection")
    def test_tracker_lifecycle_local(self, mock_http):
        agent = MagicMock()
        tracker = _LlamaProgressTracker(agent, "http://127.0.0.1:8080/v1", "test-model")
        tracker.start()
        self.assertIsNotNone(tracker.thread)
        self.assertTrue(tracker.thread.is_alive())
        tracker.stop()
        tracker.thread.join(timeout=1.0)
        self.assertFalse(tracker.thread.is_alive())

    def test_tracker_batch_heartbeat_notice(self):
        agent = MagicMock()
        tracker = _LlamaProgressTracker(agent, "http://127.0.0.1:8080/v1", "test-model")
        mock_conn = MagicMock()
        mock_resp = MagicMock()

        def mock_read():
            tracker.stop_event.set()
            return json.dumps([
                {
                    "id": 0,
                    "is_processing": True,
                    "n_prompt_tokens": 10000,
                    "n_prompt_tokens_processed": 4096,
                }
            ]).encode("utf-8")

        mock_resp.read.side_effect = mock_read
        mock_conn.getresponse.return_value = mock_resp
        tracker.conn = mock_conn

        with patch.object(tracker, "_get_connection", return_value=mock_conn):
            tracker._run()

        agent._emit_wait_notice.assert_called()
        notice_args = agent._emit_wait_notice.call_args[0][0]
        self.assertIn("Reading context: 41.0%", notice_args)
        self.assertIn("4,096/10,000", notice_args)


if __name__ == "__main__":
    unittest.main()

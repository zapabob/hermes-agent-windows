import json
import unittest
from unittest.mock import MagicMock, patch

from agent.chat_completion_helpers import _poll_local_llama_progress


class TestLocalLlamaProgress(unittest.TestCase):
    def test_none_or_empty_base_url(self):
        self.assertIsNone(_poll_local_llama_progress(None))
        self.assertIsNone(_poll_local_llama_progress(""))

    @patch("urllib.request.urlopen")
    def test_successful_progress_parsing(self, mock_urlopen):
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
        processed, total, pct = res
        self.assertEqual(processed, 5500)
        self.assertEqual(total, 10000)
        self.assertAlmostEqual(pct, 55.0)

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


if __name__ == "__main__":
    unittest.main()

"""Stable machine codes, five native locales and agent-readable documentation."""
from __future__ import annotations

import importlib
import json
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class I18nDocsTests(unittest.TestCase):
    def setUp(self):
        try:
            self.k = importlib.import_module("downstream.implementation_router.kernel")
            self.i = importlib.import_module("downstream.implementation_router.i18n")
        except ModuleNotFoundError:
            self.fail("ImplementationRouter contract is not implemented on this base")

    def test_all_native_locales_have_the_same_message_keys(self):
        catalog = self.i.load_catalog()
        self.assertEqual(set(catalog), {"en", "ja", "zh", "zh-hant", "ar"})
        keys = set(catalog["en"])
        for locale, messages in catalog.items():
            self.assertEqual(set(messages), keys, locale)
            self.assertTrue(all(isinstance(value, str) and value.strip() for value in messages.values()))

    def test_locale_aliases_fallback_and_rtl(self):
        for value, expected in (("ja_JP", "ja"), ("zh-TW", "zh-hant"), ("zh_Hant_HK", "zh-hant"),
                                ("zh-CN", "zh"), ("ar-SA", "ar"), ("unknown", "en"), (None, "en")):
            with self.subTest(value=value):
                self.assertEqual(self.i.normalise_locale(value), expected)
        self.assertEqual(self.i.text_direction("ar"), "rtl")
        self.assertEqual(self.i.text_direction("ja"), "ltr")

    def test_machine_state_and_reason_do_not_change_with_translation(self):
        result = self.k.RunResult("BLOCKED", "credential_boundary_unavailable", 0, 1, ())
        self.assertTrue(hasattr(result, "to_dict"), "RunResult must expose the localised machine-safe result")
        outputs = [result.to_dict(locale=locale) for locale in self.i.load_catalog()]
        self.assertEqual(len({row["message"] for row in outputs}), 5)
        for row in outputs:
            self.assertEqual(row["state"], "BLOCKED")
            self.assertEqual(row["reason_code"], "credential_boundary_unavailable")

    def test_unrecognised_host_text_is_not_reflected_in_public_errors(self):
        result = self.k.RunResult("secret-in-state", "synthetic-secret-in-error", 0, 1, ())
        self.assertTrue(hasattr(result, "to_dict"))
        out = result.to_dict(locale="ja")
        self.assertNotIn("secret", json.dumps(out))
        self.assertEqual(out["state"], "BLOCKED")
        self.assertEqual(out["reason_code"], "unknown_result")

    def test_each_locale_has_an_equivalent_safety_and_status_guide(self):
        for locale in self.i.load_catalog():
            guide = ROOT / "docs" / "implementation-router" / "i18n" / f"{locale}.md"
            self.assertTrue(guide.is_file(), str(guide))
            text = guide.read_text(encoding="utf-8")
            for marker in ("<!-- routing-not-moa -->", "<!-- credentials-host-only -->",
                           "<!-- native-adapter-unavailable -->", "<!-- not-os-sandbox -->"):
                self.assertIn(marker, text, locale)
            self.assertIn("AGENT_PROTOCOL.md", text)

    def test_agent_protocol_pins_no_secret_and_fail_closed_requirements(self):
        path = ROOT / "docs" / "implementation-router" / "AGENT_PROTOCOL.md"
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        for contract in ("host-brokered-credential-free-v1", "Co-authored-by", "UNKNOWN",
                         "Codex SDK", "credential_boundary_unavailable", "actual provider"):
            self.assertIn(contract, text)

    def test_locale_coverage_matches_native_desktop_when_source_is_available(self):
        path = ROOT / "apps" / "desktop" / "src" / "i18n" / "languages.ts"
        if not path.is_file():
            self.skipTest("Full-checkout locale parity is exercised by hosted qualification")
        source = path.read_text(encoding="utf-8")
        ids = set(re.findall(r"id:\s*'([^']+)'", source))
        self.assertEqual(set(self.i.load_catalog()), ids)

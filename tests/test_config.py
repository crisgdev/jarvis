import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_MODEL = "gemini-3.5-flash-lite"
REQUIRED_SECTIONS = ("voice", "llm", "memory", "gui", "audio")


class ConfigJsonTest(unittest.TestCase):
    def setUp(self):
        self._raw = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    def test_required_sections_present(self):
        for section in REQUIRED_SECTIONS:
            self.assertIn(section, self._raw, f"Falta seccion '{section}'")

    def test_llm_model_defined(self):
        self.assertIn("model", self._raw["llm"])
        self.assertTrue(self._raw["llm"]["model"])

    def test_max_output_tokens_caps_responses(self):
        self.assertGreaterEqual(self._raw["llm"].get("max_output_tokens", 0), 32)

    def test_stt_model_valid(self):
        self.assertIn(
            self._raw["voice"].get("stt_model"),
            ("small", "turbo", "medium", "large-v3"),
        )

    def test_llm_model_matches_code_default(self):
        # El default en brain.gemini.py debe coincidir con config.json
        self.assertEqual(self._raw["llm"]["model"], DEFAULT_MODEL)

    def test_voice_language_es(self):
        self.assertEqual(self._raw["voice"]["language"], "es")


class ConfigModuleTest(unittest.TestCase):
    def test_get_config_roundtrip(self):
        import config
        cfg = config.get_config()
        self.assertEqual(cfg["llm"]["model"], DEFAULT_MODEL)

    def test_get_setting_default(self):
        import config
        config.load_config()
        self.assertEqual(config.get_setting("audio", "sample_rate", 16000), 16000)
        self.assertIsNone(config.get_setting("no_existe", "nada", None))


if __name__ == "__main__":
    unittest.main()
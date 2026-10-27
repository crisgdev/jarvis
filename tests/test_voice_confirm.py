import unittest

from core.voice_confirm import interpret_confirmation


class InterpretConfirmationTest(unittest.TestCase):
    def test_confirmation_words(self):
        for phrase in ["procede", "sí", "si", "adelante", "confirmo", "de acuerdo", "hazlo", "dale"]:
            self.assertTrue(interpret_confirmation(phrase), phrase)

    def test_cancel_words(self):
        for phrase in ["no", "cancela", "cancelar", "para", "detente", "espera"]:
            self.assertFalse(interpret_confirmation(phrase), phrase)

    def test_case_and_punctuation_insensitive(self):
        self.assertTrue(interpret_confirmation("  Procede, señor. "))
        self.assertFalse(interpret_confirmation("NO, detente"))

    def test_cancel_priority_over_confirm(self):
        self.assertFalse(interpret_confirmation("no, cancela por favor"))

    def test_unclear_returns_none(self):
        for phrase in [None, "", "zzz qqq", "los lomitos del jueves"]:
            self.assertIsNone(interpret_confirmation(phrase), phrase)

    def test_no_apagues_counts_as_cancel(self):
        self.assertFalse(interpret_confirmation("no apagues la pc"))

    def test_apaga_counts_as_confirm(self):
        self.assertTrue(interpret_confirmation("apaga la pc"))


if __name__ == "__main__":
    unittest.main()
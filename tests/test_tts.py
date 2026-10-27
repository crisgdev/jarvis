import unittest

from services.tts import _split_sentences


class SplitSentencesTest(unittest.TestCase):
    def test_plain_single_sentence(self):
        self.assertEqual(_split_sentences("Abri google"), ["Abri google"])

    def test_multiple_sentences_split(self):
        result = _split_sentences("Abri google. Ya esta listo.")
        self.assertEqual(result, ["Abri google.", "Ya esta listo."])

    def test_keeps_question_and_exclamation(self):
        result = _split_sentences("Cual es la hora? Y la fecha!")
        self.assertEqual(result, ["Cual es la hora?", "Y la fecha!"])

    def test_empty_returns_single(self):
        self.assertEqual(_split_sentences(""), [""])

    def test_whitespace_trimmed(self):
        result = _split_sentences("  Abri google  ")
        self.assertEqual(result, ["Abri google"])


if __name__ == "__main__":
    unittest.main()
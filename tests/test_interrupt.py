import unittest

from core.jarvis import _is_echo, _strip_interrupt, _INTERRUPT_PATTERN


class InterruptHelpersTest(unittest.TestCase):
    def test_common_interrupt_words_detected(self):
        for phrase in ("para", "espera", "silencio", "callate", "detente",
                       "basta", "stop", "deja de hablar"):
            self.assertTrue(
                _INTERRUPT_PATTERN.search(phrase),
                f"{phrase!r} deberia detectarse como interrupcion",
            )

    def test_strip_interrupt_isolated(self):
        self.assertEqual(_strip_interrupt("cállate"), "")
        self.assertEqual(_strip_interrupt("para"), "")
        self.assertEqual(_strip_interrupt("silencio"), "")

    def test_strip_interrupt_keeps_rectification(self):
        self.assertEqual(
            _strip_interrupt("callate, dime mis eventos de mañana").strip(",. "),
            "dime mis eventos de mañana",
        )
        self.assertEqual(
            _strip_interrupt("espera, mejor abre youtube"),
            "mejor abre youtube",
        )

    def test_echo_detected(self):
        self.assertTrue(
            _is_echo("tienes clases de sistemas operativos", "tienes clases de sistemas operativos")
        )
        self.assertTrue(
            _is_echo("clases de sistemas operativos el lunes", "tienes clases de sistemas operativos")
        )

    def test_user_speech_not_echo(self):
        self.assertFalse(
            _is_echo("para, dime mi horario", "tienes clases de sistemas operativos")
        )


if __name__ == "__main__":
    unittest.main()
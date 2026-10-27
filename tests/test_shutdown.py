import unittest
from unittest import mock

from tools import system


class ShutdownTest(unittest.TestCase):
    def setUp(self):
        self.popened = []
        fake = mock.Mock(side_effect=lambda *a, **k: self.popened.append(a[0]))
        self.popener = mock.patch("subprocess.Popen", fake)
        self.popener.start()

    def tearDown(self):
        self.popener.stop()

    def _config(self, mode="sleep"):
        return {"power": {"shutdown_mode": mode}, "wol": {}}

    def test_default_suspende(self):
        with mock.patch.object(system, "get_config", return_value=self._config("sleep")):
            result = system._shutdown_pc()

        self.assertIn("SUSPENDIENDO", result["message"])
        cmd = self.popened[0]
        self.assertEqual(cmd[0], "rundll32")
        self.assertIn("powrprof.dll", cmd[1])

    def test_suspende_si_modo_omtido(self):
        with mock.patch.object(system, "get_config", return_value=self._config("sleep")):
            result = system._shutdown_pc("sleep")

        self.assertIn("SUSPENDIENDO", result["message"])

    def test_apagado_real_con_off(self):
        with mock.patch.object(system, "get_config", return_value=self._config("sleep")):
            result = system._shutdown_pc("off")

        self.assertIn("apagará de verdad", result["message"])
        self.assertEqual(self.popened[0][:2], ["shutdown", "/s"])

    def test_modo_off_por_config(self):
        with mock.patch.object(system, "get_config", return_value=self._config("off")):
            result = system._shutdown_pc()

        self.assertEqual(self.popened[0][:2], ["shutdown", "/s"])


if __name__ == "__main__":
    unittest.main()
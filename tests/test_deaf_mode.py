import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services import deaf_mode


class MatchCommandTest(unittest.TestCase):
    def test_activar(self):
        for text in (
            "JARVIS, no escuches",
            "no me escuches mas",
            "modo sordo",
            "activa el modo sordo",
            "deja de escuchar",
            "deja de escucharme",
            "no me oigas",
            "apaga el microfono",
            "apaga el micro",
            "desactiva el microfono",
        ):
            with self.subTest(text=text):
                self.assertEqual(deaf_mode.match_command(text), "on")

    def test_desactivar(self):
        for text in (
            "vuelve a escuchar",
            "vuelve a escucharme",
            "escuchame",
            "escuchame de nuevo",
            "ya puedes escuchar",
            "activa la escucha",
            "desactiva el modo sordo",
            "quita el modo sordo",
            "sal del modo sordo",
            "modo sordo off",
            "modo normal",
        ):
            with self.subTest(text=text):
                self.assertEqual(deaf_mode.match_command(text), "off")

    def test_acentos_y_puntuacion(self):
        self.assertEqual(deaf_mode.match_command("¡JARVIS, NO ESCUCHES!"), "on")
        self.assertEqual(deaf_mode.match_command("Vuelve a escucharme."), "off")

    def test_no_confunde_ordenes_normales(self):
        for text in (
            "abre youtube",
            "que hora es",
            "no escuchaste bien",
            "escucha esta cancion",
            "pon musica",
            "dime mi horario",
        ):
            with self.subTest(text=text):
                self.assertIsNone(deaf_mode.match_command(text))


class StateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "deaf_mode.json"
        self.patch = mock.patch.object(deaf_mode, "_STATE_PATH", self.path)
        self.patch.start()
        self.listeners = []
        deaf_mode._listeners.clear()
        deaf_mode.set_deaf(False, "test")
        deaf_mode._listeners.clear()

    def tearDown(self):
        deaf_mode._listeners.clear()
        deaf_mode.set_deaf(False, "test")
        self.patch.stop()
        self.tmp.cleanup()

    def test_cambia_y_persiste(self):
        deaf_mode.add_listener(self.listeners.append)
        self.assertTrue(deaf_mode.set_deaf(True, "test"))
        self.assertTrue(deaf_mode.is_deaf())
        self.assertTrue(self.path.exists())
        self.assertEqual(self.listeners, [True])

        self.assertFalse(deaf_mode.set_deaf(False, "test"))
        self.assertFalse(deaf_mode.is_deaf())
        self.assertEqual(self.listeners, [True, False])

    def test_no_repite_callback_si_no_cambia(self):
        deaf_mode.add_listener(self.listeners.append)
        deaf_mode.set_deaf(True, "test")
        deaf_mode.set_deaf(True, "test")
        self.assertEqual(self.listeners, [True])

    def test_toggle(self):
        self.assertTrue(deaf_mode.toggle("test"))
        self.assertFalse(deaf_mode.toggle("test"))

    def test_lee_estado_guardado(self):
        self.path.write_text('{"deaf": true}', encoding="utf-8")
        self.assertTrue(deaf_mode._read_state())
        self.path.write_text('{"deaf": false}', encoding="utf-8")
        self.assertFalse(deaf_mode._read_state())

    def test_lee_estado_inexistente(self):
        self.assertIsNone(deaf_mode._read_state())


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest import mock

from brain.tools_executor import execute_tool
from tools.input_tools import KEY_ALIASES, parse_combo


class ParseComboTest(unittest.TestCase):
    def test_single_key(self):
        self.assertEqual(parse_combo("i"), ["i"])

    def test_single_key_is_case_insensitive(self):
        self.assertEqual(parse_combo("I"), ["i"])

    def test_two_key_combo(self):
        self.assertEqual(parse_combo("ctrl+c"), ["ctrl", "c"])

    def test_three_key_combo(self):
        self.assertEqual(parse_combo("ctrl+shift+j"), ["ctrl", "shift", "j"])

    def test_spaces_around_plus_are_ignored(self):
        self.assertEqual(parse_combo(" ctrl + c "), ["ctrl", "c"])

    def test_spanish_aliases(self):
        self.assertEqual(parse_combo("intro"), ["enter"])
        self.assertEqual(parse_combo("esc"), ["escape"])
        self.assertEqual(parse_combo("espacio"), ["space"])
        self.assertEqual(parse_combo("borrar"), ["backspace"])
        self.assertEqual(parse_combo("flecha arriba"), ["up"])

    def test_alias_inside_combo(self):
        self.assertEqual(parse_combo("ctrl+intro"), ["ctrl", "enter"])

    def test_plus_key(self):
        self.assertEqual(parse_combo("+"), ["add"])
        self.assertEqual(parse_combo("ctrl++"), ["ctrl", "add"])

    def test_numbers_and_function_keys_pass_through(self):
        self.assertEqual(parse_combo("5"), ["5"])
        self.assertEqual(parse_combo("f12"), ["f12"])

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            parse_combo("")
        with self.assertRaises(ValueError):
            parse_combo("   ")

    def test_every_alias_maps_to_a_real_key(self):
        import pyautogui

        valid = set(pyautogui.KEYBOARD_KEYS)
        for alias, target in KEY_ALIASES.items():
            self.assertIn(target, valid, f"{alias} -> {target}")


class PressKeyTest(unittest.TestCase):
    def test_presses_single_key(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = ["i", "enter", "ctrl", "shift"]
            result = execute_tool("press_key", {"key": "i"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["keys"], ["i"])
        pg.press.assert_called_once()
        self.assertEqual(pg.press.call_args.args[0], "i")

    def test_presses_combo_with_hotkey(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = ["c", "j", "ctrl", "shift"]
            result = execute_tool("press_key", {"key": "ctrl+shift+j"})
        self.assertEqual(result["status"], "success")
        pg.hotkey.assert_called_once_with("ctrl", "shift", "j")

    def test_repeats_presses_times(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = ["i"]
            execute_tool("press_key", {"key": "i", "presses": 3})
        self.assertEqual(pg.press.call_args.kwargs["presses"], 3)

    def test_unknown_key_returns_error(self):
        result = execute_tool("press_key", {"key": "teclainventada"})
        self.assertIn("error", result)
        self.assertIn("desconocida", result["error"].lower())

    def test_empty_key_returns_error(self):
        result = execute_tool("press_key", {"key": ""})
        self.assertIn("error", result)


class TypeTextTest(unittest.TestCase):
    def test_ascii_text_uses_keyboard(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            result = execute_tool("type_text", {"text": "hola mundo"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["method"], "teclado")
        pg.write.assert_called_once()
        self.assertEqual(pg.write.call_args.args[0], "hola mundo")

    def test_text_with_accents_uses_clipboard(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            with mock.patch("tools.input_tools.pyperclip") as pc:
                pc.paste.return_value = "portapapeles viejo"
                result = execute_tool("type_text", {"text": "el niñó"})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["method"], "portapapeles")
        pc.copy.assert_any_call("el niñó")
        pg.hotkey.assert_called_once_with("ctrl", "v")
        # el portapapeles original se restaura
        pc.copy.assert_any_call("portapapeles viejo")

    def test_empty_text_returns_error(self):
        result = execute_tool("type_text", {"text": ""})
        self.assertIn("error", result)


class MouseTest(unittest.TestCase):
    def test_click_at_position(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            result = execute_tool("click", {"x": 100, "y": 200})
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["position"], [100, 200])
        pg.click.assert_called_once_with(100, 200, button="left", clicks=1)

    def test_click_invalid_button(self):
        result = execute_tool("click", {"x": 1, "y": 1, "button": "pie"})
        self.assertIn("error", result)

    def test_scroll_down_uses_negative_clicks(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            result = execute_tool("scroll", {"direction": "down", "amount": 5})
        self.assertEqual(result["status"], "success")
        pg.scroll.assert_called_once_with(-5)

    def test_scroll_up_uses_positive_clicks(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            execute_tool("scroll", {"direction": "up", "amount": 2})
        pg.scroll.assert_called_once_with(2)

    def test_scroll_horizontal_uses_hscroll(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            execute_tool("scroll", {"direction": "right", "amount": 4})
        pg.hscroll.assert_called_once_with(4)

    def test_scroll_invalid_direction(self):
        result = execute_tool("scroll", {"direction": "arriba"})
        self.assertIn("error", result)

    def test_move_mouse(self):
        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = []
            result = execute_tool("move_mouse", {"x": 10, "y": 20})
        self.assertEqual(result["status"], "success")
        pg.moveTo.assert_called_once_with(10, 20)


class FailSafeTest(unittest.TestCase):
    def test_failsafe_is_enabled(self):
        import tools.input_tools as mod

        self.assertTrue(mod.pyautogui.FAILSAFE)

    def test_failsafe_exception_becomes_friendly_error(self):
        import pyautogui

        with mock.patch("tools.input_tools.pyautogui") as pg:
            pg.KEYBOARD_KEYS = ["i"]
            pg.FailSafeException = pyautogui.FailSafeException
            pg.PyAutoGUIException = pyautogui.PyAutoGUIException
            pg.press.side_effect = pyautogui.FailSafeException(
                "pyautogui fail-safe triggered"
            )
            result = execute_tool("press_key", {"key": "i"})
        self.assertIn("error", result)
        self.assertIn("esquina", result["error"].lower())


if __name__ == "__main__":
    unittest.main()

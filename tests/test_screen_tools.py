import tempfile
import unittest
from pathlib import Path
from unittest import mock

from brain.tools_executor import execute_tool
from tools.screen_tools import parse_region


class ParseRegionTest(unittest.TestCase):
    def test_none_means_full_screen(self):
        self.assertIsNone(parse_region(None))
        self.assertIsNone(parse_region(""))

    def test_full_aliases(self):
        for alias in ("full", "all", "todo", "completa", "pantalla"):
            self.assertIsNone(parse_region(alias))

    def test_xywh(self):
        self.assertEqual(parse_region("0,0,800,600"), (0, 0, 800, 600))

    def test_spaces_and_semicolons(self):
        self.assertEqual(parse_region(" 10 ; 20 ; 30 ; 40 "), (10, 20, 30, 40))

    def test_float_values(self):
        self.assertEqual(parse_region("10.5,20.5,30,40"), (10, 20, 30, 40))

    def test_invalid_count(self):
        with self.assertRaises(ValueError):
            parse_region("0,0,800")

    def test_invalid_numbers(self):
        with self.assertRaises(ValueError):
            parse_region("a,b,c,d")

    def test_negative_size(self):
        with self.assertRaises(ValueError):
            parse_region("0,0,0,600")


class TakeScreenshotTest(unittest.TestCase):
    def _fake_image(self, size=(1920, 1080)):
        from PIL import Image

        return Image.new("RGB", size, "white")

    def test_captures_and_saves_jpeg(self):
        fake = self._fake_image()
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tools.screen_tools.ImageGrab") as grab:
                grab.grab.return_value = fake
                with mock.patch(
                    "tools.screen_tools._output_dir", return_value=Path(tmp)
                ):
                    result = execute_tool("take_screenshot", {})

            self.assertEqual(result["status"], "success")
            path = Path(result["image_path"])
            self.assertTrue(path.exists())
            self.assertEqual(path.suffix, ".jpg")
            self.assertTrue(path.stat().st_size > 0)

    def test_respects_max_width(self):
        fake = self._fake_image((2560, 1440))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tools.screen_tools.ImageGrab") as grab:
                grab.grab.return_value = fake
                with mock.patch(
                    "tools.screen_tools._output_dir", return_value=Path(tmp)
                ):
                    result = execute_tool("take_screenshot", {"max_width": 640})

        self.assertEqual(result["size"], [640, 360])
        self.assertEqual(result["original_size"], [2560, 1440])

    def test_crops_region(self):
        fake = self._fake_image((1920, 1080))
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("tools.screen_tools.ImageGrab") as grab:
                grab.grab.return_value = fake
                with mock.patch(
                    "tools.screen_tools._output_dir", return_value=Path(tmp)
                ):
                    result = execute_tool("take_screenshot", {"region": "100,50,400,300"})

        self.assertEqual(result["region"], [100, 50, 400, 300])
        self.assertEqual(result["size"], [400, 300])

    def test_invalid_region_returns_error(self):
        result = execute_tool("take_screenshot", {"region": "malo"})
        self.assertIn("error", result)

    def test_grab_failure_returns_error(self):
        with mock.patch("tools.screen_tools.ImageGrab") as grab:
            grab.grab.side_effect = RuntimeError("boom")
            result = execute_tool("take_screenshot", {})
        self.assertIn("error", result)
        self.assertIn("boom", result["error"])


if __name__ == "__main__":
    unittest.main()

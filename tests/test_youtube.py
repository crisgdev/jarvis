import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from tools import browser_tools


class YoutubeTest(unittest.TestCase):
    def setUp(self):
        self.opened = []
        self.opener = mock.patch.object(
            browser_tools.webbrowser, "open",
            side_effect=lambda url: self.opened.append(url),
        )
        self.opener.start()

    def tearDown(self):
        self.opener.stop()

    def test_url_de_youtube_abre_directo(self):
        result = browser_tools._play_youtube_video("https://www.youtube.com/watch?v=abc123")
        self.assertEqual(self.opened, ["https://www.youtube.com/watch?v=abc123"])
        self.assertIn("success", result["status"])

    def test_resuelve_primer_resultado_con_ytdlp(self):
        proc = SimpleNamespace(returncode=0, stdout="dQw4w9WgXcQ\n", stderr="")
        with mock.patch("subprocess.run", return_value=proc):
            result = browser_tools._play_youtube_video("rick astley never gonna give you up")

        self.assertEqual(self.opened, ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"])
        self.assertIn("success", result["status"])
        self.assertIn("dQw4w9WgXcQ", result["message"])

    def test_sin_yt_dlp_devuelve_guia(self):
        with mock.patch.dict(sys.modules, {"yt_dlp": None}):
            result = browser_tools._play_youtube_video("algun video")

        self.assertIn("pip install yt-dlp", result["error"])

    def test_error_de_ytdlp_reporte(self):
        proc = SimpleNamespace(returncode=1, stdout="", stderr="boom al resolver")
        with mock.patch("subprocess.run", return_value=proc):
            result = browser_tools._play_youtube_video("algun video")

        self.assertIn("error", result)
        self.assertIn("boom al resolver", result["error"])


if __name__ == "__main__":
    unittest.main()
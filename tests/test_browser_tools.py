import unittest
from unittest import mock

from brain.tools_executor import execute_tool


class NormalizeUrlTest(unittest.TestCase):
    def test_bare_name_gets_dot_com(self):
        from tools.browser_tools import _normalize_url
        self.assertEqual(_normalize_url("google"), "https://google.com")
        self.assertEqual(_normalize_url("youtube.com"), "https://youtube.com")
        self.assertEqual(_normalize_url("google.com"), "https://google.com")

    def test_full_url_passthrough(self):
        from tools.browser_tools import _normalize_url
        self.assertEqual(_normalize_url("https://www.google.com"), "https://www.google.com")
        self.assertEqual(_normalize_url("http://localhost:8080"), "http://localhost:8080")

    def test_whitespace_stripped(self):
        from tools.browser_tools import _normalize_url
        self.assertEqual(_normalize_url("  google  "), "https://google.com")


class OpenApplicationRoutingTest(unittest.TestCase):
    def test_google_routes_to_website(self):
        with mock.patch("tools.system.webbrowser.open") as mock_open:
            result = execute_tool("open_application", {"app_name": "google"})
        mock_open.assert_called_once_with("https://www.google.com")
        self.assertEqual(result["status"], "success")

    def test_youtube_routes_to_website(self):
        with mock.patch("tools.system.webbrowser.open") as mock_open:
            result = execute_tool("open_application", {"app_name": "YouTube"})
        mock_open.assert_called_once_with("https://www.youtube.com")
        self.assertEqual(result["status"], "success")

    def test_unknown_app_returns_error(self):
        with mock.patch("tools.system._resolve_app", return_value=None):
            with mock.patch("tools.system._find_folder", return_value=None):
                with mock.patch("tools.system.subprocess.Popen") as mock_popen:
                    result = execute_tool("open_application", {"app_name": "weirdthing"})
        mock_popen.assert_not_called()
        self.assertEqual(result["status"], "error")

    def test_resolved_app_uses_startfile(self):
        with mock.patch("tools.system._resolve_app", return_value=r"C:\fake\Discord.lnk") as mock_resolve:
            with mock.patch("tools.system.os.startfile") as mock_start:
                result = execute_tool("open_application", {"app_name": "discord"})
        mock_resolve.assert_called_once_with("Discord")
        mock_start.assert_called_once_with(r"C:\fake\Discord.lnk")
        self.assertEqual(result["status"], "success")

    def test_absolute_path_started_directly(self):
        with mock.patch("tools.system._resolve_app") as mock_resolve:
            with mock.patch("tools.system.os.startfile") as mock_start:
                with mock.patch("tools.system.os.path.isfile", return_value=True):
                    result = execute_tool(
                        "open_application",
                        {"app_name": r"C:\Users\USER\Desktop\Proyecto Reloaded.exe - Acceso directo.lnk"},
                    )
        mock_start.assert_called_once_with(r"C:\Users\USER\Desktop\Proyecto Reloaded.exe - Acceso directo.lnk")
        mock_resolve.assert_not_called()
        self.assertEqual(result["status"], "success")


class ResolveAppTest(unittest.TestCase):
    def test_prefers_path_command(self):
        from tools.system import _resolve_app
        with mock.patch("tools.system.shutil.which", return_value="C:\\Apps\\code.cmd"):
            self.assertEqual(_resolve_app("code"), "C:\\Apps\\code.cmd")

    def test_falls_back_to_start_menu_shortcut(self):
        from tools.system import _resolve_app
        with mock.patch("tools.system.shutil.which", return_value=None):
            with mock.patch("tools.system._find_start_menu_shortcut", return_value="C:\\lnk\\Discord.lnk"):
                self.assertEqual(_resolve_app("discord"), "C:\\lnk\\Discord.lnk")

    def test_no_match_returns_none(self):
        from tools.system import _resolve_app
        with mock.patch("tools.system.shutil.which", return_value=None):
            with mock.patch("tools.system._find_start_menu_shortcut", return_value=None):
                with mock.patch("tools.system._find_registered_app", return_value=None):
                    self.assertIsNone(_resolve_app("nadaquesaboque"))


class DeepResolveTest(unittest.TestCase):
    def test_installed_app_found(self):
        from tools.system import _resolve_app
        with mock.patch("tools.system.shutil.which", return_value=None):
            with mock.patch("tools.system._find_start_menu_shortcut", return_value=None):
                with mock.patch("tools.system._find_registered_app", return_value=None):
                    with mock.patch("tools.system._find_installed_app", return_value="C:\\PF\\Epic\\RL.exe"):
                        self.assertEqual(_resolve_app("rocket league"), "C:\\PF\\Epic\\RL.exe")

    def test_folder_resolved(self):
        from tools.system import _resolve_folder
        with mock.patch("os.path.isdir", return_value=True):
            path = _resolve_folder("descargas")
        self.assertIsNotNone(path)
        self.assertTrue(path.lower().endswith("downloads"))


class OpenFolderTest(unittest.TestCase):
    def test_open_folder(self):
        with mock.patch("tools.system._resolve_folder", return_value="C:\\\\Users\\\\example\\Downloads"):
            with mock.patch("tools.system.os.startfile") as mock_start:
                result = execute_tool("open_application", {"app_name": "descargas"})
        mock_start.assert_called_once_with("C:\\\\Users\\\\example\\Downloads")
        self.assertEqual(result["status"], "success")


class TokensMatchTest(unittest.TestCase):
    def test_ignore_case_spaces_and_punctuation(self):
        from tools.system import _tokens_match
        self.assertTrue(_tokens_match("geometry dash", "Geometry.Dash.v2.207"))
        self.assertTrue(_tokens_match("rocket league", "RocketLeague.exe"))
        self.assertTrue(_tokens_match("pokemon reloaded", "C:\\\\Users\\\\example\\Documents\\Carpetas\\Pokemon Reloaded\\Proyecto.exe"))
        self.assertFalse(_tokens_match("word", "Photoshop"))


class CloseAppTest(unittest.TestCase):
    def test_fuzzy_match_finds_process_by_name(self):
        from tools.system import _match_running_processes
        fake = mock.Mock()
        fake.info = {"name": "RocketLeague.exe", "exe": r"C:\Games\RocketLeague.exe"}
        with mock.patch("tools.system.psutil.process_iter", return_value=[fake]):
            with mock.patch("tools.system.subprocess.run") as mock_run:
                matched = _match_running_processes("rocket league")
        self.assertIn("RocketLeague.exe", matched)
        mock_run.assert_called()

    def test_close_falls_back_to_fuzzy_match(self):
        from tools.system import _close_application
        side_effects = [mock.Mock(returncode=1), mock.Mock(returncode=0)]
        with mock.patch("tools.system.subprocess.run", side_effect=side_effects):
            with mock.patch("tools.system._match_running_processes", return_value={"RocketLeague.exe"}):
                result = _close_application("rocket league")
        self.assertEqual(result["status"], "success")
        self.assertIn("RocketLeague.exe", result["message"])


if __name__ == "__main__":
    unittest.main()

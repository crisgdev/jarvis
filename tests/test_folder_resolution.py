import os
import tempfile
import unittest
from unittest import mock

import tools.system as system


class FolderMatchScoreTest(unittest.TestCase):
    def test_exact_match(self):
        self.assertEqual(system._match_score("personales", "Personales"), 1.0)

    def test_stt_confusion_caicen_kaizen(self):
        # El STT transcribio "caicen" cuando el usuario dijo "kaizen".
        self.assertGreaterEqual(system._match_score("caicen", "kaizen"), 0.85)

    def test_unrelated_names_score_low(self):
        self.assertLess(system._match_score("personales", "chrome"), 0.72)

    def test_filler_words_are_stripped(self):
        self.assertEqual(
            system._strip_folder_filler("abre el proyecto kaizen en visual studio code"),
            "kaizen",
        )


class FindFolderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, "Personales", "kaizen"))
        os.makedirs(os.path.join(self.root, "Personales", "jarvis"))
        system._FOLDER_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()
        system._FOLDER_CACHE.clear()

    def _find(self, name):
        with mock.patch.object(
            system, "_folder_search_roots", return_value=[self.root]
        ):
            return system._find_folder(name, max_depth=4, time_budget=2.0)

    def test_finds_nested_project(self):
        found = self._find("kaizen")
        self.assertEqual(os.path.basename(found), "kaizen")

    def test_finds_category_folder(self):
        found = self._find("Personales")
        self.assertEqual(os.path.basename(found), "Personales")

    def test_tolerates_stt_error(self):
        found = self._find("caicen")
        self.assertEqual(os.path.basename(found), "kaizen")

    def test_tolerates_filler_words(self):
        found = self._find("abre el proyecto kaizen")
        self.assertEqual(os.path.basename(found), "kaizen")

    def test_relative_path(self):
        found = self._find(os.path.join("Personales", "kaizen"))
        self.assertEqual(os.path.basename(found), "kaizen")

    def test_unknown_returns_none(self):
        self.assertIsNone(self._find("xyzzy"))


class ShortcutByTargetTest(unittest.TestCase):
    def test_target_path_alone_does_not_match(self):
        # Bug real: buscar "personales" devolvia el acceso directo cuyo destino
        # vivia en ...\Personales\jarvis\... y se ejecutaba ese script.
        target = (
            r"C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales"
            r"\jarvis\dismiss_lockscreen.ps1"
        )
        link = r"C:\ProgramData\Microsoft\Windows\Start Menu\Programs\Startup\Dismiss Lockscreen.lnk"
        proc = mock.Mock(stdout=f"{target}\t{link}".encode("utf-8"))
        with mock.patch.object(system.subprocess, "run", return_value=proc):
            self.assertIsNone(system._find_shortcut_by_target("personales"))

    def test_matches_by_executable_name(self):
        target = r"C:\Program Files\Discord\Discord.exe"
        link = r"C:\Start Menu\Discord.lnk"
        proc = mock.Mock(stdout=f"{target}\t{link}".encode("utf-8"))
        with mock.patch.object(system.subprocess, "run", return_value=proc):
            self.assertEqual(system._find_shortcut_by_target("discord"), link)


class OpenApplicationFolderFirstTest(unittest.TestCase):
    def test_folder_wins_over_app_resolution(self):
        folder = (
            r"C:\Users\USER\Documents\Proyectos-Ingenieria-Sistemas\Personales"
        )
        with mock.patch.object(system, "_find_folder", return_value=folder), \
                mock.patch.object(system, "_resolve_app") as resolve, \
                mock.patch.object(system.subprocess, "Popen") as popen:
            result = system._open_application("Personales")
        resolve.assert_not_called()
        popen.assert_called_once()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["path"], folder)

    def test_shortcut_app_still_wins_for_known_apps(self):
        with mock.patch.object(system, "_find_folder") as find_folder, \
                mock.patch.object(system, "_resolve_app", return_value=r"C:\Apps\discord.exe"), \
                mock.patch.object(system, "os") as fake_os:
            fake_os.path.isfile.return_value = False
            fake_os.path.isdir.return_value = False
            fake_os.startfile = mock.Mock()
            result = system._open_application("discord")
        find_folder.assert_not_called()
        fake_os.startfile.assert_called_once_with(r"C:\Apps\discord.exe")
        self.assertEqual(result["status"], "success")


class OpenVscodeFolderTest(unittest.TestCase):
    def test_uses_q_and_returns_suggestions_when_missing(self):
        with mock.patch.object(system, "_find_folder", return_value=None), \
                mock.patch.object(system, "_folder_suggestions", return_value=["kaizen"]):
            result = system._open_vscode_folder("caicen")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["suggestions"], ["kaizen"])
        self.assertIn("kaizen", result["message"])

    def test_launches_code_with_resolved_path(self):
        folder = r"C:\Proyectos\Personales\kaizen"
        fake_pyautogui = mock.Mock()
        with mock.patch.object(system, "_find_folder", return_value=folder), \
                mock.patch.object(system, "shutil") as fake_shutil, \
                mock.patch.object(system, "subprocess") as fake_subprocess, \
                mock.patch.object(system, "_disable_vscode_workspace_trust", return_value=True), \
                mock.patch.object(system, "_disable_vscode_terminal_restore", return_value=True), \
                mock.patch.object(system, "_vscode_set_keybind", return_value=True), \
                mock.patch.object(system.time, "sleep", return_value=None), \
                mock.patch.dict("sys.modules", {"pyautogui": fake_pyautogui, "tools.window_tools": mock.Mock()}):
            fake_shutil.which.return_value = r"C:\VS Code\bin\code.cmd"
            fake_subprocess.Popen = mock.Mock()
            fake_subprocess.CREATE_NO_WINDOW = 0
            result = system._open_vscode_folder("kaizen")
        fake_subprocess.Popen.assert_called_once()
        args, _kwargs = fake_subprocess.Popen.call_args
        self.assertEqual(args[0], [r"C:\VS Code\bin\code.cmd", folder])
        self.assertEqual(result["status"], "success")


if __name__ == "__main__":
    unittest.main()

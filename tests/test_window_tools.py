import unittest
from unittest import mock

from brain.tools_executor import execute_tool


class FakeWindow:
    def __init__(self, title, active=False, left=0, top=0, width=100, height=100):
        self.title = title
        self._active = active
        self.left = left
        self.top = top
        self.width = width
        self.height = height
        self.closed = False
        self.activated = False
        self.minimized = False
        self.maximized = False
        self.restored = False

    @property
    def isActive(self):
        return self._active

    def close(self):
        self.closed = True

    def activate(self):
        self.activated = True

    def minimize(self):
        self.minimized = True

    def maximize(self):
        self.maximized = True

    def restore(self):
        self.restored = True


class FakeGw:
    def __init__(self, windows, active=None):
        self._windows = windows
        self._active = active

    def getAllWindows(self):
        return list(self._windows)

    def getActiveWindow(self):
        return self._active

    def getWindowsWithTitle(self, title):
        return [w for w in self._windows if title.upper() in w.title.upper()]


class ListWindowsTest(unittest.TestCase):
    def test_lists_visible_windows(self):
        windows = [
            FakeWindow("Google Chrome"),
            FakeWindow("Spotify", active=True),
        ]
        with mock.patch("tools.window_tools.gw", FakeGw(windows)):
            result = execute_tool("list_windows", {})
        self.assertEqual(result["count"], 2)
        # la activa va primera
        self.assertEqual(result["windows"][0]["title"], "Spotify")
        self.assertTrue(result["windows"][0]["active"])
        self.assertEqual(result["active"], "Spotify")

    def test_empty(self):
        with mock.patch("tools.window_tools.gw", FakeGw([])):
            result = execute_tool("list_windows", {})
        self.assertEqual(result["windows"], [])


class CloseWindowTest(unittest.TestCase):
    def test_closes_by_title(self):
        chrome = FakeWindow("Google Chrome")
        other = FakeWindow("Spotify", active=True)
        with mock.patch("tools.window_tools.gw", FakeGw([chrome, other], other)):
            result = execute_tool("close_window", {"title": "chrome"})
        self.assertEqual(result["status"], "success")
        self.assertTrue(chrome.closed)
        self.assertFalse(other.closed)

    def test_closes_active_window_without_title(self):
        active = FakeWindow("Spotify", active=True)
        with mock.patch("tools.window_tools.gw", FakeGw([active], active)):
            result = execute_tool("close_window", {})
        self.assertEqual(result["status"], "success")
        self.assertTrue(active.closed)

    def test_unknown_title_returns_error(self):
        with mock.patch("tools.window_tools.gw", FakeGw([FakeWindow("Chrome")])):
            result = execute_tool("close_window", {"title": "inexistente"})
        self.assertIn("error", result)


class ActivateWindowTest(unittest.TestCase):
    def test_activates_matching_window(self):
        chrome = FakeWindow("Google Chrome")
        with mock.patch("tools.window_tools.gw", FakeGw([chrome])):
            result = execute_tool("activate_window", {"title": "chrome"})
        self.assertEqual(result["status"], "success")
        self.assertTrue(chrome.activated)

    def test_unknown_title_returns_error(self):
        with mock.patch("tools.window_tools.gw", FakeGw([FakeWindow("Chrome")])):
            result = execute_tool("activate_window", {"title": "nada"})
        self.assertIn("error", result)


class WindowStateTest(unittest.TestCase):
    def test_minimize_and_maximize(self):
        win = FakeWindow("Chrome")
        with mock.patch("tools.window_tools.gw", FakeGw([win], win)):
            execute_tool("minimize_window", {"title": "chrome"})
            execute_tool("maximize_window", {"title": "chrome"})
        self.assertTrue(win.minimized)
        self.assertTrue(win.maximized)

    def test_get_active_window(self):
        win = FakeWindow("Chrome", active=True)
        with mock.patch("tools.window_tools.gw", FakeGw([win], win)):
            result = execute_tool("get_active_window", {})
        self.assertEqual(result["title"], "Chrome")


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from brain.tools_executor import (
    RISK_LEVELS,
    _tool_registry,
    execute_dangerous_tool,
    execute_tool,
    get_risk_level,
    register_tool,
)

DANGEROUS_TOOLS = (
    "shutdown_pc",
    "restart_pc",
    "send_email",
    "delete_file",
    "delete_calendar_event",
    "run_python_code",
)
SAFE_TOOLS = ("get_system_info", "search_web", "search_file", "read_file")

# Tools de pantalla/teclado/raton: se ejecutan solas (sin confirmacion).
AUTO_TOOLS = (
    "take_screenshot",
    "press_key",
    "type_text",
    "click",
    "scroll",
    "move_mouse",
    "get_mouse_position",
    "list_windows",
    "get_active_window",
    "activate_window",
    "close_window",
    "minimize_window",
    "maximize_window",
)


class RiskLevelTest(unittest.TestCase):
    def test_dangerous_tools_flagged_dangerous(self):
        for name in DANGEROUS_TOOLS:
            self.assertEqual(get_risk_level(name), "dangerous", name)

    def test_safe_tools_flagged_safe(self):
        for name in SAFE_TOOLS:
            self.assertEqual(get_risk_level(name), "safe", name)

    def test_unknown_defaults_to_moderate(self):
        self.assertEqual(get_risk_level("tool_que_no_existe"), "moderate")

    def test_input_tools_run_without_confirmation(self):
        # Ninguna de las tools de pantalla/teclado debe pedir confirmacion:
        # en este proyecto "moderate" y "safe" se ejecutan directamente.
        for name in AUTO_TOOLS:
            risk = get_risk_level(name)
            self.assertIn(risk, ("safe", "moderate"), name)
            self.assertNotEqual(risk, "dangerous", name)

    def test_input_tools_registered(self):
        for name in AUTO_TOOLS:
            self.assertIn(name, _tool_registry, name)


class RegistryTest(unittest.TestCase):
    def test_every_registered_tool_has_risk_level(self):
        missing = [name for name in _tool_registry if name not in RISK_LEVELS]
        self.assertEqual(missing, [])

    def test_known_tools_registered_when_deps_available(self):
        # Verifica que al menos las tools de stdlib esten registradas
        for name in ("write_file", "read_file", "delete_file", "run_python_code"):
            self.assertIn(name, _tool_registry, name)


class DefinitionsCoverageTest(unittest.TestCase):
    def test_all_gemini_declared_tools_have_risk_level(self):
        from brain.tools_definitions import TOOLS
        declared = {t.name for t in TOOLS}
        missing = declared - set(RISK_LEVELS)
        self.assertEqual(missing, set())

    def test_all_gemini_declared_tools_are_implemented(self):
        from brain.tools_definitions import TOOLS
        declared = {t.name for t in TOOLS}
        # show_plan la intercepta brain/gemini.py (solo muestra el plan en la
        # GUI); nunca llega al ejecutor, asi que no tiene registro propio.
        intercepted = {"show_plan"}
        missing = declared - set(_tool_registry) - intercepted
        self.assertEqual(missing, set())


class DangerGatingTest(unittest.TestCase):
    def setUp(self):
        self.executed = []
        RISK_LEVELS["test_dangerous_dummy"] = "dangerous"

        @register_tool("test_dangerous_dummy")
        def _dummy(value: str = ""):
            self.executed.append(value)
            return {"ok": True}

    def tearDown(self):
        RISK_LEVELS.pop("test_dangerous_dummy", None)
        _tool_registry.pop("test_dangerous_dummy", None)

    def test_no_callback_blocks_execution(self):
        result = execute_dangerous_tool(
            "test_dangerous_dummy", {"value": "x"}, None
        )
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.executed, [])

    def test_rejected_confirmation_blocks_execution(self):
        result = execute_dangerous_tool(
            "test_dangerous_dummy",
            {"value": "x"},
            lambda name, args: False,
        )
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.executed, [])

    def test_approved_confirmation_executes(self):
        result = execute_dangerous_tool(
            "test_dangerous_dummy",
            {"value": "y"},
            lambda name, args: True,
        )
        self.assertEqual(self.executed, ["y"])
        self.assertEqual(result, {"ok": True})

    def test_failing_confirmation_blocks_execution(self):
        def _boom(name, args):
            raise RuntimeError("GUI error")

        result = execute_dangerous_tool("test_dangerous_dummy", {}, _boom)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.executed, [])


class ForgetToolTest(unittest.TestCase):
    def setUp(self):
        import memory.database as mdb

        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test_memory.db"
        self._mdb = mdb
        mdb._connection = None
        mdb._db_path = None
        self._orig_get_config = mdb.get_config
        mdb.get_config = lambda: {"memory": {"db_path": str(self._db_path)}}

    def tearDown(self):
        self._mdb.close()
        self._mdb.get_config = self._orig_get_config
        self._tmp.cleanup()

    def test_forget_deletes_matching_memory(self):
        self._mdb.save_note("TestUser tiene 19 anios", "general")
        self._mdb.save_note("comprar pan", "task")
        res = execute_tool("forget_information", {"keywords": "19 anios edad"})
        self.assertEqual(res["count"], 1)
        self.assertIn("19 anios", res["results"][0]["content"])
        self.assertEqual(self._mdb.recall_notes("anios"), [])
        self.assertEqual(self._mdb.recall_notes("pan")[0]["content"], "comprar pan")

    def test_forget_no_match_returns_empty(self):
        res = execute_tool("forget_information", {"keywords": "xyz no existe"})
        self.assertEqual(res["results"], [])


class ErrorHandlingTest(unittest.TestCase):
    def test_unknown_tool_returns_error(self):
        result = execute_tool("tool_inexistente_xyz", {})
        self.assertIn("error", result)

    def test_missing_required_args_returns_error(self):
        result = execute_tool("test_dangerous_dummy", {})
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()

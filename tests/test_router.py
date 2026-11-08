import unittest

from brain import router
from brain.prompts import CHANNEL_CHAT_NOTE, PACK_PROMPTS, PROMPT_CORE, build_prompt
from brain.tools_definitions import TOOLS, tools_for


class RouterTest(unittest.TestCase):
    def test_simple_question_uses_core_only(self):
        r = router.route("que hora es")
        self.assertEqual(r.packs, ())
        self.assertEqual(r.tier, "fast")
        self.assertEqual(set(r.tools), set(router.CORE_TOOLS))

    def test_calendar_pack_and_strong_model(self):
        r = router.route("que clases tengo el lunes")
        self.assertIn("calendar", r.packs)
        self.assertEqual(r.tier, "strong")
        self.assertIn("get_upcoming_events", r.tools)

    def test_dev_pack(self):
        r = router.route("programa un script en python para ordenar archivos")
        self.assertIn("dev", r.packs)
        self.assertEqual(r.tier, "strong")
        self.assertIn("opencode_code", r.tools)

    def test_visual_studio_code_phrase_offers_vscode_tool(self):
        # El STT escribe "Visual Studio Code" con espacios: antes el router no
        # lo reconocia y Gemini no tenia open_vscode_folder disponible.
        r = router.route("a ver el proyecto kaizen con Visual Studio Code")
        self.assertIn("dev", r.packs)
        self.assertIn("open_vscode_folder", r.tools)
        self.assertEqual(r.tier, "strong")

    def test_vscode_and_vs_code_still_detected(self):
        for text in ("abre mi proyecto en vscode", "abre el proyecto en vs code"):
            with self.subTest(text=text):
                r = router.route(text)
                self.assertIn("dev", r.packs)
                self.assertIn("open_vscode_folder", r.tools)

    def test_mail_pack(self):
        r = router.route("abre gmail institucional")
        self.assertIn("mail", r.packs)
        self.assertIn("read_recent_emails", r.tools)

    def test_screen_pack_keeps_core(self):
        r = router.route("mueve el raton y haz clic")
        self.assertIn("screen", r.packs)
        for name in router.CORE_TOOLS:
            self.assertIn(name, r.tools)

    def test_accents_and_case_are_normalized(self):
        r = router.route("Crea un EVENTO de reunión mañana")
        self.assertIn("calendar", r.packs)

    def test_unknown_text_falls_back_to_core(self):
        r = router.route("xyzzy plugh")
        self.assertEqual(r.packs, ())
        self.assertFalse(r.all_tools)

    def test_disabled_routing_returns_everything(self):
        r = router.route("que hora es", enabled=False)
        self.assertTrue(r.all_tools)
        self.assertEqual(set(r.tools), set(router.all_tool_names()))
        self.assertEqual(len(r.tools), 54)
        self.assertEqual(len(set(r.tools)), len(r.tools), "sin duplicados")

    def test_all_tool_names_are_declared(self):
        declared = {decl.name for decl in TOOLS}
        self.assertEqual(set(router.all_tool_names()), declared)

    def test_route_key_is_stable(self):
        a = router.route("que hora es")
        b = router.route("que hora es")
        self.assertEqual(a.key, b.key)

    def test_detailed_channel_uses_strong(self):
        r = router.route("hola", detailed=True)
        self.assertEqual(r.tier, "strong")


class ToolsSubsetTest(unittest.TestCase):
    def test_tools_for_keeps_requested_names(self):
        tool = tools_for(["open_application", "save_note", "no_existe"])
        names = [decl.name for decl in tool.function_declarations]
        self.assertEqual(names, ["open_application", "save_note"])

    def test_tools_for_none_returns_all(self):
        tool = tools_for(None)
        self.assertEqual(len(tool.function_declarations), len(TOOLS))

    def test_tools_for_empty_returns_all(self):
        tool = tools_for([])
        self.assertEqual(len(tool.function_declarations), len(TOOLS))


class PromptLayersTest(unittest.TestCase):
    def test_core_only_without_packs(self):
        prompt = build_prompt(PROMPT_CORE, packs=[])
        self.assertEqual(prompt, PROMPT_CORE)
        self.assertNotIn("CALENDARIO:", prompt)
        self.assertNotIn("PROGRAMAR (OpenCode)", prompt)

    def test_packs_add_their_block(self):
        prompt = build_prompt(PROMPT_CORE, packs=["calendar"])
        self.assertIn("CALENDARIO:", prompt)
        self.assertIn("get_upcoming_events", prompt)
        self.assertNotIn("PROGRAMAR (OpenCode)", prompt)

    def test_none_includes_every_pack(self):
        prompt = build_prompt(PROMPT_CORE, packs=None)
        for name in PACK_PROMPTS:
            marker = {
                "media": "APPS, WEB Y MEDIA:",
                "mail": "CUENTAS DE GOOGLE Y CORREO (CRITICO):",
                "calendar": "CALENDARIO:",
                "files": "ARCHIVOS:",
                "memory": "MEMORIA:",
                "screen": "PANTALLA, TECLADO, RATON Y VENTANAS:",
                "dev": "PROGRAMAR (OpenCode):",
                "power": "ENERGIA Y RED:",
                "bookmarks": "MARCADORES DE CHROME:",
            }[name]
            self.assertIn(marker, prompt, f"falta el pack {name}")

    def test_detailed_channel_note(self):
        prompt = build_prompt(PROMPT_CORE, packs=[], detailed=True)
        self.assertIn(CHANNEL_CHAT_NOTE, prompt)
        self.assertIn("CANAL CHAT (Telegram)", prompt)
        self.assertIn("Markdown", prompt)

    def test_prompt_order_is_stable(self):
        first = build_prompt(PROMPT_CORE, packs=["dev", "calendar", "mail"])
        second = build_prompt(PROMPT_CORE, packs=["mail", "dev", "calendar"])
        self.assertEqual(first, second)

    def test_prompt_is_smaller_for_simple_turns(self):
        simple = build_prompt(PROMPT_CORE, packs=[])
        full = build_prompt(PROMPT_CORE, packs=None)
        self.assertLess(len(simple), len(full) / 2)


if __name__ == "__main__":
    unittest.main()

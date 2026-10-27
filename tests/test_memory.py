import tempfile
import unittest
from pathlib import Path

import memory.database as db
from memory import context as ctx


class MemoryContextTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test_ctx.db"
        self._orig_get_config = db.get_config
        db.get_config = lambda: {"memory": {"db_path": str(self._db_path)}}
        db._connection = None
        db._db_path = None

    def tearDown(self):
        db.close()
        db.get_config = self._orig_get_config
        self._tmp.cleanup()

    def test_history_chronological_and_drops_last_user(self):
        sid = db.create_session("ctx")
        db.save_message(sid, "user", "primera pregunta")
        db.save_message(sid, "model", "primera respuesta")
        db.save_message(sid, "user", "pregunta actual")
        hist = ctx.build_gemini_history(sid, max_turns=4)
        texts = [c.parts[0].text for c in hist]
        self.assertEqual(texts, ["primera pregunta", "primera respuesta"])
        self.assertNotIn("pregunta actual", texts)

    def test_system_context_time_flag(self):
        with_time = ctx.build_system_context(include_time=True)
        no_time = ctx.build_system_context(include_time=False)
        self.assertIn("Hora:", with_time)
        self.assertNotIn("Hora:", no_time)
        self.assertIn("Fecha:", no_time)


class MemoryDatabaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test_memory.db"
        self._orig_get_config = db.get_config
        db.get_config = lambda: {"memory": {"db_path": str(self._db_path)}}
        db._connection = None
        db._db_path = None

    def tearDown(self):
        db.close()
        db.get_config = self._orig_get_config
        self._tmp.cleanup()

    def test_session_lifecycle(self):
        sid = db.create_session("test")
        self.assertTrue(sid)
        db.save_message(sid, "user", "hola")
        db.save_message(sid, "model", "hola!")
        msgs = db.get_messages(sid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        db.end_session(sid)
        self.assertIsNotNone(db.get_session(sid)["ended_at"])

    def test_notes_roundtrip(self):
        db.save_note("recordar comprar leche", "task")
        db.save_note("idea para jarvis", "idea")
        results = db.recall_notes("leche")
        self.assertTrue(any("leche" in n["content"] for n in results))

    def test_recall_token_fallback(self):
        db.save_note("el nombre del usuario es Cristopher", "general")
        results = db.recall_notes("nombre del usuario")
        self.assertTrue(any("Cristopher" in n["content"] for n in results))

    def test_recent_notes(self):
        db.save_note("primera nota", "a")
        db.save_note("segunda nota", "b")
        rec = db.get_recent_notes(limit=1)
        self.assertIn("segunda", rec[0]["content"])
        self.assertEqual(len(rec), 1)

    def test_projects_crud(self):
        db.create_project("jarvis", "asistente de voz")
        project = db.get_project("jarvis")
        self.assertIsNotNone(project)
        self.assertEqual(project["status"], "active")

        db.add_project_note("jarvis", "primera nota")
        project = db.get_project("jarvis")
        self.assertEqual(len(project["notes"]), 1)

        db.update_project_status("jarvis", "completed")
        project = db.get_project("jarvis")
        self.assertEqual(project["status"], "completed")
        self.assertEqual(len(db.list_projects(status="completed")), 1)

    def test_preferences(self):
        db.set_preference("idioma", "es")
        self.assertEqual(db.get_preference("idioma"), "es")
        db.set_preference("idioma", "en")
        self.assertEqual(db.get_preference("idioma"), "en")

    def test_delete_notes_by_content_case_insensitive(self):
        db.save_note("la edad de Cristopher es 19 anios.", "general")
        db.save_note("la edad del usuario es un dato personal", "general")
        db.save_note("comprar manzanas", "task")
        deleted = db.delete_notes_by_content("edad")
        self.assertEqual(len(deleted), 2)
        self.assertTrue(any("19 anios" in d["content"] for d in deleted))
        self.assertEqual(db.recall_notes("edad"), [])
        self.assertEqual(db.recall_notes("manzanas")[0]["content"], "comprar manzanas")


if __name__ == "__main__":
    unittest.main()
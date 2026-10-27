import unittest
from pathlib import Path
from unittest import mock

from brain import gemini
from brain.gemini import GeminiBrain


class FakeFC:
    def __init__(self, name, args=None):
        self.name = name
        self.args = args or {}


class FakePart:
    function_call = None
    text = None

    def __init__(self, kind, value=None):
        if kind == "fc":
            self.function_call = value
        elif kind == "text":
            self.text = value


class FakeContent:
    def __init__(self, parts):
        self.parts = parts


class FakeCandidate:
    def __init__(self, parts, finish_reason=None):
        self.content = FakeContent(parts)
        self.finish_reason = finish_reason


class FakeResponse:
    def __init__(self, parts, finish_reason=None, usage=None):
        self.candidates = [FakeCandidate(parts, finish_reason)]
        self.usage_metadata = usage


class FakeChat:
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []

    def send_message(self, content):
        self.sent.append(content)
        return self.responses.pop(0)


def make_brain(responses):
    brain = GeminiBrain.__new__(GeminiBrain)
    brain.config = {}
    brain.model = "gemini-3.5-flash-lite"
    brain.max_turns = 8
    brain.max_output_tokens = 200
    brain.temperature = 0.7
    brain.client = mock.Mock()
    brain._confirm_cb = None
    brain._exchanges = 0
    brain._retried_empty = False
    brain._detailed = False
    brain.chat = FakeChat(responses)
    brain._create_chat = lambda model, history=None: None
    return brain


class ChatMessageTest(unittest.TestCase):
    def test_text_only_response(self):
        brain = make_brain([FakeResponse([FakePart("text", "Hola!")])])
        self.assertEqual(brain.chat_message("hola"), "Hola!")
        self.assertEqual(len(brain.chat.sent), 1)

    def test_no_extra_turn_after_function_response(self):
        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("get_system_info", {"info_type": "date"}))]),
                FakeResponse([FakePart("text", "Es domingo.")]),
            ]
        )
        with mock.patch("brain.gemini.execute_tool", return_value={"date": "2026-09-21"}):
            result = brain.chat_message("que dia es")
        self.assertEqual(result, "Es domingo.")
        self.assertEqual(len(brain.chat.sent), 2)
        sent2 = brain.chat.sent[1]
        self.assertIsInstance(sent2, list)

    def test_chained_tools_pipeline(self):
        # get_system_info -> create_calendar_event -> texto final
        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("get_system_info", {"info_type": "date"}))]),
                FakeResponse([FakePart("fc", FakeFC("create_calendar_event", {"title": "Cita"}))]),
                FakeResponse([FakePart("text", "Evento creado.")]),
            ]
        )
        side_effects = [
            {"date": "2026-09-21"},
            {"result": "Evento creado"},
        ]
        with mock.patch("brain.gemini.execute_tool", side_effect=side_effects):
            result = brain.chat_message("crea un evento para manana")
        self.assertEqual(result, "Evento creado.")
        self.assertEqual(len(brain.chat.sent), 3)
        # nunca se manda un string vacio (el bug del 400 INVALID_ARGUMENT)
        for sent in brain.chat.sent:
            self.assertFalse(isinstance(sent, str) and not sent.strip())

    def test_denied_dangerous_still_closes_turn(self):
        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("send_email", {"to": "a@b.c"}))]),
                FakeResponse([FakePart("text", "Entendido, no envio.")]),
            ]
        )
        with mock.patch(
            "brain.gemini.execute_dangerous_tool",
            return_value={"status": "cancelled", "message": "El usuario cancelo."},
        ):
            result = brain.chat_message("envia un email")
        self.assertEqual(result, "Entendido, no envio.")
        self.assertEqual(len(brain.chat.sent), 2)
        self.assertIsInstance(brain.chat.sent[1], list)


class EmptyResponseTest(unittest.TestCase):
    """Una respuesta sin texto NUNCA debe become el literal 'OK'."""

    def test_empty_response_reports_finish_reason(self):
        brain = make_brain(
            [FakeResponse([FakePart("text", None)], finish_reason="SAFETY")]
        )
        result = brain.chat_message("hola")
        self.assertNotEqual(result, "OK")
        self.assertIn("SAFETY", result)

    def test_truncated_response_retries_with_more_tokens(self):
        brain = make_brain(
            [
                FakeResponse([FakePart("text", None)], finish_reason="MAX_TOKENS"),
                FakeResponse([FakePart("text", "Listo.")]),
            ]
        )
        result = brain.chat_message("crea las carpetas")
        self.assertEqual(result, "Listo.")
        self.assertEqual(len(brain.chat.sent), 2)
        self.assertGreaterEqual(brain.max_output_tokens, 1024)

    def test_truncation_retries_only_once(self):
        brain = make_brain(
            [
                FakeResponse([FakePart("text", None)], finish_reason="MAX_TOKENS"),
                FakeResponse([FakePart("text", None)], finish_reason="MAX_TOKENS"),
            ]
        )
        result = brain.chat_message("crea las carpetas")
        self.assertNotEqual(result, "OK")
        self.assertIn("MAX_TOKENS", result)
        self.assertEqual(len(brain.chat.sent), 2)

    def test_no_retry_when_pending_content_is_function_response(self):
        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("get_system_info", {"info_type": "date"}))]),
                FakeResponse([FakePart("text", None)], finish_reason="MAX_TOKENS"),
            ]
        )
        with mock.patch("brain.gemini.execute_tool", return_value={"date": "2026-10-04"}):
            result = brain.chat_message("que dia es")
        self.assertIn("MAX_TOKENS", result)
        self.assertEqual(len(brain.chat.sent), 2)

    def test_debug_info_includes_token_usage(self):
        usage = mock.Mock(
            thoughts_token_count=180,
            candidates_token_count=0,
            total_token_count=200,
        )
        brain = make_brain([FakeResponse([FakePart("text", None)], "MAX_TOKENS", usage)])
        info = brain._response_debug_info(brain.chat.responses[0])
        self.assertEqual(info["finish_reason"], "MAX_TOKENS")
        self.assertEqual(info["tokens"]["thoughts"], 180)


class FallbackTest(unittest.TestCase):
    """El fallback debe responder la pregunta real, no un ping 'OK'."""

    def test_fallback_resends_user_text(self):
        brain = make_brain([])
        brain.chat = FakeChat([FakeResponse([FakePart("text", "Soy el respaldo.")])])
        resp = brain._try_fallback("se acabaron los tokens?")
        self.assertIsNotNone(resp)
        self.assertEqual(brain.chat.sent, ["se acabaron los tokens?"])

    def test_fallback_skipped_for_function_response(self):
        brain = make_brain([])
        brain.chat = FakeChat([FakeResponse([FakePart("text", "no deberia usarse")])])
        parts = [mock.Mock()]
        self.assertIsNone(brain._try_fallback(parts))
        self.assertEqual(brain.chat.sent, [])

    def test_all_fallbacks_fail_restores_original_model(self):
        brain = make_brain([])
        brain.chat = FakeChat([])

        def fake_create_chat(model, history=None):
            brain.model = model

        with mock.patch.object(GeminiBrain, "_create_chat", side_effect=fake_create_chat):
            self.assertIsNone(brain._try_fallback("hola"))
        self.assertEqual(brain.model, "gemini-3.5-flash-lite")


class VisionTest(unittest.TestCase):
    """La captura debe viajar al modelo como imagen REAL, no solo como JSON."""

    def _write_jpeg(self, tmpdir):
        from PIL import Image

        path = Path(tmpdir) / "shot.jpg"
        Image.new("RGB", (32, 16), "red").save(path, format="JPEG")
        return str(path)

    def test_image_part_from_result(self):
        import tempfile

        brain = make_brain([])
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_jpeg(tmp)
            part = brain._image_part({"image_path": path})
        self.assertIsNotNone(part)
        self.assertTrue(hasattr(part, "inline_data"))

    def test_image_part_none_without_path(self):
        brain = make_brain([])
        self.assertIsNone(brain._image_part({"status": "success"}))
        self.assertIsNone(brain._image_part("no dict"))
        self.assertIsNone(brain._image_part({"image_path": "C:/no/existe.jpg"}))

    def test_screenshot_result_is_attached_and_registered(self):
        import tempfile

        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("take_screenshot", {}))]),
                FakeResponse([FakePart("text", "Veo un editor de codigo.")]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_jpeg(tmp)
            with mock.patch(
                "brain.gemini.execute_tool",
                return_value={"status": "success", "image_path": path},
            ):
                result = brain.chat_message("que hay en mi pantalla")

        self.assertEqual(result, "Veo un editor de codigo.")
        # el modelo recibio la imagen real en el turno siguiente
        sent = brain.chat.sent[1]
        self.assertIsInstance(sent, list)
        self.assertEqual(len(sent), 2)
        self.assertTrue(hasattr(sent[1], "inline_data"))
        # y quedo registrada como artefacto para el canal (Telegram)
        self.assertEqual(len(brain.artifacts), 1)
        self.assertEqual(brain.artifacts[0]["type"], "image")
        self.assertEqual(brain.artifacts[0]["path"], path)

    def test_artifacts_reset_between_turns(self):
        import tempfile

        brain = make_brain(
            [
                FakeResponse([FakePart("fc", FakeFC("take_screenshot", {}))]),
                FakeResponse([FakePart("text", "Listo.")]),
                FakeResponse([FakePart("text", "Otra cosa.")]),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_jpeg(tmp)
            with mock.patch(
                "brain.gemini.execute_tool",
                return_value={"status": "success", "image_path": path},
            ):
                brain.chat_message("captura")
                brain.chat_message("hola")
        self.assertEqual(len(brain.artifacts), 0)


if __name__ == "__main__":
    unittest.main()
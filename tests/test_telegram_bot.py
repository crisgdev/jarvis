import unittest
from unittest import mock

from services import telegram_bot as tg
from brain.gemini import GeminiBrain


class TelegramConfigTest(unittest.TestCase):
    @mock.patch("services.telegram_bot.get_env")
    def test_get_token(self, mock_env):
        mock_env.side_effect = lambda k: {
            "TELEGRAM_BOT_TOKEN": "123:ABC",
            "TELEGRAM_ALLOWED_USER_IDS": "",
        }.get(k)
        self.assertEqual(tg._get_token(), "123:ABC")

    @mock.patch("services.telegram_bot.get_env")
    def test_token_empty_means_not_configured(self, mock_env):
        mock_env.side_effect = lambda k: {
            "TELEGRAM_BOT_TOKEN": "",
            "TELEGRAM_ALLOWED_USER_IDS": "",
        }.get(k)
        self.assertFalse(tg.is_configured())

    @mock.patch("services.telegram_bot.get_env")
    def test_parse_allowed_ids(self, mock_env):
        mock_env.side_effect = lambda k: {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ALLOWED_USER_IDS": "123, 456 789",
        }.get(k)
        self.assertEqual(tg._get_allowed_ids(), {123, 456, 789})

    @mock.patch("services.telegram_bot.get_env")
    def test_ignore_invalid_ids(self, mock_env):
        mock_env.side_effect = lambda k: {
            "TELEGRAM_BOT_TOKEN": "t",
            "TELEGRAM_ALLOWED_USER_IDS": "123,abc,,",
        }.get(k)
        self.assertEqual(tg._get_allowed_ids(), {123})


class BrainDetailedTest(unittest.TestCase):
    def test_detailed_mode_adds_chat_instructions(self):
        brain = GeminiBrain.__new__(GeminiBrain)
        brain._detailed = True
        with mock.patch(
            "brain.gemini.build_system_context", return_value=""
        ):
            prompt = brain._build_system_prompt()
        self.assertIn("CANAL CHAT (Telegram)", prompt)
        self.assertIn("Markdown", prompt)

    def test_non_detailed_mode_has_no_chat_instructions(self):
        brain = GeminiBrain.__new__(GeminiBrain)
        brain._detailed = False
        with mock.patch(
            "brain.gemini.build_system_context", return_value=""
        ):
            prompt = brain._build_system_prompt()
        self.assertNotIn("CANAL CHAT (Telegram)", prompt)


class SendPhotoTest(unittest.TestCase):
    """La captura de pantalla debe viajar al celular como FOTO."""

    def _fake_app(self):
        app = mock.Mock()
        app.bot.send_photo = mock.AsyncMock()
        app.bot.send_message = mock.AsyncMock()
        return app

    def test_sends_photo_with_caption(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shot.jpg"
            Image.new("RGB", (16, 16), "blue").save(path, format="JPEG")

            app = self._fake_app()
            tg._application = app
            tg._loop = asyncio.new_event_loop()
            try:
                coro = tg._send_photo(123, str(path), "Veo Chrome")
                tg._loop.run_until_complete(coro)
            finally:
                tg._loop.close()
                tg._loop = None
                tg._application = None

        app.bot.send_photo.assert_awaited_once()
        kwargs = app.bot.send_photo.await_args.kwargs
        self.assertEqual(kwargs["chat_id"], 123)
        self.assertEqual(kwargs["caption"], "Veo Chrome")
        self.assertTrue(kwargs["photo"].endswith("shot.jpg"))

    def test_missing_file_is_skipped(self):
        import asyncio

        app = self._fake_app()
        tg._application = app
        tg._loop = asyncio.new_event_loop()
        try:
            coro = tg._send_photo(123, "C:/no/existe.jpg", "x")
            tg._loop.run_until_complete(coro)
        finally:
            tg._loop.close()
            tg._loop = None
            tg._application = None

        app.bot.send_photo.assert_not_awaited()

    def test_long_caption_is_truncated(self):
        import asyncio
        import tempfile
        from pathlib import Path
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shot.jpg"
            Image.new("RGB", (16, 16), "blue").save(path, format="JPEG")

            app = self._fake_app()
            tg._application = app
            tg._loop = asyncio.new_event_loop()
            try:
                coro = tg._send_photo(123, str(path), "x" * 2000)
                tg._loop.run_until_complete(coro)
            finally:
                tg._loop.close()
                tg._loop = None
                tg._application = None

        caption = app.bot.send_photo.await_args.kwargs["caption"]
        self.assertLessEqual(len(caption), tg._MAX_CAPTION)


class ProcessForArtifactsTest(unittest.TestCase):
    """Si el turno tomo capturas, se envian como foto en vez de texto solo."""

    def test_artifacts_trigger_photo_reply(self):
        brain = mock.Mock()
        brain.chat_message.return_value = "Veo Chrome"
        brain.artifacts = [{"type": "image", "path": "C:/tmp/x.jpg"}]

        with mock.patch.object(tg, "_get_brain", return_value=brain):
            with mock.patch.object(tg, "_reply_with_images") as mock_imgs:
                with mock.patch.object(tg, "_reply") as mock_reply:
                    with mock.patch("memory.context.save_conversation"):
                        with mock.patch("memory.search.store_memory"):
                            tg._process_for(55, "que hay en mi pantalla")

        mock_imgs.assert_called_once()
        mock_reply.assert_not_called()
        chat_id, text, images = mock_imgs.call_args.args
        self.assertEqual(chat_id, 55)
        self.assertEqual(text, "Veo Chrome")
        self.assertEqual(images[0]["path"], "C:/tmp/x.jpg")

    def test_without_artifacts_sends_plain_text(self):
        brain = mock.Mock()
        brain.chat_message.return_value = "Hola"
        brain.artifacts = []

        with mock.patch.object(tg, "_get_brain", return_value=brain):
            with mock.patch.object(tg, "_reply_with_images") as mock_imgs:
                with mock.patch.object(tg, "_reply") as mock_reply:
                    with mock.patch("memory.context.save_conversation"):
                        with mock.patch("memory.search.store_memory"):
                            tg._process_for(55, "hola")

        mock_imgs.assert_not_called()
        mock_reply.assert_called_once_with(55, "Hola")


if __name__ == "__main__":
    unittest.main()
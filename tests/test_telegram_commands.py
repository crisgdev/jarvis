import unittest
from unittest import mock

from services import telegram_bot as tg

OWNER = 42
CHAT = 99


class FakeNotice:
    def __init__(self):
        self.edited = []
        self.deleted = False

    async def edit_text(self, text, **kwargs):
        self.edited.append(text)
        return self

    async def delete(self):
        self.deleted = True


class FakeMessage:
    def __init__(self):
        self.replies = []
        self.notice = FakeNotice()

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)
        return self.notice


class FakeUpdate:
    def __init__(self, user_id=OWNER, chat_id=CHAT):
        self.effective_user = mock.Mock(id=user_id)
        self.effective_chat = mock.Mock(id=chat_id)
        self.message = FakeMessage()


def _allowed():
    return mock.patch.object(tg, "_get_allowed_ids", return_value={OWNER})


class TelegramTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tg._confirm_state.clear()
        tg._jarvis = None
        tg._started_at = 0.0

    def tearDown(self):
        tg._confirm_state.clear()
        tg._jarvis = None
        tg._started_at = 0.0


class FormatUptimeTest(unittest.TestCase):
    def test_segundos(self):
        self.assertEqual(tg._format_uptime(9), "9s")

    def test_minutos(self):
        self.assertEqual(tg._format_uptime(125), "2m 05s")

    def test_horas(self):
        self.assertEqual(tg._format_uptime(7200), "2h 00m")

    def test_negativo(self):
        self.assertEqual(tg._format_uptime(-5), "0s")


class EstadoTest(TelegramTestBase):
    @staticmethod
    def _sin_audio():
        return (
            mock.patch("services.audio.is_recording", return_value=False),
            mock.patch("services.tts.is_speaking", return_value=False),
        )

    async def test_panel_sin_instancia(self):
        rec, speak = self._sin_audio()
        with _allowed(), rec, speak:
            update = FakeUpdate()
            await tg._on_estado(update, None)

        text = update.message.replies[-1]
        self.assertIn("JARVIS", text)
        self.assertIn("solo Telegram", text)
        self.assertIn("Modo sordo:", text)
        self.assertIn("Micro: libre", text)

    async def test_panel_con_instancia(self):
        fake = mock.Mock()
        fake.state = mock.Mock(value="deaf")
        fake.get_model.return_value = "gemini-3.5-flash-lite"
        fake.is_call_active.return_value = False

        rec, speak = self._sin_audio()
        with _allowed(), rec, speak, mock.patch.object(tg, "_jarvis", fake):
            update = FakeUpdate()
            await tg._on_estado(update, None)

        text = update.message.replies[-1]
        self.assertIn("voz + Telegram", text)
        self.assertIn("modo sordo", text)
        self.assertIn("gemini-3.5-flash-lite", text)

    def test_modo_sordo_aparece(self):
        with mock.patch.object(
            tg.deaf_mode,
            "status_text",
            return_value="activado desde 2026-11-07T10:00:00 (telegram)",
        ):
            text = tg._status_text()
        self.assertIn("Modo sordo: activado", text)

    async def test_no_autorizado(self):
        with mock.patch.object(tg, "_get_allowed_ids", return_value={1}):
            update = FakeUpdate(user_id=99)
            await tg._on_estado(update, None)
        self.assertIn("No autorizado", update.message.replies[-1])


class CapturaTest(TelegramTestBase):
    async def test_envia_foto(self):
        result = {
            "status": "success",
            "image_path": "C:/tmp/shot.jpg",
            "message": "Captura de pantalla tomada.",
        }
        send = mock.AsyncMock(return_value=object())
        with _allowed(), mock.patch(
            "tools.screen_tools._take_screenshot", return_value=result
        ), mock.patch.object(tg, "_send_photo", new=send):
            update = FakeUpdate()
            await tg._on_captura(update, None)

        send.assert_awaited_once()
        self.assertEqual(send.await_args.args[0], CHAT)
        self.assertEqual(send.await_args.args[1], "C:/tmp/shot.jpg")
        self.assertTrue(update.message.notice.deleted)

    async def test_error_de_captura(self):
        with _allowed(), mock.patch(
            "tools.screen_tools._take_screenshot", return_value={"error": "boom"}
        ), mock.patch.object(tg, "_send_photo", new=mock.AsyncMock()) as send:
            update = FakeUpdate()
            await tg._on_captura(update, None)

        send.assert_not_awaited()
        self.assertIn("boom", update.message.notice.edited[-1])

    async def test_foto_no_enviada(self):
        result = {"status": "success", "image_path": "C:/tmp/shot.jpg"}
        with _allowed(), mock.patch(
            "tools.screen_tools._take_screenshot", return_value=result
        ), mock.patch.object(
            tg, "_send_photo", new=mock.AsyncMock(return_value=None)
        ):
            update = FakeUpdate()
            await tg._on_captura(update, None)

        self.assertIn("no pude enviarla", update.message.notice.edited[-1])


class ConfirmationTest(TelegramTestBase):
    async def test_boton_si(self):
        async def fake_send(chat_id, text):
            state = tg._confirm_state[chat_id]
            state["result"] = True
            state["event"].set()

        with mock.patch.object(tg, "_send_yes_no", new=fake_send):
            ok = await tg._ask_confirmation(CHAT, "¿Confirmas?")

        self.assertTrue(ok)
        self.assertNotIn(CHAT, tg._confirm_state)

    async def test_sin_respuesta(self):
        with mock.patch.object(tg, "_send_yes_no", new=mock.AsyncMock()):
            ok = await tg._ask_confirmation(CHAT, "¿Confirmas?", timeout=0)

        self.assertFalse(ok)
        self.assertNotIn(CHAT, tg._confirm_state)


class ApagarTest(TelegramTestBase):
    async def test_cancelado_no_hiberna(self):
        with _allowed(), mock.patch.object(
            tg, "_ask_confirmation", new=mock.AsyncMock(return_value=False)
        ), mock.patch("tools.system._shutdown_pc") as shutdown:
            update = FakeUpdate()
            await tg._on_apagar(update, None)

        shutdown.assert_not_called()
        self.assertIn("Cancelado", update.message.replies[-1])

    async def test_confirmado_hiberna(self):
        with _allowed(), mock.patch.object(
            tg, "_ask_confirmation", new=mock.AsyncMock(return_value=True)
        ), mock.patch(
            "tools.system._shutdown_pc", return_value={"status": "success"}
        ) as shutdown, mock.patch("services.tts.stop_speech"), mock.patch.object(
            tg, "_HIBERNATE_DELAY", 0
        ):
            update = FakeUpdate()
            await tg._on_apagar(update, None)

        shutdown.assert_called_once_with("hibernate")
        self.assertIn("Hibernando", update.message.replies[-1])

    async def test_error_al_hibernar(self):
        with _allowed(), mock.patch.object(
            tg, "_ask_confirmation", new=mock.AsyncMock(return_value=True)
        ), mock.patch(
            "tools.system._shutdown_pc", return_value={"error": "sin permisos"}
        ), mock.patch("services.tts.stop_speech"), mock.patch.object(
            tg, "_HIBERNATE_DELAY", 0
        ):
            update = FakeUpdate()
            await tg._on_apagar(update, None)

        self.assertIn("sin permisos", update.message.replies[-1])


class ReiniciarTest(TelegramTestBase):
    async def test_reinicia(self):
        with _allowed(), mock.patch(
            "tools.system._restart_pc", return_value={"status": "success"}
        ) as restart:
            update = FakeUpdate()
            await tg._on_reiniciar(update, None)

        restart.assert_called_once_with()
        self.assertIn("60 segundos", update.message.replies[-1])

    async def test_no_autorizado(self):
        with mock.patch.object(tg, "_get_allowed_ids", return_value={1}), mock.patch(
            "tools.system._restart_pc"
        ) as restart:
            update = FakeUpdate(user_id=99)
            await tg._on_reiniciar(update, None)

        restart.assert_not_called()
        self.assertIn("No autorizado", update.message.replies[-1])


class PrenderTest(TelegramTestBase):
    async def test_envia_wol(self):
        with _allowed(), mock.patch(
            "tools.system._wake_on_lan", return_value={"result": "enviado"}
        ) as wake:
            update = FakeUpdate()
            await tg._on_prender(update, None)

        wake.assert_called_once_with()
        self.assertIn("Wake-on-LAN", update.message.replies[-1])

    async def test_avisa_si_la_pc_esta_encendida(self):
        fake = mock.Mock()
        with _allowed(), mock.patch(
            "tools.system._wake_on_lan", return_value={"result": "enviado"}
        ), mock.patch.object(tg, "_jarvis", fake):
            update = FakeUpdate()
            await tg._on_prender(update, None)

        text = update.message.replies[-1]
        self.assertIn("misma PC", text)
        self.assertIn("wake_listener", text)

    async def test_error_wol(self):
        with _allowed(), mock.patch(
            "tools.system._wake_on_lan", return_value={"error": "MAC invalida"}
        ):
            update = FakeUpdate()
            await tg._on_prender(update, None)

        self.assertIn("MAC invalida", update.message.replies[-1])


if __name__ == "__main__":
    unittest.main()

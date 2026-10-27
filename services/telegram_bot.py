"""Bot de Telegram para JARVIS.

Corre la biblioteca python-telegram-bot en un hilo propio con su propio
event loop. Comparte con la voz el mismo cerebro (GeminiBrain), la misma
memoria (SQLite) y las mismas tools; solo mantiene su propia conversacion
en curso para no pisar el canal de voz.

Confirmacion de acciones peligrosas: se envia un mensaje con botones
inline y se espera la respuesta del dueno hasta confirm_timeout.
"""

import asyncio
import logging
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from config import get_env, get_setting

logger = logging.getLogger("jarvis.telegram")

_application = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_bot_thread: Optional[threading.Thread] = None
_stop_event = threading.Event()
_running = False

_brains: dict[int, object] = {}
_brains_lock = threading.Lock()
_chat_locks: dict[int, threading.Lock] = {}
_confirm_state: dict[int, dict] = {}
_confirm_lock = threading.Lock()


def _get_token() -> str:
    return (get_env("TELEGRAM_BOT_TOKEN") or "").strip()


def _get_allowed_ids() -> set[int]:
    raw = (get_env("TELEGRAM_ALLOWED_USER_IDS") or "").strip()
    ids: set[int] = set()
    for part in raw.replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            logger.warning("Id de Telegram invalido en config: %r", part)
    return ids


def is_configured() -> bool:
    return bool(_get_token())


def is_running() -> bool:
    return _running


def start_telegram_bot():
    global _bot_thread, _running, _stop_event

    if _running:
        logger.warning("Telegram bot ya esta corriendo")
        return

    token = _get_token()
    if not token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN no configurado en .env; Telegram desactivado"
        )
        return

    try:
        from telegram.ext import (  # noqa: F401
            Application,
            CallbackQueryHandler,
            CommandHandler,
            MessageHandler,
            filters,
        )
        from telegram import Update  # noqa: F401
    except ImportError:
        logger.warning(
            "python-telegram-bot no instalado. Instala con: pip install python-telegram-bot"
        )
        return

    _stop_event.clear()
    _running = True
    _bot_thread = threading.Thread(
        target=_run_bot, args=(token,), daemon=True
    )
    _bot_thread.start()
    logger.info("Telegram bot iniciado")


def stop_telegram_bot():
    global _running, _bot_thread
    if not _running:
        return
    _running = False
    _stop_event.set()
    if _bot_thread is not None and _bot_thread is not threading.current_thread():
        _bot_thread.join(timeout=3.0)
    _bot_thread = None
    logger.info("Telegram bot detenido")


def _run_bot(token: str):
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    try:
        _loop.run_until_complete(_async_main(token))
    except Exception as e:
        logger.error("Error en loop de Telegram: %s", e)
    finally:
        try:
            _loop.close()
        except Exception:
            pass
        _loop = None
        logger.info("Telegram bot terminado")


async def _async_main(token: str):
    global _application
    from telegram import Update
    from telegram.ext import (
        Application,
        CallbackQueryHandler,
        CommandHandler,
        MessageHandler,
        filters,
    )

    app = Application.builder().token(token).build()
    _application = app

    app.add_handler(CommandHandler("start", _on_start))
    app.add_handler(CallbackQueryHandler(_on_confirm_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _on_voice))
    app.add_error_handler(_on_error)

    await app.initialize()
    await app.start()
    await app.updater.start_polling(
        allowed_updates=[Update.MESSAGE, Update.CALLBACK_QUERY],
        drop_pending_updates=True,
    )
    logger.info("Telegram bot en linea")

    while not _stop_event.is_set():
        await asyncio.sleep(0.5)

    await app.updater.stop()
    await app.stop()
    await app.shutdown()


async def _on_error(update, context):
    logger.error("Error de Telegram: %s", context.error)


async def _on_start(update, context):
    user = update.effective_user
    user_id = user.id if user else -1

    if not _get_allowed_ids():
        logger.info(
            "Primer contacto de Telegram: configura TELEGRAM_ALLOWED_USER_IDS con el id %s",
            user_id,
        )
        await update.message.reply_text(
            f"Hola {user.first_name or 'amigo'}.\n"
            f"JARVIS no tiene configurado TELEGRAM_ALLOWED_USER_IDS.\n"
            f"Tu id de Telegram es: {user_id}\n\n"
            f"Agregalo en .env para poder usar el chat."
        )
        return

    if user_id not in _get_allowed_ids():
        await update.message.reply_text(
            f"No autorizado para usar este bot. Tu id es {user_id}."
        )
        return

    await update.message.reply_text(
        "Hola, soy JARVIS. Escribeme y ejecutare tareas en tu PC.\n"
        "Comparto memoria y herramientas con el canal de voz."
    )


async def _on_message(update, context):
    msg = update.effective_message
    if not msg or not msg.text:
        return

    user_id = msg.from_user.id if msg.from_user else -1
    if user_id not in _get_allowed_ids():
        await msg.reply_text(
            f"No autorizado para usar este bot. Tu id es {user_id}."
        )
        return

    text = msg.text.strip()
    if not text:
        return

    chat_id = msg.chat_id
    logger.info("Telegram [%s]: %s", chat_id, text[:100])

    thread = threading.Thread(
        target=_process_for, args=(chat_id, text), daemon=True
    )
    thread.start()


async def _on_voice(update, context):
    msg = update.effective_message
    if not msg:
        return

    user_id = msg.from_user.id if msg.from_user else -1
    if user_id not in _get_allowed_ids():
        await msg.reply_text(
            f"No autorizado para usar este bot. Tu id es {user_id}."
        )
        return

    media = msg.voice or msg.audio
    if media is None:
        return

    chat_id = msg.chat_id
    file_id = media.file_id
    logger.info("Telegram [%s]: nota de voz (%.1fs)", chat_id, getattr(media, "duration", 0) or 0)

    tmp_dir = Path(tempfile.gettempdir()) / "jarvis_telegram"
    tmp_dir.mkdir(exist_ok=True)
    path = tmp_dir / f"voice_{chat_id}_{uuid.uuid4().hex[:8]}.ogg"

    try:
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(custom_path=str(path))
    except Exception as e:
        logger.error("Error descargando audio de Telegram: %s", e)
        await msg.reply_text("No pude descargar tu audio.")
        return

    thread = threading.Thread(
        target=_process_voice_for, args=(chat_id, str(path)), daemon=True
    )
    thread.start()


def _process_voice_for(chat_id: int, filepath: str):
    from services.stt import transcribe_file

    try:
        t0 = time.perf_counter()
        text = transcribe_file(filepath)
        logger.info(
            "LATENCIA STT (telegram voice): %.0f ms",
            (time.perf_counter() - t0) * 1000,
        )

        if not text:
            _reply(chat_id, "No te entendí el audio. Inténtalo de nuevo.")
            return

        logger.info("Telegram voice [%s]: %s", chat_id, text[:100])
        _process_for(chat_id, text)
    except Exception as e:
        logger.exception("Error procesando audio de Telegram")
        _reply(chat_id, f"Tuve un error procesando tu audio: {e}")
    finally:
        try:
            Path(filepath).unlink(missing_ok=True)
        except Exception:
            pass


def _process_for(chat_id: int, text: str):
    with _chat_locks.setdefault(chat_id, threading.Lock()):
        try:
            brain = _get_brain(chat_id)
            from memory.context import save_conversation
            from memory.search import store_memory

            save_conversation("user", text)

            t0 = time.perf_counter()
            response = brain.chat_message(text)
            logger.info("LATENCIA GEMINI (telegram): %.0f ms", (time.perf_counter() - t0) * 1000)

            if not response:
                response = "No pude generar una respuesta."

            save_conversation("model", response)
            store_memory(response, source="telegram")

            # Si el turno tomo capturas de pantalla, se envian como foto
            # para que el usuario vea su pantalla desde el celular.
            artifacts = list(getattr(brain, "artifacts", []) or [])
            images = [a for a in artifacts if a.get("type") == "image"]

            if images:
                _reply_with_images(chat_id, response, images)
            else:
                _reply(chat_id, response)
        except Exception as e:
            logger.exception("Error procesando mensaje de Telegram")
            _reply(chat_id, f"Tuve un error al procesar tu mensaje: {e}")


def _get_brain(chat_id: int):
    with _brains_lock:
        if chat_id not in _brains:
            from brain.gemini import GeminiBrain

            brain = GeminiBrain(detailed=True)
            brain.set_confirmation_callback(
                lambda tool, args: _confirm_for(chat_id, tool, args)
            )
            _brains[chat_id] = brain
        return _brains[chat_id]


def _confirm_for(chat_id: int, tool_name: str, args: dict) -> bool:
    timeout = int(get_setting("telegram", "confirm_timeout", 60))
    state = {"event": threading.Event(), "result": None}

    with _confirm_lock:
        _confirm_state[chat_id] = state

    if _loop is not None and _application is not None:
        asyncio.run_coroutine_threadsafe(
            _send_confirmation(chat_id, tool_name, args), _loop
        )

    state["event"].wait(timeout)

    with _confirm_lock:
        state = _confirm_state.pop(chat_id, None) or state

    return bool(state["result"])


async def _send_confirmation(chat_id: int, tool_name: str, args: dict):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    from core.confirmations import confirmation_to_message

    text = confirmation_to_message(tool_name, args)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Si, confirmar", callback_data="confirm"),
                InlineKeyboardButton("No, cancelar", callback_data="cancel"),
            ]
        ]
    )
    await _application.bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


async def _on_confirm_callback(update, context):
    query = update.callback_query
    await query.answer()

    chat_id = query.message.chat_id
    state = _confirm_state.get(chat_id)
    if state is None:
        await query.edit_message_text("La confirmacion expiro o ya fue respondida.")
        return

    ok = query.data == "confirm"
    state["result"] = ok
    state["event"].set()

    label = "SI" if ok else "NO"
    await query.edit_message_text(f"Confirmacion respondida: {label}")


def _reply(chat_id: int, text: str):
    if _loop is None or _application is None:
        return
    asyncio.run_coroutine_threadsafe(_send_reply(chat_id, text), _loop)


# Limite de Telegram para el pie de foto de una foto.
_MAX_CAPTION = 1024


def _reply_with_images(chat_id: int, text: str, images: list[dict]):
    """Envia la(s) captura(s) como foto(s) y la respuesta del modelo."""
    if _loop is None or _application is None:
        return

    caption = (text or "").strip()

    first = images[0]
    extra_text = text if len(text or "") > _MAX_CAPTION else None

    coros = [
        _send_photo(chat_id, first.get("path"), caption or "Captura de tu PC")
    ]
    for image in images[1:]:
        coros.append(_send_photo(chat_id, image.get("path"), "Captura de tu PC"))
    if extra_text:
        coros.append(_send_reply(chat_id, text))

    asyncio.run_coroutine_threadsafe(_gather(*coros), _loop)


async def _gather(*coros):
    for coro in coros:
        try:
            await coro
        except Exception as e:
            logger.warning("Error enviando artefacto a Telegram: %s", e)


async def _send_photo(chat_id: int, path: str, caption: str):
    """Envia una captura de pantalla como foto al chat.

    Devuelve el Message de Telegram (o None si no se pudo enviar).
    """
    from telegram.error import TelegramError

    if not path:
        return None
    if not Path(path).exists():
        logger.warning("La captura %s ya no existe", path)
        return None

    caption = (caption or "").strip()
    if len(caption) > _MAX_CAPTION:
        caption = caption[: _MAX_CAPTION - 3].rstrip() + "..."

    try:
        return await _application.bot.send_photo(
            chat_id=chat_id,
            photo=str(path),
            caption=caption,
        )
    except TelegramError as e:
        logger.warning("No se pudo enviar la foto (%s), reintento sin pie de foto", e)
        try:
            return await _application.bot.send_photo(chat_id=chat_id, photo=str(path))
        except TelegramError as e2:
            logger.error("Error enviando la captura a %s: %s", chat_id, e2)
            return None


async def _send_reply(chat_id: int, text: str):
    from telegram.error import TelegramError

    try:
        await _application.bot.send_message(
            chat_id=chat_id, text=text, parse_mode="Markdown"
        )
    except TelegramError:
        try:
            await _application.bot.send_message(chat_id=chat_id, text=text)
        except TelegramError as e:
            logger.error("Error enviando mensaje a %s: %s", chat_id, e)
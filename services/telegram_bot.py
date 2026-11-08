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

from telegram.constants import ChatAction

from config import get_env, get_setting
from services import deaf_mode

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

_typing_stops: dict[int, threading.Event] = {}
_typing_lock = threading.Lock()

# Instancia de JARVIS (voz + GUI). En --telegram-only queda en None.
_jarvis = None
_started_at = 0.0


def set_jarvis(instance):
    """Registra la instancia de JARVIS para las ordenes que la necesitan.

    main.py la llama al arrancar con GUI/voz. Sin instancia (modo
    --telegram-only) los comandos de voz responden que no hay canal activo
    en vez de fallar.
    """
    global _jarvis
    _jarvis = instance


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


def _start_typing(chat_id: int) -> threading.Event:
    """Lanza un hilo que envia la accion 'typing' a Telegram cada 4s.

    Devuelve el Event para detenerlo.
    """
    stop = threading.Event()
    with _typing_lock:
        prev = _typing_stops.pop(chat_id, None)
        if prev is not None:
            prev.set()
        _typing_stops[chat_id] = stop

    def worker():
        while not stop.is_set():
            try:
                if _loop is not None and _application is not None:
                    asyncio.run_coroutine_threadsafe(
                        _application.bot.send_chat_action(
                            chat_id=chat_id, action=ChatAction.TYPING
                        ),
                        _loop,
                    )
            except Exception:
                pass
            stop.wait(4.0)

    threading.Thread(target=worker, daemon=True).start()
    return stop


def _stop_typing(stop: Optional[threading.Event]):
    if stop is not None:
        stop.set()


def start_telegram_bot():
    global _bot_thread, _running, _stop_event, _started_at

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
    _started_at = time.time()
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
    app.add_handler(CommandHandler("estado", _on_estado))
    app.add_handler(CommandHandler("captura", _on_captura))
    app.add_handler(CommandHandler("sordo", _on_deaf_on))
    app.add_handler(CommandHandler("escucha", _on_deaf_off))
    app.add_handler(CommandHandler("apagar", _on_apagar))
    app.add_handler(CommandHandler("reiniciar", _on_reiniciar))
    app.add_handler(CommandHandler("prender", _on_prender))
    app.add_handler(CallbackQueryHandler(_on_confirm_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _on_message))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, _on_voice))
    app.add_error_handler(_on_error)

    await app.initialize()
    await app.start()

    try:
        from telegram import BotCommand

        await app.bot.set_my_commands(
            [
                BotCommand("estado", "Como estoy: modo sordo, modelo, micro y voz"),
                BotCommand("captura", "Captura de pantalla al chat"),
                BotCommand("sordo", "Dejar de escuchar (modo sordo)"),
                BotCommand("escucha", "Volver a escuchar"),
                BotCommand("apagar", "Hibernar la PC (pide confirmacion)"),
                BotCommand("reiniciar", "Reiniciar la PC en 60 segundos"),
                BotCommand("prender", "Enviar wake-on-LAN a la PC"),
            ]
        )
    except Exception as e:
        logger.warning("No se pudo registrar la lista de comandos: %s", e)

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
        "Comparto memoria y herramientas con el canal de voz.\n\n"
        "Comandos:\n"
        "/estado - como estoy (modo sordo, modelo, micro y voz)\n"
        "/captura - captura de pantalla al chat\n"
        "/sordo - dejo de escuchar el microfono (util si la laptop esta sonando)\n"
        "/escucha - vuelvo a escuchar\n"
        "/apagar - hiberno la PC (pedire confirmacion)\n"
        "/reiniciar - reinicio la PC en 60 segundos\n"
        "/prender - envio wake-on-LAN a la PC\n\n"
        "Tambien entiendo \"modo sordo\" y \"vuelve a escuchar\" escritos o en nota de voz."
    )


def _deaf_message(command: str) -> str:
    if command == "on":
        return (
            "MODO SORDO ACTIVADO\n"
            "No escucho el microfono, ni las palmadas, ni el atajo Ctrl+Alt+Shift+J.\n"
            "Para volver a escucharte: /escucha"
        )
    return (
        "MODO SORDO DESACTIVADO\n"
        "Vuelvo a escuchar por el microfono."
    )


def _unauthorized_text(update) -> str | None:
    """Mensaje de rechazo, o None si el usuario esta autorizado."""
    user = update.effective_user
    user_id = user.id if user else -1
    if user_id in _get_allowed_ids():
        return None
    return f"No autorizado para usar este bot. Tu id es {user_id}."


# ---------------------------------------------------------------------------
# /estado
# ---------------------------------------------------------------------------
_STATE_TEXT = {
    "idle": "en espera",
    "listening": "escuchando",
    "processing": "procesando",
    "speaking": "hablando",
    "call": "en llamada",
    "deaf": "modo sordo",
}


def _format_uptime(seconds: float) -> str:
    seconds = int(max(0.0, float(seconds or 0)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _status_text() -> str:
    """Panel de estado local: no pasa por Gemini ni gasta tokens."""
    lines = ["*JARVIS*", ""]

    if _jarvis is not None:
        lines.append("Canal: voz + Telegram")
        state = getattr(getattr(_jarvis, "state", None), "value", "?")
        lines.append(f"Estado: {_STATE_TEXT.get(state, state)}")
        try:
            lines.append(f"Modelo: {_jarvis.get_model()}")
        except Exception:
            pass
        try:
            lines.append(f"Llamada: {'activa' if _jarvis.is_call_active() else 'no'}")
        except Exception:
            pass
    else:
        lines.append("Canal: solo Telegram (sin voz ni GUI)")
        lines.append(f"Modelo: {get_setting('llm', 'model', '-')}")

    lines.append(f"Modo sordo: {deaf_mode.status_text()}")

    try:
        from services.audio import is_recording
        from services.tts import is_speaking

        lines.append(f"Micro: {'grabando' if is_recording() else 'libre'}")
        lines.append(f"Voz: {'hablando' if is_speaking() else 'callada'}")
    except Exception as e:
        logger.debug("No se pudo leer el estado de audio: %s", e)

    if _started_at:
        lines.append(f"Bot activo desde hace: {_format_uptime(time.time() - _started_at)}")

    return "\n".join(lines)


async def _on_estado(update, context):
    """Comando /estado: como esta JARVIS ahora mismo."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return
    await update.message.reply_text(_status_text(), parse_mode="Markdown")


# ---------------------------------------------------------------------------
# /captura
# ---------------------------------------------------------------------------
async def _on_captura(update, context):
    """Comando /captura: manda una captura de la pantalla como foto."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return

    chat_id = update.effective_chat.id
    notice = await update.message.reply_text("Capturando la pantalla...")

    try:
        from tools.screen_tools import _take_screenshot

        result = await asyncio.to_thread(_take_screenshot)
    except Exception as e:
        logger.error("Error capturando pantalla desde Telegram: %s", e)
        await notice.edit_text(f"No pude capturar la pantalla: {e}")
        return

    path = (result or {}).get("image_path")
    if not path:
        error = (result or {}).get("error", "error desconocido")
        await notice.edit_text(f"No pude capturar la pantalla: {error}")
        return

    sent = await _send_photo(
        chat_id, path, (result or {}).get("message") or "Captura de tu PC"
    )
    if sent is None:
        await notice.edit_text("Tome la captura pero no pude enviarla.")
        return
    try:
        await notice.delete()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# /apagar, /reiniciar y /prender
# ---------------------------------------------------------------------------
# Pausa para que el aviso salga antes de hibernar (congela la sesion).
_HIBERNATE_DELAY = 1.0


async def _send_yes_no(chat_id: int, text: str):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Si, confirmar", callback_data="confirm"),
                InlineKeyboardButton("No, cancelar", callback_data="cancel"),
            ]
        ]
    )
    await _application.bot.send_message(
        chat_id=chat_id, text=text, parse_mode="Markdown", reply_markup=keyboard
    )


async def _ask_confirmation(chat_id: int, text: str, timeout: int = 45) -> bool:
    """Pregunta Si/No con botones inline y espera la respuesta.

    Reusa el mismo mecanismo que las acciones peligrosas de Gemini
    (`_confirm_state` + `_on_confirm_callback`).
    """
    state = {"event": threading.Event(), "result": None}
    with _confirm_lock:
        _confirm_state[chat_id] = state

    try:
        await _send_yes_no(chat_id, text)
    except Exception as e:
        logger.warning("No pude pedir confirmacion: %s", e)
        with _confirm_lock:
            _confirm_state.pop(chat_id, None)
        return False

    await asyncio.to_thread(state["event"].wait, timeout)

    with _confirm_lock:
        state = _confirm_state.pop(chat_id, None) or state
    return bool(state["result"])


async def _on_apagar(update, context):
    """/apagar: hiberna la PC (con confirmacion)."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return

    chat_id = update.effective_chat.id
    ok = await _ask_confirmation(
        chat_id,
        "*Hibernar la PC*\n"
        "Guardo la RAM en disco y la PC queda apagada hasta que la enciendas "
        "con /prender o con el boton.\n"
        "¿Confirmas?",
    )
    if not ok:
        await update.message.reply_text("Cancelado: la PC sigue encendida.")
        return

    try:
        from services.tts import stop_speech

        stop_speech()
    except Exception:
        pass

    await update.message.reply_text("Hibernando la PC...")
    # Deja que el mensaje salga antes de congelar la sesion.
    await asyncio.sleep(_HIBERNATE_DELAY)

    from tools.system import _shutdown_pc

    result = await asyncio.to_thread(_shutdown_pc, "hibernate")
    error = (result or {}).get("error")
    if error:
        await update.message.reply_text(f"No pude hibernar la PC: {error}")


async def _on_reiniciar(update, context):
    """/reiniciar: reinicia la PC en 60 segundos (cancelable)."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return

    from tools.system import _restart_pc

    result = await asyncio.to_thread(_restart_pc)
    error = (result or {}).get("error")
    if error:
        await update.message.reply_text(f"No pude reiniciar la PC: {error}")
        return

    await update.message.reply_text(
        "Reiniciando la PC en 60 segundos.\n"
        "Para cancelar a tiempo, ejecuta en la PC: shutdown /a"
    )


async def _on_prender(update, context):
    """/prender: envia un paquete Wake-on-LAN a la PC."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return

    from tools.system import _wake_on_lan

    result = await asyncio.to_thread(_wake_on_lan)
    error = (result or {}).get("error")
    if error:
        await update.message.reply_text(f"No pude enviar wake-on-LAN: {error}")
        return

    mac = get_setting("wol", "mac", "")
    lines = [f"Paquete Wake-on-LAN enviado a {mac}."]
    if _jarvis is not None:
        lines.append(
            "Ojo: estoy corriendo en esa misma PC, asi que ya esta encendida. "
            "Si esta apagada o hibernada, este comando lo atiende "
            "wake_listener.py en otro dispositivo de tu red."
        )
    await update.message.reply_text("\n".join(lines))


async def _on_deaf_on(update, context):
    """Comando /sordo: activa el modo sordo (JARVIS deja de escuchar)."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return
    deaf_mode.set_deaf(True, source_name="telegram")
    logger.info("Modo sordo activado desde Telegram")
    await update.message.reply_text(_deaf_message("on"))


async def _on_deaf_off(update, context):
    """Comando /escucha: vuelve a escuchar."""
    denied = _unauthorized_text(update)
    if denied:
        await update.message.reply_text(denied)
        return
    deaf_mode.set_deaf(False, source_name="telegram")
    logger.info("Modo sordo desactivado desde Telegram")
    await update.message.reply_text(_deaf_message("off"))


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

    # Acuse de recibo inmediato: que el usuario vea que JARVIS recibio el
    # mensaje aunque el procesamiento tarde.
    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception:
        pass

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

    try:
        await update.effective_chat.send_action(ChatAction.TYPING)
    except Exception:
        pass

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

    typing_stop = _start_typing(chat_id)
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
        _stop_typing(typing_stop)
        try:
            Path(filepath).unlink(missing_ok=True)
        except Exception:
            pass


def _process_for(chat_id: int, text: str):
    # Orden de modo sordo ("modo sordo" / "vuelve a escuchar"): se atiende
    # aqui, antes de Gemini, tanto si llega escrita como en nota de voz.
    command = deaf_mode.match_command(text)
    if command is not None:
        deaf_mode.set_deaf(command == "on", source_name="telegram")
        logger.info("Modo sordo %s desde Telegram", command)
        _reply(chat_id, _deaf_message(command))
        return

    from services.power_commands import match_power_command

    power_cmd = match_power_command(text)
    if power_cmd is not None:
        import time as _time

        action = power_cmd.get("action")
        if action == "shutdown":
            ok = _confirm_for(chat_id, "shutdown_pc", {"mode": power_cmd.get("mode")})
            if not ok:
                _reply(chat_id, "Cancelado: la PC sigue encendida.")
                return
            try:
                from services.tts import stop_speech

                stop_speech()
            except Exception:
                pass
            label = "Hibernando" if power_cmd.get("mode") in (None, "hibernate", "hibernar") else (
                "Suspendiendo" if power_cmd.get("mode") == "sleep" else "Apagando"
            )
            _reply(chat_id, f"{label} la PC...")
            _time.sleep(_HIBERNATE_DELAY)
            from tools.system import _shutdown_pc

            result = _shutdown_pc(power_cmd.get("mode"))
            error = (result or {}).get("error")
            if error:
                _reply(chat_id, f"No pude: {error}")
            return
        if action == "restart":
            ok = _confirm_for(chat_id, "restart_pc", {})
            if not ok:
                _reply(chat_id, "Cancelado: la PC no se reiniciara.")
                return
            from tools.system import _restart_pc

            result = _restart_pc()
            error = (result or {}).get("error")
            if error:
                _reply(chat_id, f"No pude: {error}")
            else:
                _reply(chat_id, (result or {}).get("message") or "Reiniciando la PC.")
            return
        if action == "wake":
            from tools.system import _wake_on_lan

            result = _wake_on_lan()
            error = (result or {}).get("error")
            if error:
                _reply(chat_id, f"No pude: {error}")
            else:
                _reply(chat_id, (result or {}).get("message") or "Paquete Wake-on-LAN enviado.")
            return

    # Cada peticion usa su propio brain (sin lock compartido): asincronia real,
    # las peticiones no se atan unas a otras. El estado (artifacts, exchanges)
    # queda aislado por peticion.
    typing_stop = _start_typing(chat_id)
    sent_images: set[str] = set()

    try:
        from brain.gemini import GeminiBrain

        brain = GeminiBrain(detailed=True)
        brain.set_confirmation_callback(
            lambda tool, args: _confirm_for(chat_id, tool, args)
        )

        def _on_artifact(art: dict):
            path = art.get("path")
            if path and path not in sent_images:
                sent_images.add(path)
                # Envio inmediato de la captura, sin esperar al final del turno.
                _send_photo_now(chat_id, path, "Captura de tu PC")

        brain.set_artifact_callback(_on_artifact)

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

        # Las capturas ya enviadas incrementalmente no se reenvian.
        artifacts = list(getattr(brain, "artifacts", []) or [])
        images = [
            a
            for a in artifacts
            if a.get("type") == "image" and a.get("path") not in sent_images
        ]

        if images:
            _reply_with_images(chat_id, response, images)
        else:
            _reply(chat_id, response)
    except Exception as e:
        logger.exception("Error procesando mensaje de Telegram")
        _reply(chat_id, f"Tuve un error al procesar tu mensaje: {e}")
    finally:
        _stop_typing(typing_stop)


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


def _send_photo_now(chat_id: int, path: str, caption: str):
    """Programa el envio inmediato de una captura (sin bloquear)."""
    if _loop is None or _application is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _send_photo(chat_id, path, caption), _loop
        )
    except Exception as e:
        logger.warning("Error programando envio inmediato de foto: %s", e)


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
    try:
        await asyncio.gather(*coros, return_exceptions=True)
    except Exception as e:
        logger.warning("Error enviando artefactos a Telegram: %s", e)


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
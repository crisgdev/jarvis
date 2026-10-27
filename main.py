import sys
import time
import logging
import signal
import atexit
import queue
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from utils.logger import setup_logger
from config import get_env, load_config, get_setting
from memory.context import start_session, end_current_session
from memory.search import init_semantic_search

logger = logging.getLogger("jarvis.main")

from core.confirmations import confirmation_request


def validate_env() -> bool:
    api_key = get_env("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY no encontrada en .env")
        return False
    return True


def run_telegram_only():
    """Ejecuta solo el bot de Telegram, sin GUI ni voz.

    Necesita python main.py --telegram-only. Se detiene con Ctrl+C.
    """
    setup_logger("jarvis", level=logging.INFO)
    logger.info("Iniciando JARVIS (solo Telegram, sin GUI)...")

    if not validate_env():
        sys.exit(1)

    load_config()
    logger.info("Configuracion cargada")

    if not get_setting("telegram", "enabled", True):
        logger.warning("telegram.enabled=False en config.json; nada que iniciar")
        sys.exit(0)

    mem_enabled = get_setting("memory", "semantic_search", False)
    init_semantic_search(enabled=mem_enabled)

    start_session()
    logger.info("Sesion iniciada")

    from services.telegram_bot import start_telegram_bot, stop_telegram_bot, is_running

    start_telegram_bot()
    if not is_running():
        logger.error(
            "El bot no pudo iniciar. Revisa TELEGRAM_BOT_TOKEN en .env "
            "y la seccion telegram de config.json"
        )
        end_current_session()
        sys.exit(1)

    logger.info("JARVIS Telegram en linea. Ctrl+C para detener.")

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            from tools.opencode_tools import stop_server as stop_opencode
            stop_opencode()
        except Exception as e:
            logger.warning("No se pudo detener OpenCode: %s", e)
        stop_telegram_bot()
        end_current_session()
        try:
            from memory.database import close as close_database
            close_database()
        except Exception as e:
            logger.warning("No se pudo cerrar la base de datos: %s", e)
        logger.info("JARVIS Telegram detenido")


def main():
    if "--telegram-only" in sys.argv or "--headless" in sys.argv:
        run_telegram_only()
        return

    setup_logger("jarvis", level=logging.INFO)
    logger.info("Iniciando JARVIS...")

    if not validate_env():
        sys.exit(1)

    load_config()
    logger.info("Configuracion cargada")

    mem_enabled = get_setting("memory", "semantic_search", False)
    init_semantic_search(enabled=mem_enabled)

    start_session()
    logger.info("Sesion iniciada")

    from core.jarvis import JARVIS
    from gui.app import JarvisGUI

    jarvis = JARVIS()
    app = JarvisGUI()

    def on_state(state):
        app.set_state(state)

    def on_message(role, text):
        app.add_message(role, text)

    def on_audio_level():
        level = jarvis.get_audio_level()
        app.update_audio_level(level)
        if jarvis.state.value in ("listening", "call"):
            app.after(100, on_audio_level)

    def on_user_message(text):
        jarvis.process_text(text)

    def on_mic_toggle(active):
        if active:
            jarvis.start_listening()
            app.after(100, on_audio_level)
        else:
            jarvis.stop_listening()

    def on_call_toggle(active):
        if active:
            jarvis.start_call()
            app.after(100, on_audio_level)
        else:
            jarvis.stop_call()

    def on_emergency():
        jarvis.emergency_stop()

    def on_call_active(active):
        app.after(0, lambda: app.set_call_active(active))

    def on_confirmation(tool_name, args):
        title, _message = confirmation_request(tool_name, args)
        return jarvis.confirm_by_voice(
            f"Señor, ¿confirma la accion: {title}?",
            listen_timeout=int(get_setting("voice", "confirm_timeout", 10)),
        )

    jarvis.set_callbacks(
        on_state_change=on_state,
        on_message=on_message,
        on_confirmation=on_confirmation,
        on_call_active=on_call_active,
    )
    app.set_state(jarvis.state.value)
    app.set_call_active(jarvis.is_call_active())
    app.on_user_message(on_user_message)
    app.on_mic_toggle(on_mic_toggle)
    app.on_call_toggle(on_call_toggle)
    app.on_emergency(on_emergency)
    app.on_force_process(jarvis.force_process)

    from services import wake_word
    wake_word.start_listening(
        jarvis.toggle_conversation,
        once_callback=jarvis.start_listening,
    )

    # Detector de doble palmada (activa JARVIS con un aplauso)
    clap_enabled = bool(get_setting("voice", "clap_enabled", False))
    if clap_enabled:
        try:
            from services import clap_detector

            if clap_detector.start_clap_listener(jarvis.on_double_clap):
                logger.info("Detector de palmadas activo")
            else:
                logger.info("Detector de palmadas desactivado por config")
        except Exception as e:
            logger.warning("No se pudo iniciar el detector de palmadas: %s", e)

    auto_start = bool(get_setting("voice", "auto_start", True))
    if auto_start:
        logger.info("Modo voz 100%%: iniciando conversacion continua")
        app.after(500, jarvis.start_call)
    else:
        logger.info("JARVIS en reposo. Ctrl+Alt+Shift+J o bandeja para una consulta")

    telegram_enabled = bool(get_setting("telegram", "enabled", True))
    if telegram_enabled:
        from services.telegram_bot import start_telegram_bot
        start_telegram_bot()

    def on_event(event_type, message):
        app.after(0, lambda: app.add_message("system", f"[{event_type}] {message}"))

    from core.events import EventMonitor
    monitor = EventMonitor()
    monitor.start(on_event=on_event, interval=60)

    background = "--background" in sys.argv
    tray_commands = queue.Queue()

    def _handle_tray_commands():
        try:
            while True:
                cmd = tray_commands.get_nowait()
                if cmd == "listen":
                    jarvis.start_listening()
                elif cmd == "show":
                    app.deiconify()
                    app.lift()
                    app.focus_force()
                elif cmd == "quit":
                    cleanup()
                    app.destroy()
                    return
        except queue.Empty:
            pass
        app.after(300, _handle_tray_commands)

    def _go_background():
        app.withdraw()
        if get_setting("gui", "tray", True):
            try:
                from gui.tray import start as start_tray
                start_tray(tray_commands)
            except Exception as e:
                logger.warning("Bandeja no disponible: %s", e)
        _handle_tray_commands()

    _cleaned = False

    def cleanup():
        nonlocal _cleaned
        if _cleaned:
            return
        _cleaned = True
        logger.info("Cerrando JARVIS...")
        monitor.stop()
        from services.telegram_bot import stop_telegram_bot
        stop_telegram_bot()
        try:
            from tools.opencode_tools import stop_server as stop_opencode
            stop_opencode()
        except Exception as e:
            logger.warning("No se pudo detener OpenCode: %s", e)
        from services import wake_word
        wake_word.stop_listening()
        try:
            from services import clap_detector

            clap_detector.stop_clap_listener()
        except Exception:
            pass
        try:
            from gui.tray import stop as stop_tray
            stop_tray()
        except Exception:
            pass
        jarvis.shutdown()
        end_current_session()
        try:
            from memory.database import close as close_database
            close_database()
        except Exception as e:
            logger.warning("No se pudo cerrar la base de datos: %s", e)

    atexit.register(cleanup)

    def signal_handler(sig, frame):
        cleanup()
        app.destroy()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    if background:
        app.protocol(
            "WM_DELETE_WINDOW",
            lambda: (app.withdraw(), _handle_tray_commands()),
        )
    else:
        app.protocol("WM_DELETE_WINDOW", lambda: (cleanup(), app.destroy()))

    logger.info("JARVIS listo. GUI abierta.")

    if background:
        app.after(2500, _go_background)

    app.mainloop()


if __name__ == "__main__":
    main()

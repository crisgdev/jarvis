import logging
import threading
from typing import Callable

from config import get_config

logger = logging.getLogger("jarvis.wake_word")

_listener_thread: threading.Thread | None = None
_running = False
_callback: Callable | None = None
_once_callback: Callable | None = None


def _get_hotkey() -> str:
    cfg = get_config().get("voice", {})
    return cfg.get("activation_key", "ctrl+shift+j")


def _get_hotkey_once() -> str:
    cfg = get_config().get("voice", {})
    return cfg.get("once_key", "ctrl+alt+shift+j")


def start_listening(callback: Callable, once_callback: Callable | None = None):
    global _listener_thread, _running, _callback, _once_callback

    if _running:
        logger.warning("Ya esta escuchando")
        return

    _callback = callback
    _once_callback = once_callback
    _running = True
    hotkey = _get_hotkey()
    hotkey_once = _get_hotkey_once()

    def _listen():
        try:
            import keyboard

            logger.info("Escuchando hotkeys: %s (toggle) y %s (una consulta)", hotkey, hotkey_once)
            keyboard.add_hotkey(hotkey, _on_trigger)
            if hotkey_once and hotkey_once != hotkey:
                keyboard.add_hotkey(hotkey_once, _on_trigger_once)
            keyboard.wait()
        except ImportError:
            logger.warning("Libreria 'keyboard' no instalada. Instala con: pip install keyboard")
            logger.info("Modo fallback: presiona Enter para activar")
            while _running:
                input()
                if _running and _callback:
                    _callback()
        except Exception as e:
            logger.error("Error en listener: %s", e)

    _listener_thread = threading.Thread(target=_listen, daemon=True)
    _listener_thread.start()
    logger.info("Wake word listener iniciado")


def _on_trigger():
    logger.info("Hotkey detectada!")
    if _callback:
        _callback()


def _on_trigger_once():
    logger.info("Hotkey una consulta detectada!")
    if _once_callback:
        _once_callback()


def stop_listening():
    global _running
    _running = False
    try:
        import keyboard
        keyboard.unhook_all()
    except Exception:
        pass
    logger.info("Wake word listener detenido")


def is_listening() -> bool:
    return _running

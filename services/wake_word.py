import logging
import threading
from typing import Callable

from config import get_config

logger = logging.getLogger("jarvis.wake_word")

_listener_thread: threading.Thread | None = None
_running = False
_once_callback: Callable | None = None


def _get_hotkey() -> str:
    """Unico atajo de activacion: una consulta por pulsacion."""
    cfg = get_config().get("voice", {})
    return cfg.get("once_key", "ctrl+alt+shift+j")


def start_listening(once_callback: Callable):
    global _listener_thread, _running, _once_callback

    if _running:
        logger.warning("Ya esta escuchando")
        return

    _once_callback = once_callback
    _running = True
    hotkey = _get_hotkey()

    def _listen():
        try:
            import keyboard

            logger.info("Escuchando hotkey: %s (una consulta)", hotkey)
            keyboard.add_hotkey(hotkey, _on_trigger)
            keyboard.wait()
        except ImportError:
            logger.warning("Libreria 'keyboard' no instalada. Instala con: pip install keyboard")
            logger.info("Modo fallback: presiona Enter para activar")
            while _running:
                input()
                if _running:
                    _on_trigger()
        except Exception as e:
            logger.error("Error en listener: %s", e)

    _listener_thread = threading.Thread(target=_listen, daemon=True)
    _listener_thread.start()
    logger.info("Listener de activacion iniciado")


def _on_trigger():
    logger.info("Hotkey detectada!")
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
    logger.info("Listener de activacion detenido")


def is_listening() -> bool:
    return _running

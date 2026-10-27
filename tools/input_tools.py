"""Control del teclado y del raton de la PC.

Usa pyautogui. Convierte lo que dice el usuario ("presiona la i", "escribe
hola", "haz scroll hacia abajo") en pulsaciones reales.

Notas de seguridad:
- FAILSAFE queda activo: si el puntero del raton llega a la esquina (0,0),
  pyautogui aborta en vez de seguir mandando pulsaciones a ciegas.
- type_text nunca pulsa Enter, asi que no puede ejecutar comandos.
"""

import logging
import time

from brain.tools_executor import register_tool
from config import get_config
from tools.window_tools import _activate_window

logger = logging.getLogger("jarvis.tools.input")

try:
    import pyautogui
except ImportError:  # pragma: no cover
    pyautogui = None

try:
    import pyperclip
except ImportError:  # pragma: no cover
    pyperclip = None


pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05

# Traducciones de nombres de tecla a los que usa pyautogui.
KEY_ALIASES = {
    "intro": "enter",
    "entrar": "enter",
    "retorno": "enter",
    "return": "enter",
    "esc": "escape",
    "escapar": "escape",
    "espacio": "space",
    "borrar": "backspace",
    "retroceso": "backspace",
    "supr": "delete",
    "eliminar": "delete",
    "tabulador": "tab",
    "mayus": "capslock",
    "mayusculas": "capslock",
    "flecha arriba": "up",
    "flecha abajo": "down",
    "flecha izquierda": "left",
    "flecha derecha": "right",
    "arriba": "up",
    "abajo": "down",
    "izquierda": "left",
    "derecha": "right",
    "mas": "add",
    "mas igual": "add",
    "guion": "-",
    "guion bajo": "_",
    "asterisco": "*",
    "coma": ",",
    "punto": ".",
    "punto y coma": ";",
    "barra": "/",
    "barra invertida": "\\",
    "tilde": "~",
    "acento grave": "`",
    "ctrl": "ctrl",
    "control": "ctrl",
    "mayuscula": "shift",
    "shift": "shift",
    "alt": "alt",
    "opcion": "alt",
    "win": "win",
    "windows": "win",
    "meta": "win",
    "command": "win",
}

# Modificadores que pyautogui acepta en hotkey().
_MODIFIERS = {"ctrl", "shift", "alt", "win", "command", "option"}

_MOUSE_BUTTONS = {"left", "right", "middle"}
_SCROLL_DIRECTIONS = {"up", "down", "left", "right"}


def _require_pyautogui():
    if pyautogui is None:
        raise RuntimeError(
            "pyautogui no esta instalado (pip install pyautogui)"
        )
    return pyautogui


def _input_settings() -> dict:
    return get_config().get("input", {}) or {}


def parse_combo(key: str) -> list[str]:
    """Convierte 'ctrl+shift+j' en ['ctrl', 'shift', 'j'].

    Acepta una sola tecla ('i'), combinaciones ('ctrl+c') y el caso raro
    de la tecla '+' ('ctrl++').
    """
    raw = (key or "").strip().lower()
    if not raw:
        raise ValueError("No se indico ninguna tecla.")

    if raw in ("+", "plus", "mas"):
        return ["add"]

    if raw.endswith("++"):
        head = raw[:-2]
        parts = [p.strip() for p in head.split("+") if p.strip()] if head else []
        return [_resolve_key(p) for p in parts] + ["add"]

    parts = [p.strip() for p in raw.split("+") if p.strip()]
    if not parts:
        raise ValueError(f"Tecla invalida: {key!r}")
    return [_resolve_key(p) for p in parts]


def _resolve_key(part: str) -> str:
    part = part.strip()
    if not part:
        raise ValueError("Tecla vacia en la combinacion.")
    return KEY_ALIASES.get(part, part)


def _is_ascii(text: str) -> bool:
    try:
        text.encode("ascii")
        return True
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False


def _focus_window(window: str | None) -> str | None:
    """Activa la ventana indicada. Devuelve el titulo real o None."""
    if not window or not window.strip():
        return None
    result = _activate_window(window.strip())
    if result.get("status") == "success":
        return result.get("title")
    return None


def _guard_fail_safe(func, *args, **kwargs):
    """Ejecuta una accion de pyautogui manejando el FAILSAFE."""
    module = _require_pyautogui()
    try:
        return func(*args, **kwargs)
    except module.FailSafeException:
        logger.warning("FAILSAFE activado: el raton esta en la esquina (0,0)")
        raise RuntimeError(
            "Accion cancelada: el puntero del raton esta en la esquina "
            "superior izquierda (moverlo y reintentar)."
        )
    except module.PyAutoGUIException as e:
        raise RuntimeError(f"No se pudo ejecutar la accion: {e}")


def _validate_combo(combo: list[str]) -> None:
    """Comprueba que las teclas existen antes de mandarlas."""
    module = _require_pyautogui()
    valid = getattr(module, "KEYBOARD_KEYS", [])
    for part in combo:
        if part in _MODIFIERS:
            continue
        if valid and part not in valid:
            raise ValueError(
                f"Tecla desconocida: '{part}'. "
                "Ejemplos validos: i, enter, escape, space, tab, flechas, f1-f24."
            )


@register_tool("press_key")
def _press_key(key: str, presses: int = 1, window: str = None) -> dict:
    """Pulsa una tecla o una combinacion de teclas."""
    try:
        combo = parse_combo(key)
        _validate_combo(combo)
        presses = max(1, int(presses or 1))
        focused = _focus_window(window)
        module = _require_pyautogui()

        if len(combo) == 1:
            _guard_fail_safe(module.press, combo[0], presses=presses)
            action = f"pulsaste la tecla '{combo[0]}'"
        else:
            for _ in range(presses):
                _guard_fail_safe(module.hotkey, *combo)
            action = f"pulsaste '{'+'.join(combo)}'"

        target = f" en '{focused}'" if focused else ""
        logger.info("Tecla: %s%s", "+".join(combo), target)
        return {
            "status": "success",
            "keys": combo,
            "message": f"Listo, {action}{target}.",
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"No se pudo pulsar la tecla: {e}"}


@register_tool("type_text")
def _type_text(text: str, window: str = None) -> dict:
    """Escribe un texto en la ventana enfocada."""
    if not text:
        return {"error": "No hay texto para escribir."}
    try:
        focused = _focus_window(window)
        delay = float(_input_settings().get("type_delay", 0.02))
        module = _require_pyautogui()

        if _is_ascii(text):
            _guard_fail_safe(module.write, text, interval=delay)
            method = "teclado"
        else:
            # Con acentos, ñ o emoji: pyautogui.write no puede, asi que
            # se usa el portapapeles y un ctrl+v (y se restaura despues).
            if pyperclip is None:
                return {
                    "error": "No se puede escribir ese texto (necesita pyperclip)."
                }
            saved = None
            try:
                saved = pyperclip.paste()
            except Exception:
                saved = None
            pyperclip.copy(text)
            _guard_fail_safe(module.hotkey, "ctrl", "v")
            time.sleep(0.2)
            if saved is not None:
                try:
                    pyperclip.copy(saved)
                except Exception:
                    pass
            method = "portapapeles"

        target = f" en '{focused}'" if focused else ""
        logger.info("Texto escrito (%d chars)%s", len(text), target)
        return {
            "status": "success",
            "length": len(text),
            "method": method,
            "message": f"Listo, escribi {len(text)} caracteres{target}.",
        }
    except ValueError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"No se pudo escribir el texto: {e}"}


@register_tool("click")
def _click(x: int = None, y: int = None, button: str = "left", clicks: int = 1,
           window: str = None) -> dict:
    """Haz un clic del raton, en una posicion o donde este el puntero."""
    try:
        button = (button or "left").strip().lower()
        if button not in _MOUSE_BUTTONS:
            return {"error": f"Boton invalido: {button}. Usa left, right o middle."}
        clicks = max(1, int(clicks or 1))
        focused = _focus_window(window)
        module = _require_pyautogui()

        if x is not None and y is not None:
            _guard_fail_safe(module.click, int(x), int(y), button=button, clicks=clicks)
            where = f"({x}, {y})"
        else:
            _guard_fail_safe(module.click, button=button, clicks=clicks)
            where = "donde estaba el puntero"

        target = f" en '{focused}'" if focused else ""
        logger.info("Clic %s%s", where, target)
        return {
            "status": "success",
            "position": [x, y] if x is not None and y is not None else None,
            "message": f"Listo, hice clic {where}{target}.",
        }
    except Exception as e:
        return {"error": f"No se pudo hacer clic: {e}"}


@register_tool("scroll")
def _scroll(direction: str = "down", amount: int = 3) -> dict:
    """Haz scroll con la rueda del raton."""
    try:
        direction = (direction or "down").strip().lower()
        if direction not in _SCROLL_DIRECTIONS:
            return {
                "error": f"Direccion invalida: {direction}. Usa up, down, left o right."
            }
        amount = max(1, int(amount or 1))
        module = _require_pyautogui()

        if direction in ("up", "down"):
            clicks = amount if direction == "up" else -amount
            _guard_fail_safe(module.scroll, clicks)
        else:
            clicks = amount if direction == "right" else -amount
            _guard_fail_safe(module.hscroll, clicks)

        logger.info("Scroll %s x%d", direction, amount)
        return {
            "status": "success",
            "direction": direction,
            "amount": amount,
            "message": f"Listo, hice scroll {direction} {amount} vez/veces.",
        }
    except Exception as e:
        return {"error": f"No se pudo hacer scroll: {e}"}


@register_tool("move_mouse")
def _move_mouse(x: int, y: int) -> dict:
    """Mueve el puntero del raton a una posicion."""
    try:
        module = _require_pyautogui()
        _guard_fail_safe(module.moveTo, int(x), int(y))
        logger.info("Raton movido a (%s, %s)", x, y)
        return {
            "status": "success",
            "position": [int(x), int(y)],
            "message": f"Listo, movi el raton a ({x}, {y}).",
        }
    except Exception as e:
        return {"error": f"No se pudo mover el raton: {e}"}


@register_tool("get_mouse_position")
def _get_mouse_position() -> dict:
    """Devuelve la posicion actual del puntero del raton."""
    try:
        module = _require_pyautogui()
        pos = module.position()
        return {
            "x": int(pos[0]),
            "y": int(pos[1]),
            "screen": list(module.size()),
        }
    except Exception as e:
        return {"error": f"No se pudo leer la posicion del raton: {e}"}

"""Gestion de ventanas de Windows: listar, activar y cerrar.

Se apoya en pygetwindow, que en Windows usa ctypes puro (no necesita pywin32).
"""

import ctypes
import logging

from brain.tools_executor import register_tool

logger = logging.getLogger("jarvis.tools.window")

try:
    import pygetwindow as gw
except ImportError:  # pragma: no cover
    gw = None


WM_CLOSE = 0x0010
SW_RESTORE = 9
SW_MINIMIZE = 6
SW_MAXIMIZE = 3

# Teclas que JARVIS ignora al listar ventanas (ruido del sistema).
_IGNORED_TITLES = {
    "",
    "Program Manager",
    "Windows Input Experience",
    "Microsoft Text Input Application",
    "Search",
    "SysFloatingPopup",
    "Windows.UI.Core.CoreWindow",
    "Shell_TrayWnd",
}


def _require_gw():
    if gw is None:
        raise RuntimeError(
            "pygetwindow no esta instalado (pip install pyautogui)"
        )
    return gw


def _visible_windows():
    """Ventanas visibles con titulo, en orden: la activa va primera."""
    module = _require_gw()
    windows = []
    for win in module.getAllWindows():
        try:
            title = (win.title or "").strip()
        except Exception:
            continue
        if not title or title in _IGNORED_TITLES:
            continue
        try:
            active = bool(win.isActive)
        except Exception:
            active = False
        windows.append((active, win, title))
    # la ventana activa primero: es la que el usuario ve
    windows.sort(key=lambda item: item[0], reverse=True)
    return windows


def _describe(win, title: str) -> dict:
    try:
        position = [win.left, win.top]
        size = [win.width, win.height]
    except Exception:
        position, size = [0, 0], [0, 0]
    try:
        active = bool(win.isActive)
    except Exception:
        active = False
    return {
        "title": title,
        "active": active,
        "position": position,
        "size": size,
    }


def find_window(title: str, exact: bool = False):
    """Busca la ventana que mejor coincide con `title`."""
    module = _require_gw()
    if not title or not title.strip():
        return None
    title = title.strip()

    candidates = []
    for active, win, win_title in _visible_windows():
        if exact:
            if win_title.lower() == title.lower():
                candidates.append((0 if active else 1, win, win_title))
        else:
            low = win_title.lower()
            needle = title.lower()
            if needle in low:
                # coincidencias exactas pesan mas que parciales
                exactness = 0 if low == needle else 1
                candidates.append((exactness + (0 if active else 2), win, win_title))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates[0][2]


def _force_foreground(hwnd: int) -> bool:
    """Roba el foco de verdad.

    Windows no deja que una app en background llame a SetForegroundWindow.
    El truco clasico es simular una pulsacion de ALT: el sistema libera el
    foco al ver que el usuario (nuestro proceso) esta "presionando" una
    tecla de modificacion.
    """
    user32 = ctypes.windll.user32
    VK_MENU = 0x12
    ALT_DOWN = 0x0001
    ALT_UP = 0x0002
    try:
        user32.keybd_event(VK_MENU, 0, ALT_DOWN, 0)
        result = user32.SetForegroundWindow(hwnd)
        user32.keybd_event(VK_MENU, 0, ALT_UP, 0)
        return bool(result)
    except Exception as e:
        logger.warning("No se pudo forzar el foco: %s", e)
        return False


@register_tool("list_windows")
def _list_windows(limit: int = 25) -> dict:
    """Lista las ventanas abiertas ahora mismo en la PC."""
    try:
        windows = _visible_windows()
    except Exception as e:
        return {"error": f"No se pudieron listar las ventanas: {e}"}

    described = [_describe(win, title) for _, win, title in windows]
    described = described[: max(1, int(limit or 25))]
    if not described:
        return {"windows": [], "message": "No hay ventanas visibles."}
    return {
        "windows": described,
        "count": len(described),
        "active": next(
            (d["title"] for d in described if d["active"]),
            described[0]["title"],
        ),
    }


@register_tool("get_active_window")
def _get_active_window() -> dict:
    """Devuelve la ventana que esta enfocada ahora mismo."""
    try:
        module = _require_gw()
        win = module.getActiveWindow()
        if win is None:
            return {"error": "No hay ninguna ventana activa."}
        title = (win.title or "").strip()
        if not title:
            return {"error": "La ventana activa no tiene titulo."}
        return _describe(win, title)
    except Exception as e:
        return {"error": f"No se pudo leer la ventana activa: {e}"}


@register_tool("activate_window")
def _activate_window(title: str) -> dict:
    """Pone una ventana en primer plano (le da el foco)."""
    try:
        found = find_window(title)
        if not found:
            return {"error": f"No encontre ninguna ventana que contenga '{title}'."}
        win, real_title = found
        try:
            win.restore()
        except Exception:
            pass
        ok = False
        try:
            win.activate()
            ok = True
        except Exception:
            ok = _force_foreground(win._hWnd)
        if not ok:
            _force_foreground(win._hWnd)
        logger.info("Ventana activada: %s", real_title)
        return {
            "status": "success",
            "title": real_title,
            "message": f"Ventana activada: {real_title}",
        }
    except Exception as e:
        return {"error": f"No se pudo activar la ventana: {e}"}


@register_tool("close_window")
def _close_window(title: str = None) -> dict:
    """Cierra una ventana por titulo, o la ventana enfocada si no se indica."""
    try:
        if title and title.strip():
            found = find_window(title)
            if not found:
                return {"error": f"No encontre ninguna ventana que contenga '{title}'."}
            win, real_title = found
        else:
            module = _require_gw()
            win = module.getActiveWindow()
            if win is None:
                return {"error": "No hay ninguna ventana activa para cerrar."}
            real_title = (win.title or "").strip() or "(sin titulo)"

        win.close()
        logger.info("Ventana cerrada: %s", real_title)
        return {
            "status": "success",
            "title": real_title,
            "message": f"Ventana cerrada: {real_title}",
        }
    except Exception as e:
        return {"error": f"No se pudo cerrar la ventana: {e}"}


@register_tool("minimize_window")
def _minimize_window(title: str = None) -> dict:
    """Minimiza una ventana por titulo, o la ventana enfocada."""
    try:
        if title and title.strip():
            found = find_window(title)
            if not found:
                return {"error": f"No encontre ninguna ventana que contenga '{title}'."}
            win, real_title = found
        else:
            module = _require_gw()
            win = module.getActiveWindow()
            if win is None:
                return {"error": "No hay ninguna ventana activa."}
            real_title = (win.title or "").strip() or "(sin titulo)"

        win.minimize()
        return {
            "status": "success",
            "title": real_title,
            "message": f"Ventana minimizada: {real_title}",
        }
    except Exception as e:
        return {"error": f"No se pudo minimizar la ventana: {e}"}


@register_tool("maximize_window")
def _maximize_window(title: str = None) -> dict:
    """Maximiza una ventana por titulo, o la ventana enfocada."""
    try:
        if title and title.strip():
            found = find_window(title)
            if not found:
                return {"error": f"No encontre ninguna ventana que contenga '{title}'."}
            win, real_title = found
        else:
            module = _require_gw()
            win = module.getActiveWindow()
            if win is None:
                return {"error": "No hay ninguna ventana activa."}
            real_title = (win.title or "").strip() or "(sin titulo)"

        win.maximize()
        return {
            "status": "success",
            "title": real_title,
            "message": f"Ventana maximizada: {real_title}",
        }
    except Exception as e:
        return {"error": f"No se pudo maximizar la ventana: {e}"}

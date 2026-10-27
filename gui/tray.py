"""Icono en la bandeja del sistema (pystray).

Convierte comandos de la bandeja a una cola que la GUI consume en su propio
hilo (tkinter no es thread-safe: nada toca la ventana desde aqui).
"""

import logging
import queue

import pystray
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger("jarvis.tray")

_icon = None


def _build_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (13, 17, 23, 255))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 6, 58, 58], radius=14, fill=(46, 204, 113, 255))
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except Exception:
        font = ImageFont.load_default()
    d.text((20, 13), "J", font=font, fill=(13, 17, 23, 255))
    return img


def start(commands: queue.Queue):
    """Despliega el icono. Los comandos ('listen'/'show'/'quit') van a `commands`."""
    global _icon
    if _icon is not None:
        return
    _icon = pystray.Icon(
        "jarvis",
        _build_image(),
        "JARVIS - Asistente Personal",
        menu=pystray.Menu(
            pystray.MenuItem("Iniciar escucha", lambda i, n: commands.put("listen")),
            pystray.MenuItem(
                "Abrir ventana", lambda i, n: commands.put("show"), default=True
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", lambda i, n: commands.put("quit")),
        ),
    )
    try:
        _icon.run_detached()
        logger.info("Icono de bandeja iniciado")
    except Exception as e:
        logger.warning("No se pudo iniciar la bandeja: %s", e)
        _icon = None


def stop():
    global _icon
    if _icon is not None:
        try:
            _icon.stop()
        except Exception:
            pass
        _icon = None
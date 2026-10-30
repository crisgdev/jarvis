"""Paleta y tipografia compartidas por la GUI de JARVIS.

Todo el fondo de la interfaz usa un unico color (BG) para que la ventana se
vea como una sola superficie; los acentos son celeste (etiquetas), verde
(texto del usuario / tareas completadas), naranja (tarea en curso) y blanco.

Las fuentes se crean con `font(size, weight)` y quedan registradas, de modo
que `set_scale()` puede agrandarlas o achicarlas EN CALIENTE cuando cambia el
tamano de la ventana (la GUI llama a `scale_for_width(width)` al redimensionar).
"""

import customtkinter as ctk

BG = "#0a0a1a"
CELESTE = "#57c7ff"
GREEN = "#2ecc71"
ORANGE = "#f39c12"
RED = "#e74c3c"
WHITE = "#e6edf3"
MUTED = "#6b7c93"
BORDER = "#1b3a52"

FONT = "Consolas"

# Ancho de ventana de referencia: a 900 px la escala es 1.0
BASE_WIDTH = 900
MIN_SCALE = 0.9
MAX_SCALE = 1.45

_scale = 1.0
_fonts: list[tuple] = []
_cache: dict = {}


def hex_to_rgb(color: str) -> tuple:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb: tuple) -> str:
    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def lerp_color(start: str, end: str, t: float) -> str:
    """Interpola entre dos colores hex (t=0 -> start, t=1 -> end)."""
    t = max(0.0, min(1.0, t))
    c1 = hex_to_rgb(start)
    c2 = hex_to_rgb(end)
    return rgb_to_hex(tuple(a + (b - a) * t for a, b in zip(c1, c2)))


def font(size, weight: str = "normal"):
    """Fuente registrada (y cacheada) que se reescala con la ventana."""
    key = (float(size), weight)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    actual = ctk.CTkFont(
        family=FONT, size=max(8, int(round(key[0] * _scale))), weight=weight
    )
    _cache[key] = actual
    _fonts.append((actual, key[0], weight))
    return actual


def scale() -> float:
    return _scale


def px(value: float) -> int:
    """Convierte una medida de diseno a pixeles segun la escala actual."""
    return int(round(value * _scale))


def scale_for_width(width: int) -> float:
    return max(MIN_SCALE, min(MAX_SCALE, float(width) / BASE_WIDTH))


def set_scale(new_scale: float) -> bool:
    """Reescala todas las fuentes registradas. True si cambio de verdad."""
    global _scale
    new_scale = max(MIN_SCALE, min(MAX_SCALE, float(new_scale)))
    if abs(new_scale - _scale) < 0.02:
        return False
    _scale = new_scale
    for actual, base_size, weight in _fonts:
        try:
            actual.configure(size=max(8, int(round(base_size * _scale))))
        except Exception:
            pass
    return True

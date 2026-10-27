"""Captura de pantalla de la PC.

La imagen se guarda en disco y la tool devuelve su ruta. El cerebro
(brain/gemini.py) lee esa ruta y adjunta la imagen REAL al modelo, para que
Gemini pueda ver lo que hay en pantalla y describirlo.
"""

import datetime
import logging
import os
from pathlib import Path

from brain.tools_executor import register_tool
from config import get_config

logger = logging.getLogger("jarvis.tools.screen")

try:
    from PIL import Image, ImageGrab
except ImportError:  # pragma: no cover
    Image = None
    ImageGrab = None


def _screen_settings() -> dict:
    return get_config().get("input", {}) or {}


def parse_region(region: str | None):
    """Interpreta 'x,y,w,h' o 'full'. Devuelve None para toda la pantalla."""
    if not region or not str(region).strip():
        return None
    raw = str(region).strip().lower()
    if raw in ("full", "all", "todo", "completa", "pantalla"):
        return None
    parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
    if len(parts) != 4:
        raise ValueError(
            "Region invalida. Usa 'x,y,w,h' (por ejemplo '0,0,800,600') o 'full'."
        )
    try:
        x, y, w, h = (int(float(p)) for p in parts)
    except ValueError:
        raise ValueError(
            "Region invalida. Usa 'x,y,w,h' (por ejemplo '0,0,800,600') o 'full'."
        )
    if w <= 0 or h <= 0:
        raise ValueError("El ancho y el alto de la region deben ser positivos.")
    return (x, y, w, h)


def _output_dir() -> Path:
    cfg = _screen_settings()
    raw = cfg.get("screenshot_dir", "logs/screenshots")
    path = Path(raw)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def _prepare_image(image, max_width: int | None):
    """Redimensiona la captura para no gastar tokens de mas."""
    cfg = _screen_settings()
    if max_width is None:
        max_width = int(cfg.get("max_image_width", 1280) or 1280)
    quality = int(cfg.get("jpeg_quality", 75) or 75)

    image = image.convert("RGB")
    if max_width and image.width > max_width:
        ratio = max_width / image.width
        new_size = (max_width, max(1, int(image.height * ratio)))
        image = image.resize(new_size)
    return image, quality


def _prune_old(out_dir: Path, keep: int = 50):
    """Borra las capturas viejas para que no se llene el disco."""
    try:
        shots = sorted(
            out_dir.glob("screen_*.jpg"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for old in shots[keep:]:
            old.unlink(missing_ok=True)
    except Exception as e:
        logger.warning("No se pudieron limpiar capturas viejas: %s", e)


@register_tool("take_screenshot")
def _take_screenshot(region: str = None, max_width: int = None) -> dict:
    """Captura la pantalla (o una region) de la PC."""
    if ImageGrab is None:
        return {"error": "Pillow no esta instalado (pip install Pillow)"}

    try:
        box = parse_region(region)
    except ValueError as e:
        return {"error": str(e)}

    try:
        image = ImageGrab.grab(all_screens=True)
        if box:
            x, y, w, h = box
            image = image.crop((x, y, x + w, y + h))

        original_size = image.size
        image, quality = _prepare_image(image, max_width)

        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        out_dir = _output_dir()
        path = out_dir / f"screen_{stamp}.jpg"
        image.save(path, format="JPEG", quality=quality)
        _prune_old(out_dir)

        logger.info("Captura guardada: %s (%s)", path, image.size)
        return {
            "status": "success",
            "image_path": str(path),
            "size": list(image.size),
            "original_size": list(original_size),
            "region": list(box) if box else "full",
            "message": f"Captura de pantalla tomada ({image.size[0]}x{image.size[1]}).",
        }
    except Exception as e:
        logger.error("Error capturando pantalla: %s", e)
        return {"error": f"No se pudo capturar la pantalla: {e}"}

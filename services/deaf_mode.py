"""Modo sordo: JARVIS deja de escuchar hasta que se lo pidan.

Por que existe
--------------
Con la laptop sonando (un video, musica) el microfono captura el audio del
altavoz: el detector de doble palmada se despierta con los aplausos del video
y el STT transcribe el video como si fuera el usuario. En vez de intentar
separar ese eco (fragil y caro), el dueno puede apagar la escucha del todo y
volver a encenderla cuando quiera.

Que se apaga
------------
* detector de doble palmada (`services.clap_detector.pause`)
* atajo Ctrl+Alt+Shift+J (se ignora en `JARVIS.start_listening`)
* push-to-talk (ESPACIO / orbe): la GUI no inicia la grabacion
* interrupcion mientras JARVIS habla (tambien es una grabacion)
* modo llamada y auto_start

Que sigue funcionando
---------------------
* Telegram: es la via principal para salir del modo sordo
* el TTS: JARVIS puede confirmar con voz que quedo sordo
* el teclado de la GUI: tocar el orbe o mantener ESPACIO vuelve a escuchar
  (es una accion deliberada, no audio)

Persistencia
------------
El estado se guarda en `logs/deaf_mode.json` para que un reinicio no lo
reactive por accidente (si estabas viendo un video, seguiria sordo). Para
salir sin Telegram: borra ese archivo o pon `"deaf": false` y reinicia.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import datetime
from pathlib import Path

from config import BASE_DIR, get_setting

logger = logging.getLogger("jarvis.deaf")

_STATE_PATH = Path(BASE_DIR) / "logs" / "deaf_mode.json"

_lock = threading.Lock()
_deaf = False
_since = ""
_source = ""
_listeners: list = []


# ---------------------------------------------------------------------------
# Frases que activan / desactivan el modo sordo
# ---------------------------------------------------------------------------
def _norm(text: str) -> str:
    """Minusculas, sin acentos y sin puntuacion (como habla el STT)."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("ñ", "n")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_ON_PATTERNS = [
    r"\bmodo sordo\b",
    r"\bno (me )?escuches\b",
    r"\bdeja de (escuchar|escucharme|oir|oirme)\b",
    r"\bno (me )?oigas\b",
    r"\bapaga (el|tu|la) (microfono|micro)\b",
    r"\bdesactiva (el|la) (microfono|escucha)\b",
]

_OFF_PATTERNS = [
    r"\bdesactiva el modo sordo\b",
    r"\bquita el modo sordo\b",
    r"\bsal del modo sordo\b",
    r"\bmodo sordo (off|desactivado|apagado)\b",
    r"\bvuelve a escuchar(me)?\b",
    r"\bya (puedes |me puedes )?escuchar(me)?\b",
    r"\bactiva (la )?escucha\b",
    r"\bescuchame( de nuevo)?\b",
    r"\bmodo normal\b",
]

_ON_RE = re.compile("|".join(_ON_PATTERNS))
_OFF_RE = re.compile("|".join(_OFF_PATTERNS))


def match_command(text: str) -> str | None:
    """Devuelve "on", "off" o None segun lo que pida el texto.

    Se mira primero OFF: "quita el modo sordo" o "modo sordo off" tambien
    contienen "modo sordo", y la intencion correcta es desactivar.
    """
    norm = _norm(text)
    if not norm:
        return None
    if _OFF_RE.search(norm):
        return "off"
    if _ON_RE.search(norm):
        return "on"
    return None


def is_on_command(text: str) -> bool:
    return match_command(text) == "on"


def is_off_command(text: str) -> bool:
    return match_command(text) == "off"


# ---------------------------------------------------------------------------
# Persistencia
# ---------------------------------------------------------------------------
def _read_state() -> bool | None:
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return bool(data.get("deaf"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        logger.warning("No se pudo leer %s: %s", _STATE_PATH, e)
        return None


def _write_state(value: bool, source: str):
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "deaf": bool(value),
                    "since": datetime.now().isoformat(timespec="seconds"),
                    "source": source or "manual",
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except OSError as e:
        logger.warning("No se pudo guardar el modo sordo: %s", e)


def _initial_state() -> bool:
    saved = _read_state()
    if saved is not None:
        return saved
    return bool(get_setting("voice", "deaf_mode", False))


_deaf = _initial_state()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
def is_deaf() -> bool:
    return _deaf


def since() -> str:
    return _since


def source() -> str:
    return _source


def add_listener(callback):
    """Registra `callback(deaf: bool)`, se llama en cada cambio de estado."""
    if callback and callback not in _listeners:
        _listeners.append(callback)


def set_deaf(value: bool, source_name: str = "manual") -> bool:
    global _deaf, _since, _source
    value = bool(value)
    with _lock:
        if value == _deaf:
            return _deaf
        _deaf = value
        _since = datetime.now().isoformat(timespec="seconds")
        _source = source_name or "manual"
        _write_state(value, _source)

    logger.info(
        "Modo sordo %s (%s)", "ACTIVADO" if value else "DESACTIVADO", _source
    )
    for callback in list(_listeners):
        try:
            callback(value)
        except Exception as e:
            logger.warning("Error en listener de modo sordo: %s", e)
    return _deaf


def toggle(source_name: str = "manual") -> bool:
    return set_deaf(not _deaf, source_name)


def status_text() -> str:
    if _deaf:
        detail = f" desde {_since} ({_source})" if _since else ""
        return f"activado{detail}"
    return "desactivado"

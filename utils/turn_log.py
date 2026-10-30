"""Registro estructurado de turnos en JSONL para analisis posterior.

Un turno = una linea JSON en `logs/turns.jsonl`. Sirve para responder
preguntas con datos en vez de intuicion:

  * que modelo se uso y si hubo que escalar
  * cuantas iteraciones de tools necesito cada tipo de orden
  * latencia por tier y por pack
  * que temas terminan en error (candidatos a mejorar el prompt o el router)

Cuando haya unos cientos de turnos se puede entrenar un clasificador real
para elegir modelo; mientras tanto esto es el dataset que hoy no existe.

No guarda audio ni capturas: solo el texto de la orden, truncado.
"""

import json
import logging
import threading
import time
from pathlib import Path

from config import get_config

logger = logging.getLogger("jarvis.turnlog")

_lock = threading.Lock()
_MAX_TEXT = 300


def _log_path() -> Path:
    cfg = get_config().get("logging", {})
    raw = cfg.get("turn_log_path") or "logs/turns.jsonl"
    return Path(raw)


def is_enabled() -> bool:
    return bool(get_config().get("logging", {}).get("turn_log", True))


def record(**fields) -> None:
    """Agrega un turno al JSONL. Nunca lanza: el logging no rompe el turno."""
    if not is_enabled():
        return

    entry = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S")}
    entry.update(fields)

    text = entry.get("text")
    if isinstance(text, str) and len(text) > _MAX_TEXT:
        entry["text"] = text[:_MAX_TEXT]

    try:
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(entry, ensure_ascii=False)
        with _lock:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
    except Exception as e:  # pragma: no cover - defensivo
        logger.debug("No se pudo escribir turns.jsonl: %s", e)

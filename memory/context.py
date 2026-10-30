import logging
import time
from datetime import datetime
from typing import Optional

from google.genai import types

import memory.database as _db
from memory.database import (
    create_session,
    end_session,
    save_message,
    get_messages,
    search_messages,
    get_all_messages,
    get_preference,
    set_preference,
    list_projects,
)

logger = logging.getLogger("jarvis.context")

_current_session_id: Optional[str] = None

# ── Presupuesto de contexto ───────────────────────────────────────────────
# Antes el bloque de memoria crecia sin techo: todas las preferencias, todos
# los proyectos activos y 8 notas de 160 caracteres viajaban en CADA llamada a
# Gemini (y son dos llamadas por orden). Ahora hay topes por seccion y un
# presupuesto total, llenado por prioridad.
PREFS_MAX_CHARS = 300
NOTES_MAX_CHARS = 240
NOTES_MAX_CHARS_FULL = 400
PROJECTS_MAX_CHARS = 250
RECENT_MAX_CHARS = 200

# Umbral de notas segun si el turno activo el pack de memoria.
NOTES_LIMIT = 3
NOTES_LIMIT_FULL = 6

_CACHE_TTL = 120.0
_cache: dict = {"key": None, "ts": 0.0, "value": ""}


def start_session(summary: str = None) -> str:
    global _current_session_id
    _current_session_id = create_session(summary)
    logger.info("Sesion iniciada: %s", _current_session_id)
    return _current_session_id


def end_current_session():
    global _current_session_id
    if _current_session_id:
        end_session(_current_session_id)
        logger.info("Sesion terminada: %s", _current_session_id)
        _current_session_id = None


def get_current_session_id() -> Optional[str]:
    return _current_session_id


def save_conversation(role: str, content: str, session_id: str = None):
    sid = session_id or _current_session_id
    if not sid:
        sid = start_session()
    save_message(sid, role, content)


def build_gemini_history(session_id: str = None, max_turns: int = 20) -> list[types.Content]:
    sid = session_id or _current_session_id
    if not sid:
        return []

    # get_messages ya devuelve cronológico (nuevo al final).
    messages = get_messages(sid, limit=max_turns * 2)
    history = []
    for msg in messages:
        role = "user" if msg["role"] == "user" else "model"
        history.append(
            types.Content(
                role=role,
                parts=[types.Part(text=msg["content"])],
            )
        )
    # El ultimo mensaje de la sesion es el 'user' que se está procesando ahora
    # (se guarda antes de llamar a Gemini); si se incluye, quedaria duplicado
    # al reenviarlo como entrada en el nuevo chat.
    if history and history[-1].role == "user":
        history.pop()
    return history


def get_relevant_context(query: str, max_results: int = 5) -> str:
    messages = search_messages(query, limit=max_results)
    if not messages:
        return ""

    parts = []
    for msg in messages:
        ts = msg.get("created_at", "")
        parts.append(f"[{ts}] {msg['role']}: {msg['content'][:200]}")

    return "\n".join(parts)


def _clip(lines: list[str], max_chars: int) -> list[str]:
    """Corta una lista de lineas al presupuesto, de arriba hacia abajo.

    El orden de entrada ya viene por recencia (lo mas nuevo primero), asi que
    recortar por el final preserva lo reciente y descarta lo viejo. Si la
    primera linea sola ya se pasa del presupuesto se recorta esa linea, para
    que el bloque nunca exceda el tope.
    """
    out = []
    used = 0
    for line in lines:
        cost = len(line) + 1
        if used + cost > max_chars:
            if not out:
                room = max(0, max_chars - 3)
                out.append(line[:room] + "...")
            break
        out.append(line)
        used += cost
    return out


def get_user_preferences_summary(max_chars: int = PREFS_MAX_CHARS) -> str:
    from memory.database import list_preferences as db_list_prefs
    prefs = db_list_prefs()
    if not prefs:
        return ""
    lines = _clip([f"  {k}: {v}" for k, v in prefs.items()], max_chars)
    if not lines:
        return ""
    header = "Preferencias del usuario:\n"
    return header + "\n".join(lines)


def get_active_projects_summary(max_chars: int = PROJECTS_MAX_CHARS) -> str:
    projects = list_projects(status="active")
    if not projects:
        return ""
    lines = _clip(
        [f"  - {p['name']}: {p.get('description') or 'sin descripcion'}" for p in projects],
        max_chars,
    )
    if not lines:
        return ""
    return "Proyectos activos:\n" + "\n".join(lines)


def get_notes_summary(limit: int = NOTES_LIMIT, max_chars: int = NOTES_MAX_CHARS) -> str:
    from memory.database import get_recent_notes as db_recent_notes
    notes = db_recent_notes(limit)
    if not notes:
        return ""
    # get_recent_notes ya devuelve de la mas nueva a la mas vieja.
    lines = _clip([f"  - {(n['content'] or '').strip()[:150]}" for n in notes], max_chars)
    if not lines:
        return ""
    return "Datos y notas del usuario:\n" + "\n".join(lines)


def get_recent_user_messages(limit: int = 4, max_chars: int = RECENT_MAX_CHARS) -> str:
    """Devuelve un resumen de los ultimos mensajes del usuario para que el
    modelo no pierda el hilo de la conversacion."""
    sid = _current_session_id
    if not sid:
        return ""
    try:
        messages = get_messages(sid, limit=limit * 2)
    except Exception:
        return ""
    if not messages:
        return ""
    lines = []
    for msg in messages[-limit:]:
        role = "Usuario" if msg["role"] == "user" else "JARVIS"
        text = (msg["content"] or "").strip().replace("\n", " ")
        if len(text) > 140:
            text = text[:140] + "..."
        lines.append(f"  - {role}: {text}")
    if not lines:
        return ""
    lines = _clip(lines, max_chars)
    return (
        "Ultimos mensajes de esta conversacion (usalo para recordar el contexto):\n"
        + "\n".join(lines)
    )


def _memory_block(packs) -> str:
    """Bloque de memoria con cache invalidado por memory_version.

    Se llama 2+ veces por turno (crear el chat y calcular el fingerprint); sin
    cache eran 4-5 consultas SQLite por turno.
    """
    full = packs is None or "memory" in packs
    key = (_db.memory_version(), str(getattr(_db, "_db_path", "")), full)

    now = time.monotonic()
    if _cache["key"] == key and (now - _cache["ts"]) < _CACHE_TTL:
        return _cache["value"]

    parts = []
    prefs = get_user_preferences_summary()
    if prefs:
        parts.append(prefs)

    notes = get_notes_summary(
        limit=NOTES_LIMIT_FULL if full else NOTES_LIMIT,
        max_chars=NOTES_MAX_CHARS_FULL if full else NOTES_MAX_CHARS,
    )
    if notes:
        parts.append(notes)

    if full:
        projects = get_active_projects_summary()
        if projects:
            parts.append(projects)

    value = "\n".join(parts)
    _cache.update({"key": key, "ts": now, "value": value})
    return value


def build_system_context(
    include_time: bool = True,
    include_date: bool = True,
    packs=None,
) -> str:
    """Contexto que se inyecta al system prompt.

    packs: packs activos del turno (brain/router.py). None = todos.
           Con el pack "memory" se incluyen proyectos y mas notas; sin el, el
           bloque se queda en el minimo para no pagar tokens en preguntas
           simples.
    """
    now = datetime.now()
    parts = []
    if include_date:
        parts.append(f"Fecha: {now.strftime('%Y-%m-%d')}")
        parts.append(f"Dia: {now.strftime('%A')}")
    if include_time:
        parts.append(f"Hora: {now.strftime('%H:%M:%S')}")

    memory = _memory_block(packs)
    if memory:
        parts.append(memory)

    return "\n".join(parts)

import logging
from datetime import datetime
from typing import Optional

from google.genai import types

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


def get_user_preferences_summary() -> str:
    from memory.database import list_preferences as db_list_prefs
    prefs = db_list_prefs()
    if not prefs:
        return ""
    lines = [f"  {k}: {v}" for k, v in prefs.items()]
    return "Preferencias del usuario:\n" + "\n".join(lines)


def get_active_projects_summary() -> str:
    projects = list_projects(status="active")
    if not projects:
        return ""
    lines = [f"  - {p['name']}: {p.get('description', 'sin descripcion')}" for p in projects]
    return "Proyectos activos:\n" + "\n".join(lines)


def get_notes_summary(limit: int = 8) -> str:
    from memory.database import get_recent_notes as db_recent_notes
    notes = db_recent_notes(limit)
    if not notes:
        return ""
    lines = [f"  - {n['content'][:160]}" for n in notes]
    return "Datos y notas del usuario:\n" + "\n".join(lines)


def build_system_context(include_time: bool = True) -> str:
    now = datetime.now()
    parts = [
        f"Fecha: {now.strftime('%Y-%m-%d')}",
    ]
    if include_time:
        parts.append(f"Hora: {now.strftime('%H:%M:%S')}")
    parts.append(f"Dia: {now.strftime('%A')}")

    prefs = get_user_preferences_summary()
    if prefs:
        parts.append(prefs)

    projs = get_active_projects_summary()
    if projs:
        parts.append(projs)

    notes = get_notes_summary()
    if notes:
        parts.append(notes)

    return "\n".join(parts)

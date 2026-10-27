import sqlite3
import uuid
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import get_config

logger = logging.getLogger("jarvis.memory")

_db_path: Optional[Path] = None
_connection: Optional[sqlite3.Connection] = None
_db_lock = threading.RLock()


def _locked(func):
    def _wrapper(*args, **kwargs):
        with _db_lock:
            return func(*args, **kwargs)

    return _wrapper


def _get_connection() -> sqlite3.Connection:
    global _connection, _db_path
    with _db_lock:
        if _connection is None:
            config = get_config()
            db_name = config.get("memory", {}).get("db_path", "jarvis_memory.db")
            _db_path = Path(__file__).parent.parent / db_name
            _connection = sqlite3.connect(str(_db_path), check_same_thread=False)
            _connection.row_factory = sqlite3.Row
            _connection.execute("PRAGMA journal_mode=WAL")
            # Checkpoint automatico cada ~500 KB: JARVIS suele terminar con
            # Stop-Process -Force (Reiniciar JARVIS.vbs), asi que el checkpoint
            # de close() no siempre corre y sin esto el -wal crece sin control.
            _connection.execute("PRAGMA wal_autocheckpoint=128")
            _connection.execute("PRAGMA foreign_keys=ON")
            _init_tables()
            logger.info("Base de datos conectada: %s", _db_path)
    return _connection


def _init_tables():
    conn = _connection
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP,
            summary TEXT
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT REFERENCES sessions(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS preferences (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            description TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS project_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER REFERENCES projects(id),
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
        CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role);
        CREATE INDEX IF NOT EXISTS idx_projects_status ON projects(status);
        CREATE INDEX IF NOT EXISTS idx_project_notes_project ON project_notes(project_id);

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_notes_category ON notes(category);
    """)
    conn.commit()


def close():
    global _connection
    if _connection:
        # Compactar el WAL antes de cerrar: sin esto el -wal crece sin limite
        # (se vio en 2.7 MB con una DB de 156 KB) porque nadie hace checkpoint.
        try:
            busy, _, _ = _connection.execute(
                "PRAGMA wal_checkpoint(TRUNCATE)"
            ).fetchone()
            if busy:
                logger.warning("WAL: checkpoint TRUNCATE ocupado (busy=%s)", busy)
        except Exception as e:
            logger.warning("No se pudo compactar el WAL: %s", e)
        _connection.close()
        _connection = None
        logger.info("Base de datos cerrada (WAL compactado)")


# ── Sessions ──

def create_session(summary: str = None) -> str:
    conn = _get_connection()
    session_id = uuid.uuid4().hex[:12]
    conn.execute(
        "INSERT INTO sessions (id, summary) VALUES (?, ?)",
        (session_id, summary),
    )
    conn.commit()
    return session_id


def end_session(session_id: str):
    conn = _get_connection()
    conn.execute(
        "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP WHERE id = ?",
        (session_id,),
    )
    conn.commit()


def get_session(session_id: str) -> Optional[dict]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def list_sessions(limit: int = 10) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM sessions ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


# ── Messages ──

def save_message(session_id: str, role: str, content: str) -> int:
    conn = _get_connection()
    cursor = conn.execute(
        "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
        (session_id, role, content),
    )
    conn.commit()
    return cursor.lastrowid


def get_messages(session_id: str, limit: int = 50) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (session_id, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_all_messages(limit: int = 100) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM messages ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def search_messages(query: str, limit: int = 20) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM messages WHERE content LIKE ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (f"%{query}%", limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Preferences ──

def set_preference(key: str, value: str):
    conn = _get_connection()
    conn.execute(
        "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP) "
        "ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP",
        (key, value, value),
    )
    conn.commit()


def get_preference(key: str, default: str = None) -> Optional[str]:
    conn = _get_connection()
    row = conn.execute("SELECT value FROM preferences WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def list_preferences() -> dict[str, str]:
    conn = _get_connection()
    rows = conn.execute("SELECT key, value FROM preferences").fetchall()
    return {r["key"]: r["value"] for r in rows}


def delete_preference(key: str):
    conn = _get_connection()
    conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
    conn.commit()


# ── Projects ──

def create_project(name: str, description: str = "") -> int:
    conn = _get_connection()
    cursor = conn.execute(
        "INSERT INTO projects (name, description) VALUES (?, ?)",
        (name, description),
    )
    conn.commit()
    return cursor.lastrowid


def get_project(name: str) -> Optional[dict]:
    conn = _get_connection()
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (name,)).fetchone()
    if not row:
        return None
    project = dict(row)
    notes = conn.execute(
        "SELECT * FROM project_notes WHERE project_id = ? ORDER BY created_at, id",
        (project["id"],),
    ).fetchall()
    project["notes"] = [dict(n) for n in notes]
    return project


def list_projects(status: str = None) -> list[dict]:
    conn = _get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC, id DESC",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC, id DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def update_project_status(name: str, status: str):
    conn = _get_connection()
    conn.execute(
        "UPDATE projects SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE name = ?",
        (status, name),
    )
    conn.commit()


def delete_project(name: str):
    conn = _get_connection()
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute("DELETE FROM project_notes WHERE project_id = ?", (row["id"],))
        conn.execute("DELETE FROM projects WHERE id = ?", (row["id"],))
        conn.commit()


# ── Project Notes ──

def add_project_note(project_name: str, content: str) -> int:
    conn = _get_connection()
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project_name,)).fetchone()
    if not row:
        raise ValueError(f"Proyecto '{project_name}' no encontrado")
    cursor = conn.execute(
        "INSERT INTO project_notes (project_id, content) VALUES (?, ?)",
        (row["id"], content),
    )
    conn.execute(
        "UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (row["id"],),
    )
    conn.commit()
    return cursor.lastrowid


def get_project_notes(project_name: str) -> list[dict]:
    conn = _get_connection()
    row = conn.execute("SELECT id FROM projects WHERE name = ?", (project_name,)).fetchone()
    if not row:
        return []
    notes = conn.execute(
        "SELECT * FROM project_notes WHERE project_id = ? ORDER BY created_at, id",
        (row["id"],),
    ).fetchall()
    return [dict(n) for n in notes]


# ── Notes ──

def save_note(content: str, category: str = "general") -> int:
    conn = _get_connection()
    cursor = conn.execute(
        "INSERT INTO notes (content, category) VALUES (?, ?)",
        (content, category),
    )
    conn.commit()
    return cursor.lastrowid


def recall_notes(query: str, limit: int = 10) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM notes ORDER BY created_at DESC, id DESC LIMIT 100"
    ).fetchall()
    if not rows:
        return []

    q = (query or "").strip().lower()
    tokens = [t for t in re.findall(r"[a-z0-9áéíóúñü]+", q) if len(t) >= 4]
    if not tokens:
        return [dict(r) for r in rows[:limit]]

    scored = []
    for r in rows:
        content = (r["content"] or "").lower()
        if not content:
            continue
        score = 0
        if q in content:
            score += 100
        hits = sum(1 for t in tokens if t in content)
        if hits:
            score += hits * 10
        if score:
            scored.append((score, r))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [dict(r) for _, r in scored[:limit]]


def get_recent_notes(limit: int = 8) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM notes ORDER BY created_at DESC, id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_notes_by_category(category: str, limit: int = 10) -> list[dict]:
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM notes WHERE category = ? "
        "ORDER BY created_at DESC, id DESC LIMIT ?",
        (category, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_notes_by_content(query: str) -> list[dict]:
    """Elimina las notas cuyo contenido contenga 'query' (sin distinguir mayusculas).

    Devuelve las notas eliminadas para que la respuesta pueda citarlas.
    """
    conn = _get_connection()
    rows = conn.execute(
        "SELECT * FROM notes WHERE content LIKE ? COLLATE NOCASE",
        (f"%{query}%",),
    ).fetchall()
    deleted = [dict(r) for r in rows]
    for r in rows:
        conn.execute("DELETE FROM notes WHERE id = ?", (r["id"],))
    conn.commit()
    return deleted


_LOCKED_FUNCS = [
    "close",
    "create_session",
    "end_session",
    "get_session",
    "list_sessions",
    "save_message",
    "get_messages",
    "get_all_messages",
    "search_messages",
    "set_preference",
    "get_preference",
    "list_preferences",
    "delete_preference",
    "create_project",
    "get_project",
    "list_projects",
    "update_project_status",
    "delete_project",
    "add_project_note",
    "get_project_notes",
    "save_note",
    "recall_notes",
    "get_recent_notes",
    "get_notes_by_category",
    "delete_notes_by_content",
]
for _name in _LOCKED_FUNCS:
    globals()[_name] = _locked(globals()[_name])
del _name

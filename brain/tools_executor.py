import json
import logging
from typing import Any, Callable

logger = logging.getLogger("jarvis.tools")

RISK_LEVELS = {
    "show_plan": "safe",
    "get_system_info": "safe",
    "open_application": "moderate",
    "open_vscode_folder": "moderate",
    "vscode_disable_restricted_mode": "moderate",
    "close_application": "moderate",
    "control_volume": "moderate",
    "wake_on_lan": "moderate",
    "shutdown_pc": "dangerous",
    "restart_pc": "dangerous",
    "browse_url": "safe",
    "search_web": "safe",
    "play_youtube_video": "safe",
    "list_bookmarks": "safe",
    "open_bookmark": "safe",
    "search_file": "safe",
    "read_file": "safe",
    "write_file": "moderate",
    "delete_file": "dangerous",
    "send_email": "dangerous",
    "read_recent_emails": "safe",
    "get_upcoming_events": "safe",
    "list_calendars": "safe",
    "create_calendar_event": "moderate",
    "update_calendar_event": "moderate",
    "delete_calendar_event": "dangerous",
    "save_note": "moderate",
    "recall_information": "safe",
    "forget_information": "moderate",
    "create_project": "moderate",
    "add_project_note": "moderate",
    "get_project_info": "safe",
    "list_projects": "safe",
    "update_project_status": "moderate",
    "run_python_code": "dangerous",
    # Pantalla, teclado, raton y ventanas.
    # "moderate" en este proyecto significa que se ejecuta directamente
    # (sin confirmacion), segun lo pedido por el usuario.
    "take_screenshot": "safe",
    "press_key": "moderate",
    "type_text": "moderate",
    "click": "moderate",
    "scroll": "moderate",
    "move_mouse": "moderate",
    "get_mouse_position": "safe",
    "list_windows": "safe",
    "get_active_window": "safe",
    "activate_window": "moderate",
    "close_window": "moderate",
    "minimize_window": "moderate",
    "maximize_window": "moderate",
    # Programacion con OpenCode. "moderate" = se ejecuta sin confirmacion
    # (el usuario pidio que JARVIS programe solo). Sube a "dangerous" si
    # quieres que pida permiso antes de tocar codigo.
    "opencode_code": "moderate",
    "opencode_code_visual": "moderate",
    "opencode_result": "safe",
    "opencode_sessions": "safe",
    "opencode_mcp": "moderate",
}

_tool_registry: dict[str, Callable] = {}


def register_tool(name: str):
    def decorator(func: Callable):
        _tool_registry[name] = func
        return func
    return decorator


def get_risk_level(tool_name: str) -> str:
    return RISK_LEVELS.get(tool_name, "moderate")


def get_all_risk_levels() -> dict[str, str]:
    return dict(RISK_LEVELS)


def execute_tool(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name not in _tool_registry:
        logger.warning("Tool desconocida: %s", tool_name)
        return {"error": f"Tool '{tool_name}' no tiene implementacion"}

    risk = get_risk_level(tool_name)
    logger.info(
        "Ejecutando tool=%s risk=%s args=%s",
        tool_name,
        risk,
        json.dumps(args, ensure_ascii=False)[:200],
    )

    try:
        result = _tool_registry[tool_name](**args)
        if isinstance(result, dict):
            return result
        return {"result": str(result)}
    except Exception as e:
        logger.error("Error ejecutando %s: %s", tool_name, e)
        return {"error": str(e)}


def execute_dangerous_tool(
    tool_name: str,
    args: dict[str, Any],
    confirm_cb: Callable | None,
) -> dict[str, Any]:
    if confirm_cb is None:
        logger.warning(
            "Accion dangerous '%s' bloqueada: sin confirmacion configurada",
            tool_name,
        )
        return {
            "status": "cancelled",
            "message": "Accion bloqueada por seguridad: no hay confirmacion configurada.",
        }

    try:
        approved = bool(confirm_cb(tool_name, args))
    except Exception as e:
        logger.error("Error verificando confirmacion de %s: %s", tool_name, e)
        return {
            "status": "cancelled",
            "message": "No se pudo confirmar la accion. Cancelada por seguridad.",
        }

    if approved:
        return execute_tool(tool_name, args)

    logger.info("Usuario cancelo la accion dangerous '%s'", tool_name)
    return {
        "status": "cancelled",
        "message": f"El usuario cancelo la accion '{tool_name}'.",
    }


# ── Importar modulos de tools (registran automaticamente) ──
try:
    from tools import system
except Exception as e:
    logger.warning("No se pudo cargar tools/system: %s", e)

try:
    from tools import file_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/file_tools: %s", e)

try:
    from tools import browser_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/browser_tools: %s", e)

try:
    from tools import bookmark_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/bookmark_tools: %s", e)

try:
    from tools import email_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/email_tools: %s", e)

try:
    from tools import calendar_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/calendar_tools: %s", e)

try:
    from tools import code_executor
except Exception as e:
    logger.warning("No se pudo cargar tools/code_executor: %s", e)

try:
    from tools import window_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/window_tools: %s", e)

try:
    from tools import input_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/input_tools: %s", e)

try:
    from tools import screen_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/screen_tools: %s", e)

try:
    from tools import opencode_tools
except Exception as e:
    logger.warning("No se pudo cargar tools/opencode_tools: %s", e)


# ── Tools de memoria (usando SQLite) ──
from memory.database import (
    save_note,
    recall_notes,
    get_notes_by_category,
    delete_notes_by_content,
)


@register_tool("save_note")
def _save_note(content: str, category: str = "general") -> dict:
    try:
        save_note(content, category)
        return {"result": f"Nota guardada: {content}"}
    except Exception as e:
        return {"error": f"Error guardando nota: {e}"}


@register_tool("recall_information")
def _recall_information(query: str) -> dict:
    try:
        from memory.search import is_enabled as semantic_enabled, search_memory

        notes = recall_notes(query)
        # Busqueda semantica (ChromaDB, opcional): complementa las notas por
        # palabra clave con coincidencias por significado.
        semantic = []
        if semantic_enabled():
            semantic = [
                {"content": m.get("text", ""), "source": m.get("source", ""),
                 "relevance": m.get("relevance")}
                for m in search_memory(query, top_k=3)
            ]
        if notes or semantic:
            return {"results": notes, "semantic_results": semantic}
        return {"results": [], "message": "No encontré nada en la memoria."}
    except Exception as e:
        return {"error": f"Error buscando en memoria: {e}"}


@register_tool("forget_information")
def _forget_information(keywords: str) -> dict:
    try:
        tokens = [t for t in keywords.replace(",", " ").split() if t.strip()]
        if not tokens:
            return {"error": "Necesito al menos una palabra para saber qué olvidar."}

        deleted = []
        seen = set()
        for kw in tokens:
            for note in delete_notes_by_content(kw.strip()):
                if note["id"] not in seen:
                    seen.add(note["id"])
                    deleted.append(note)

        if not deleted:
            return {"results": [], "message": "No encontré nada que olvidar con esas palabras."}
        return {
            "results": deleted,
            "count": len(deleted),
            "message": "Memoria eliminada de la base de datos.",
        }
    except Exception as e:
        return {"error": f"Error olvidando: {e}"}


# ── Tools de proyectos (usando SQLite) ──
from memory.database import (
    create_project,
    add_project_note,
    get_project,
    list_projects,
    update_project_status,
)


@register_tool("create_project")
def _create_project(name: str, description: str = "") -> dict:
    try:
        create_project(name, description)
        return {"result": f"Proyecto '{name}' creado"}
    except Exception as e:
        return {"error": f"Error creando proyecto: {e}"}


@register_tool("add_project_note")
def _add_project_note(project_name: str, content: str) -> dict:
    try:
        project = get_project(project_name)
        if not project:
            return {"error": f"Proyecto '{project_name}' no encontrado"}
        add_project_note(project_name, content)
        return {"result": f"Nota agregada a '{project_name}'"}
    except Exception as e:
        return {"error": f"Error: {e}"}


@register_tool("get_project_info")
def _get_project_info(project_name: str) -> dict:
    try:
        project = get_project(project_name)
        if not project:
            return {"error": f"Proyecto '{project_name}' no encontrado"}
        return {
            "name": project["name"],
            "description": project["description"],
            "status": project["status"],
            "created_at": project["created_at"],
        }
    except Exception as e:
        return {"error": f"Error: {e}"}


@register_tool("list_projects")
def _list_projects() -> dict:
    try:
        projects = list_projects()
        if projects:
            return {"projects": [p["name"] for p in projects]}
        return {"projects": [], "message": "No hay proyectos."}
    except Exception as e:
        return {"error": f"Error: {e}"}


@register_tool("update_project_status")
def _update_project_status(project_name: str, status: str) -> dict:
    try:
        project = get_project(project_name)
        if not project:
            return {"error": f"Proyecto '{project_name}' no encontrado"}
        update_project_status(project["id"], status)
        return {"result": f"'{project_name}' ahora es {status}"}
    except Exception as e:
        return {"error": f"Error: {e}"}

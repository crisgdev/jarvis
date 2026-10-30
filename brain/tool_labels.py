"""Etiquetas en espanol para las subtareas que muestra la GUI.

Cuando Gemini no declara un plan con `show_plan`, el panel de pendientes se
llena con cada tool real que se ejecuta; este modulo traduce el nombre tecnico
de la tool (y sus argumentos) a una frase corta y legible.
"""

import re

_TEMPLATES = {
    "get_system_info": "Consultar el sistema",
    "open_application": "Abrir {app_name}",
    "open_vscode_folder": "Abrir {folder_name} en VS Code",
    "vscode_disable_restricted_mode": "Quitar modo restringido",
    "close_application": "Cerrar aplicacion",
    "control_volume": "Ajustar el volumen",
    "wake_on_lan": "Encender la PC por red",
    "shutdown_pc": "Apagar la PC",
    "restart_pc": "Reiniciar la PC",
    "browse_url": "Abrir {url}",
    "search_web": "Buscar en la web",
    "play_youtube_video": "Reproducir en YouTube",
    "youtube_loop": "Poner video en bucle",
    "list_bookmarks": "Revisar marcadores",
    "open_bookmark": "Abrir marcador",
    "search_file": "Buscar {name}",
    "read_file": "Leer archivo",
    "write_file": "Escribir archivo",
    "delete_file": "Eliminar archivo",
    "send_email": "Enviar correo",
    "read_recent_emails": "Leer correos",
    "get_upcoming_events": "Revisar el calendario",
    "list_calendars": "Listar calendarios",
    "create_calendar_event": "Crear evento {title}",
    "update_calendar_event": "Actualizar evento",
    "delete_calendar_event": "Eliminar evento",
    "save_note": "Guardar nota",
    "recall_information": "Buscar en la memoria",
    "forget_information": "Olvidar informacion",
    "create_project": "Crear proyecto {name}",
    "add_project_note": "Agregar nota al proyecto",
    "get_project_info": "Consultar proyecto",
    "list_projects": "Listar proyectos",
    "update_project_status": "Actualizar proyecto",
    "run_python_code": "Ejecutar codigo",
    "take_screenshot": "Mirar la pantalla",
    "press_key": "Pulsar {key}",
    "type_text": "Escribir texto",
    "click": "Hacer clic",
    "scroll": "Desplazar la vista",
    "move_mouse": "Mover el puntero",
    "get_mouse_position": "Leer el puntero",
    "list_windows": "Listar ventanas",
    "get_active_window": "Ver la ventana activa",
    "activate_window": "Enfocar ventana",
    "close_window": "Cerrar ventana",
    "minimize_window": "Minimizar ventana",
    "maximize_window": "Maximizar ventana",
    "opencode_code": "Programar con OpenCode",
    "opencode_code_visual": "Escribir en OpenCode",
    "opencode_result": "Recoger resultado de OpenCode",
    "opencode_sessions": "Revisar sesiones de OpenCode",
    "opencode_mcp": "Gestionar servidores MCP",
}

_ARG_KEYS = (
    "app_name", "folder_name", "url", "name", "title", "key", "query",
    "file_name", "path", "project_name", "content", "task",
)


def _humanize(name: str) -> str:
    text = re.sub(r"[_\-]+", " ", name or "").strip()
    return text[:1].upper() + text[1:] if text else "Trabajando\u2026"


def describe_tool_call(name: str, args: dict | None = None) -> str:
    args = args or {}
    template = _TEMPLATES.get(name)

    if template is None:
        return _humanize(name)

    values = {}
    for key in _ARG_KEYS:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            values[key] = value.strip()

    try:
        label = template.format(**values)
    except (KeyError, IndexError):
        label = template.split("{")[0].strip() or _humanize(name)

    # Si quedo un hueco tipo "Abrir en VS Code", se recorta.
    label = re.sub(r"\s{2,}", " ", label).strip()
    if label.endswith(" en VS Code") and "Abrir en" in label:
        label = "Abrir el proyecto en VS Code"
    return label[:48]

"""Confirmaciones de acciones peligrosas, compartidas entre voz y Telegram."""

DANGEROUS_TOOL_LABELS = {
    "shutdown_pc": ("Apagar la PC", "JARVIS apagara la PC en 10 segundos."),
    "restart_pc": ("Reiniciar la PC", "JARVIS reiniciara la PC en 10 segundos."),
    "send_email": ("Enviar email", "Se enviara un email a {to} con asunto '{subject}'."),
    "delete_calendar_event": ("Eliminar evento", "Se eliminara un evento del calendario."),
    "delete_file": ("Eliminar archivo", "Se eliminara el archivo {filepath}."),
    "run_python_code": ("Ejecutar codigo", "Se ejecutara codigo Python en tu PC."),
}


def confirmation_request(tool_name: str, args: dict) -> tuple[str, str]:
    title, template = DANGEROUS_TOOL_LABELS.get(
        tool_name, (tool_name, "Se ejecutara una accion peligrosa.")
    )
    if tool_name == "delete_calendar_event":
        summary = (args or {}).get("summary")
        if summary:
            return title, f"Se eliminara '{summary}' del calendario."
        return title, "Se eliminara un evento del calendario."
    try:
        message = template.format(**args) if isinstance(args, dict) else template
    except KeyError:
        message = template
    return title, message


def confirmation_to_message(tool_name: str, args: dict) -> str:
    title, message = confirmation_request(tool_name, args)
    return f"*{title}*\n{message}\n\n¿Confirmas la accion?"
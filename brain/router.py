"""Router de turno: decide packs de prompt, subconjunto de tools y modelo.

Es una funcion pura y determinista (sin tokens, sin latencia): mira el texto
del usuario, detecta el tema y devuelve tres cosas a la vez:

    packs  -> que bloques de prompt se activan (brain/prompts.py)
    tools  -> que declaraciones de herramientas viajan a Gemini
    tier   -> "fast" (modelo ligero) o "strong" (modelo completo)

Ventaja de tenerlo en un solo lugar: prompt, tools y modelo no se contradicen
entre si.

Seguridad: si el router no reconoce nada, se queda con el nucleo (que incluye
abrir apps, navegar, buscar, volumen y sistema). Si aun asi el modelo necesita
una tool que no tiene, brain/gemini.py reintenta el turno con TODAS las tools
(_retry_with_full_tools), asi que un fallo del router cuesta un turno, no una
funcion perdida.
"""

import re
import unicodedata
from dataclasses import dataclass, field

# ── Herramientas ──────────────────────────────────────────────────────────
# Nucleo: siempre disponibles. Son las de uso mas comun y las que resuelven
# ordenes genericas ("abre", "busca", "que hora es").
CORE_TOOLS = (
    "show_plan",
    "get_system_info",
    "open_application",
    "close_application",
    "control_volume",
    "browse_url",
    "search_web",
    "play_youtube_video",
)

# Tools extra que aporta cada pack (ademas del nucleo).
PACK_TOOLS = {
    "media": ("youtube_loop",),
    "mail": ("send_email", "read_recent_emails"),
    "calendar": (
        "get_upcoming_events",
        "list_calendars",
        "create_calendar_event",
        "update_calendar_event",
        "delete_calendar_event",
    ),
    "files": ("search_file", "read_file", "write_file", "delete_file"),
    "memory": (
        "save_note",
        "recall_information",
        "forget_information",
        "create_project",
        "add_project_note",
        "get_project_info",
        "list_projects",
        "update_project_status",
    ),
    "screen": (
        "take_screenshot",
        "press_key",
        "type_text",
        "click",
        "scroll",
        "move_mouse",
        "get_mouse_position",
        "list_windows",
        "get_active_window",
        "activate_window",
        "close_window",
        "minimize_window",
        "maximize_window",
    ),
    "dev": (
        "run_python_code",
        "opencode_code",
        "opencode_code_visual",
        "opencode_result",
        "opencode_sessions",
        "opencode_mcp",
        "open_vscode_folder",
        "vscode_disable_restricted_mode",
    ),
    "power": ("wake_on_lan", "shutdown_pc", "restart_pc"),
    "bookmarks": ("list_bookmarks", "open_bookmark"),
}

# Packs cuyo tema es lo bastante delicado para usar el modelo completo si o si.
STRONG_PACKS = frozenset({"calendar", "dev", "mail"})


# ── Senales de intencion ──────────────────────────────────────────────────
# Se comparan contra el texto normalizado (minusculas, sin acentos).
PACK_SIGNALS = {
    "media": (
        "youtube", "video", "videos", "musica", "cancion", "canciones",
        "spotify", "reproduce", "pon ", "play", "volumen", "sube el",
        "baja el", "silencia", "silencio", "mute", "netflix", "pelicula",
        "peliculas", "juego", "juegos", "abre", "abrir", "cierra", "cerrar",
        "app", "aplicacion", "programa", "bucle", "loop", "repeticion",
        "repetir",
    ),
    "mail": (
        "gmail", "correo", "correos", "email", "emails", "mail", "bandeja",
        "inbox", "cuenta de google", "cuentas de google", "outlook",
        "institucional", "principal", "secundaria", "profesional",
        "universidad", "continental",
    ),
    "calendar": (
        "evento", "eventos", "calendario", "calendarios", "cita", "citas",
        "agenda", "agendar", "clase", "clases", "reunion", "reuniones",
        "horario", "recordatorio", "recordatorios", "examen", "examenes",
        "cumpleanos", "se repite", "recurrencia", "semanal", "mensual",
    ),
    "files": (
        "archivo", "archivos", "carpeta", "carpetas", "documento",
        "documentos", "pdf", "excel", "word", "txt",
    ),
    "memory": (
        "recuerda", "recuerdame", "recuerdas", "olvida", "olvidar", "olvido",
        "memoria", "nota", "notas", "proyecto", "proyectos",
    ),
    "screen": (
        "pantalla", "captura", "screenshot", "raton", "mouse", "cursor",
        "click", "clic", "tecla", "teclado", "presiona", "pulsa",
        "escribe", "escribir", "ventana", "ventanas", "minimiza", "maximiza",
        "scroll", "rueda", "desplaza", "enfoca",
    ),
    "dev": (
        "codigo", "programa", "programar", "programacion", "opencode",
        "github", "git", "repo", "repositorio", "commit", "bug", "bugs",
        "vscode", "vs code", "refactor", "refactoriza", "script", "api",
        "docker", "instala", "dependencia", "dependencias", "compila",
        "despliega", "deploy", "backend", "frontend", "base de datos",
        "funcion", "test", "tests", "terminal", "servidor",
    ),
    "power": (
        "apaga", "apagar", "apagate", "suspende", "suspender", "suspension",
        "reinicia", "reiniciar", "duerme", "dormir", "enciende la pc",
        "wake on lan", "wol", "prende la pc",
    ),
    "bookmarks": (
        "marcador", "marcadores", "bookmark", "bookmarks", "favoritos",
    ),
}

# Expresiones que sugieren una orden compleja o de varios pasos.
STRONG_PATTERNS = (
    r"\btodos los\b", r"\btodas las\b", r"\bcada\b", r"\bhasta el\b",
    r"\by luego\b", r"\by despues\b", r"\bdespues de\b", r"\btambien\b",
    r"\bvarios\b", r"\bvarias\b", r"\bcompara\b", r"\banaliza\b",
    r"\bexplica\b", r"\bconfigura\b", r"\borganiza\b", r"\bplanifica\b",
)

_WORD_RE = re.compile(r"\S+")

# Umbral de longitud (en palabras) a partir del cual se asume orden compleja.
LONG_QUERY_WORDS = 16


def _normalize(text: str) -> str:
    """Minusculas y sin acentos, para que 'reunion' == 'reunión'."""
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


@dataclass
class Route:
    packs: tuple[str, ...] = ()
    tools: tuple[str, ...] = CORE_TOOLS
    tier: str = "fast"
    reason: str = ""
    all_tools: bool = field(default=False)

    @property
    def key(self) -> tuple:
        """Identidad de la ruta para no recrear el chat si no cambio nada."""
        return (self.tier, self.packs, self.tools)

    def as_log(self) -> dict:
        return {
            "packs": list(self.packs),
            "tier": self.tier,
            "tools": len(self.tools),
            "reason": self.reason,
        }


def all_tool_names() -> tuple[str, ...]:
    """Las 53 herramientas, en orden estable."""
    names = list(CORE_TOOLS)
    for pack in PACK_TOOLS:
        for name in PACK_TOOLS[pack]:
            if name not in names:
                names.append(name)
    return tuple(names)


def route(text: str, detailed: bool = False, enabled: bool = True) -> Route:
    """Clasifica un turno del usuario.

    enabled=False devuelve el comportamiento anterior (todas las tools, todos
    los packs) sin cambiar el resto del flujo.
    """
    if not enabled:
        return Route(
            packs=tuple(PACK_TOOLS),
            tools=all_tool_names(),
            tier="strong" if detailed else "fast",
            reason="routing desactivado",
            all_tools=True,
        )

    norm = _normalize(text)

    packs = []
    for name, signals in PACK_SIGNALS.items():
        if any(sig in norm for sig in signals):
            packs.append(name)

    tools = list(CORE_TOOLS)
    for name in packs:
        for tool_name in PACK_TOOLS.get(name, ()):
            if tool_name not in tools:
                tools.append(tool_name)

    words = len(_WORD_RE.findall(norm))

    if detailed:
        tier, why = "strong", "canal detallado"
    elif STRONG_PACKS.intersection(packs):
        tier, why = "strong", "pack complejo: " + ",".join(sorted(STRONG_PACKS & set(packs)))
    elif any(re.search(pat, norm) for pat in STRONG_PATTERNS):
        tier, why = "strong", "orden compuesta"
    elif words >= LONG_QUERY_WORDS:
        tier, why = "strong", f"consulta larga ({words} palabras)"
    else:
        tier, why = "fast", "consulta simple"

    if not packs:
        why += " (sin pack reconocido)"

    return Route(
        packs=tuple(packs),
        tools=tuple(tools),
        tier=tier,
        reason=why,
    )

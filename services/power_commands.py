"""Intercepcion determinista de ordenes de energia (apagar/hibernar/suspender/
reiniciar/encender por red).

Se atienden ANTES de Gemini, igual que el modo sordo, para que "apaga la pc"
siempre termine ejecutando la herramienta correcta en vez de depender de que
el modelo la elija (y de que la confirme con texto).
"""

import re
import unicodedata


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return " ".join(text.split())


# Palabras que indican que el objetivo NO es la PC (volumen, musica, etc.).
_NON_PC_TARGETS = (
    "musica", "cancion", "canciones", "video", "videos", "volumen",
    "sonido", "audio", "youtube", "spotify", "netflix", "luz", "luces",
    "monitor", "pantalla",
)

_PC_CONTEXT = (
    "pc", "computadora", "computador", "equipo", "laptop", "maquina",
    "ordenador", "sistema", "windows", "notebook",
)

_SHUTDOWN_VERBS = (
    "apaga", "apagar", "apagate", "hiberna", "hibernar", "suspender",
    "suspension", "suspender", "duerme", "dormir", "apagado",
)

_RESTART_VERBS = ("reinicia", "reiniciar", "reboot", "reiniciar pc")

_WAKE_PHRASES = (
    "enciende la pc", "enciende el pc", "enciende la computadora",
    "enciende el equipo", "enciende la laptop", "prende la pc",
    "prende el pc", "prende la computadora", "prende el equipo",
    "wake on lan", "wake-on-lan", "wol", "encender la pc",
    "encender la computadora", "encender el equipo",
)


def match_power_command(text: str) -> dict | None:
    """Devuelve un dict {'action','mode'} o None si no es orden de energia."""
    norm = _normalize(text)
    if not norm:
        return None

    # Excluir ordenes cuyo objetivo claramente no es la PC.
    if any(t in norm for t in _NON_PC_TARGETS):
        if not any(c in norm for c in _PC_CONTEXT):
            return None

    has_pc_context = any(c in norm for c in _PC_CONTEXT)
    off_intent = any(k in norm for k in ("del todo", "real", "quitar energia",
                                       "apagado real", "apagar del todo"))

    # Wake on LAN
    if any(p in norm for p in _WAKE_PHRASES):
        return {"action": "wake", "mode": None}

    # Restart (solo si es la PC o la frase es el verbo solo)
    if any(v in norm for v in _RESTART_VERBS):
        if has_pc_context or norm in ("reinicia", "reiniciar", "reboot"):
            return {"action": "restart", "mode": None}

    # Shutdown / hibernate / sleep
    shutdown_hit = any(v in norm for v in _SHUTDOWN_VERBS)
    if not shutdown_hit:
        return None

    # Bare verbs counts only if there is PC context OR the whole phrase is
    # just the verb (usuario dice "apaga" esperando apagar la PC).
    bare = norm in ("apaga", "apagar", "apagate", "hiberna", "hibernar",
                    "suspender", "duerme", "dormir", "apagado")
    if not (has_pc_context or bare or off_intent):
        return None

    # Mode
    mode = "hibernate"
    if any(k in norm for k in ("suspender", "suspension", "duerme", "dormir")):
        mode = "sleep"
    if any(k in norm for k in ("off", "real", "del todo", "quitar energia",
                               "apagado real", "apagar del todo")):
        mode = "off"

    return {"action": "shutdown", "mode": mode}

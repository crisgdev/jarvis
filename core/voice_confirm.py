import re

WORD_RE = re.compile(r"[a-z0-9áéíóúüñ]+")

CANCEL_TOKENS = {
    "no", "cancela", "cancelar", "cancelalo", "cancelarlo", "cancelado",
    "para", "detente", "detener", "espera", "alto", "negativo", "nada",
    "deshacer",
}

CONFIRM_TOKENS = {
    "si", "sí", "procede", "proceda", "adelante", "confirmo", "confirmar",
    "confirma", "deacuerdo", "acuerdo", "claro", "hazlo", "hagalo",
    "dale", "ok", "vale", "listo", "ejecuta", "apaga", "reinicia",
    "correcto", "vamos", "yes", "yep",
}


def interpret_confirmation(text: str | None) -> bool | None:
    """Interpreta una respuesta de confirmacion.

    Retorna True (confirma), False (cancela) o None (indefinido).
    """
    if not text:
        return None

    tokens = set(WORD_RE.findall(text.lower()))
    if not tokens:
        return None

    if tokens & CANCEL_TOKENS:
        return False
    if tokens & CONFIRM_TOKENS:
        return True
    return None
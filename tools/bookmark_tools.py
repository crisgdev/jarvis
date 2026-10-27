import json
import logging
import os
import re
import unicodedata
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

from brain.tools_executor import register_tool
from config import get_config

logger = logging.getLogger("jarvis.tools.bookmarks")

_BOOKMARK_FILES = ("AccountBookmarks", "Bookmarks")
_PROFILE_RE = re.compile(r"^(Default|Profile \d+)$")


def _user_data_dir() -> Path | None:
    candidates = []
    env_dir = os.getenv("CHROME_USER_DATA")
    if env_dir:
        candidates.append(Path(env_dir))
    local = os.getenv("LOCALAPPDATA")
    if local:
        candidates.append(Path(local) / "Google" / "Chrome" / "User Data")
    home = os.getenv("USERPROFILE")
    if home:
        candidates.append(Path(home) / "AppData" / "Local" / "Google" / "Chrome" / "User Data")
    for path in candidates:
        if path and path.is_dir():
            return path
    return None


def _count_entries(node: dict) -> int:
    total = 0
    for child in node.get("children", []) or []:
        total += 1
        if child.get("type") == "folder":
            total += _count_entries(child)
    return total


def _read_bar(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("No se pudo leer %s: %s", path, e)
        return None
    bar = (data.get("roots") or {}).get("bookmark_bar")
    if not bar or bar.get("type") != "folder":
        return None
    return bar


def _load_bookmark_bar() -> tuple[dict | None, str]:
    """Devuelve (nodo raiz de la barra, nombre del perfil) del perfil mas poblado."""
    user_data = _user_data_dir()
    if not user_data:
        return None, ""

    wanted = str((get_config().get("browser") or {}).get("chrome_profile", "auto")).strip()
    profiles = [
        p for p in sorted(user_data.iterdir(), key=lambda x: x.name)
        if p.is_dir() and _PROFILE_RE.match(p.name)
    ]
    if wanted and wanted.lower() != "auto":
        profiles.sort(key=lambda p: 0 if p.name.lower() == wanted.lower() else 1)

    best: tuple[dict | None, str, int] = (None, "", -1)
    for profile in profiles:
        for filename in _BOOKMARK_FILES:
            bar = _read_bar(profile / filename)
            if bar is None:
                continue
            entries = _count_entries(bar)
            if entries > best[2]:
                best = (bar, profile.name, entries)
            break
        if wanted and best[1].lower() == wanted.lower() and best[0] is not None:
            break
    return best[0], best[1]


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).strip().lower()


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _norm(text))


def _label(node: dict) -> str:
    name = (node.get("name") or "").strip()
    if name:
        return name
    host = urlparse(node.get("url") or "").netloc
    return f"sin titulo ({host})" if host else "sin titulo"


def _children(node: dict) -> list[dict]:
    return [c for c in (node.get("children") or []) if isinstance(c, dict)]


def _resolve_folder(bar: dict, path: str) -> tuple[dict | None, list[str]]:
    """Sigue 'carpeta/subcarpeta' dentro de la barra. Devuelve (nodo, nombres usados)."""
    node = bar
    used: list[str] = []
    for part in [p for p in (path or "").replace("\\", "/").split("/") if p.strip()]:
        target = _norm(part)
        match = None
        for child in _children(node):
            if child.get("type") != "folder":
                continue
            name = _norm(child.get("name"))
            if name == target:
                match = child
                break
            if match is None and target and (target in name or name in target):
                match = child
        if match is None:
            return None, used
        node = match
        used.append(_label(match))
    return node, used


def _flatten(node: dict, depth: int = 0, path: tuple[str, ...] = ()) -> list[tuple[dict, int, tuple[str, ...]]]:
    out: list[tuple[dict, int, tuple[str, ...]]] = []
    for child in _children(node):
        child_path = path + (_label(child),)
        out.append((child, depth, child_path))
        if child.get("type") == "folder":
            out.extend(_flatten(child, depth + 1, child_path))
    return out


def _score(query: str, candidate: str) -> int:
    q, c = _norm(query), _norm(candidate)
    if not q or not c:
        return 0
    if q == c:
        return 100
    if c.startswith(q):
        return 80
    if q in c:
        return 60
    if c in q:
        return 40
    return 0


def _collect_urls(node: dict) -> list[str]:
    urls = []
    for child, _depth, _path in _flatten(node):
        if child.get("type") == "url" and child.get("url"):
            urls.append((child["url"], _label(child)))
    return urls


@register_tool("list_bookmarks")
def _list_bookmarks(folder: str = "", limit: int = 60) -> dict:
    """Lista el contenido de la barra de marcadores de Chrome (paginas y carpetas)."""
    bar, profile = _load_bookmark_bar()
    if bar is None:
        return {"error": "No encontre los marcadores de Chrome en esta PC."}

    node, used = _resolve_folder(bar, folder)
    if node is None:
        return {"error": f"No encontre la carpeta '{folder}' en la barra de marcadores."}

    entries = []
    for child in _children(node)[: max(1, int(limit or 60))]:
        if child.get("type") == "folder":
            entries.append({
                "type": "folder",
                "name": _label(child),
                "path": "/".join(used + [_label(child)]),
                "items": len(_children(child)),
            })
        else:
            entries.append({
                "type": "page",
                "name": _label(child),
                "url": child.get("url", ""),
            })

    return {
        "profile": profile,
        "folder": " / ".join(used) if used else "barra de marcadores",
        "entries": entries,
        "count": len(entries),
    }


@register_tool("open_bookmark")
def _open_bookmark(name: str, max_tabs: int = None) -> dict:
    """Abre una pagina guardada o todas las paginas de una carpeta de marcadores."""
    query = (name or "").strip()
    if not query:
        return {"error": "Falta el nombre del marcador o carpeta."}

    bar, profile = _load_bookmark_bar()
    if bar is None:
        return {"error": "No encontre los marcadores de Chrome en esta PC."}

    cfg = get_config().get("browser") or {}
    limit = int(max_tabs or cfg.get("max_tabs_per_folder", 8))

    folder_node, used = _resolve_folder(bar, query)
    if folder_node is not None and used and _key(" / ".join(used)) != _key(query):
        folder_node = None
    if folder_node is not None and used:
        entries = _collect_urls(folder_node)
        if not entries:
            return {"message": f"La carpeta '{' / '.join(used)}' no tiene paginas guardadas."}
        opened = []
        for url, label in entries[: max(1, limit)]:
            webbrowser.open(url)
            opened.append({"name": label, "url": url})
        skipped = len(entries) - len(opened)
        message = f"Abrí {len(opened)} página(s) de la carpeta '{' / '.join(used)}'."
        if skipped > 0:
            message += f" ({skipped} más sin abrir por el límite; pídelas por nombre si las quieres.)"
        return {"status": "success", "profile": profile, "folder": " / ".join(used), "opened": opened, "message": message}

    candidates = []
    for child, depth, path in _flatten(bar):
        if child.get("type") != "url":
            continue
        label = _label(child)
        score = max(_score(query, label), _score(query, path[-1]) if len(path) > 1 else 0)
        if score:
            candidates.append((score - depth, label, child.get("url", ""), " / ".join(path[:-1])))
        else:
            host = urlparse(child.get("url") or "").netloc
            if _norm(host).startswith(_norm(query)):
                candidates.append((30 - depth, label, child.get("url", ""), " / ".join(path[:-1])))

    if not candidates:
        hint = _suggest_folders(bar, query)
        msg = f"No encontré el marcador '{query}' en la barra de Chrome."
        if hint:
            msg += f" Carpetas parecidas: {', '.join(hint)}."
        return {"error": msg, "suggestion": "Usa list_bookmarks para ver el contenido de la barra."}

    candidates.sort(key=lambda c: c[0], reverse=True)
    best = candidates[0]
    webbrowser.open(best[2])
    others = [c[1] for c in candidates[1:4]]
    message = f"Abrí '{best[1]}' desde tus marcadores."
    if others:
        message += f" También había: {', '.join(others)}."
    return {
        "status": "success",
        "profile": profile,
        "opened": [{"name": best[1], "url": best[2]}],
        "folder": best[3],
        "message": message,
    }


def _suggest_folders(bar: dict, query: str, limit: int = 5) -> list[str]:
    names = []
    for child, depth, _path in _flatten(bar):
        if child.get("type") != "folder":
            continue
        label = _label(child)
        if _norm(query) in _norm(label) or _norm(label) in _norm(query):
            names.append(label)
        if len(names) >= limit:
            break
    return names
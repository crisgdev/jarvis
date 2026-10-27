import os
from pathlib import Path

from brain.tools_executor import register_tool


def _compact(s: str) -> str:
    return "".join(c for c in s.lower() if c.isalnum())


@register_tool("search_file")
def _search_file(filename: str) -> dict:
    name = (filename or "").strip()
    if not name:
        return {"results": [], "message": "No indicó qué buscar"}

    results = []
    seen = set()

    def add(p):
        try:
            p = os.path.abspath(p)
        except Exception:
            return
        if p and os.path.exists(p) and p not in seen:
            seen.add(p)
            results.append(p)

    needle = _compact(name)

    # 1) Resolución rápida: apps, accesos directos y carpetas conocidas
    try:
        from tools.system import _resolve_app, _resolve_folder
        add(_resolve_app(name))
        add(_resolve_folder(name))
    except Exception:
        pass

    # 2) Búsqueda por nombre en raíces habituales del usuario
    roots = [
        Path.home() / "Desktop",
        Path.home() / "Downloads",
        Path.home() / "Documents",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu",
    ]
    for root in roots:
        if not root.exists():
            continue
        for dirpath, dirs, files in os.walk(root):
            for d in dirs:
                cd = _compact(d)
                if cd and (needle in cd or (len(cd) >= 4 and cd in needle)):
                    add(os.path.join(dirpath, d))
            for f in files:
                if needle and needle in _compact(f):
                    add(os.path.join(dirpath, f))
            if len(results) >= 10:
                return {"results": results[:10], "count": len(results)}

    if results:
        return {"results": results[:10], "count": len(results)}

    # 3) Barrido general de la PC
    for search_dir in (Path.home(), Path("C:/")):
        if not search_dir.exists():
            continue
        for _root, _dirs, _files in os.walk(search_dir):
            for f in _files:
                if needle and needle in _compact(f):
                    add(os.path.join(_root, f))
                    if len(results) >= 10:
                        return {"results": results[:10], "count": len(results)}
            if len(results) >= 10:
                break
        if results:
            break

    if results:
        return {"results": results[:10], "count": len(results)}
    return {"results": [], "message": f"No encontré archivos con '{name}'"}


@register_tool("read_file")
def _read_file(filepath: str) -> dict:
    try:
        path = Path(filepath)
        if not path.exists():
            return {"error": f"Archivo no encontrado: {filepath}"}
        if path.stat().st_size > 1_000_000:
            return {"error": "Archivo muy grande (más de 1MB). No lo leo completo."}
        content = path.read_text(encoding="utf-8", errors="replace")
        return {"content": content[:5000], "truncated": len(content) > 5000}
    except Exception as e:
        return {"error": f"Error leyendo archivo: {e}"}


@register_tool("write_file")
def _write_file(filepath: str, content: str, mode: str = "write") -> dict:
    try:
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        if mode == "append" and path.exists():
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            return {"status": "success", "message": f"Contenido agregado a {filepath}"}

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "message": f"Archivo creado/actualizado: {filepath}"}
    except Exception as e:
        return {"error": f"Error escribiendo archivo: {e}"}


@register_tool("delete_file")
def _delete_file(filepath: str) -> dict:
    try:
        path = Path(filepath)
        if not path.exists():
            return {"error": f"Archivo no encontrado: {filepath}"}
        if path.is_dir():
            return {"error": f"No borro carpetas, solo archivos: {filepath}"}
        path.unlink()
        return {"status": "success", "message": f"Archivo eliminado: {filepath}"}
    except Exception as e:
        return {"error": f"Error eliminando archivo: {e}"}

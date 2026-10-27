import shutil
import subprocess
import sys
import webbrowser

from duckduckgo_search import DDGS

from brain.tools_executor import register_tool


def _normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith(("http://", "https://")):
        return url
    if "." not in url:
        return f"https://{url}.com"
    return "https://" + url


def _is_youtube_url(url: str) -> bool:
    low = url.lower()
    return ("youtube.com" in low or "youtu.be" in low) and any(
        marker in low for marker in ("watch?v=", "youtu.be/", "/shorts/", "/live/", "/playlist?list=")
    )


@register_tool("browse_url")
def _browse_url(url: str) -> dict:
    url = _normalize_url(url)
    try:
        webbrowser.open(url)
        return {"status": "success", "message": f"Abrí {url} en el navegador"}
    except Exception as e:
        return {"error": f"No pude abrir {url}: {e}"}


@register_tool("search_web")
def _search_web(query: str) -> dict:
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))

        if results:
            formatted = []
            for r in results:
                formatted.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
            return {"results": formatted}
        return {"message": f"No encontré resultados para '{query}'"}
    except Exception as e:
        return {"error": f"Error buscando: {e}"}


@register_tool("play_youtube_video")
def _play_youtube_video(query: str) -> dict:
    q = (query or "").strip()
    if not q:
        return {"error": "Falta el nombre del video."}

    if _is_youtube_url(q):
        webbrowser.open(q)
        return {"status": "success", "message": f"Abrí el video de YouTube: {q}"}

    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return {"error": "Falta yt-dlp para resolver videos. Instalalo con: pip install yt-dlp"}

    try:
        proc = subprocess.run(
            [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--no-playlist",
             "--print", "%(id)s", f"ytsearch1:{q}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return {"error": "YouTube no respondió a tiempo al buscar el video."}
    except Exception as e:
        return {"error": f"yt-dlp falló: {e}"}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1] if (proc.stderr or proc.stdout) else ""
        return {"error": f"No pude obtener el video '{q}': {detail or 'error desconocido'}"}

    video_id = (proc.stdout or "").strip().splitlines()[-1].strip() if proc.stdout else ""
    if not video_id:
        return {"error": f"No encontré el video '{q}' en YouTube."}

    url = f"https://www.youtube.com/watch?v={video_id}"
    webbrowser.open(url)
    return {"status": "success", "message": f"Abrí el video '{q}': {url}"}

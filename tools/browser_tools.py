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


@register_tool("youtube_loop")
def _youtube_loop(video_name: str = None) -> dict:
    """Pone un video de YouTube en bucle (repeticion infinita).

    Si se indica video_name, busca ese video en YouTube, lo reproduce y lo
    pone en bucle. Si no se indica, activa el bucle en el video de YouTube
    que ya este reproduciendose en una pestaña abierta.

    El bucle se activa enviando una peticion al servidor Flask de JARVIS
    (http://127.0.0.1:5050/loop), que la extension de Chrome consume para
    ejecutar document.querySelector('video').loop = true; en la pestaña
    de YouTube.
    """
    import time

    FLASK_URL = "http://127.0.0.1:5050/loop"

    url = None
    if video_name:
        q = (video_name or "").strip()
        if not q:
            return {"error": "Falta el nombre del video."}

        if _is_youtube_url(q):
            url = q
        else:
            try:
                import yt_dlp  # noqa: F401
            except ImportError:
                return {
                    "error": "Falta yt-dlp para resolver videos. Instalalo con: pip install yt-dlp"
                }

            try:
                proc = subprocess.run(
                    [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--no-playlist",
                     "--print", "%(id)s", f"ytsearch1:{q}"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                return {"error": "YouTube no respondio a tiempo al buscar el video."}
            except Exception as e:
                return {"error": f"yt-dlp fallo: {e}"}

            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1] if (proc.stderr or proc.stdout) else ""
                return {"error": f"No pude obtener el video '{q}': {detail or 'error desconocido'}"}

            video_id = (proc.stdout or "").strip().splitlines()[-1].strip() if proc.stdout else ""
            if not video_id:
                return {"error": f"No encontre el video '{q}' en YouTube."}

            url = f"https://www.youtube.com/watch?v={video_id}"

    if url:
        try:
            webbrowser.open(url)
            time.sleep(3.0)
        except Exception as e:
            return {"error": f"No pude abrir {url}: {e}"}

    # Notificar al servidor Flask para que la extension active el bucle
    try:
        import urllib.request
        import urllib.error
        import json as _json

        payload = _json.dumps({"video_name": video_name}).encode("utf-8")
        req = urllib.request.Request(
            FLASK_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status != 200:
                return {
                    "error": f"El servidor Flask respondio con codigo {resp.status}. "
                             f"Asegurate de que este corriendo (python services/youtube_loop_server.py)."
                }
    except urllib.error.URLError as e:
        return {
            "error": "No pude contactar con el servidor Flask de YouTube Loop. "
                     "Inicialo con: python services/youtube_loop_server.py "
                     f"(error: {e})"
        }
    except Exception as e:
        return {"error": f"Notificando al servidor Flask: {e}"}

    return {
        "status": "success",
        "message": "Bucle activado en YouTube. "
                   "Asegurate de tener la extension de Chrome instalada y el servidor Flask corriendo.",
    }

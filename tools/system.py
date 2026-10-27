import datetime
import logging
import os
import re
import socket
import subprocess
import webbrowser
import shutil
import psutil

from brain.tools_executor import register_tool
from config import get_config

logger = logging.getLogger("jarvis.tools.system")

try:
    import winreg
except ImportError:  # pragma: no cover
    winreg = None


@register_tool("get_system_info")
def _get_system_info(info_type: str = "all") -> dict:
    now = datetime.datetime.now()

    if info_type == "time":
        return {"time": now.strftime("%H:%M:%S")}
    if info_type == "date":
        return {"date": now.strftime("%Y-%m-%d"), "weekday": now.strftime("%A")}

    result = {
        "time": now.strftime("%H:%M:%S"),
        "date": now.strftime("%Y-%m-%d"),
        "weekday": now.strftime("%A"),
    }

    if info_type in ("all", "cpu"):
        result["cpu_percent"] = psutil.cpu_percent(interval=1)
        result["cpu_count"] = psutil.cpu_count()

    if info_type in ("all", "memory"):
        mem = psutil.virtual_memory()
        result["ram_total_gb"] = round(mem.total / (1024**3), 1)
        result["ram_used_gb"] = round(mem.used / (1024**3), 1)
        result["ram_percent"] = mem.percent

    if info_type in ("all", "disk"):
        disk = psutil.disk_usage("/")
        result["disk_total_gb"] = round(disk.total / (1024**3), 1)
        result["disk_free_gb"] = round(disk.free / (1024**3), 1)
        result["disk_percent"] = disk.percent

    if info_type in ("all", "battery"):
        bat = psutil.sensors_battery()
        if bat:
            result["battery_percent"] = bat.percent
            result["battery_plugged"] = bat.power_plugged
        else:
            result["battery"] = "No detectada"

    return result


def _wol_payload(mac: str) -> bytes:
    clean = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(clean) != 12:
        raise ValueError(f"MAC invalida: {mac!r}. Formato esperado: XX:XX:XX:XX:XX:XX")
    mac_bytes = bytes.fromhex(clean)
    return b"\xff" * 6 + mac_bytes * 16


@register_tool("wake_on_lan")
def _wake_on_lan(mac: str = None, broadcast: str = None, port: int = 9) -> dict:
    """Envia un paquete magico Wake-on-LAN para encender una PC de la red local."""
    wol_cfg = get_config().get("wol", {})
    mac = (mac or wol_cfg.get("mac", "")).strip() or None
    broadcast = broadcast or wol_cfg.get("broadcast", "255.255.255.255")
    port = int(port or wol_cfg.get("port", 9))

    if not mac:
        return {"error": "No hay MAC configurada (config.json -> wol.mac)"}

    try:
        payload = _wol_payload(mac)
    except ValueError as e:
        return {"error": str(e)}

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.sendto(payload, (broadcast, port))
        logger.info("Paquete WOL enviado a %s (broadcast %s:%d)", mac, broadcast, port)
        return {"result": f"Paquete Wake-on-LAN enviado a {mac}"}
    except Exception as e:
        logger.error("Error enviando WOL: %s", e)
        return {"error": f"Error enviando WOL: {e}"}


_APP_MAP = {
    "chrome": "chrome",
    "google chrome": "chrome",
    "spotify": "spotify",
    "vscode": "code",
    "vs code": "code",
    "visual studio code": "code",
    "notepad": "notepad",
    "explorer": "explorer",
    "file explorer": "explorer",
    "calculator": "calc",
    "calculadora": "calc",
    "word": "winword",
    "excel": "excel",
    "powerpoint": "powerpnt",
    "cmd": "cmd",
    "terminal": "cmd",
    "powershell": "powershell",
    "discord": "Discord",
    "steam": "steam",
    "slack": "slack",
    "telegram": "Telegram",
}


_WEBSITE_MAP = {
    "google": "https://www.google.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "facebook": "https://www.facebook.com",
    "instagram": "https://www.instagram.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "linkedin": "https://www.linkedin.com",
    "whatsapp": "https://web.whatsapp.com",
    "netflix": "https://www.netflix.com",
    "wikipedia": "https://www.wikipedia.org",
    "chatgpt": "https://chatgpt.com",
    "openai": "https://openai.com",
}

_FOLDER_ALIASES = {
    "descargas": "downloads",
    "downloads": "downloads",
    "download":  "downloads",
    "documentos": "documents",
    "documents":  "documents",
    "escritorio":  "desktop",
    "desktop":     "desktop",
    "musica":  "music",
    "music":   "music",
    "videos":  "videos",
    "imagenes": "pictures",
    "pictures":  "pictures",
}

_FOLDER_PATHS = {
    "downloads": ("USERPROFILE", "Downloads"),
    "documents": ("USERPROFILE", "Documents"),
    "desktop":   ("USERPROFILE", "Desktop"),
    "music":     ("USERPROFILE", "Music"),
    "videos":    ("USERPROFILE", "Videos"),
    "pictures":  ("USERPROFILE", "Pictures"),
}

_INSTALL_ROOTS = [
    r"C:\Program Files",
    r"C:\Program Files (x86)",
    r"C:\Program Files\Epic Games",
    r"C:\Program Files (x86)\Epic Games",
    r"C:\Program Files\Steam\steamapps\common",
    r"C:\Program Files (x86)\Steam\steamapps\common",
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "Downloads"),
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "Desktop"),
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "Documents"),
]


def _tokens_match(name: str, token: str) -> bool:
    """Compara dos nombres ignorando mayusculas, puntuacion y espacios."""
    name_l = name.lower()
    name_c = re.sub(r"[^a-z0-9]", "", name_l)
    token_l = str(token).lower()
    if not name_c or not token_l:
        return False
    if token_l == name_l or name_l in token_l:
        return True
    token_c = re.sub(r"[^a-z0-9]", "", token_l)
    return bool(token_c) and (name_c == token_c or name_c in token_c)


def _resolve_folder(name: str) -> str | None:
    key = _FOLDER_ALIASES.get(name.lower().strip())
    if key is None:
        return None
    env_key, sub = _FOLDER_PATHS[key]
    folder = os.path.join(os.environ.get(env_key, ""), sub)
    return folder if os.path.isdir(folder) else None


def _find_installed_app(name: str) -> str | None:
    name_l = name.lower()
    name_compact = re.sub(r"[^a-z0-9]", "", name_l)
    if not name_compact:
        return None

    fallback = None
    visited = set()
    for root in _INSTALL_ROOTS:
        root = os.path.expandvars(root)
        if not root or not os.path.isdir(root) or root in visited:
            continue
        visited.add(root)
        base_depth = root.rstrip(os.sep).count(os.sep)
        for dirpath, dirnames, files in os.walk(root):
            depth = dirpath.rstrip(os.sep).count(os.sep) - base_depth
            if depth > 5:
                dirnames[:] = []
                continue
            dir_matches = _tokens_match(name, os.path.basename(dirpath))
            for f in files:
                if not f.lower().endswith(".exe"):
                    continue
                path = os.path.join(dirpath, f)
                if _tokens_match(name, os.path.splitext(f)[0]):
                    return path
                if fallback is None and dir_matches:
                    fallback = path
    return fallback


_START_MENU_ROOTS = [
    os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs"),
    os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"), "Microsoft", "Windows", "Start Menu", "Programs"),
    os.path.join(os.environ.get("USERPROFILE", "C:\\Users"), "Desktop"),
]


def _find_start_menu_shortcut(name: str) -> str | None:
    for root in _START_MENU_ROOTS:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirs, files in os.walk(root):
            for f in files:
                if not f.lower().endswith(".lnk"):
                    continue
                stem = os.path.splitext(f)[0]
                if _tokens_match(name, stem):
                    return os.path.join(dirpath, f)
    return _find_shortcut_by_target(name)


def _find_shortcut_by_target(name: str) -> str | None:
    """Busca accesos directos leyendo su destino interno (TargetPath)."""
    script = r'''
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$roots = @(
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs",
  "$env:PROGRAMDATA\Microsoft\Windows\Start Menu\Programs",
  "$env:USERPROFILE\Desktop"
)
$shell = New-Object -ComObject WScript.Shell
Get-ChildItem -Path $roots -Recurse -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {
  $t = $shell.CreateShortcut($_.FullName).TargetPath
  if ($t) { Write-Output ($t + [char]9 + $_.FullName) }
}
'''
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=30,
        )
    except Exception as e:
        logger.warning("No se pudieron leer accesos directos: %s", e)
        return None

    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        target, link = parts
        if _tokens_match(name, target):
            return link
    return None


def _find_registered_app(name: str) -> str | None:
    if winreg is None:
        return None
    base = name.lower()
    for hive, root in (
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ):
        try:
            with winreg.OpenKey(hive, root) as key:
                count = winreg.QueryInfoKey(key)[0]
                for i in range(count):
                    try:
                        sub = winreg.EnumKey(key, i)
                        if sub.lower().startswith(base):
                            with winreg.OpenKey(key, sub) as subkey:
                                value, _ = winreg.QueryValueEx(subkey, "")
                                if value and os.path.exists(value):
                                    return value
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def _resolve_app(exe: str) -> str | None:
    """Resuelve una app a un path lanzable.

    Orden: PATH -> Menú Inicio -> App Paths del registro -> escaneo de
    directorios de instalación comunes (juegos incluidos).
    """
    base = os.path.splitext(exe)[0]
    found = shutil.which(exe) or shutil.which(f"{base}.exe")
    if found:
        return found

    shortcut = _find_start_menu_shortcut(base)
    if shortcut:
        return shortcut

    registered = _find_registered_app(base)
    if registered:
        return registered

    return _find_installed_app(base)


@register_tool("open_application")
def _open_application(app_name: str) -> dict:
    key = app_name.lower().strip()

    if os.path.isfile(app_name):
        try:
            os.startfile(app_name)
            return {"status": "success", "message": f"Abrí {app_name}"}
        except Exception as e:
            return {"error": f"No pude abrir {app_name}: {e}"}

    folder = _resolve_folder(key)
    if folder:
        try:
            os.startfile(folder)
            return {"status": "success", "message": f"Abrí la carpeta {app_name}"}
        except Exception as e:
            return {"error": f"No pude abrir la carpeta: {e}"}

    if key in _WEBSITE_MAP:
        try:
            webbrowser.open(_WEBSITE_MAP[key])
            return {"status": "success", "message": f"Abrí {app_name} en el navegador"}
        except Exception as e:
            return {"error": f"No pude abrir {app_name}: {e}"}

    exe = _APP_MAP.get(key, key)

    target = _resolve_app(exe)
    if not target:
        return {"status": "error", "message": f"No encontré la aplicación '{app_name}'"}

    try:
        os.startfile(target)
        return {"status": "success", "message": f"Abrí {app_name}"}
    except Exception as e:
        return {"error": f"No pude abrir {app_name}: {e}"}


@register_tool("close_application")
def _close_application(app_name: str) -> dict:
    if app_name.lower() == "all":
        return {"error": "Cerrar todas las apps es peligroso. Usa shutdown_pc o reinicia."}

    exe = _APP_MAP.get(app_name.lower(), app_name.lower())
    if exe == "explorer":
        return {"error": "No cierro el explorador de archivos, podría causar problemas."}

    target = exe if exe.lower().endswith(".exe") else f"{exe}.exe"
    try:
        result = subprocess.run(
            ["taskkill", "/IM", target, "/F"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return {"status": "success", "message": f"Cerré {app_name}"}
    except Exception as e:
        return {"error": f"Error cerrando {app_name}: {e}"}

    killed = _match_running_processes(app_name)
    if killed:
        return {"status": "success", "message": f"Cerré {app_name}: {', '.join(sorted(killed))}"}
    return {"error": f"No encontré {app_name} ejecutándose"}


def _match_running_processes(app_name: str) -> set[str]:
    """Busca procesos por coincidencia difusa de nombre/path del ejecutable."""
    matched = set()
    try:
        for proc in psutil.process_iter(["name", "exe"]):
            try:
                pname = proc.info.get("name") or ""
                pexe = proc.info.get("exe") or ""
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            haystack = f"{pname} {pexe} {os.path.basename(pexe)}"
            if _tokens_match(app_name, haystack):
                matched.add(pname or os.path.basename(pexe) or "proceso")
        if not matched:
            return set()
        for name in matched:
            try:
                subprocess.run(
                    ["taskkill", "/IM", name, "/F"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
            except Exception:
                continue
    except Exception:
        return set()
    return matched


@register_tool("control_volume")
def _control_volume(action: str, level: int = None) -> dict:
    if action == "set" and level is not None:
        level = max(0, min(100, level))
        ps_level = int(level * 65535 / 100)
        script = f"""
        $wshShell = New-Object -ComObject WScript.Shell
        1..50 | ForEach-Object {{$wshShell.SendKeys([char]174)}}
        for ($i=0; $i -lt {level / 2}; $i++) {{$wshShell.SendKeys([char]175)}}
        """
    elif action == "up":
        script = '(New-Object -ComObject WScript.Shell).SendKeys([char]175)'
    elif action == "down":
        script = '(New-Object -ComObject WScript.Shell).SendKeys([char]174)'
    elif action == "mute":
        script = '(New-Object -ComObject WScript.Shell).SendKeys([char]173)'
    elif action == "unmute":
        script = '(New-Object -ComObject WScript.Shell).SendKeys([char]173)'
    else:
        return {"error": f"Acción de volumen no válida: {action}"}

    try:
        subprocess.run(
            ["powershell", "-Command", script],
            capture_output=True,
            timeout=5,
        )
        msg = f"Volumen: {action}"
        if action == "set" and level is not None:
            msg += f" a {level}%"
        return {"status": "success", "message": msg}
    except Exception as e:
        return {"error": f"Error controlando volumen: {e}"}


@register_tool("shutdown_pc")
def _shutdown_pc(mode: str = None) -> dict:
    default = str(get_config().get("power", {}).get("shutdown_mode", "sleep")).lower()
    chosen = (mode or default or "sleep").lower()

    try:
        if chosen in ("off", "poweroff", "real", "full", "apagar"):
            subprocess.Popen(["shutdown", "/s", "/t", "60", "/c", "JARVIS apagando la PC en 60 segundos"])
            return {"status": "success", "message": "La PC se apagará de verdad en 60 segundos. Para cancelar: shutdown /a"}
        subprocess.Popen(["rundll32", "powrprof.dll,SetSuspendState", "0,1,0"])
        return {
            "status": "success",
            "message": "La PC se está SUSPENDIENDO (podras encenderla con wake-on-LAN).",
        }
    except Exception as e:
        return {"error": f"Error aplicando {chosen}: {e}"}


@register_tool("restart_pc")
def _restart_pc() -> dict:
    try:
        subprocess.Popen(["shutdown", "/r", "/t", "60", "/c", "JARVIS reiniciando la PC en 60 segundos"])
        return {"status": "success", "message": "PC se reiniciará en 60 segundos. Para cancelar: shutdown /a"}
    except Exception as e:
        return {"error": f"Error reiniciando PC: {e}"}

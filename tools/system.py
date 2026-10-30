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

# Perfiles de Chrome para cada cuenta de Gmail.
# Cada perfil mantiene su propia sesion iniciada, asi se puede abrir la
# cuenta correcta sin hacer login cada vez.
CHROME_USER_DATA = os.path.expandvars(
    r"%LOCALAPPDATA%\Google\Chrome\User Data"
)

GMAIL_PROFILES = {
    "cristopherguevara2006@gmail.com": ("Principal", "Default"),
    "cristopherguevara456@gmail.com": ("Secundaria", "Profile 5"),
    "70597122@continental.edu.pe": ("Institucional", "Profile 2"),
    "cristopher.guevara.dev@gmail.com": ("Profesional", "Profile 7"),
}

# Alias amigables -> correo de la cuenta
GMAIL_ALIASES = {
    "gmail principal": "cristopherguevara2006@gmail.com",
    "gmail personal": "cristopherguevara2006@gmail.com",
    "mi gmail": "cristopherguevara2006@gmail.com",
    "gmail secundaria": "cristopherguevara456@gmail.com",
    "gmail personal secundaria": "cristopherguevara456@gmail.com",
    "gmail institucional": "70597122@continental.edu.pe",
    "correo institucional": "70597122@continental.edu.pe",
    "universidad": "70597122@continental.edu.pe",
    "continental": "70597122@continental.edu.pe",
    "gmail profesional": "cristopher.guevara.dev@gmail.com",
    "correo profesional": "cristopher.guevara.dev@gmail.com",
    "trabajo": "cristopher.guevara.dev@gmail.com",
    "dev": "cristopher.guevara.dev@gmail.com",
}


def _detectar_cuenta_gmail(texto: str) -> str | None:
    """Detecta qué cuenta de Gmail pide el usuario en 'texto'.

    Prioridad:
      1. Match exacto del texto con un alias o correo conocido.
      2. El correo completo aparece como subcadena del texto.
      3. El alias más largo (más específico) que aparezca como subcadena.
    """
    key = texto.lower().strip()

    # 1. Match exacto
    if key in GMAIL_ALIASES:
        return GMAIL_ALIASES[key]
    if key in GMAIL_PROFILES:
        return key

    # 2. El correo completo está contenido en la frase
    for correo in GMAIL_PROFILES:
        if correo in key:
            return correo

    # 3. Alias más largo (más específico) que aparezca como subcadena
    mejor_alias = None
    mejor_len = 0
    for alias, correo in GMAIL_ALIASES.items():
        if alias in key and len(alias) > mejor_len:
            mejor_alias = correo
            mejor_len = len(alias)
    if mejor_alias:
        return mejor_alias

    return None


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

# Ultima carpeta abierta con open_vscode_folder. La usan opencode_code y
# opencode_code_visual como directorio/ventana por defecto, para que las
# tareas de programacion caigan en el proyecto que el usuario acaba de abrir
# (y no en la carpeta del proyecto JARVIS).
_LAST_VSCODE_FOLDER: dict | None = None


def last_vscode_folder(max_age_seconds: int = 1800) -> str | None:
    """Devuelve la ultima carpeta abierta con open_vscode_folder (si es
    reciente y sigue existiendo). None si no hay ninguna valida."""
    import time as _t

    info = _LAST_VSCODE_FOLDER
    if not info:
        return None
    try:
        if _t.time() - float(info.get("ts") or 0) > max_age_seconds:
            return None
        path = info.get("path")
        if not path or not os.path.isdir(path):
            return None
        return path
    except Exception:
        return None


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


# Raíces donde buscar carpetas arbitrarias por nombre (proyectos, trabajo,
# etc.). Se completa con extra_project_roots de config.json si existe.
def _folder_search_roots() -> list[str]:
    roots = []
    user_profile = os.environ.get("USERPROFILE", "")
    if user_profile:
        roots.extend([
            user_profile,
            os.path.join(user_profile, "Documents"),
            os.path.join(user_profile, "Desktop"),
            os.path.join(user_profile, "Downloads"),
        ])
    for extra in (get_config().get("paths", {}) or {}).get("extra_project_roots", []):
        if extra and extra not in roots:
            roots.append(extra)
    # Carpetas comunes de proyectos (ingenieria, trabajos, etc.) para encontrar
    # proyectos anidados mas rapidamente sin tener que caminar todo el disco.
    documents = os.path.join(user_profile, "Documents")
    for sub in (
        "Proyectos",
        "Proyectos-Ingenieria-Sistemas",
        "Proyectos-Ingenieria-Sistemas/Personales",
        "Projects",
    ):
        cand = os.path.join(documents, *sub.split("/"))
        if os.path.isdir(cand) and cand not in roots:
            roots.append(cand)
    # Raíces de unidad como último recurso (búsqueda superficial).
    for drive in ("C:", "D:"):
        if os.path.isdir(drive) and drive not in roots:
            roots.append(drive)
    return roots


def _extraer_nombre_carpeta(texto: str) -> str | None:
    """Si el usuario pide abrir una carpeta, devuelve el nombre real de la
    carpeta (sin palabras de relleno como 'la', 'carpeta', 'del', 'de',
    'proyecto', 'mi', etc.) o None si no pide abrir una carpeta.

    Ejemplos:
      "abre la carpeta del proyecto jarvis" -> "jarvis"
      "abre el directorio de descargas"     -> "descargas"
      "abre spotify"                        -> None (no pide carpeta)
    """
    import re as _re

    t = texto.lower().strip()
    if not ("carpeta" in t or "directorio" in t):
        return None

    filler = {
        "abre", "abrir", "la", "el", "las", "los", "una", "un",
        "carpeta", "directorio", "del", "de", "proyecto",
        "mi", "mis", "en", "explorador", "archivo", "archivos",
    }
    # Separar en tokens y quitar solo palabras completas de relleno, para no
    # romper nombres como "documentos" (contiene "de") ni "descargas".
    tokens = _re.findall(r"[a-z0-9]+", t)
    nombre = " ".join(tok for tok in tokens if tok not in filler)
    if not nombre:
        return None
    return nombre


def _tokens_match_folder(name: str, token: str) -> bool:
    """Compara nombres de carpeta ignorando mayusculas, puntuacion y espacios.

    El termino de busqueda (token) debe estar contenido en el nombre de la
    carpeta (no al revés), para evitar falsos positivos como que "R" coincida
    con "weirdthing".
    """
    name_l = name.lower()
    name_c = re.sub(r"[^a-z0-9]", "", name_l)
    token_l = str(token).lower()
    if not name_c or not token_l:
        return False
    if token_l == name_l or token_l in name_l:
        return True
    token_c = re.sub(r"[^a-z0-9]", "", token_l)
    return bool(token_c) and (name_c == token_c or token_c in name_c)


def _find_folder(name: str, max_depth: int = 8) -> str | None:
    """Busca una carpeta por nombre en ubicaciones comunes del usuario.

    Devuelve la ruta de la carpeta si la encuentra, None si no.
    La busqueda es superficial (max_depth) para no recorrer todo el disco.
    """
    token = name.strip()
    if not token:
        return None

    # Si ya es una ruta directa y existe como carpeta, usarla.
    if os.path.isdir(token):
        return token

    # Si tiene separadores de ruta, intentar como ruta relativa desde el usuario.
    if os.sep in token or "/" in token:
        candidate = os.path.join(os.environ.get("USERPROFILE", ""), token)
        if os.path.isdir(candidate):
            return candidate

    exact_matches: list[str] = []
    partial_matches: list[str] = []

    for root in _folder_search_roots():
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, _files in os.walk(root):
                depth = dirpath.rstrip(os.sep).count(os.sep) - root.rstrip(os.sep).count(os.sep)
                if depth > max_depth:
                    dirnames[:] = []
                    continue
                # Verificar si el nombre del directorio actual coincide con el token.
                if _tokens_match_folder(os.path.basename(dirpath), token):
                    full = dirpath
                    if _tokens_match_folder(os.path.basename(dirpath), token) and (
                        re.sub(r"[^a-z0-9]", "", os.path.basename(dirpath).lower())
                        == re.sub(r"[^a-z0-9]", "", token.lower())
                    ):
                        exact_matches.append(full)
                    else:
                        partial_matches.append(full)
                # Verificar subcarpetas.
                for d in dirnames:
                    if _tokens_match_folder(d, token):
                        full = os.path.join(dirpath, d)
                        if _tokens_match_folder(d, token) and (
                            re.sub(r"[^a-z0-9]", "", d.lower())
                            == re.sub(r"[^a-z0-9]", "", token.lower())
                        ):
                            exact_matches.append(full)
                        else:
                            partial_matches.append(full)
        except OSError:
            continue

    # Preferir coincidencia exacta, luego la mas corta (mas cercana a la raiz).
    if exact_matches:
        exact_matches.sort(key=len)
        return exact_matches[0]
    if partial_matches:
        partial_matches.sort(key=len)
        return partial_matches[0]
    return None


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

    Si el resultado es un acceso directo (.lnk), se resuelve a su target real
    para que los argumentos de línea de comandos (--profile-directory, etc.)
    lleguen al ejecutable y no se pierdan.
    """
    base = os.path.splitext(exe)[0]
    found = shutil.which(exe) or shutil.which(f"{base}.exe")
    if found:
        return found

    shortcut = _find_start_menu_shortcut(base)
    if shortcut:
        if shortcut.lower().endswith(".lnk"):
            resolved = _resolve_lnk_target(shortcut)
            if resolved:
                return resolved
        return shortcut

    registered = _find_registered_app(base)
    if registered:
        return registered

    return _find_installed_app(base)


def _resolve_lnk_target(lnk_path: str) -> str | None:
    """Lee un acceso directo .lnk y devuelve su TargetPath real."""
    script = r'''
[Console]::OutputEncoding=[Text.Encoding]::UTF8
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut("LNK_PATH")
if ($shortcut.TargetPath) { Write-Output $shortcut.TargetPath }
'''
    script = script.replace("LNK_PATH", lnk_path)
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            timeout=15,
        )
        target = proc.stdout.decode("utf-8", errors="replace").strip()
        return target if target and os.path.exists(target) else None
    except Exception as e:
        logger.warning("No se pudo resolver acceso directo %s: %s", lnk_path, e)
        return None


@register_tool("open_application")
def _open_application(app_name: str) -> dict:
    key = app_name.lower().strip()

    # --- Soporte para cuentas de Gmail con perfil de Chrome dedicado ---
    cuenta = _detectar_cuenta_gmail(key)

    if cuenta:
        perfil_nombre, perfil_dir = GMAIL_PROFILES[cuenta]
        profile_dir = os.path.join(CHROME_USER_DATA, perfil_dir)
        if not os.path.isdir(profile_dir):
            return {
                "status": "error",
                "message": (
                    f"No encontré el perfil de Chrome '{perfil_dir}' para "
                    f"{cuenta}. Verifica que exista en tu PC."
                ),
            }
        chrome_exe = _resolve_app("chrome")
        if not chrome_exe:
            return {
                "status": "error",
                "message": "No encontré Google Chrome instalado en tu PC.",
            }
        try:
            subprocess.Popen(
                [
                    chrome_exe,
                    "--new-window",
                    f"--user-data-dir={CHROME_USER_DATA}",
                    f"--profile-directory={perfil_dir}",
                    "https://mail.google.com",
                ],
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return {
                "status": "success",
                "message": f"Abrí Gmail ({cuenta}) con el perfil '{perfil_nombre}' de Chrome.",
            }
        except Exception as e:
            return {"error": f"No pude abrir Gmail con el perfil {perfil_nombre}: {e}"}

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
            return {
                "status": "success",
                "message": f"Abrí la carpeta {app_name} en el explorador de archivos.",
            }
        except Exception as e:
            return {"error": f"No pude abrir la carpeta {app_name}: {e}"}

    # --- Detección de "abrir carpeta": extraer el nombre real de la carpeta ---
    # El usuario puede decir "abre la carpeta del proyecto jarvis", "abre el
    # directorio de descargas", etc. Aquí quitamos palabras de relleno para
    # buscar solo el nombre de la carpeta y abrirla en el explorador.
    folder_name = _extraer_nombre_carpeta(app_name)
    if folder_name:
        found_folder = _find_folder(folder_name)
        if found_folder:
            try:
                subprocess.Popen(
                    ["explorer", found_folder],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return {
                    "status": "success",
                    "message": (
                        f"Abrí la carpeta '{os.path.basename(found_folder)}' "
                        f"en el explorador de archivos."
                    ),
                }
            except Exception as e:
                return {"error": f"No pude abrir la carpeta '{found_folder}': {e}"}

    if key in _WEBSITE_MAP:
        try:
            webbrowser.open(_WEBSITE_MAP[key])
            return {"status": "success", "message": f"Abrí {app_name} en el navegador"}
        except Exception as e:
            return {"error": f"No pude abrir {app_name}: {e}"}

    exe = _APP_MAP.get(key, key)

    target = _resolve_app(exe)
    if not target:
        # Antes de rendirse, buscar si es una carpeta arbitraria (proyecto,
        # trabajo, etc.) en lugar de una aplicación.
        found_folder = _find_folder(key)
        if found_folder:
            try:
                subprocess.Popen(
                    ["explorer", found_folder],
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
                return {
                    "status": "success",
                    "message": (
                        f"Abrí la carpeta '{os.path.basename(found_folder)}' "
                        f"en el explorador de archivos."
                    ),
                }
            except Exception as e:
                return {"error": f"No pude abrir la carpeta '{found_folder}': {e}"}
        return {"status": "error", "message": f"No encontré la aplicación '{app_name}'"}

    try:
        os.startfile(target)
        return {"status": "success", "message": f"Abrí {app_name}"}
    except Exception as e:
        return {"error": f"No pude abrir {app_name}: {e}"}


def _vscode_user_settings_paths() -> list[str]:
    """Rutas candidatas de settings.json de VS Code (estable e Insiders)."""
    appdata = os.environ.get("APPDATA", "")
    paths = []
    for sub in ("Code", "Code - Insiders"):
        paths.append(os.path.join(appdata, sub, "User", "settings.json"))
    return paths


def _vscode_edit_settings(updates: dict) -> bool:
    """Aplica cambios a settings.json de VS Code (idempotente).

    Devuelve True si al menos un archivo se modifico (o ya tenia los valores).
    """
    import json as _json
    import re as _re

    ok_any = False
    for settings_path in _vscode_user_settings_paths():
        try:
            os.makedirs(os.path.dirname(settings_path), exist_ok=True)
            if not os.path.isfile(settings_path):
                # Solo escribir si el directorio de usuario existe (VS Code
                # instalado); si no, saltar.
                user_dir = os.path.dirname(settings_path)
                if not os.path.isdir(user_dir):
                    continue
            data = {}
            if os.path.isfile(settings_path):
                try:
                    with open(settings_path, "r", encoding="utf-8") as fh:
                        raw = fh.read()
                    # settings.json permite comentarios: quitarlos para parsear.
                    cleaned = _re.sub(r"//.*", "", raw)
                    cleaned = _re.sub(r"/\*.*?\*/", "", cleaned, flags=_re.S)
                    data = _json.loads(cleaned) if cleaned.strip() else {}
                except Exception:
                    data = {}
            if not isinstance(data, dict):
                data = {}

            changed = False
            for key, value in updates.items():
                if data.get(key) != value:
                    data[key] = value
                    changed = True
            if not changed:
                ok_any = True
                continue

            with open(settings_path, "w", encoding="utf-8") as fh:
                _json.dump(data, fh, indent=4, ensure_ascii=False)
            ok_any = True
            logger.info("settings.json de VS Code actualizado (%s)", settings_path)
        except Exception as e:
            logger.warning("No se pudo modificar %s: %s", settings_path, e)
    return ok_any


def _disable_vscode_workspace_trust() -> bool:
    """Desactiva el Restricted Mode (Workspace Trust) en settings.json de VS Code.

    Devuelve True si se modifico (o ya estaba desactivado), False si no se
    pudo (VS Code no instalado o error de IO).
    """
    return _vscode_edit_settings({"security.workspace.trust.enabled": False})


def _disable_vscode_terminal_restore() -> bool:
    """Evita que VS Code restaure terminales (el chat de OpenCode) al abrir.

    VS Code guarda las terminales de la sesion anterior y las reabre solo
    al entrar a un proyecto; esto lo desactiva para que el chat solo se
    abra cuando JARVIS presiona el atajo.
    """
    return _vscode_edit_settings({"terminal.integrated.enablePersistentSessions": False})


def _vscode_set_keybind(command: str, key: str) -> bool:
    """Configura un keybind en keybindings.json de VS Code.

    Quita entradas previas del mismo comando con otra tecla y agrega la
    nueva. Idempotente.
    """
    import json as _json

    appdata = os.environ.get("APPDATA", "")
    ok = False
    for sub in ("Code", "Code - Insiders"):
        kb_path = os.path.join(appdata, sub, "User", "keybindings.json")
        user_dir = os.path.dirname(kb_path)
        if not os.path.isdir(user_dir):
            continue
        try:
            os.makedirs(user_dir, exist_ok=True)
            bindings = []
            if os.path.isfile(kb_path):
                try:
                    with open(kb_path, "r", encoding="utf-8") as fh:
                        raw = fh.read()
                    import re as _re
                    cleaned = _re.sub(r"//.*", "", raw)
                    cleaned = _re.sub(r"/\*.*?\*/", "", cleaned, flags=_re.S)
                    bindings = _json.loads(cleaned) if cleaned.strip() else []
                except Exception:
                    bindings = []
            if not isinstance(bindings, list):
                bindings = []

            # Quitar entradas previas del mismo comando con otra tecla y
            # cualquier entrada que ya use esta tecla para otro comando.
            new_bindings = []
            for entry in bindings:
                if not isinstance(entry, dict):
                    new_bindings.append(entry)
                    continue
                if entry.get("command") == command or entry.get("key") == key:
                    continue
                new_bindings.append(entry)

            new_bindings.append({"key": key, "command": command})

            with open(kb_path, "w", encoding="utf-8") as fh:
                _json.dump(new_bindings, fh, indent=4, ensure_ascii=False)
            ok = True
            logger.info("Keybind '%s' -> %s en %s", key, command, kb_path)
        except Exception as e:
            logger.warning("No se pudo modificar %s: %s", kb_path, e)
    return ok


@register_tool("open_vscode_folder")
def _open_vscode_folder(folder_name: str) -> dict:
    """Abre Visual Studio Code en una carpeta existente de la PC.

    Busca la carpeta por nombre en el escritorio, documentos, descargas y
    OneDrive, y lanza 'code "ruta"' para que VS Code abra ESA carpeta (no
    solo VS Code vacio).
    """
    name = (folder_name or "").strip()
    if not name:
        return {"error": "Falta el nombre de la carpeta a abrir en VS Code"}

    # Candidatos de base donde suelen estar las carpetas del usuario.
    # Incluye la carpeta de proyectos de ingenieria y sus subcarpetas.
    bases = []
    up = os.environ.get("USERPROFILE", "")
    candidate_subs = [
        "Desktop",
        "Documents",
        "Downloads",
        "OneDrive\\Desktop",
        "OneDrive\\Documents",
        "Documents\\Proyectos-Ingenieria-Sistemas",
        "Documents\\Proyectos-Ingenieria-Sistemas\\Personales",
        "Documents\\Proyectos",
        "Documents\\Projects",
    ]
    for sub in candidate_subs:
        p = os.path.join(up, sub)
        if os.path.isdir(p):
            bases.append(p)

    # También bases adicionales configuradas (config.json -> paths.extra_project_roots)
    try:
        extra = get_config().get("paths", {}).get("extra_project_roots", []) or []
        for e in extra:
            if isinstance(e, str) and os.path.isdir(e):
                bases.append(e)
    except Exception:
        pass

    # Deduplicar bases.
    seen_bases = set()
    uniq_bases = []
    for b in bases:
        nb = os.path.normpath(b).lower()
        if nb in seen_bases:
            continue
        seen_bases.add(nb)
        uniq_bases.append(b)
    bases = uniq_bases

    # 1) Coincidencia exacta / por tokens en el primer nivel de cada base.
    candidates = []
    for base in bases:
        try:
            for item in os.listdir(base):
                if _tokens_match(name, item):
                    full = os.path.join(base, item)
                    if os.path.isdir(full):
                        candidates.append(full)
        except OSError:
            continue

    # 2) Si no hubo coincidencia directa, busqueda recursiva mas profunda.
    if not candidates:
        name_compact = re.sub(r"[^a-z0-9]", "", name.lower())
        _skip = {"node_modules", ".git", "__pycache__", "venv", ".venv", ".idea", ".vscode", "dist", "build", "target"}
        for base in bases:
            for root, dirs, _files in os.walk(base):
                depth = root.count(os.sep) - base.count(os.sep)
                if depth > 5:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if d.lower() not in _skip]
                for d in list(dirs):
                    dc = re.sub(r"[^a-z0-9]", "", d.lower())
                    if _tokens_match(name, d) or dc == name_compact or name_compact in dc:
                        full = os.path.join(root, d)
                        if os.path.isdir(full):
                            candidates.append(full)
                            dirs.remove(d)
                if candidates:
                    break
            if candidates:
                break

    if not candidates:
        return {
            "status": "error",
            "message": f"No encontre una carpeta llamada '{name}' en el escritorio/documentos/descargas.",
        }

    # Preferir la coincidencia mas corta (mas cercana a la raiz).
    candidates.sort(key=lambda p: (p.count(os.sep), len(p)))
    chosen = candidates[0]

    try:
        subprocess.Popen(["code", chosen], shell=True)
    except Exception as e:
        return {"error": f"No pude abrir VS Code en '{chosen}': {e}"}

    # Recordar la carpeta: opencode_code la usara como directory por defecto
    # y opencode_code_visual como pista de ventana, para que las tareas
    # caigan en el proyecto que el usuario acaba de abrir.
    import time as _ts

    global _LAST_VSCODE_FOLDER
    _LAST_VSCODE_FOLDER = {"path": chosen, "ts": _ts.time()}

    # Flujo automatico al entrar al proyecto:
    # 1) Restricted Mode desactivado permanente (settings.json).
    # 2) No restaurar terminales de la sesion anterior (evita que el chat
    #    de OpenCode se abra solo al entrar; el welcome page sigue igual).
    # 3) Keybind Ctrl+Shift+Alt+O -> opencode.openTerminal (si no existe).
    # 4) Esperar 4s a que VS Code cargue y presionar el atajo para abrir
    #    la extension de OpenCode.
    trust_ok = _disable_vscode_workspace_trust()
    _disable_vscode_terminal_restore()
    _vscode_set_keybind("opencode.openTerminal", "ctrl+shift+alt+o")

    import time as _t
    _t.sleep(2.0)

    # Enfocar la ventana de VS Code antes de mandar el atajo: si otra
    # ventana tiene el foco, el hotkey no llegaria a VS Code y podria
    # quedar "escrito" en otra parte.
    try:
        from tools.window_tools import _activate_window

        folder_title = os.path.basename(chosen)
        activated = None
        for attempt_title in (folder_title, "Visual Studio Code"):
            result = _activate_window(attempt_title)
            if isinstance(result, dict) and result.get("status") == "success":
                activated = result.get("title")
                break
        if activated:
            logger.info("Ventana de VS Code enfocada: %s", activated)
        _t.sleep(0.8)
    except Exception as e:
        logger.warning("No se pudo enfocar VS Code antes del atajo: %s", e)

    try:
        import pyautogui as _pg
        _pg.hotkey("ctrl", "shift", "alt", "o")
        _t.sleep(2.0)
    except Exception as e:
        logger.warning("No se pudo enviar el atajo de OpenCode: %s", e)

    # Segundo envío del atajo tras 8 segundos
    _t.sleep(8.0)
    try:
        import pyautogui as _pg
        _pg.hotkey("ctrl", "shift", "alt", "o")
        _t.sleep(2.0)
    except Exception as e2:
        logger.warning("No se pudo enviar el segundo atajo de OpenCode: %s", e2)

    msg = f"Abri VS Code en la carpeta: {chosen}."
    if trust_ok:
        msg += " Restricted Mode desactivado y OpenCode lanzado con Ctrl+Shift+Alt+O."
    else:
        msg += " OpenCode lanzado con Ctrl+Shift+Alt+O (no pude tocar settings.json)."
    return {
        "status": "success",
        "message": msg,
        "path": chosen,
        "trust_disabled": trust_ok,
        "opencode_launched": True,
    }


@register_tool("vscode_disable_restricted_mode")
def _vscode_disable_restricted_mode() -> dict:
    """Desactiva el Restricted Mode (Workspace Trust) en VS Code de forma
    permanente, editando settings.json. Util cuando el usuario quiere que las
    extensiones (OpenCode) se ejecuten sin pedir confianza.
    """
    ok = _disable_vscode_workspace_trust()
    if ok:
        return {
            "status": "success",
            "message": "Restricted Mode desactivado en VS Code. Reinicia VS Code para que tome efecto.",
        }
    return {
        "status": "error",
        "message": "No encontre settings.json de VS Code (¿esta instalado?) o no pude modificarlo.",
    }

@register_tool("close_application")
def _close_application(app_name: str) -> dict:
    if app_name.lower() == "all":
        return {"error": "Cerrar todas las apps es peligroso. Usa shutdown_pc o reinicia."}

    exe = _APP_MAP.get(app_name.lower(), app_name.lower())
    if exe == "explorer":
        # No matar explorer.exe entero (cerraría el escritorio). En su lugar,
        # intentamos cerrar ventanas del Explorador por titulo (carpetas
        # abiertas, etc.).
        return _close_explorer_windows_by_title(app_name)

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

    # Ultimo recurso: intentar cerrar ventanas cuyo titulo coincida (carpetas,
    # navegador, etc. que no tienen un proceso propio distinto).
    return _close_explorer_windows_by_title(app_name)


def _close_explorer_windows_by_title(app_name: str) -> dict:
    """Cierra ventanas visibles cuyo titulo contenga el nombre pedido.

    Se usa para carpetas del Explorador de Archivos (Documentos, Descargas,
    proyectos...) y cualquier ventana que no tenga un proceso propio que
    podamos matar con taskkill.
    """
    try:
        import pygetwindow as gw
    except ImportError:
        return {"error": f"No encontré {app_name} ejecutándose (y no puedo leer ventanas)."}

    try:
        windows = gw.getAllWindows()
    except Exception as e:
        return {"error": f"No se pudieron listar ventanas: {e}"}

    needle = app_name.lower().strip()
    closed = []
    for win in windows:
        try:
            title = (win.title or "").strip()
        except Exception:
            continue
        if not title:
            continue
        low = title.lower()
        # Saltar ruido del sistema
        if low in {
            "", "program manager", "windows input experience",
            "microsoft text input application", "search", "sysfloatingpopup",
            "windows.ui.core.corewindow", "shell_traywnd",
        }:
            continue
        # Coincidencia: el nombre pedido esta en el titulo de la ventana
        if needle in low or low in needle:
            try:
                win.close()
                closed.append(title)
            except Exception:
                continue

    if closed:
        return {
            "status": "success",
            "message": f"Cerré {len(closed)} ventana(s): {', '.join(closed)}",
        }
    return {"error": f"No encontré {app_name} ejecutándose ni ninguna ventana con ese título."}


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

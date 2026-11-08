"""Dismiss Lock Screen - Script que presiona Enter automaticamente al despertar.

Se ejecuta en segundo plano desde el inicio de Windows. Detecta cuando la PC
despierta de hibernacion/suspension y envia un Enter para descartar la
pantalla de bloqueo (lock screen), permitiendo acceso directo al escritorio.

Uso:
    python dismiss_lockscreen.py          -> ejecutar en primer plano (ver logs)
    pythonw dismiss_lockscreen.py         -> ejecutar en segundo plano (sin consola)

Para que arranque automaticamente con Windows, usa el VBS:
    "Iniciar Dismiss Lockscreen.vbs"
"""
import ctypes
import ctypes.wintypes
import threading
import time
import os
import sys
from pathlib import Path

# --- Configuracion ---
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "dismiss_lockscreen.log"
WAIT_AFTER_WAKE = 5.0  # segundos a esperar antes de enviar Enter
RETRY_DELAY = 2.0     # segundos entre reintentos
MAX_RETRIES = 5        # numero de reintentos

# --- Constantes de Windows ---
WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012
PBT_APMRESUMESUSPEND = 0x0007
PBT_APMRESUMECRITICAL = 0x0006

VK_RETURN = 0x0D
KEYEVENTF_KEYUP = 0x0002

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Configurar tipos para 64-bit
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
kernel32.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]

kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
kernel32.GetLastError.restype = ctypes.c_uint32

user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.DefWindowProcW.argtypes = [
    ctypes.c_void_p,  # HWND
    ctypes.c_uint,    # UINT
    ctypes.c_size_t,  # WPARAM
    ctypes.c_ssize_t, # LPARAM
]

user32.CreateWindowExW.restype = ctypes.c_void_p
user32.CreateWindowExW.argtypes = [
    ctypes.c_uint,    # dwExStyle
    ctypes.c_wchar_p, # lpClassName
    ctypes.c_wchar_p, # lpWindowName
    ctypes.c_uint,    # dwStyle
    ctypes.c_int,     # X
    ctypes.c_int,     # Y
    ctypes.c_int,     # nWidth
    ctypes.c_int,     # nHeight
    ctypes.c_void_p,  # hWndParent
    ctypes.c_void_p,  # hMenu
    ctypes.c_void_p,  # hInstance
    ctypes.c_void_p,  # lpParam
]

user32.SendInput.restype = ctypes.c_uint
user32.SendInput.argtypes = [
    ctypes.c_uint,    # nInputs
    ctypes.c_void_p,  # pInputs
    ctypes.c_int,     # cbSize
]

user32.GetSystemMetrics.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]

user32.GetForegroundWindow.restype = ctypes.c_void_p
user32.GetForegroundWindow.argtypes = []

user32.GetWindowTextLengthW.restype = ctypes.c_int
user32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]

user32.GetWindowTextW.restype = ctypes.c_int
user32.GetWindowTextW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_int]

user32.RegisterClassW.restype = ctypes.c_ushort
user32.RegisterClassW.argtypes = [ctypes.c_void_p]


def log(msg: str):
    """Escribe en el log y en consola (si hay)."""
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:
            pass


# Constantes para SendInput
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_uint),
        ("dwFlags", ctypes.c_uint),
        ("time", ctypes.c_uint),
        ("dwExtraInfo", ctypes.c_size_t),
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_uint),
        ("union", INPUT_UNION),
    ]

def send_key(vk_code):
    """Envia una tecla via SendInput (mas confiable que keybd_event)."""
    try:
        # Key down
        inp_down = INPUT()
        inp_down.type = INPUT_KEYBOARD
        inp_down.union.ki.wVk = vk_code
        inp_down.union.ki.dwFlags = 0
        # Key up
        inp_up = INPUT()
        inp_up.type = INPUT_KEYBOARD
        inp_up.union.ki.wVk = vk_code
        inp_up.union.ki.dwFlags = KEYEVENTF_KEYUP
        # Enviar ambos
        arr = (INPUT * 2)(inp_down, inp_up)
        user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(INPUT))
        return True
    except Exception as e:
        log(f"Error enviando tecla 0x{vk_code:02X}: {e}")
        return False

VK_SPACE = 0x20

def send_enter():
    """Envia Enter + Space + clic de raton para descartar el lock screen."""
    try:
        # Intentar Enter
        log("  Enviando Enter via SendInput...")
        send_key(VK_RETURN)
        time.sleep(0.3)
        # Intentar Space
        log("  Enviando Space via SendInput...")
        send_key(VK_SPACE)
        time.sleep(0.3)
        # Intentar clic de raton (centro de pantalla)
        log("  Enviando clic de raton...")
        try:
            sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            # Mover raton al centro
            inp_move = INPUT()
            inp_move.type = INPUT_MOUSE
            inp_move.union.mi.dx = int(sw / 2 * 65535 / sw) if sw > 0 else 0
            inp_move.union.mi.dy = int(sh / 2 * 65535 / sh) if sh > 0 else 0
            inp_move.union.mi.dwFlags = 0x0001 | 0x8000  # MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            user32.SendInput(1, ctypes.byref(inp_move), ctypes.sizeof(INPUT))
            time.sleep(0.1)
            # Clic
            inp_down = INPUT()
            inp_down.type = INPUT_MOUSE
            inp_down.union.mi.dwFlags = MOUSEEVENTF_LEFTDOWN
            inp_up = INPUT()
            inp_up.type = INPUT_MOUSE
            inp_up.union.mi.dwFlags = MOUSEEVENTF_LEFTUP
            arr = (INPUT * 2)(inp_down, inp_up)
            user32.SendInput(2, ctypes.byref(arr), ctypes.sizeof(INPUT))
        except Exception as e:
            log(f"  Error en clic de raton: {e}")
        return True
    except Exception as e:
        log(f"Error en send_enter: {e}")
        return False


def get_foreground_window_title():
    """Obtiene el titulo de la ventana en primer plano."""
    try:
        hwnd = user32.GetForegroundWindow()
        if hwnd:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                return buf.value
        return "(sin titulo)"
    except Exception:
        return "(error)"

def dismiss_lockscreen():
    """Espera y envia Enter para descartar el lock screen."""
    log("Detectado despertar de hibernacion/suspension. Esperando lock screen...")
    time.sleep(WAIT_AFTER_WAKE)
    log(f"Ventana en primer plano: {get_foreground_window_title()}")

    for attempt in range(1, MAX_RETRIES + 1):
        log(f"Enviando Enter (intento {attempt}/{MAX_RETRIES})...")
        if send_enter():
            log("Enter enviado correctamente.")
            break
        time.sleep(RETRY_DELAY)
    else:
        log("No se pudo enviar Enter despues de todos los intentos.")


def wnd_proc(hwnd, msg, wparam, lparam):
    """Procesador de mensajes de la ventana oculta."""
    if msg == WM_POWERBROADCAST:
        if wparam in (PBT_APMRESUMEAUTOMATIC, PBT_APMRESUMESUSPEND, PBT_APMRESUMECRITICAL):
            log(f"Evento de despertar recibido (wParam=0x{wparam:04X}).")
            threading.Thread(target=dismiss_lockscreen, daemon=True).start()
    return user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def main():
    # Single-instance check via mutex
    mutex_name = "DismissLockScreen_SingleInstance_Mutex"
    mutex = kernel32.CreateMutexW(None, True, mutex_name)
    if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        log("Ya hay una instancia ejecutandose. Saliendo.")
        return
    log("Dismiss Lock Screen iniciado. Escuchando eventos de energia...")

    # Registrar clase de ventana
    # En Windows 64-bit, LRESULT/WPARAM/LPARAM son de 64 bits
    WNDPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t,   # LRESULT (64-bit)
        ctypes.c_void_p,     # HWND
        ctypes.c_uint,       # UINT
        ctypes.c_size_t,     # WPARAM (64-bit)
        ctypes.c_ssize_t,    # LPARAM (64-bit, signed)
    )
    wndproc_cb = WNDPROC(wnd_proc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style", ctypes.c_uint),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", ctypes.c_void_p),
            ("hIcon", ctypes.c_void_p),
            ("hCursor", ctypes.c_void_p),
            ("hbrBackground", ctypes.c_void_p),
            ("lpszMenuName", ctypes.c_wchar_p),
            ("lpszClassName", ctypes.c_wchar_p),
        ]

    wc = WNDCLASS()
    wc.lpfnWndProc = wndproc_cb
    wc.lpszClassName = "DismissLockScreenHidden"
    wc.hInstance = kernel32.GetModuleHandleW(None)

    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        log("Error: no se pudo registrar la clase de ventana.")
        return

    # Crear ventana oculta
    hwnd = user32.CreateWindowExW(
        0,
        "DismissLockScreenHidden",
        "DismissLockScreenHidden",
        0,  # WS_OVERLAPPED (sin WS_VISIBLE)
        0, 0, 0, 0,
        None, None, wc.hInstance, None,
    )
    if not hwnd:
        log("Error: no se pudo crear la ventana oculta.")
        return

    # Registrar para recibir notificaciones de energia
    # (la ventana ya recibe WM_POWERBROADCAST por defecto)

    log("Ventana oculta creada. Monitoreando despertares...")

    # Bucle de mensajes (infinito)
    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))

    log("Dismiss Lock Screen detenido.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Interrumpido por el usuario.")
    except Exception as e:
        log(f"Error fatal: {e}")
        raise
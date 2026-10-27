"""Detector de doble palmada (clap) para activar a JARVIS.

Corre un InputStream de sounddevice en segundo plano y detecta dos
transientes (palmadas) dentro de una ventana de tiempo. Al detectarlas,
invoca el callback registrado (saludo + escucha) en un hilo aparte.

Solo esta activo cuando JARVIS esta en reposo (IDLE): se pausa al grabar,
procesar o hablar, y se reanuda al volver a IDLE. Asi evita conflictos con
el microfono y reduce falsos positivos.
"""

import logging
import threading
import time

import numpy as np
import sounddevice as sd

from config import get_config, get_setting

logger = logging.getLogger("jarvis.clap")

# --- estado del modulo ---
_enabled = False
_running = False
_paused = False
_callback = None
_stream = None
_lock = threading.RLock()

_threshold = 21000          # pico minimo (int16) para considerar palmada
_min_window = 0.12         # segundos entre palmadas (min)
_max_window = 0.9          # segundos entre palmadas (max)
_cooldown = 2.5            # segundos de silencio tras disparar
_greeting = "Hola, en qué te ayudo"

_in_clap = False
_last_clap_time: float | None = None
_cooldown_until = 0.0
_sample_rate = 16000
_blocksize = 800           # 50 ms


def _settings():
    cfg = get_config().get("voice", {}) or {}
    return {
        "enabled": bool(cfg.get("clap_enabled", False)),
        "threshold": float(cfg.get("clap_threshold", 0.65)),
        "min_window": float(cfg.get("clap_double_window_min", 0.12)),
        "max_window": float(cfg.get("clap_double_window_max", 0.9)),
        "cooldown": float(cfg.get("clap_cooldown", 2.5)),
        "greeting": str(cfg.get("clap_greeting", "Hola, en qué te ayudo")),
    }


def _input_device():
    try:
        devices = sd.query_devices()
        for i, d in enumerate(devices):
            if d["max_input_channels"] > 0 and "mic" in d["name"].lower():
                return i
    except Exception as e:
        logger.error("Error buscando microfono (clap): %s", e)
    return None


def _open_stream():
    global _stream
    if _stream is not None:
        return
    device = _input_device()

    def callback(indata, frames, time_info, status):
        if status:
            logger.debug("Clap audio status: %s", status)
        if _paused or not _running or not _enabled:
            return
        try:
            peak = int(np.max(np.abs(indata)))
        except Exception:
            return
        _handle_chunk(peak, time.monotonic())

    try:
        _stream = sd.InputStream(
            samplerate=_sample_rate,
            channels=1,
            dtype="int16",
            device=device,
            callback=callback,
            blocksize=_blocksize,
        )
        _stream.start()
        logger.info("Detector de palmadas activo (device=%s, umbral=%d)", device, _threshold)
    except Exception as e:
        _stream = None
        logger.error("No pude abrir el stream de palmadas: %s", e)


def _close_stream():
    global _stream
    if _stream is None:
        return
    try:
        _stream.stop()
        _stream.close()
    except Exception as e:
        logger.debug("Error cerrando stream de palmadas: %s", e)
    _stream = None


def _handle_chunk(peak: int, now: float):
    global _in_clap, _last_clap_time, _cooldown_until
    with _lock:
        if _paused or not _running or not _enabled:
            return
        if now < _cooldown_until:
            return
        # flanco de subida: solo cuenta una palmada por transiente
        if peak >= _threshold and not _in_clap:
            _in_clap = True
            _register_clap(now)
        elif peak < _threshold // 2:
            _in_clap = False


def _register_clap(now: float):
    global _last_clap_time, _cooldown_until
    if now < _cooldown_until:
        return
    if _last_clap_time is not None and (_min_window <= now - _last_clap_time <= _max_window):
        # doble palmada
        _last_clap_time = None
        _cooldown_until = now + _cooldown
        _close_stream()  # liberar el microfono para JARVIS
        # disparar en hilo aparte para no bloquear el callback de audio
        threading.Thread(target=_fire_callback, daemon=True).start()
    else:
        _last_clap_time = now


def _fire_callback():
    try:
        if _callback:
            _callback()
    except Exception as e:
        logger.error("Error en callback de doble palmada: %s", e)


def start_clap_listener(callback):
    """Arranca el detector. callback se invoca al detectar doble palmada."""
    global _enabled, _running, _callback, _paused
    global _threshold, _min_window, _max_window, _cooldown, _greeting
    global _in_clap, _last_clap_time, _cooldown_until

    s = _settings()
    if not s["enabled"]:
        logger.info("Detector de palmadas desactivado (voice.clap_enabled=false)")
        return False

    with _lock:
        _threshold = int(32767 * s["threshold"])
        _min_window = s["min_window"]
        _max_window = s["max_window"]
        _cooldown = s["cooldown"]
        _greeting = s["greeting"]
        _in_clap = False
        _last_clap_time = None
        _cooldown_until = 0.0
        _callback = callback
        _enabled = True
        _running = True
        _paused = False

    _open_stream()
    return True


def stop_clap_listener():
    global _enabled, _running, _paused, _callback
    with _lock:
        _running = False
        _enabled = False
        _paused = False
        _callback = None
    _close_stream()
    logger.info("Detector de palmadas detenido")


def pause():
    """Pausa la captura (libera el microfono) sin desactivar el detector."""
    global _paused
    with _lock:
        if not _running or _paused:
            return
        _paused = True
    _close_stream()


def resume():
    """Reanuda la captura si el detector esta activo y pausado."""
    global _paused
    with _lock:
        if not _running or not _enabled or not _paused:
            return
        _paused = False
    _open_stream()


def is_listening() -> bool:
    return _running and _enabled


def get_greeting() -> str:
    return _greeting

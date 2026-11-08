import logging
import math
import time

import numpy as np
import sounddevice as sd
from config import get_config

logger = logging.getLogger("jarvis.audio")

_recording = False
_audio_data: list[np.ndarray] = []
_stream = None
_detector = None


class SilenceDetector:
    """Detecta el fin de una frase por silencio tras hablar.

    Umbral ADAPTATIVO AL PICO de la voz: el umbral efectivo es el mayor
    entre un suelo de sensibilidad (threshold * min_ratio) y una fraccion
    del pico reciente de la grabacion (drop_ratio). Asi:
      * funciona aunque hables bajito (por debajo del umbral absoluto):
        tu propia voz define su piso y el silencio se mide relativo a esa voz;
      * no se contamina si empiezas a hablar justo al arrancar el LISTENING
        (nada se "aprende" del primer segundo);
      * un ambiente constante muy bajo nunca dispara por si solo.
    """
    def __init__(
        self,
        threshold: float = 500,
        timeout: float = 1.2,
        min_duration: float = 0.4,
        drop_ratio: float = 0.3,
        min_ratio: float = 0.5,
        peak_decay: float = 0.6,
    ):
        self.threshold = threshold
        self.timeout = timeout
        self.min_duration = min_duration
        self.drop_ratio = drop_ratio
        self.min_ratio = min_ratio
        self.peak_decay = peak_decay
        self._was_speaking = False
        self._silence_start = None
        self._peak = 0.0
        self._last_now = None
        self._speech_logged = False

    def reset(self):
        self._was_speaking = False
        self._silence_start = None
        self._peak = 0.0
        self._last_now = None
        self._speech_logged = False

    def _effective_threshold(self) -> float:
        return max(self.threshold * self.min_ratio, self._peak * self.drop_ratio)

    def update(self, rms: float, now: float):
        if self._last_now is not None:
            dt = max(0.0, now - self._last_now)
        else:
            dt = 0.0
        self._last_now = now
        self._peak = max(rms, self._peak * math.exp(-self.peak_decay * dt))

        threshold = self._effective_threshold()
        if rms < threshold:
            if self._was_speaking and self._silence_start is None:
                self._silence_start = now
        else:
            if not self._was_speaking and not self._speech_logged:
                self._speech_logged = True
                logger.info(
                    "Voz detectada (rms=%.0f, pico=%.0f, umbral=%.0f)",
                    rms,
                    self._peak,
                    threshold,
                )
            self._was_speaking = True
            self._silence_start = None

    def is_detected(self, now: float, recorded_duration: float) -> bool:
        if self._silence_start is None:
            return False
        if recorded_duration < self.min_duration:
            return False
        return (now - self._silence_start) >= self.timeout


def _get_config():
    cfg = get_config().get("audio", {})
    return {
        "sample_rate": cfg.get("sample_rate", 16000),
        "channels": 1,
        "max_record_seconds": cfg.get("max_record_seconds", 0),
        "silence_threshold": cfg.get("silence_threshold", 500),
        "silence_timeout": cfg.get("silence_timeout", 2.0),
        "safety_max_seconds": cfg.get("safety_max_seconds", 45),
    }


def get_max_record_seconds() -> int:
    return int(_get_config()["max_record_seconds"])


def get_input_device() -> int | None:
    """Devuelve el indice del microfono a usar.

    Prioridad:
      1. Si `audio.input_device` esta configurado (substring del nombre del
         dispositivo, sin distinguir mayusculas), se usa el primer dispositivo
         de entrada cuyo nombre lo contenga. Asi se puede bloquear un mic
         concreto (ej. "Realtek") y nunca otro.
      2. Si no, el dispositivo de entrada por defecto de Windows.
      3. Respaldo: primer dispositivo con "mic" que NO sea el Sound Mapper
         generico de Microsoft (que captura con ganancia muy baja).
    """
    try:
        audio_cfg = get_config().get("audio", {}) or {}
        configured = (audio_cfg.get("input_device") or "").strip().lower()

        devices = sd.query_devices()

        # 1. Dispositivo configurado explicitamente (substring del nombre)
        if configured:
            for i, d in enumerate(devices):
                if d.get("max_input_channels", 0) <= 0:
                    continue
                if configured in (d.get("name") or "").lower():
                    logger.info(
                        "Microfono seleccionado por config: device=%d (%s)",
                        i, d.get("name"),
                    )
                    return i
            logger.warning(
                "No se encontro dispositivo de audio que contenga '%s'; "
                "usando el por defecto de Windows",
                configured,
            )

        # 2. Dispositivo de entrada por defecto de Windows
        try:
            default_input = sd.default.device[0]
            if default_input is not None and int(default_input) >= 0:
                dev = devices[int(default_input)]
                if dev.get("max_input_channels", 0) > 0:
                    name = (dev.get("name") or "").lower()
                    if "mapper" not in name:
                        logger.info(
                            "Microfono por defecto de Windows: device=%d (%s)",
                            int(default_input), dev.get("name"),
                        )
                        return int(default_input)
        except Exception:
            pass

        # 3. Respaldo: primer mic real (excluyendo Sound Mapper generico)
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) <= 0:
                continue
            name = (d.get("name") or "").lower()
            if "mapper" in name or "sound mapper" in name:
                continue
            if "mic" in name or "microphone" in name or "micrófono" in name:
                logger.info("Microfono (respaldo): device=%d (%s)", i, d.get("name"))
                return i
    except Exception as e:
        logger.error("Error buscando microfono: %s", e)
    return None


_DETECT_RMS = 500.0
_MAX_RMS = 15000.0


def _level_from_rms(rms: float) -> float:
    """Escala logaritmica 0-100 pensada para la GUI.

    Con rms = umbral de deteccion (500) marca ~15, asi la barra muestra un
    indicador en el umbral y el habla normal (1000-8000) recorre bien la
    escala en vez de quedarse pegada en 0-3%.
    """
    if rms is None or rms <= 0:
        return 0.0
    if rms <= _DETECT_RMS:
        return 15.0 * rms / _DETECT_RMS
    t = (math.log10(rms) - math.log10(_DETECT_RMS)) / (
        math.log10(_MAX_RMS) - math.log10(_DETECT_RMS)
    )
    return 15.0 + 85.0 * max(0.0, min(1.0, t))


def get_threshold_level() -> float:
    """Nivel (0-100) que corresponde al umbral de deteccion de silencio."""
    return _level_from_rms(_DETECT_RMS)


def get_audio_level() -> float:
    if not _recording or not _audio_data:
        return 0.0
    try:
        last_chunk = _audio_data[-1]
        if len(last_chunk) == 0:
            return 0.0
        rms = np.sqrt(np.mean(last_chunk.astype(np.float32) ** 2))
        return _level_from_rms(float(rms))
    except Exception:
        return 0.0


def is_silence_detected() -> bool:
    if not _recording or _detector is None:
        return False
    if not _audio_data:
        return False

    cfg = _get_config()
    total_samples = sum(len(chunk) for chunk in _audio_data)
    duration = total_samples / cfg["sample_rate"]

    safety = cfg["safety_max_seconds"]
    if safety and duration >= safety:
        logger.warning(
            "Grabacion llego al tope de seguridad (%.0fs): cortando",
            safety,
        )
        return True

    return _detector.is_detected(time.monotonic(), duration)


def start_recording(threshold: float | None = None, min_duration: float = 0.4):
    global _recording, _audio_data, _stream, _detector

    if _recording:
        logger.warning("Ya esta grabando")
        return

    cfg = _get_config()
    device = get_input_device()

    _recording = True
    _audio_data = []
    _detector = SilenceDetector(
        threshold=threshold if threshold is not None else cfg["silence_threshold"],
        timeout=cfg["silence_timeout"],
        min_duration=min_duration,
    )

    def callback(indata, frames, time_info, status):
        if status:
            logger.warning("Audio status: %s", status)
        if _recording:
            chunk = indata.copy()
            _audio_data.append(chunk)
            rms = np.sqrt(np.mean(chunk.astype(np.float32) ** 2))
            _detector.update(rms, time.monotonic())

    try:
        _stream = sd.InputStream(
            samplerate=cfg["sample_rate"],
            channels=cfg["channels"],
            dtype="int16",
            device=device,
            callback=callback,
            blocksize=int(cfg["sample_rate"] * 0.1),
        )
        _stream.start()
        logger.info(
            "Grabando (device=%s, rate=%d, max=%ds)",
            device,
            cfg["sample_rate"],
            cfg["max_record_seconds"],
        )
    except Exception as e:
        _recording = False
        logger.error("Error iniciando grabacion: %s", e)
        raise


def stop_recording() -> np.ndarray | None:
    global _recording, _stream, _detector

    if not _recording:
        return None

    _recording = False
    _detector = None

    if _stream:
        try:
            _stream.stop()
            _stream.close()
        except Exception as e:
            logger.error("Error cerrando stream: %s", e)
        _stream = None

    if not _audio_data:
        logger.warning("No se grabo audio")
        return None

    audio = np.concatenate(_audio_data, axis=0).flatten()
    cfg = _get_config()
    duration = len(audio) / cfg["sample_rate"]
    logger.info("Audio grabado: %.1fs, %d samples", duration, len(audio))

    return audio


def is_recording() -> bool:
    return _recording
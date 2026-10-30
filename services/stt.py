import logging
import os

import numpy as np
from faster_whisper import WhisperModel

from config import get_config

logger = logging.getLogger("jarvis.stt")

_model: WhisperModel | None = None
_model_key: tuple | None = None


def _voice_cfg() -> dict:
    return get_config().get("voice", {})


def _cpu_threads(cfg: dict) -> int:
    """Hilos de CPU para CTranslate2.

    WhisperModel(cpu_threads=0) deja el valor por defecto de CTranslate2, que
    son 4 hilos: en un CPU de 8 nucleos eso deja la mitad sin usar. Aqui el
    default es "todos los nucleos" (tope 8) y se puede fijar a mano con
    voice.stt_cpu_threads. Mas hilos = mas rapido, sin tocar la precision.
    """
    configured = int(cfg.get("stt_cpu_threads", 0) or 0)
    if configured > 0:
        return configured
    return max(1, min(os.cpu_count() or 4, 8))


def _config_key(cfg: dict) -> tuple:
    """Identidad de la config del modelo: si cambia, se recarga."""
    return (
        cfg.get("stt_model", "base"),
        _cpu_threads(cfg),
    )


def _get_model() -> WhisperModel:
    global _model, _model_key
    cfg = _voice_cfg()
    key = _config_key(cfg)

    if _model is not None and _model_key == key:
        return _model

    model_size = cfg.get("stt_model", "base")
    threads = _cpu_threads(cfg)
    logger.info("Cargando modelo Whisper: %s (cpu_threads=%d)", model_size, threads)
    _model = WhisperModel(
        model_size,
        device="cpu",
        compute_type="int8",
        cpu_threads=threads,
    )
    _model_key = key
    logger.info("Modelo Whisper cargado: %s", model_size)
    return _model


def preload_model() -> bool:
    try:
        _get_model()
        return True
    except Exception as e:
        logger.error("Error precargando modelo STT: %s", e)
        return False


def _build_hotwords(cfg: dict) -> str | None:
    """Nombres propios que Whisper debe reconocer (mejora del punto 3.4 del video).

    `hotwords` se aplica en TODAS las ventanas de decodificacion (a diferencia
    de initial_prompt, que solo abre la primera), asi que es el sitio correcto
    para sesgar la transcripcion hacia 'JARVIS', 'OpenCode', 'Gmail', etc.
    """
    names = cfg.get("stt_hotwords") or []
    if isinstance(names, str):
        names = [n for n in names.split(",")]
    clean = [str(n).strip() for n in names if str(n).strip()]
    if not clean:
        return None
    return ", ".join(clean)


def _build_initial_prompt(cfg: dict) -> str | None:
    """Frase de contexto en espanol con el vocabulario habitual del usuario."""
    prompt = (cfg.get("stt_initial_prompt") or "").strip()
    return prompt or None


def _transcribe_kwargs(cfg: dict, vad_filter: bool) -> dict:
    return dict(
        language=cfg.get("language", "es"),
        beam_size=cfg.get("stt_beam_size", 1),
        temperature=cfg.get("stt_temperature", 0),
        condition_on_previous_text=False,
        without_timestamps=True,
        vad_filter=vad_filter,
        vad_parameters=dict(
            min_silence_duration_ms=500,
            speech_pad_ms=200,
        ),
        initial_prompt=_build_initial_prompt(cfg),
        hotwords=_build_hotwords(cfg),
    )


def transcribe(
    audio: np.ndarray,
    language: str = "es",
    vad_filter: bool = True,
) -> str | None:
    if audio is None or len(audio) == 0:
        logger.warning("Audio vacio")
        return None

    model = _get_model()
    cfg = _voice_cfg()

    kwargs = _transcribe_kwargs(cfg, vad_filter)
    kwargs["language"] = language
    logger.debug(
        "STT %s (beam=%s, hilos=%d, hotwords=%s)",
        cfg.get("stt_model", "?"),
        kwargs["beam_size"],
        _cpu_threads(cfg),
        "si" if kwargs.get("hotwords") else "no",
    )

    audio_float = audio.astype(np.float32) / 32768.0

    try:
        segments, info = model.transcribe(audio_float, **kwargs)

        text_parts = [seg.text.strip() for seg in segments]
        text = " ".join(text_parts).strip()

        # Fallback: si el VAD filtró todo (frases cortas o voz baja), reintentar
        # sin VAD para no perder la transcripción.
        if not text and vad_filter:
            logger.info("VAD no detecto voz; reintentando sin VAD")
            retry_kwargs = _transcribe_kwargs(cfg, False)
            retry_kwargs["language"] = language
            segments, info = model.transcribe(audio_float, **retry_kwargs)
            text_parts = [seg.text.strip() for seg in segments]
            text = " ".join(text_parts).strip()

        if text:
            logger.info(
                "Transcrito (%.1fs, %s): %s",
                info.duration,
                info.language,
                text[:100],
            )
        else:
            logger.info("No se detecto voz en el audio")

        return text if text else None

    except Exception as e:
        logger.error("Error transcribiendo: %s", e)
        return None


def transcribe_file(filepath: str, language: str = "es") -> str | None:
    model = _get_model()
    cfg = _voice_cfg()
    kwargs = _transcribe_kwargs(cfg, True)
    kwargs["language"] = language
    try:
        segments, info = model.transcribe(filepath, **kwargs)
        text_parts = [seg.text.strip() for seg in segments]
        text = " ".join(text_parts).strip()

        if text:
            logger.info(
                "Transcrito archivo %.1fs: %s",
                info.duration,
                text[:100],
            )
        else:
            logger.info("No se detecto voz en el archivo")

        return text if text else None
    except Exception as e:
        logger.error("Error transcribiendo archivo: %s", e)
        return None

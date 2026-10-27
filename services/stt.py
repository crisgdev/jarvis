import logging
import numpy as np
from faster_whisper import WhisperModel
from config import get_config

logger = logging.getLogger("jarvis.stt")

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        cfg = get_config().get("voice", {})
        model_size = cfg.get("stt_model", "turbo")
        logger.info("Cargando modelo Whisper: %s", model_size)
        _model = WhisperModel(model_size, device="cpu", compute_type="int8")
        logger.info("Modelo Whisper cargado")
    return _model


def preload_model() -> bool:
    try:
        _get_model()
        return True
    except Exception as e:
        logger.error("Error precargando modelo STT: %s", e)
        return False


def transcribe(
    audio: np.ndarray,
    language: str = "es",
    vad_filter: bool = True,
) -> str | None:
    if audio is None or len(audio) == 0:
        logger.warning("Audio vacio")
        return None

    model = _get_model()
    cfg = get_config().get("audio", {})
    sample_rate = cfg.get("sample_rate", 16000)

    vcfg = get_config().get("voice", {})
    beam_size = vcfg.get("stt_beam_size", 5)
    temperature = vcfg.get("stt_temperature", 0)
    initial_prompt = vcfg.get("stt_initial_prompt") or None

    audio_float = audio.astype(np.float32) / 32768.0

    try:
        segments, info = model.transcribe(
            audio_float,
            language=language,
            beam_size=beam_size,
            temperature=temperature,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=vad_filter,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
            initial_prompt=initial_prompt,
        )

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
    vcfg = get_config().get("voice", {})
    beam_size = vcfg.get("stt_beam_size", 5)
    temperature = vcfg.get("stt_temperature", 0)
    initial_prompt = vcfg.get("stt_initial_prompt") or None
    try:
        segments, info = model.transcribe(
            filepath,
            language=language,
            beam_size=beam_size,
            temperature=temperature,
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200,
            ),
            initial_prompt=initial_prompt,
        )
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

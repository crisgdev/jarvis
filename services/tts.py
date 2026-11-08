import asyncio
import logging
import queue
import re
import tempfile
import threading
import time
import uuid
from pathlib import Path

import edge_tts
import pygame

from config import get_config

logger = logging.getLogger("jarvis.tts")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?…])\s+")

_text_queue: "queue.Queue" = queue.Queue()
_audio_queue: "queue.Queue" = queue.Queue()

_gen = 0
_gen_lock = threading.Lock()

_pending = 0
_pending_lock = threading.Lock()

_worker: threading.Thread | None = None
_player: threading.Thread | None = None


def _get_voice() -> str:
    cfg = get_config().get("voice", {})
    return cfg.get("tts_voice", "es-HN-CarlosNeural")


def _split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text.strip())]
    parts = [p for p in parts if p]
    return parts or [text.strip()]


def _get_tmp_dir() -> Path:
    tmp_dir = Path(tempfile.gettempdir()) / "jarvis_tts"
    tmp_dir.mkdir(exist_ok=True)
    return tmp_dir


async def _generate_audio(text: str, output_path: str, voice: str):
    communicate = edge_tts.Communicate(text, voice)
    await communicate.save(output_path)


def _synthesize(sentence: str) -> Path | None:
    voice = _get_voice()
    path = _get_tmp_dir() / f"sentence_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.mp3"
    try:
        asyncio.run(_generate_audio(sentence, str(path), voice))
        if not path.exists() or path.stat().st_size == 0:
            return None
        return path
    except Exception as e:
        logger.error("Error generando audio de frase: %s", e)
        return None


def _play_file(path: Path):
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()

        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.wait(50)
        pygame.mixer.music.unload()
    except Exception as e:
        logger.error("Error reproduciendo audio: %s", e)


def _delete_file(path: Path | None):
    if not path:
        return
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _note_done():
    global _pending
    with _pending_lock:
        _pending = max(0, _pending - 1)


def _synth_loop():
    while True:
        item = _text_queue.get()
        if item is None:
            break

        gen, sentence = item
        with _gen_lock:
            if gen != _gen:
                _note_done()
                continue

        path = _synthesize(sentence)
        if path is None:
            _note_done()
            continue

        _audio_queue.put((gen, path))


def _player_loop():
    while True:
        item = _audio_queue.get()
        if item is None:
            break

        gen, path = item
        with _gen_lock:
            if gen != _gen:
                _delete_file(path)
                _note_done()
                continue

        _play_file(path)
        _delete_file(path)
        _note_done()


def _ensure_threads():
    global _worker, _player
    if _worker is None:
        _worker = threading.Thread(target=_synth_loop, daemon=True)
        _worker.start()
    if _player is None:
        _player = threading.Thread(target=_player_loop, daemon=True)
        _player.start()


def speak(text: str, voice: str = None):
    global _pending
    if not text or not text.strip():
        return

    _ensure_threads()

    with _gen_lock:
        gen = _gen

    sentences = _split_sentences(text)
    with _pending_lock:
        _pending += len(sentences)

    for sentence in sentences:
        _text_queue.put((gen, sentence))

    logger.info("TTS encolado (%d frases), voz=%s", len(sentences), voice or _get_voice())


def stop_speech():
    global _gen, _pending
    with _gen_lock:
        _gen += 1

    while True:
        try:
            _text_queue.get_nowait()
        except queue.Empty:
            break

    while True:
        try:
            _, path = _audio_queue.get_nowait()
            _delete_file(path)
        except queue.Empty:
            break

    with _pending_lock:
        _pending = 0

    try:
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
    except Exception as e:
        logger.error("Error deteniendo audio: %s", e)


def is_speaking() -> bool:
    with _pending_lock:
        return _pending > 0


def shutdown():
    _text_queue.put(None)
    _audio_queue.put(None)
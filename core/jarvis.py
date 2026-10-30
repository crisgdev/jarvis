import logging
import re
import threading
import time
from enum import Enum

import numpy as np

from config import get_config
from brain.gemini import GeminiBrain
from brain.tools_executor import execute_tool, get_risk_level
from services.audio import (
    start_recording, stop_recording, get_audio_level,
    is_recording, is_silence_detected, get_max_record_seconds,
)
from services.stt import transcribe, preload_model as preload_stt
from services.tts import speak, stop_speech, shutdown as shutdown_tts, is_speaking
from memory.context import (
    start_session, end_current_session, save_conversation,
    build_system_context,
)
from memory.search import store_memory
from core.voice_confirm import interpret_confirmation

logger = logging.getLogger("jarvis.core")

_INTERRUPT_PHRASES = [
    "deja de hablar",
    "para de hablar",
    "no sigas hablando",
    "no continues",
    "cállate ya",
    "basta ya",
    "silencio",
    "silencia",
    "cállate",
    "callate",
    "detente",
    "espera",
    "espérate",
    "ya para",
    "suficiente",
    "para",
    "basta",
    "stop",
    "alto",
]
_INTERRUPT_PATTERN = re.compile(
    "|".join(re.escape(p) for p in sorted(_INTERRUPT_PHRASES, key=len, reverse=True)),
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-záéíóúüñ]+")


def _is_echo(text: str, spoken: str) -> bool:
    """¿El texto transcrito es solo eco de la propia respuesta de JARVIS?"""
    if not text or not spoken:
        return False
    tokens = {t for t in _WORD_RE.findall(text.lower()) if len(t) > 3}
    spoken_tokens = {t for t in _WORD_RE.findall(spoken.lower()) if len(t) > 3}
    if not tokens:
        return True
    overlap = sum(1 for t in tokens if t in spoken_tokens)
    return overlap / len(tokens) >= 0.6


def _strip_interrupt(text: str) -> str:
    """Quita la palabra de interrupcion ('para', 'cállate', ...) del texto."""
    cleaned = _INTERRUPT_PATTERN.sub("", text or "")
    cleaned = re.sub(r"^[\s.,;:!?…—_\-]+", "", cleaned).strip()
    return cleaned


def _amplify_audio(audio, peak: int):
    """Amplifica clips tranquilos para que el STT capture voz baja."""
    if peak >= 8000:
        return audio
    gain = min(12000.0 / max(peak, 1), 8.0)
    return np.clip(audio.astype(np.float32) * gain, -32767, 32767).astype(np.int16)


class State(Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CALL = "call"


class JARVIS:
    def __init__(self):
        self.state = State.IDLE
        self._brain = GeminiBrain()
        self._brain.set_confirmation_callback(self.confirm_action)
        self._running = False
        self._lock = threading.Lock()
        self._call_active = False
        self._push_to_talk = False
        self._ptt_wanted = False

        self._on_state_change = None
        self._on_message = None
        self._on_audio_level = None
        self._on_confirmation = None
        self._on_call_active = None
        self._on_task = None

        self._brain.set_task_callback(self._emit_task)

        start_session()
        threading.Thread(target=preload_stt, daemon=True).start()
        logger.info("JARVIS inicializado")

    def set_callbacks(self, on_state_change=None, on_message=None, on_audio_level=None, on_confirmation=None, on_call_active=None, on_task=None):
        self._on_state_change = on_state_change
        self._on_message = on_message
        self._on_audio_level = on_audio_level
        self._on_confirmation = on_confirmation
        self._on_call_active = on_call_active
        self._on_task = on_task

    def get_model(self) -> str:
        """Modelo que esta usando el cerebro ahora mismo (puede cambiar por fallback)."""
        return getattr(self._brain, "model", "") or ""

    def _emit_task(self, event: dict):
        """Reenvia a la GUI los eventos de subtareas del cerebro."""
        if self._on_task is None:
            return
        try:
            self._on_task(event)
        except Exception as e:
            logger.debug("Error en callback de tareas: %s", e)

    def is_call_active(self) -> bool:
        return self._call_active

    def _set_call_active(self, active: bool):
        """Unico punto donde cambia _call_active: avisa a la GUI para que el
        boton de llamada no se desincronice (hotkey, bandeja o boton)."""
        if self._call_active == active:
            return
        self._call_active = active
        if self._on_call_active:
            try:
                self._on_call_active(active)
            except Exception as e:
                logger.warning("Error en callback de llamada: %s", e)

    def confirm_by_voice(self, prompt: str, listen_timeout: int = 10) -> bool:
        """Habla el prompt de confirmacion y escucha la respuesta del usuario.

        Confirma si el usuario dice "si"/"procede"/"adelante", cancela si dice
        "no"/"cancela" o si no se entiende nada tras 2 intentos.

        El audio se amplifica si llega bajo y se transcribe sin VAD, para que
        respuestas breves ("si") o dichas en voz baja no se pierdan.
        """
        import numpy as np

        for attempt in (1, 2):
            self._set_state(State.SPEAKING)
            speak(prompt)
            while is_speaking():
                time.sleep(0.1)

            self._set_state(State.LISTENING)
            start_recording()
            start_time = time.time()
            audio = None
            try:
                while is_recording():
                    if is_silence_detected():
                        break
                    if time.time() - start_time > listen_timeout:
                        break
                    time.sleep(0.1)
            finally:
                audio = stop_recording()

            if audio is None or len(audio) < 1600:
                logger.info("Confirmacion por voz: sin voz detectada (intento %d)", attempt)
                prompt = "No escuche nada. ¿Confirma la accion o la cancelo?"
                continue

            peak = int(np.max(np.abs(audio)))
            if peak < 300:
                logger.info(
                    "Confirmacion por voz: audio muy bajo (peak=%d, intento %d)",
                    peak,
                    attempt,
                )
                prompt = "No te escuche. Habla mas fuerte: ¿confirma o cancela?"
                continue

            self._set_state(State.PROCESSING)
            text = transcribe(_amplify_audio(audio, peak), vad_filter=False)
            if text:
                self._notify_message("user", text)
                logger.info("Confirmacion por voz transcrita: %r", text)

            decision = interpret_confirmation(text)
            if decision is not None:
                return decision

            prompt = "No le entendi. ¿Confirma o cancela?"
            logger.warning("Confirmacion por voz no clara (intento %d)", attempt)

        logger.info("Confirmacion por voz agotada, cancelando por seguridad")
        return False

    def confirm_action(self, tool_name: str, args: dict) -> bool:
        if self._on_confirmation is None:
            logger.warning(
                "Sin confirmacion GUI configurada. Bloqueando accion dangerous: %s",
                tool_name,
            )
            return False
        try:
            return bool(self._on_confirmation(tool_name, args))
        except Exception as e:
            logger.error("Error en confirmacion GUI para %s: %s", tool_name, e)
            return False

    def _set_state(self, new_state: State):
        self.state = new_state
        if self._on_state_change:
            self._on_state_change(new_state.value)
        logger.info("Estado: %s", new_state.value)

        # El detector de palmadas solo vive mientras JARVIS esta en reposo:
        # se pausa al grabar/procesar/hablar y se reanuda al volver a IDLE.
        try:
            from services import clap_detector

            if new_state == State.IDLE:
                clap_detector.resume()
            else:
                clap_detector.pause()
        except Exception as e:
            logger.debug("Clap detector no disponible: %s", e)

    def process_text(self, text: str):
        if self.state != State.IDLE:
            logger.warning("No se puede procesar, estado: %s", self.state.value)
            return

        thread = threading.Thread(target=self._process_text_thread, args=(text,), daemon=True)
        thread.start()

    def _process_text_thread(self, text: str):
        with self._lock:
            self._set_state(State.PROCESSING)
            self._notify_message("user", text)
            save_conversation("user", text)

            try:
                response = self._brain.chat_message(text)

                if response:
                    self._set_state(State.SPEAKING)
                    self._notify_message("model", response)
                    save_conversation("model", response)
                    store_memory(response, source="jarvis")

            except Exception as e:
                logger.error("Error procesando: %s", e)
                self._notify_message("model", "Tuve un error al procesar tu mensaje.")

            finally:
                self._set_state(State.IDLE)

    def start_listening(self, push_to_talk: bool = False):
        self._ptt_wanted = bool(push_to_talk)

        # Push-to-talk encima del habla: corta el TTS y espera (en segundo
        # plano, sin congelar la GUI) a que el hilo de respuesta vuelva a IDLE.
        if self.state == State.SPEAKING:
            self.interrupt_speaking()
            threading.Thread(
                target=self._listen_when_idle, args=(push_to_talk,), daemon=True
            ).start()
            return

        self._begin_listening(push_to_talk)

    def _listen_when_idle(self, push_to_talk: bool):
        deadline = time.time() + 3.0
        while self.state != State.IDLE and time.time() < deadline:
            if push_to_talk and not self._ptt_wanted:
                return
            time.sleep(0.05)
        if push_to_talk and not self._ptt_wanted:
            return
        self._begin_listening(push_to_talk)

    def _begin_listening(self, push_to_talk: bool):
        if self.state != State.IDLE:
            return

        with self._lock:
            self._set_state(State.LISTENING)
            self._push_to_talk = bool(push_to_talk)
            try:
                start_recording()
            except Exception as e:
                logger.error("Error iniciando grabacion: %s", e)
                self._push_to_talk = False
                self._set_state(State.IDLE)
                return

        threading.Thread(target=self._watch_recording, daemon=True).start()

    def interrupt_speaking(self):
        """Corta la voz de JARVIS para que el usuario hable encima."""
        if not is_speaking():
            return
        logger.info("Interrupcion por push-to-talk: cortando TTS")
        stop_speech()

    def _watch_recording(self):
        """Corta la grabacion de una consulta unica al detectar silencio (o tope).

        Sin esto, una escucha iniciada con start_listening() (hotkey una
        consulta, boton de la GUI) dejaria grabando por siempre: el poll de
        silencio solo lo hacian el call loop y las confirmaciones de voz.

        En push-to-talk (mantener ESPACIO o el orbe) NO se corta por silencio:
        manda el usuario al soltar, para poder pensar una pausa sin que se
        cierre el microfono.
        """
        start_time = time.time()
        max_seconds = get_max_record_seconds()
        ptt_max = float(
            get_config().get("voice", {}).get("push_to_talk_max_seconds", 60)
        )
        while self.state == State.LISTENING and is_recording():
            try:
                if not self._push_to_talk and is_silence_detected():
                    break
                if self._push_to_talk and not self._ptt_wanted:
                    # El usuario solto ESPACIO / el orbe antes de empezar.
                    break
                if self._push_to_talk and ptt_max > 0 and time.time() - start_time > ptt_max:
                    logger.warning("Push-to-talk llego al tope (%.0fs): cortando", ptt_max)
                    break
                if max_seconds > 0 and time.time() - start_time > max_seconds:
                    break
            except Exception as e:
                logger.error("Error vigilando grabacion: %s", e)
                break
            time.sleep(0.1)
        if self.state == State.LISTENING and not self._push_to_talk:
            # Solo el flujo no-PTT (hotkey Ctrl+Alt+Shift+J) llega aqu�:
            # detecto silencio o tope de tiempo y paso a procesar.
            # Para PTT (ESPACIO / orbe) es _ptt_release quien llama a
            # stop_listening(), as� evitamos condiciones de carrera entre
            # este hilo y el hilo de la GUI.
            self.stop_listening()

    def on_double_clap(self):
        """Callback del detector de palmadas: saluda y empieza a escuchar."""
        if self.state != State.IDLE:
            logger.info("Doble palmada ignorada (estado=%s)", self.state.value)
            return

        greeting = (
            get_config().get("voice", {}).get("clap_greeting", "Hola, en qué te ayudo")
        )

        def _run():
            try:
                speak(greeting)
                # Esperar a que termine el saludo para no capturar la propia voz
                deadline = time.time() + 6
                while is_speaking() and time.time() < deadline:
                    time.sleep(0.1)
                self.start_listening()
            except Exception as e:
                logger.error("Error tras doble palmada: %s", e)

        logger.info("Doble palmada detectada: saludando y escuchando")
        threading.Thread(target=_run, daemon=True).start()

    def stop_listening(self):
        self._ptt_wanted = False
        if self.state != State.LISTENING:
            return
        # Guardia contra doble ejecucion: si otro hilo (ej. _watch_recording)
        # ya detuvo la grabacion, no re-procesar (evita que el segundo intento
        # reciba None de stop_recording y sobrescriba PROCESSING con IDLE).
        if not is_recording():
            return

        self._push_to_talk = False
        audio = stop_recording()
        if audio is None or len(audio) < 1600:
            logger.info("Audio muy corto, ignorando")
            self._set_state(State.IDLE)
            return

        self._set_state(State.PROCESSING)
        thread = threading.Thread(target=self._process_audio_thread, args=(audio,), daemon=True)
        thread.start()

    def cancel_listening(self):
        """Cancela una escucha push-to-talk demasiado corta (clic accidental)."""
        self._ptt_wanted = False
        if self.state != State.LISTENING:
            return
        self._push_to_talk = False
        if is_recording():
            stop_recording()
        self._set_state(State.IDLE)

    def _process_audio_thread(self, audio):
        t0 = time.perf_counter()
        try:
            text = transcribe(audio)
            t1 = time.perf_counter()
            logger.info("LATENCIA STT: %.0f ms", (t1 - t0) * 1000)

            if not text:
                logger.info("No se detecto voz")
                speak("No te escuche, intenta de nuevo.")
                while is_speaking():
                    pass
                self._set_state(State.IDLE)
                return

            self._notify_message("user", text)
            save_conversation("user", text)

            response = self._brain.chat_message(text)
            t2 = time.perf_counter()
            logger.info("LATENCIA GEMINI: %.0f ms", (t2 - t1) * 1000)

            if response:
                while True:
                    self._set_state(State.SPEAKING)
                    self._notify_message("model", response)
                    save_conversation("model", response)
                    store_memory(response, source="jarvis")
                    speak(response)
                    t3 = time.perf_counter()
                    logger.info("LATENCIA TOTAL (voz->audio): %.0f ms", (t3 - t0) * 1000)

                    interrupted, new_text = self._wait_for_interrupt(response)
                    if not interrupted:
                        break

                    clean = _strip_interrupt(new_text)
                    if not clean:
                        break

                    self._set_state(State.PROCESSING)
                    self._notify_message("user", clean)
                    save_conversation("user", clean)
                    response = self._brain.chat_message(clean)
                    if not response:
                        break

        except Exception as e:
            logger.error("Error procesando audio: %s", e)
            speak("Tuve un error al procesar el audio.")
            while is_speaking():
                pass

        finally:
            self._set_state(State.IDLE)

    def start_call(self):
        if self._call_active:
            return

        self._set_call_active(True)
        self._set_state(State.CALL)
        thread = threading.Thread(target=self._call_loop, daemon=True)
        thread.start()
        logger.info("Llamada iniciada")

    def stop_call(self):
        self._set_call_active(False)
        self._push_to_talk = False
        if is_recording():
            stop_recording()
        if is_speaking():
            stop_speech()
        self._set_state(State.IDLE)
        logger.info("Llamada terminada")

    def force_process(self):
        """Boton TERMINE: corta la grabacion aunque no se haya detectado
        silencio y procesa lo hablado."""
        if not is_recording():
            return

        def _do():
            try:
                audio = stop_recording()
                if audio is not None and len(audio) >= 1600:
                    self._process_call_audio(audio)
            except Exception as e:
                logger.error("Error en force_process: %s", e)

        threading.Thread(target=_do, daemon=True).start()

    def _call_loop(self):
        while self._call_active:
            try:
                self._set_state(State.LISTENING)
                start_recording()

                start_time = time.time()
                max_seconds = get_max_record_seconds()

                while self._call_active and is_recording():
                    if is_silence_detected():
                        audio = stop_recording()
                        if audio is not None and len(audio) >= 1600:
                            self._process_call_audio(audio)
                        break
                    if max_seconds > 0 and time.time() - start_time > max_seconds:
                        audio = stop_recording()
                        if audio is not None and len(audio) >= 1600:
                            self._process_call_audio(audio)
                        break
                    time.sleep(0.1)

                if not self._call_active:
                    break

            except Exception as e:
                logger.error("Error en call loop: %s", e)
                if is_recording():
                    stop_recording()
                if is_speaking():
                    stop_speech()

    def _process_call_audio(self, audio):
        t0 = time.perf_counter()
        try:
            text = transcribe(audio)
            if not text:
                peak = int(np.max(np.abs(audio))) if len(audio) else 0
                if peak > 0:
                    text = transcribe(_amplify_audio(audio, peak))
            t1 = time.perf_counter()
            logger.info("LATENCIA STT (call): %.0f ms", (t1 - t0) * 1000)

            if not text:
                return

            self._notify_message("user", text)
            save_conversation("user", text)

            response = self._brain.chat_message(text)
            t2 = time.perf_counter()
            logger.info("LATENCIA GEMINI (call): %.0f ms", (t2 - t1) * 1000)

            if not response:
                return

            while True:
                self._set_state(State.SPEAKING)
                self._notify_message("model", response)
                save_conversation("model", response)
                store_memory(response, source="jarvis")

                speak(response)
                t3 = time.perf_counter()
                logger.info("LATENCIA TOTAL (call): %.0f ms", (t3 - t0) * 1000)

                interrupted, new_text = self._wait_for_interrupt(response)
                if not interrupted or not self._call_active:
                    break

                clean = _strip_interrupt(new_text)
                if not clean:
                    break

                self._set_state(State.PROCESSING)
                self._notify_message("user", clean)
                save_conversation("user", clean)
                response = self._brain.chat_message(clean)
                if not response:
                    break

        except Exception as e:
            logger.error("Error en call audio: %s", e)

    def _wait_for_interrupt(self, spoken: str) -> tuple:
        """Mientras JARVIS habla, escucha si el usuario dice algo (para,
        silencio, o rectifica). Devuelve (False, None) si llego hasta el final,
        o (True, texto) si el usuario interrumpio y termino de hablar.

        Usa un umbral mas alto y filtra eco para no oirse a si mismo.
        """
        voice = get_config().get("voice", {})
        if not voice.get("interrupt_enabled", True):
            while is_speaking():
                time.sleep(0.1)
            return False, None

        threshold = float(voice.get("interrupt_threshold", 1500))
        max_wait = float(voice.get("interrupt_max_wait", 8))

        while is_speaking():
            start_recording(threshold=threshold)
            start_time = time.time()
            audio = None
            try:
                while is_recording():
                    if is_silence_detected():
                        audio = stop_recording()
                        break
                    if not is_speaking() and not self._call_active:
                        audio = stop_recording()
                        break
                    if time.time() - start_time > max_wait:
                        audio = stop_recording()
                        break
                    time.sleep(0.05)
            except Exception:
                if is_recording():
                    stop_recording()
                audio = None

            if audio is None or len(audio) < 8000:
                continue

            peak = int(np.max(np.abs(audio)))
            if peak < 1000:
                continue

            text = transcribe(_amplify_audio(audio, peak), vad_filter=False)
            if not text or _is_echo(text, spoken):
                continue

            stop_speech()
            logger.info("Interrupcion detectada: %r", text[:100])
            return True, text

        if is_recording():
            stop_recording()
        return False, None

    def stop_speaking(self):
        stop_speech()

    def emergency_stop(self):
        self._set_call_active(False)
        self._push_to_talk = False
        stop_speech()
        if is_recording():
            stop_recording()
        self._set_state(State.IDLE)
        logger.info("EMERGENCY STOP")

    def get_audio_level(self) -> float:
        if self.state in (State.LISTENING, State.CALL):
            return get_audio_level()
        return 0.0

    def shutdown(self):
        self._running = False
        self._set_call_active(False)
        stop_speech()
        if is_recording():
            stop_recording()
        shutdown_tts()
        end_current_session()
        logger.info("JARVIS apagado")

    def _notify_message(self, role: str, text: str):
        if self._on_message:
            self._on_message(role, text)

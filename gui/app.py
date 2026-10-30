import threading
import time
import tkinter as tk

import customtkinter as ctk

from config import get_config
from gui import theme
from gui.call_view import CallView
from gui.header import HINT_IDLE, HINT_LISTENING, InfoCard, TopBar
from gui.subtitles import SubtitleStack
from gui.tasks import TaskPanel

STATE_LABELS = {
    "idle": "EN ESPERA",
    "listening": "ESCUCHANDO",
    "processing": "PROCESANDO",
    "speaking": "HABLANDO",
    "call": "EN LLAMADA",
}


class JarvisGUI(ctk.CTk):
    MIN_HOLD_SECONDS = 0.35

    def __init__(self):
        super().__init__()

        cfg = get_config().get("gui", {})
        self._title = cfg.get("window_title", "JARVIS - Asistente Personal")
        size = cfg.get("window_size", [900, 700])

        # Escala tipografica relativa al ancho de la ventana (1.0 a 900 px).
        theme.set_scale(theme.scale_for_width(size[0]))

        self.title(self._title)
        self.geometry(f"{size[0]}x{size[1]}")
        self.minsize(780, 580)
        self.configure(fg_color=theme.BG)

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._on_user_message = None
        self._on_mic_toggle = None
        self._on_emergency = None
        self._on_force_process = None
        self._on_ptt_start = None
        self._on_ptt_stop = None
        self._on_ptt_cancel = None
        self._on_ptt_interrupt = None
        self._on_call_toggle = None
        self._model_provider = None

        self._state = "idle"
        self._call_active = False
        self._ptt_active = False
        self._ptt_began = 0.0
        self._turn_start = None
        self._turn_seconds = 0.0
        self._font_job = None

        self._build_ui()
        self._bind_shortcuts()
        self._call_view.start_animation()
        self.after(200, self._tick)

    # ── Construccion de la interfaz ──────────────────────────────────

    def _build_ui(self):
        self._top_bar = TopBar(self)
        self._top_bar.pack(fill="x")

        self._stage = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self._stage.pack(fill="both", expand=True)

        self._call_view = CallView(
            self._stage,
            on_press=self._ptt_press,
            on_release=self._ptt_release,
        )
        self._call_view.pack(fill="both", expand=True)

        self._tasks = TaskPanel(self._stage)
        self._tasks.place(x=24, y=10, anchor="nw")

        self._info = InfoCard(self._stage)
        self._info.place(relx=0.985, rely=0.03, anchor="ne")

        self._subtitles = SubtitleStack(self)
        self._subtitles.pack(side="bottom", fill="x")

    # ── Atajos de teclado: mantener ESPACIO para hablar ──────────────

    def _bind_shortcuts(self):
        # bind_all: el evento llega aunque el foco este en el canvas, en una
        # etiqueta o en cualquier hijo del frame (no solo en la ventana).
        self.bind_all("<KeyPress-space>", self._on_space_press, add="+")
        self.bind_all("<KeyRelease-space>", self._on_space_release, add="+")
        self.bind("<Configure>", self._on_configure, add="+")
        self.bind("<Map>", self._on_map, add="+")

    def _on_map(self, event):
        """Al mostrarse la ventana (bandeja / deiconify) se toma el foco.

        Sin foco de teclado Windows no entrega el ESPACIO a la app, y el
        push-to-talk "no funcionaba" aunque el binding estuviera bien.
        """
        if event.widget is not self:
            return
        self.after(80, self._take_focus)

    def _take_focus(self):
        try:
            self.lift()
            self.focus_force()
        except Exception:
            pass
        # Windows NO deja que un proceso en segundo plano llame a
        # SetForegroundWindow. AllowSetForegroundWindow(-1) + BringWindowToTop
        # es la forma que SI funciona sin dejar ALT "pegado" (el truco de
        # simular ALT con keybd_event se filtraba al estado del teclado y
        # convertia el ESPACIO en ALT+ESPACIO, rompiendo el push-to-talk).
        try:
            import ctypes

            user32 = ctypes.windll.user32
            hwnd = user32.GetAncestor(self.winfo_id(), 2)  # GA_ROOT
            if not hwnd or user32.GetForegroundWindow() == hwnd:
                return
            user32.AllowSetForegroundWindow(-1)  # ASFW_ANY
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _on_configure(self, event):
        """La ventana cambio de tamano: reprograma el reescalado de fuentes."""
        if event.widget is not self:
            return
        if self._font_job is not None:
            try:
                self.after_cancel(self._font_job)
            except Exception:
                pass
        self._font_job = self.after(220, self._apply_font_scale)

    def _apply_font_scale(self):
        self._font_job = None
        if not theme.set_scale(theme.scale_for_width(self.winfo_width())):
            return
        self._tasks.refresh_geometry()
        self._info.place_configure(relx=0.985, rely=0.03, anchor="ne")

    def _is_typing(self) -> bool:
        try:
            widget = self.focus_get()
        except Exception:
            return False
        return isinstance(widget, (tk.Entry, tk.Text, ctk.CTkEntry, ctk.CTkTextbox))

    def _in_other_window(self) -> bool:
        """True si el foco esta en un dialogo (Toplevel) de JARVIS."""
        try:
            widget = self.focus_get()
        except Exception:
            return False
        if widget is None:
            return False
        try:
            return widget.winfo_toplevel() is not self
        except Exception:
            return False

    def _on_space_press(self, event):
        # 0x4 = Ctrl, 0x20000 = Alt (Tk 8.6+). No se mira Mod1 (0x8): en
        # algunas versiones de Tk queda marcado por restos de teclas
        # modificadoras y bloqueaba el push-to-talk sin motivo.
        if event.state & 0x0004 or event.state & 0x20000:
            return  # Ctrl o Alt: es un atajo, no push-to-talk
        if self._is_typing() or self._in_other_window():
            return
        self._ptt_press()

    def _on_space_release(self, event):
        if self._is_typing() or self._in_other_window():
            return
        self._ptt_release()

    def _ptt_press(self):
        if self._ptt_active:
            return
        if self._state == "speaking":
            # Hablar encima de JARVIS: corta el TTS y escucha.
            if self._on_ptt_interrupt is not None:
                try:
                    self._on_ptt_interrupt()
                except Exception:
                    pass
        elif self._state != "idle":
            return
        if self._on_ptt_start is None:
            return
        self._ptt_active = True
        self._ptt_began = time.perf_counter()
        self._top_bar.set_hint(HINT_LISTENING)
        try:
            self._on_ptt_start()
        except Exception:
            self._ptt_active = False
            self._top_bar.set_hint(HINT_IDLE)

    def _ptt_release(self):
        if not self._ptt_active:
            return
        held = time.perf_counter() - self._ptt_began
        self._ptt_active = False
        self._top_bar.set_hint(HINT_IDLE)

        if held < self.MIN_HOLD_SECONDS:
            # Clic/tecla demasiado corta: cancela sin transcribir ni hablar.
            if self._on_ptt_cancel is not None:
                try:
                    self._on_ptt_cancel()
                except Exception:
                    pass
            return

        if self._on_ptt_stop is not None:
            try:
                self._on_ptt_stop()
            except Exception:
                pass

    # ── Bucle de refresco (reloj, cronometros, subtitulos) ───────────

    def _tick(self):
        try:
            self._top_bar.tick()
            self._tasks.tick()
            self._subtitles.tick()

            if self._turn_start is not None:
                self._turn_seconds = time.perf_counter() - self._turn_start
            self._info.set_turn_seconds(self._turn_seconds)

            if self._model_provider is not None:
                try:
                    model = self._model_provider()
                except Exception:
                    model = None
                if model:
                    self._info.set_model(model)
        except Exception:
            pass
        finally:
            try:
                self.after(200, self._tick)
            except Exception:
                pass

    # ── Puente seguro con hilos de trabajo ───────────────────────────

    def _ui(self, func, *args):
        if threading.current_thread() is threading.main_thread():
            func(*args)
            return
        try:
            self.after(0, lambda: func(*args))
        except Exception:
            pass

    # ── API usada por core/ ──────────────────────────────────────────

    def set_state(self, state: str):
        self._ui(self._apply_state, state)

    def _apply_state(self, state: str):
        self._state = state
        self._call_view.set_state(state)
        # Forzar repintado inmediato para que la esfera cambie de color y
        # texto sin esperar al siguiente ciclo del event loop de Tkinter.
        self.update_idletasks()
        self._info.set_state(STATE_LABELS.get(state, state.upper()))

        if state == "processing":
            if self._turn_start is None:
                self._turn_start = time.perf_counter()
        elif state in ("idle", "listening", "call"):
            self._freeze_turn()
            if state == "idle":
                self._tasks.close_open()

        if state == "listening" and self._ptt_active:
            self._top_bar.set_hint(HINT_LISTENING)
        elif state in ("processing", "speaking", "call"):
            self._top_bar.set_hint(HINT_IDLE)

    def add_message(self, role: str, text: str):
        self._ui(self._apply_message, role, text)

    def _apply_message(self, role: str, text: str):
        if not text:
            return
        self._subtitles.add(role, text)

        if role == "user":
            if self._turn_start is None:
                self._turn_start = time.perf_counter()
        elif role == "model":
            self._tasks.finish_interpret()

    def add_task_event(self, event: dict):
        self._ui(self._apply_task_event, event or {})

    def _apply_task_event(self, event: dict):
        kind = event.get("kind")
        if kind == "turn_start":
            self._tasks.begin_turn()
        elif kind == "plan":
            self._tasks.set_plan(event.get("steps") or [])
        elif kind == "task_start":
            self._tasks.start_task(event.get("label"), key=event.get("id"))
        elif kind == "task_done":
            self._tasks.finish_task(
                key=event.get("id"), ok=bool(event.get("ok", True))
            )
        elif kind == "turn_end":
            self._tasks.close_open()

    def _freeze_turn(self):
        if self._turn_start is None:
            return
        self._turn_seconds = time.perf_counter() - self._turn_start
        self._turn_start = None

    def set_model_provider(self, provider):
        self._model_provider = provider

    def set_call_active(self, active: bool):
        self._call_active = bool(active)

    def update_audio_level(self, level: float):
        self._call_view.update_audio_level(level)

    # ── Callbacks que conecta main.py ────────────────────────────────

    def on_user_message(self, callback):
        self._on_user_message = callback

    def on_mic_toggle(self, callback):
        self._on_mic_toggle = callback

    def on_emergency(self, callback):
        self._on_emergency = callback

    def on_force_process(self, callback):
        self._on_force_process = callback

    def on_ptt_start(self, callback):
        self._on_ptt_start = callback

    def on_ptt_stop(self, callback):
        self._on_ptt_stop = callback

    def on_ptt_cancel(self, callback):
        self._on_ptt_cancel = callback

    def on_ptt_interrupt(self, callback):
        """Corta el habla de JARVIS para que el usuario pueda hablar encima."""
        self._on_ptt_interrupt = callback

    def on_call_toggle(self, callback):
        """Registra el callback para activar/desactivar el modo llamada."""
        self._on_call_toggle = callback

    def _emergency_stop(self):
        self.set_state("idle")
        self.update_audio_level(0)
        if self._on_emergency:
            self._on_emergency()

    def _force_process(self):
        if self._on_force_process:
            self._on_force_process()

    def ask_confirmation(
        self,
        title: str,
        message: str,
        risk_level: str = "dangerous",
        timeout: int = 30,
        voice_confirm=None,
    ) -> bool:
        from gui.confirmation import ask_confirmation as _ask_confirmation
        from services.tts import speak

        def _voice_prompt():
            try:
                speak(f"{title}. {message}")
            except Exception:
                pass

        if voice_confirm is None:
            threading.Thread(target=_voice_prompt, daemon=True).start()

        return _ask_confirmation(
            self,
            title=title,
            message=message,
            risk_level=risk_level,
            timeout=timeout,
            voice_confirm=voice_confirm,
        )

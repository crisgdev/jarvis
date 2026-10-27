import threading
import customtkinter as ctk
from gui.components import StatusIndicator, AudioLevelBar, ControlBar
from gui.call_view import CallView
from config import get_config
from services.audio import get_threshold_level


class JarvisGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        cfg = get_config().get("gui", {})
        self._title = cfg.get("window_title", "JARVIS - Asistente Personal")
        size = cfg.get("window_size", [900, 700])

        self.title(self._title)
        self.geometry(f"{size[0]}x{size[1]}")
        self.minsize(600, 400)
        self.configure(fg_color="#0d1117")

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self._on_user_message = None
        self._on_mic_toggle = None
        self._on_call_toggle = None
        self._on_emergency = None
        self._on_force_process = None

        self._build_ui()
        self._call_view.start_animation()

    def _build_ui(self):
        header = ctk.CTkFrame(self, fg_color="#161b22", corner_radius=0, height=50)
        header.pack(fill="x")
        header.pack_propagate(False)

        ctk.CTkLabel(
            header, text="J.A.R.V.I.S.",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color="#2ecc71",
        ).pack(side="left", padx=20, pady=10)

        self._status = StatusIndicator(header)
        self._status.pack(side="right", padx=10, pady=8)

        self._view_container = ctk.CTkFrame(self, fg_color="#0d1117", corner_radius=0)
        self._view_container.pack(fill="both", expand=True, padx=0, pady=0)
        self._view_container.pack_propagate(False)

        self._call_view = CallView(self._view_container)
        self._call_view.pack(fill="both", expand=True)

        audio_frame = ctk.CTkFrame(self, fg_color="#161b22", corner_radius=0, height=88)
        audio_frame.pack(fill="x", padx=10, pady=(5, 0))
        audio_frame.pack_propagate(False)

        self._audio_bar = AudioLevelBar(audio_frame, threshold=get_threshold_level())
        self._audio_bar.pack(side="left", padx=10, pady=5, fill="x", expand=True)

        controls_frame = ctk.CTkFrame(self, fg_color="#161b22", corner_radius=0, height=70)
        controls_frame.pack(fill="x", padx=10, pady=5)
        controls_frame.pack_propagate(False)

        self._control_bar = ControlBar(
            controls_frame,
            on_call_toggle=self._call_toggled,
            onEmergency=self._emergency_stop,
            onForce=self._force_process,
        )
        self._control_bar.pack(fill="x", padx=(0, 10), pady=5)

    def _call_toggled(self, active: bool):
        if self._on_call_toggle:
            self._on_call_toggle(active)

    def _emergency_stop(self):
        self.set_state("idle")
        self.update_audio_level(0)
        if self._on_emergency:
            self._on_emergency()

    def _force_process(self):
        if self._on_force_process:
            self._on_force_process()

    def add_message(self, role: str, text: str):
        pass

    def set_state(self, state: str):
        self._status.set_state(state)
        self._call_view.set_state(state)

    def set_call_active(self, active: bool):
        self._control_bar.set_call_active(active)

    def update_audio_level(self, level: float):
        self._audio_bar.update_level(level)
        self._call_view.update_audio_level(level)

    def on_user_message(self, callback):
        self._on_user_message = callback

    def on_mic_toggle(self, callback):
        self._on_mic_toggle = callback

    def on_call_toggle(self, callback):
        self._on_call_toggle = callback

    def on_emergency(self, callback):
        self._on_emergency = callback

    def on_force_process(self, callback):
        self._on_force_process = callback

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
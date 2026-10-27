import customtkinter as ctk


class StatusIndicator(ctk.CTkFrame):
    STATES = {
        "idle": ("Esperando", "#7f8c8d"),
        "listening": ("Escuchando...", "#2ecc71"),
        "processing": ("Procesando...", "#f39c12"),
        "speaking": ("Hablando...", "#3498db"),
        "call": ("En llamada...", "#9b59b6"),
    }

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#1c1c1c", corner_radius=10, **kwargs)

        self._dot = ctk.CTkLabel(self, text="\u25cf", font=ctk.CTkFont(size=20), text_color="#7f8c8d")
        self._dot.pack(side="left", padx=(10, 5), pady=5)

        self._label = ctk.CTkLabel(self, text="Esperando", font=ctk.CTkFont(size=13))
        self._label.pack(side="left", padx=(0, 10), pady=5)

        self._state = "idle"

    def set_state(self, state: str):
        label, color = self.STATES.get(state, ("Desconocido", "#7f8c8d"))
        self._state = state
        self._dot.configure(text_color=color)
        self._label.configure(text=label)

    def get_state(self) -> str:
        return self._state


def _hex_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip("#")
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def _lerp_color(c1: tuple, c2: tuple, t: float) -> str:
    t = max(0.0, min(1.0, t))
    rgb = tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


class AudioLevelBar(ctk.CTkFrame):
    """Medidor de nivel de voz tipo barra, con degradado verde->ambar->rojo,
    una marca blanca en el umbral de deteccion y lectura numerica + estado.
    """

    def __init__(self, master, threshold=15.0, **kwargs):
        super().__init__(master, fg_color="#161b22", corner_radius=8, **kwargs)

        self._threshold_pct = max(1.0, min(99.0, float(threshold)))
        self._level = 0.0

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=(4, 0))

        ctk.CTkLabel(
            header, text="NIVEL DE VOZ", font=ctk.CTkFont(size=14, weight="bold"),
            text_color="#59d9a1", anchor="w",
        ).pack(side="left")

        self._status_label = ctk.CTkLabel(
            header, text="SILENCIO", font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#7f8c8d", anchor="e",
        )
        self._status_label.pack(side="right")

        self._canvas = ctk.CTkCanvas(
            self, height=30, bg="#161b22", highlightthickness=0,
        )
        self._canvas.pack(fill="x", padx=8, pady=(2, 4))

        self._pct_label = ctk.CTkLabel(
            self, text="0%", font=ctk.CTkFont(size=11),
            text_color="#8b949e", anchor="w",
        )
        self._pct_label.pack(fill="x", padx=10, pady=(0, 4))

        self.after(30, self._draw_meter)

    def set_threshold(self, threshold: float):
        self._threshold_pct = max(1.0, min(99.0, float(threshold)))
        self._draw_meter()

    def _fill_color(self, x_ratio: float) -> str:
        if x_ratio < 0.5:
            return _lerp_color((46, 204, 113), (243, 156, 18), x_ratio / 0.5)
        return _lerp_color((243, 156, 18), (231, 76, 60), (x_ratio - 0.5) / 0.5)

    def _draw_meter(self):
        c = self._canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 10:
            self.after(50, self._draw_meter)
            return

        x0, x1, y0, y1 = 2.0, w - 2.0, 3.0, 27.0
        full = x1 - x0

        c.create_rectangle(x0, y0, x1, y1, fill="#0d1117", outline="#30363d")

        thr_x = x0 + full * (self._threshold_pct / 100.0)
        c.create_line(thr_x, y0 - 2, thr_x, y1 + 2, fill="#f2f2f2", width=2)

        fill = max(0.0, min(1.0, self._level / 100.0))
        if fill > 0.01:
            fx = x0 + full * fill
            c.create_rectangle(x0, y0, fx, y1, fill=self._fill_color(fill), outline="")
            glow = f"#{127:02x}{255:02x}{212:02x}"
            c.create_line(x0, y0 - 0.5, fx, y0 - 0.5, fill=glow)

    def update_level(self, level: float):
        self._level = max(0.0, min(float(level), 100.0))
        self._draw_meter()

        pct = int(round(self._level))
        self._pct_label.configure(text=f"{pct}%")

        if self._level < 5:
            state, color = "SILENCIO", "#7f8c8d"
        elif self._level < self._threshold_pct:
            state, color = "HABLA MAS FUERTE", "#f39c12"
        elif self._level < 85:
            state, color = "TE OIGO", "#2ecc71"
        else:
            state, color = "MUY FUERTE", "#e74c3c"
        self._status_label.configure(text=state, text_color=color)


class ControlBar(ctk.CTkFrame):
    def __init__(self, master, on_call_toggle=None, onEmergency=None, onForce=None, **kwargs):
        super().__init__(master, fg_color="#1c1c1c", corner_radius=10, **kwargs)

        self._call_active = False
        self._on_call_toggle = on_call_toggle
        self._on_emergency = onEmergency
        self._on_force = onForce

        self._call_btn = ctk.CTkButton(
            self, text="\u23f9", font=ctk.CTkFont(size=22),
            width=50, height=50, corner_radius=25,
            fg_color="#e74c3c", hover_color="#c0392b",
            command=self._toggle_call,
        )
        self._call_btn.pack(side="left", padx=(15, 5), pady=10)

        ctk.CTkLabel(
            self, text="JARVIS", font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#2ecc71",
        ).pack(side="left", expand=True)

        self._force_btn = ctk.CTkButton(
            self, text="TERMINE", font=ctk.CTkFont(size=12, weight="bold"),
            width=74, height=35, corner_radius=8,
            fg_color="#2ecc71", hover_color="#27ae60",
            command=self._force,
        )
        self._force_btn.pack(side="right", padx=(0, 5), pady=10)

        self._emergency_btn = ctk.CTkButton(
            self, text="STOP", font=ctk.CTkFont(size=12, weight="bold"),
            width=60, height=35, corner_radius=8,
            fg_color="#e74c3c", hover_color="#c0392b",
            command=self._emergency,
        )
        self._emergency_btn.pack(side="right", padx=15, pady=10)

    def _toggle_call(self):
        self._call_active = not self._call_active
        if self._call_active:
            self._call_btn.configure(fg_color="#e74c3c", hover_color="#c0392b", text="\u23f9")
        else:
            self._call_btn.configure(fg_color="#3498db", hover_color="#2980b9", text="\u260e")
        if self._on_call_toggle:
            self._on_call_toggle(self._call_active)

    def _emergency(self):
        self._call_active = False
        self._call_btn.configure(fg_color="#3498db", hover_color="#2980b9", text="\u260e")
        if self._on_emergency:
            self._on_emergency()

    def _force(self):
        if self._on_force:
            self._on_force()

    def set_call_active(self, active: bool):
        self._call_active = active
        if active:
            self._call_btn.configure(fg_color="#e74c3c", hover_color="#c0392b", text="\u23f9")
        else:
            self._call_btn.configure(fg_color="#3498db", hover_color="#2980b9", text="\u260e")

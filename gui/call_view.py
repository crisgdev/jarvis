import math
import random

import customtkinter as ctk

from gui import theme


class CallView(ctk.CTkFrame):
    def __init__(self, master, on_press=None, on_release=None, **kwargs):
        super().__init__(master, fg_color=theme.BG, corner_radius=0, **kwargs)

        self._anim_running = False
        self._audio_level = 0.0
        self._state = "idle"
        self._angle = 0
        self._particles = []
        self._on_press = on_press
        self._on_release = on_release

        self._build_ui()
        self._bind_hold()
        self.set_state("idle")

    def _bind_hold(self):
        """Mantener pulsado el orbe = push-to-talk (igual que ESPACIO)."""
        for widget in (self._canvas, self._state_label):
            widget.bind("<ButtonPress-1>", self._handle_press, add="+")
            widget.bind("<ButtonRelease-1>", self._handle_release, add="+")

    def _handle_press(self, _event=None):
        if self._on_press is not None:
            self._on_press()

    def _handle_release(self, _event=None):
        if self._on_release is not None:
            self._on_release()

    def _build_ui(self):
        self._canvas = ctk.CTkCanvas(
            self, bg=theme.BG, highlightthickness=0, cursor="hand2",
        )
        self._canvas.pack(fill="both", expand=True)

        self._state_label = ctk.CTkLabel(
            self, text="LISTO",
            font=theme.font(18, "bold"),
            text_color=theme.GREEN,
        )
        self._state_label.place(relx=0.5, rely=0.88, anchor="center")

    def start_animation(self):
        self._anim_running = True
        self._animate()

    def stop_animation(self):
        self._anim_running = False

    def set_state(self, state: str):
        self._state = state
        colors = {
            "listening": theme.GREEN,
            "processing": theme.ORANGE,
            "speaking": "#3498db",
        }
        color = colors.get(state, "#7f8c8d")
        labels = {
            "idle": "LISTO",
            "call": "EN LLAMADA...",
            "listening": "ESCUCHANDO...",
            "processing": "PROCESANDO...",
            "speaking": "HABLANDO...",
        }
        self._state_label.configure(text=labels.get(state, state.upper()), text_color=color)

    def update_audio_level(self, level: float):
        self._audio_level = level

    def _animate(self):
        if not self._anim_running:
            return

        self._canvas.delete("all")
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()

        if w < 10 or h < 10:
            self.after(30, self._animate)
            return

        # Esfera centrada y un poco por debajo del centro: la leyenda de
        # estado vive abajo y asi hay aire entre el orbe y el borde superior.
        cx, cy = w // 2, h // 2 + 10
        # El orbe acompaña el tamano de la ventana pero con topes, para que
        # nunca se salga del lienzo en la ventana minima ni quede diminuto
        # en pantalla completa. Referencia: 488 px de alto en 900x700.
        self._k = max(0.62, min(1.35, min(w, h) / 488.0))
        self._angle += 0.03

        state_colors = {
            "listening": (46, 204, 113),
            "processing": (243, 156, 18),
            "speaking": (52, 152, 219),
        }
        base_rgb = state_colors.get(self._state, (127, 140, 141))

        level = self._audio_level / 100.0

        self._draw_rings(cx, cy, base_rgb, level)
        self._draw_orb(cx, cy, base_rgb, level)
        self._draw_particles(cx, cy, w, h, base_rgb, level)
        self._draw_rings_outer(cx, cy, base_rgb, level)

        self.after(33, self._animate)

    def _draw_rings(self, cx, cy, base_rgb, level):
        k = getattr(self, "_k", 1.0)
        for i in range(3):
            r = (76 + i * 28 + level * 22) * k
            alpha = max(0.05, 0.2 - i * 0.06 - level * 0.05)
            r_c = min(255, int(base_rgb[0] * alpha + 40))
            g_c = min(255, int(base_rgb[1] * alpha + 40))
            b_c = min(255, int(base_rgb[2] * alpha + 40))
            color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"

            wobble = math.sin(self._angle + i * 0.8) * 3 * k
            self._canvas.create_oval(
                cx - r + wobble, cy - r - wobble,
                cx + r + wobble, cy + r - wobble,
                outline=color, width=2,
            )

    def _draw_rings_outer(self, cx, cy, base_rgb, level):
        k = getattr(self, "_k", 1.0)
        for i in range(2):
            r = (168 + i * 34 + level * 32) * k
            alpha = max(0.03, 0.1 - i * 0.03)
            r_c = min(255, int(base_rgb[0] * alpha + 30))
            g_c = min(255, int(base_rgb[1] * alpha + 30))
            b_c = min(255, int(base_rgb[2] * alpha + 30))
            color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"

            self._canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=color, width=1, dash=(4, 8),
            )

    def _draw_orb(self, cx, cy, base_rgb, level):
        k = getattr(self, "_k", 1.0)
        pulse = (52 + level * 28 + math.sin(self._angle * 2) * 6) * k

        for i in range(5, 0, -1):
            r = pulse + i * 9 * k
            fade = max(0.02, 0.08 - i * 0.015)
            r_c = min(255, int(base_rgb[0] * fade + 20))
            g_c = min(255, int(base_rgb[1] * fade + 20))
            b_c = min(255, int(base_rgb[2] * fade + 20))
            color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"
            self._canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                fill=color, outline="",
            )

        core_r = pulse
        r_c = min(255, base_rgb[0] + 80)
        g_c = min(255, base_rgb[1] + 80)
        b_c = min(255, base_rgb[2] + 80)
        core_color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"

        self._canvas.create_oval(
            cx - core_r, cy - core_r,
            cx + core_r, cy + core_r,
            fill=core_color, outline="",
        )

        inner_r = core_r * 0.5
        self._canvas.create_oval(
            cx - inner_r, cy - inner_r,
            cx + inner_r, cy + inner_r,
            fill="#ffffff", outline="",
        )

    def _draw_particles(self, cx, cy, w, h, base_rgb, level):
        k = getattr(self, "_k", 1.0)
        num_particles = int(8 + level * 15)

        random.seed(int(self._angle * 10) % 100)

        for _ in range(num_particles):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(100 * k, min(w, h) * 0.44)
            px = cx + math.cos(angle + self._angle * 0.5) * dist
            py = cy + math.sin(angle + self._angle * 0.5) * dist
            size = random.uniform(1, 3)
            alpha = max(0.1, 0.5 - dist / (min(w, h) * 0.5))
            r_c = min(255, int(base_rgb[0] * alpha + 40))
            g_c = min(255, int(base_rgb[1] * alpha + 40))
            b_c = min(255, int(base_rgb[2] * alpha + 40))
            color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"

            self._canvas.create_oval(
                px - size, py - size, px + size, py + size,
                fill=color, outline="",
            )

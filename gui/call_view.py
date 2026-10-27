import math
import customtkinter as ctk


class CallView(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color="#0a0a1a", corner_radius=0, **kwargs)

        self._anim_running = False
        self._audio_level = 0.0
        self._state = "idle"
        self._angle = 0
        self._particles = []

        self._build_ui()
        self.set_state("idle")

    def _build_ui(self):
        self._canvas = ctk.CTkCanvas(
            self, bg="#0a0a1a", highlightthickness=0,
        )
        self._canvas.pack(fill="both", expand=True)

        self._state_label = ctk.CTkLabel(
            self, text="LISTO",
            font=ctk.CTkFont(size=16, weight="bold"),
            text_color="#2ecc71",
        )
        self._state_label.place(relx=0.5, rely=0.85, anchor="center")

        self._hint_label = ctk.CTkLabel(
            self, text="Ctrl+Shift+J o \u23f9 para colgar   |   TERMINE procesa ahora",
            font=ctk.CTkFont(size=11),
            text_color="#555555",
        )
        self._hint_label.place(relx=0.5, rely=0.92, anchor="center")

    def start_animation(self):
        self._anim_running = True
        self._animate()

    def stop_animation(self):
        self._anim_running = False

    def set_state(self, state: str):
        self._state = state
        colors = {
            "listening": "#2ecc71",
            "processing": "#f39c12",
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

        cx, cy = w // 2, h // 2 - 30
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
        self._draw_level_strip(w, h, base_rgb)

        self.after(33, self._animate)

    def _draw_level_strip(self, w, h, base_rgb):
        bar_h = 10
        bar_w = min(w * 0.5, 320)
        x0 = (w - bar_w) / 2
        y0 = h - 78
        y1 = y0 + bar_h

        def lerp(c1, c2, t):
            t = max(0.0, min(1.0, t))
            return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))

        def hexc(t):
            return f"#{t[0]:02x}{t[1]:02x}{t[2]:02x}"

        green, amber, red = (46, 204, 113), (243, 156, 18), (231, 76, 60)

        self._canvas.create_rectangle(x0, y0, x0 + bar_w, y1, fill="#0d1117", outline="#30363d")

        thr_x = x0 + bar_w * 0.15
        self._canvas.create_line(thr_x, y0 - 2, thr_x, y1 + 2, fill="#ffffff", width=2)

        level = max(0.0, min(1.0, self._audio_level / 100.0))
        if level > 0.01:
            ratio = level * 0.95
            if ratio < 0.5:
                col = lerp(green, amber, ratio / 0.5)
            else:
                col = lerp(amber, red, (ratio - 0.5) / 0.5)
            fill_w = bar_w * level
            self._canvas.create_rectangle(x0, y0, x0 + fill_w, y1, fill=hexc(col), outline="")
            self._canvas.create_rectangle(x0, y0 - 1, x0 + fill_w, y0, fill=hexc(tuple(min(255, c + 60) for c in col)))

    def _draw_rings(self, cx, cy, base_rgb, level):
        for i in range(3):
            r = 60 + i * 25 + level * 20
            alpha = max(0.05, 0.2 - i * 0.06 - level * 0.05)
            r_c = min(255, int(base_rgb[0] * alpha + 40))
            g_c = min(255, int(base_rgb[1] * alpha + 40))
            b_c = min(255, int(base_rgb[2] * alpha + 40))
            color = f"#{r_c:02x}{g_c:02x}{b_c:02x}"

            wobble = math.sin(self._angle + i * 0.8) * 3
            self._canvas.create_oval(
                cx - r + wobble, cy - r - wobble,
                cx + r + wobble, cy + r - wobble,
                outline=color, width=2,
            )

    def _draw_rings_outer(self, cx, cy, base_rgb, level):
        for i in range(2):
            r = 140 + i * 30 + level * 30
            dash_offset = self._angle * 20 + i * 40
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
        pulse = 40 + level * 25 + math.sin(self._angle * 2) * 5

        for i in range(5, 0, -1):
            r = pulse + i * 8
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
        import random
        num_particles = int(8 + level * 15)

        random.seed(int(self._angle * 10) % 100)

        for _ in range(num_particles):
            angle = random.uniform(0, 2 * math.pi)
            dist = random.uniform(80, min(w, h) * 0.4)
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

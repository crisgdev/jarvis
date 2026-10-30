"""Subtitulos tipo YouTube para lo que dice el usuario y lo que responde JARVIS.

Las lineas nuevas entran abajo, centradas; las viejas suben y, tras unos
segundos, se desvanecen interpolando su color hacia el fondo y se eliminan.
"""

import time

import customtkinter as ctk

from gui import theme

ROLE_STYLE = {
    "user": ("T\u00da >", theme.GREEN),
    "model": ("JARVIS >", theme.WHITE),
    "system": ("SISTEMA >", theme.MUTED),
}

MAX_CHARS = 360


class SubtitleStack(ctk.CTkFrame):
    HEIGHT = 138
    MAX_LINES = 3
    TTL = 7.0
    FADE = 2.0
    WRAP = 720

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG, corner_radius=0, height=self.HEIGHT, **kwargs)
        self.pack_propagate(False)

        self._container = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self._container.pack(side="bottom", fill="x", padx=24, pady=(0, 8))

        self._entries = []

    def add(self, role: str, text: str):
        text = " ".join(str(text or "").split())
        if not text:
            return
        if len(text) > MAX_CHARS:
            text = text[: MAX_CHARS - 1].rstrip() + "\u2026"

        prefix_text, color = ROLE_STYLE.get(role, ROLE_STYLE["system"])

        # Fila a todo el ancho; dentro, una linea que se empaqueta centrada
        # para que el bloque completo (prefijo + texto) quede al medio.
        row = ctk.CTkFrame(self._container, fg_color=theme.BG, corner_radius=0)
        row.pack(side="top", fill="x", pady=2)

        line = ctk.CTkFrame(row, fg_color=theme.BG, corner_radius=0)
        line.pack(anchor="center")

        prefix = ctk.CTkLabel(
            line, text=prefix_text, font=theme.font(13, "bold"),
            text_color=theme.CELESTE, anchor="w", justify="left",
        )
        prefix.pack(side="left", anchor="n", padx=(0, 8))

        body = ctk.CTkLabel(
            line, text=text, font=theme.font(13), text_color=color,
            anchor="w", justify="left", wraplength=self.WRAP,
        )
        body.pack(side="left", anchor="n")

        entry = {
            "frame": row,
            "prefix": prefix,
            "body": body,
            "prefix_color": theme.CELESTE,
            "body_color": color,
            "created": time.perf_counter(),
        }
        self._entries.append(entry)

        while len(self._entries) > self.MAX_LINES:
            self._drop(self._entries[0])

    def clear(self):
        for entry in list(self._entries):
            self._drop(entry)

    def tick(self):
        now = time.perf_counter()
        for entry in list(self._entries):
            age = now - entry["created"]
            if age <= self.TTL:
                continue
            t = (age - self.TTL) / self.FADE
            if t >= 1.0:
                self._drop(entry)
                continue
            entry["prefix"].configure(
                text_color=theme.lerp_color(entry["prefix_color"], theme.BG, t)
            )
            entry["body"].configure(
                text_color=theme.lerp_color(entry["body_color"], theme.BG, t)
            )

    def _drop(self, entry):
        if entry in self._entries:
            self._entries.remove(entry)
        try:
            entry["frame"].destroy()
        except Exception:
            pass

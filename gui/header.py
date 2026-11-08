"""Barra superior (titulo, leyenda de push-to-talk y reloj) y tarjeta de estado."""

import datetime

import customtkinter as ctk

from gui import theme

WEEKDAYS = ["DOM", "LUN", "MAR", "MI\u00c9", "JUE", "VIE", "S\u00c1B"]
MONTHS = [
    "ENE", "FEB", "MAR", "ABR", "MAY", "JUN",
    "JUL", "AGO", "SEP", "OCT", "NOV", "DIC",
]

HINT_IDLE = "MANT\u00c9N ESPACIO O EL ORBE PARA HABLAR"
HINT_LISTENING = "ESCUCHANDO\u2026 SUELTA PARA ENVIAR"
HINT_DEAF = "MODO SORDO \u2014 TOCA EL ORBE PARA VOLVER A ESCUCHAR"


def format_turn_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m {rest:02d}s"


class TopBar(ctk.CTkFrame):
    HEIGHT = 74

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG, corner_radius=0, height=self.HEIGHT, **kwargs)
        self.pack_propagate(False)

        ctk.CTkLabel(
            self, text="J.A.R.V.I.S.", font=theme.font(25, "bold"),
            text_color=theme.CELESTE,
        ).pack(side="left", padx=(24, 0))

        clock = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        clock.pack(side="right", padx=(0, 24))

        top = ctk.CTkFrame(clock, fg_color=theme.BG, corner_radius=0)
        top.pack(anchor="e")

        self._time = ctk.CTkLabel(
            top, text="--:--:--", font=theme.font(29, "bold"),
            text_color=theme.CELESTE,
        )
        self._time.pack(side="left")

        self._ampm = ctk.CTkLabel(
            top, text="", font=theme.font(11, "bold"), text_color=theme.CELESTE,
        )
        self._ampm.pack(side="left", anchor="s", padx=(4, 0), pady=(0, 7))

        self._date = ctk.CTkLabel(
            clock, text="", font=theme.font(12, "bold"),
            text_color=theme.CELESTE, anchor="e",
        )
        self._date.pack(anchor="e")

        # place() para que quede centrada respecto a la VENTANA, no a los
        # hermanos que estan a la izquierda y derecha.
        self._hint = ctk.CTkLabel(
            self, text=HINT_IDLE, font=theme.font(12, "bold"), text_color=theme.CELESTE,
        )
        self._hint.place(relx=0.5, rely=0.5, anchor="center")

        self._last_clock = None
        self.tick()

    def set_hint(self, text: str):
        self._hint.configure(text=text)

    def tick(self):
        now = datetime.datetime.now()
        hour = now.hour % 12 or 12
        stamp = f"{hour}:{now.minute:02d}:{now.second:02d}"
        if stamp != self._last_clock:
            self._last_clock = stamp
            self._time.configure(text=stamp)
            self._ampm.configure(text="AM" if now.hour < 12 else "PM")
            self._date.configure(
                text=f"{WEEKDAYS[(now.weekday() + 1) % 7]}, {now.day:02d} {MONTHS[now.month - 1]}"
            )


class InfoCard(ctk.CTkFrame):
    """Cuadrito tecnologico: MODELO / ESTADO / TIEMPO TURNO.

    Las fuentes salen de `theme.font()`, asi que crecen junto con la ventana
    (y un poco mas que el resto: es el panel que el usuario mira de reojo).
    """

    ROWS = (
        ("MODELO", "model"),
        ("ESTADO", "state"),
        ("TIEMPO TURNO", "turn"),
    )

    def __init__(self, master, **kwargs):
        super().__init__(
            master, fg_color=theme.BG, corner_radius=8,
            border_width=1, border_color=theme.BORDER, **kwargs,
        )
        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)

        self._values = {}
        for index, (label, key) in enumerate(self.ROWS):
            ctk.CTkLabel(
                self, text=label, font=theme.font(11, "bold"),
                text_color=theme.CELESTE, anchor="w",
            ).grid(row=index, column=0, sticky="w", padx=(16, 20), pady=(9 if index == 0 else 2, 2))

            value = ctk.CTkLabel(
                self, text="\u2014", font=theme.font(12, "bold"),
                text_color=theme.WHITE, anchor="e",
            )
            value.grid(row=index, column=1, sticky="e", padx=(0, 16), pady=(9 if index == 0 else 2, 2))
            self._values[key] = value

        self._values["turn"].grid_configure(pady=(2, 9))

        self._last = {}

    def _set(self, key: str, text: str):
        if self._last.get(key) == text:
            return
        self._last[key] = text
        self._values[key].configure(text=text)

    def set_model(self, model: str):
        self._set("model", (model or "\u2014").upper())

    def set_state(self, state: str):
        self._set("state", state)

    def set_turn_seconds(self, seconds: float):
        self._set("turn", format_turn_time(seconds))

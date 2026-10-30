"""Panel de subtareas del turno actual (estilo 'Todos' de OpenCode).

Las filas se crean de dos formas:
  * con el plan que declara Gemini (tool `show_plan`), o
  * automaticamente con cada tool que se ejecuta de verdad.

Estados de una fila:
  pending -> blanca, sin tiempo
  running -> blanca con el tiempo en naranja (sube segundo a segundo)
  done    -> tiempo en verde + ✔
  error   -> tiempo en rojo + ✖

Las alturas se calculan con `theme.px()`, asi que el panel crece junto con
las fuentes cuando la ventana cambia de tamano.
"""

import time

import customtkinter as ctk

from gui import theme

PADDING = 6


def header_height() -> int:
    return theme.px(24)


def row_height() -> int:
    return theme.px(24)


def format_seconds(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    rest = int(seconds % 60)
    return f"{minutes}m {rest:02d}s"


def shorten(text: str, limit: int = 32) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "\u2026"


class TaskPanel(ctk.CTkFrame):
    WIDTH = 310

    def __init__(self, master, **kwargs):
        super().__init__(master, fg_color=theme.BG, corner_radius=0, **kwargs)

        self._rows = []
        self._plan_rows = []
        self._active = None
        self._counter = 0
        self._last_height = -1

        self._header = ctk.CTkFrame(
            self, fg_color=theme.BG, corner_radius=0, height=header_height()
        )
        self._header.pack(fill="x")
        self._header.pack_propagate(False)

        self._title = ctk.CTkLabel(
            self._header, text="PENDIENTES", font=theme.font(13, "bold"),
            text_color=theme.CELESTE, anchor="w",
        )
        self._title.pack(side="left")

        self._count = ctk.CTkLabel(
            self._header, text="0", font=theme.font(13, "bold"),
            text_color=theme.CELESTE, anchor="e",
        )
        self._count.pack(side="right")

        self._body = ctk.CTkFrame(self, fg_color=theme.BG, corner_radius=0)
        self._body.pack(fill="x")

        self._update_geometry()

    # ── API ──────────────────────────────────────────────────────────

    def begin_turn(self):
        """Arranca un turno nuevo: limpia y deja 'Interpretar la orden'."""
        self.reset()
        self._add_row("Interpretar la orden", state="running", kind="interpret", key="interpret")

    def finish_interpret(self):
        for row in self._rows:
            if row["kind"] == "interpret" and row["state"] == "running":
                self._finish_row(row, ok=True)

    def set_plan(self, steps):
        """Gemini declaro el plan: se agregan como pendientes (blancas)."""
        for row in list(self._plan_rows):
            self._destroy_row(row)
        self._plan_rows = []
        for step in steps:
            label = str(step or "").strip()
            if not label:
                continue
            row = self._add_row(label, state="pending", kind="plan")
            self._plan_rows.append(row)
        self._update_geometry()

    def start_task(self, label=None, key=None):
        """Marca en naranja la primera subtarea pendiente del plan.

        Si no queda plan por delante, agrega una fila con la etiqueta de la
        tool real (fallback cuando Gemini no llamo a `show_plan`).
        """
        self.finish_interpret()
        row = next((r for r in self._rows if r["state"] == "pending"), None)
        if row is None:
            row = self._add_row(label or "Trabajando\u2026", state="running", kind="tool")
        row["state"] = "running"
        row["key"] = key
        row["started"] = time.perf_counter()
        self._active = row
        self._paint(row)
        self._update_geometry()
        return row["id"]

    def finish_task(self, key=None, ok=True):
        row = None
        if key is not None:
            row = next((r for r in self._rows if r.get("key") == key), None)
        if row is None:
            row = self._active
        if row is None or row["state"] != "running":
            return
        self._finish_row(row, ok=ok)
        self._update_geometry()

    def close_open(self):
        """Cierra el turno: nada queda naranja ni pendiente para siempre."""
        if self._active is not None and self._active["state"] == "running":
            self._finish_row(self._active, ok=True)
        for row in self._rows:
            if row["state"] == "pending":
                row["state"] = "done"
                row["elapsed"] = 0.0
                self._paint(row)
        self._update_geometry()

    def reset(self):
        for row in self._rows:
            row["frame"].destroy()
        self._rows = []
        self._plan_rows = []
        self._active = None
        self._count.configure(text="0")
        self._update_geometry()

    def refresh_geometry(self):
        """Recalcula tamanos tras un cambio de escala de fuentes."""
        self._last_height = -1
        self._update_geometry()

    def tick(self):
        running = 0
        now = time.perf_counter()
        for row in self._rows:
            if row["state"] != "running":
                continue
            running += 1
            row["elapsed"] = max(0.0, now - row["started"])
            text = format_seconds(row["elapsed"])
            if row.get("shown") != text:
                row["shown"] = text
                row["time"].configure(text=text)
        return running

    # ── Interno ──────────────────────────────────────────────────────

    def _add_row(self, label, state="pending", kind="tool", key=None):
        self._counter += 1
        frame = ctk.CTkFrame(
            self._body, fg_color=theme.BG, corner_radius=0, height=row_height(),
        )
        frame.pack(fill="x")
        frame.pack_propagate(False)

        label_w = ctk.CTkLabel(
            frame, text=shorten(label), font=theme.font(12),
            text_color=theme.WHITE, anchor="w", justify="left",
        )
        label_w.pack(side="left", fill="x", expand=True)

        time_w = ctk.CTkLabel(
            frame, text="0s", font=theme.font(12), text_color=theme.MUTED,
            anchor="e", width=theme.px(60),
        )
        time_w.pack(side="right")

        row = {
            "id": self._counter,
            "frame": frame,
            "label": label_w,
            "time": time_w,
            "state": state,
            "kind": kind,
            "key": key,
            "started": time.perf_counter() if state == "running" else None,
            "elapsed": 0.0,
            "shown": None,
            "ok": True,
        }
        self._rows.append(row)
        self._paint(row)
        return row

    def _paint(self, row):
        state = row["state"]
        if state == "running":
            row["elapsed"] = max(0.0, time.perf_counter() - (row["started"] or 0.0))
        row["shown"] = format_seconds(row["elapsed"])
        if state == "pending":
            row["time"].configure(text="", text_color=theme.MUTED)
        elif state == "running":
            row["time"].configure(text=row["shown"], text_color=theme.ORANGE)
        elif state == "error":
            row["time"].configure(text=f"{row['shown']} \u2716", text_color=theme.RED)
        else:
            row["time"].configure(text=f"{row['shown']} \u2714", text_color=theme.GREEN)

    def _finish_row(self, row, ok=True):
        if row["started"] is not None and row["state"] == "running":
            row["elapsed"] = max(0.0, time.perf_counter() - row["started"])
        row["state"] = "done" if ok else "error"
        row["ok"] = ok
        self._paint(row)
        if self._active is row:
            self._active = None

    def _destroy_row(self, row):
        try:
            row["frame"].destroy()
        except Exception:
            pass
        if row in self._rows:
            self._rows.remove(row)
        if self._active is row:
            self._active = None

    def _update_geometry(self):
        try:
            self._count.configure(text=str(len(self._rows)))
            self._header.configure(height=header_height())
            for row in self._rows:
                row["frame"].configure(height=row_height())
                row["time"].configure(width=theme.px(60))
            height = header_height() + PADDING + row_height() * max(1, len(self._rows))
            if height != self._last_height:
                self._last_height = height
                self.place_configure(width=theme.px(self.WIDTH), height=height)
        except Exception:
            pass

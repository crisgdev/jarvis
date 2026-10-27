import customtkinter as ctk
import threading
import logging

logger = logging.getLogger("jarvis.confirmation")


class ConfirmationDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        title: str,
        message: str,
        risk_level: str = "moderate",
        on_confirm=None,
        on_cancel=None,
        timeout: int = 30,
        voice_mode: bool = False,
        **kwargs,
    ):
        super().__init__(master, **kwargs)

        self.result = None
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._timeout = timeout
        self._voice_mode = voice_mode
        self._timer = None

        self.title(title)
        self.geometry("420x250")
        self.resizable(False, False)
        self.configure(fg_color="#1a1a2e")
        self.transient(master)
        self.grab_set()

        self.after(100, self._center)

        border_color = "#e74c3c" if risk_level == "dangerous" else "#f39c12"

        ctk.CTkFrame(self, fg_color=border_color, corner_radius=0).pack(fill="x", padx=0, pady=0)

        content = ctk.CTkFrame(self, fg_color="#16213e", corner_radius=0)
        content.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        risk_label = "PELIGROSO" if risk_level == "dangerous" else "REQUIERE CONFIRMACION"
        ctk.CTkLabel(
            content, text=risk_label, font=ctk.CTkFont(size=11, weight="bold"),
            text_color="#e74c3c" if risk_level == "dangerous" else "#f39c12",
        ).pack(pady=(15, 5))

        ctk.CTkLabel(
            content, text=title, font=ctk.CTkFont(size=15, weight="bold"),
            text_color="#ecf0f1",
        ).pack(pady=(5, 5))

        ctk.CTkLabel(
            content, text=message, font=ctk.CTkFont(size=12),
            text_color="#bdc3c7", wraplength=360,
        ).pack(pady=(0, 10))

        self._timer_label = ctk.CTkLabel(
            content, text=f"Auto-cancelar en {self._timeout}s",
            font=ctk.CTkFont(size=10), text_color="#7f8c8d",
        )
        self._timer_label.pack()

        btn_frame = ctk.CTkFrame(content, fg_color="transparent")
        btn_frame.pack(pady=(5, 10))

        ctk.CTkButton(
            btn_frame, text="Cancelar", width=120, height=35,
            fg_color="#7f8c8d", hover_color="#95a5a6",
            command=self._cancel,
        ).pack(side="left", padx=10)

        confirm_color = "#e74c3c" if risk_level == "dangerous" else "#2ecc71"
        confirm_hover = "#c0392b" if risk_level == "dangerous" else "#27ae60"
        ctk.CTkButton(
            btn_frame, text="Confirmar", width=120, height=35,
            fg_color=confirm_color, hover_color=confirm_hover,
            command=self._confirm,
        ).pack(side="left", padx=10)

        self._start_timer()

    def _center(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _start_timer(self):
        if self._voice_mode:
            self._remaining = None
            self._timer_label.configure(text="Confirma por voz o con los botones")
            return
        self._remaining = self._timeout
        self._tick()

    def _tick(self):
        if self._remaining <= 0:
            self._cancel()
            return
        self._timer_label.configure(text=f"Auto-cancelar en {self._remaining}s")
        self._remaining -= 1
        self._timer = self.after(1000, self._tick)

    def _confirm(self):
        self.result = True
        if self._timer:
            self.after_cancel(self._timer)
        if self._on_confirm:
            self._on_confirm()
        self.grab_release()
        self.destroy()

    def _cancel(self):
        self.result = False
        if self._timer:
            self.after_cancel(self._timer)
        if self._on_cancel:
            self._on_cancel()
        self.grab_release()
        self.destroy()

    def _force_close(self):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


def ask_confirmation(
    master,
    title: str,
    message: str,
    risk_level: str = "moderate",
    timeout: int = 30,
    voice_confirm=None,
) -> bool:
    result = [None]
    event = threading.Event()
    dialog_ref: dict = {}

    def set_result(val: bool):
        if result[0] is not None:
            return
        result[0] = bool(val)
        event.set()
        dlg = dialog_ref.get("dlg")
        if dlg is not None:
            try:
                master.after(0, dlg._force_close)
            except Exception:
                pass

    def _open():
        dlg = ConfirmationDialog(
            master,
            title=title,
            message=message,
            risk_level=risk_level,
            on_confirm=lambda: set_result(True),
            on_cancel=lambda: set_result(False),
            timeout=timeout,
            voice_mode=voice_confirm is not None,
        )
        dialog_ref["dlg"] = dlg

    master.after(0, _open)

    if voice_confirm is not None:
        def _voice_worker():
            try:
                set_result(bool(voice_confirm()))
            except Exception as e:
                logger.error("Error en confirmacion por voz: %s", e)
                set_result(False)

        threading.Thread(target=_voice_worker, daemon=True).start()

    wait_seconds = timeout + 30 if voice_confirm is not None else timeout + 5
    event.wait(wait_seconds)

    dlg = dialog_ref.get("dlg")
    if result[0] is None and dlg is not None:
        try:
            master.after(0, dlg._force_close)
        except Exception:
            pass

    return bool(result[0])

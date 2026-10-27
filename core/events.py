import logging
import threading
import time
import psutil
from typing import Callable, Optional

logger = logging.getLogger("jarvis.events")


class EventMonitor:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._on_event: Optional[Callable] = None
        self._interval = 60
        self._last_battery = None
        self._last_disk = None

    def start(self, on_event: Callable, interval: int = 60):
        if self._running:
            return
        self._on_event = on_event
        self._interval = interval
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("EventMonitor iniciado (interval=%ds)", interval)

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("EventMonitor detenido")

    def _loop(self):
        while self._running:
            try:
                self._check_events()
            except Exception as e:
                logger.error("Error chequeando eventos: %s", e)
            time.sleep(self._interval)

    def _check_events(self):
        self._check_battery()
        self._check_disk()
        self._check_memory()

    def _check_battery(self):
        battery = psutil.sensors_battery()
        if not battery:
            return

        percent = battery.percent
        plugged = battery.power_plugged

        if self._last_battery is not None:
            prev_percent, prev_plugged = self._last_battery

            if not plugged and prev_plugged:
                self._emit("battery_unplugged", f"Bateria: {percent}% (desconectada)")

            if percent <= 15 and prev_percent > 15:
                self._emit("battery_low", f"Bateria critica: {percent}%%")

            if percent <= 5:
                self._emit("battery_critical", f"Bateria al {percent}%%, conecta el cargador!")

        self._last_battery = (percent, plugged)

    def _check_disk(self):
        disk = psutil.disk_usage("/")
        percent = disk.percent

        if self._last_disk is not None:
            if percent >= 90 and self._last_disk < 90:
                free_gb = disk.free / (1024**3)
                self._emit("disk_full", f"Disco al {percent}%%, solo {free_gb:.1f}GB libres")

        self._last_disk = percent

    def _check_memory(self):
        mem = psutil.virtual_memory()
        if mem.percent >= 90:
            self._emit("memory_high", f"RAM al {mem.percent}%%, rendimiento puede degradarse")

    def _emit(self, event_type: str, message: str):
        logger.info("Evento: %s - %s", event_type, message)
        if self._on_event:
            self._on_event(event_type, message)

import time
import unittest
from unittest import mock

from services import clap_detector as cd


class ClapLogicTest(unittest.TestCase):
    def setUp(self):
        # Reset global state without opening any stream
        with cd._lock:
            cd._enabled = True
            cd._running = True
            cd._paused = False
            cd._threshold = 20000
            cd._min_window = 0.12
            cd._max_window = 0.9
            cd._cooldown = 2.5
            cd._in_clap = False
            cd._last_clap_time = None
            cd._cooldown_until = 0.0
            cd._callback = None
            cd._stream = None

    def test_single_clap_sets_last_time(self):
        now = time.monotonic()
        cd._register_clap(now)
        self.assertEqual(cd._last_clap_time, now)
        self.assertEqual(cd._cooldown_until, 0.0)

    def test_double_clap_within_window_triggers(self):
        t0 = time.monotonic()
        cd._register_clap(t0)
        self.assertIsNotNone(cd._last_clap_time)
        # segunda palmada dentro de la ventana
        t1 = t0 + 0.3
        cd._register_clap(t1)
        # tras doble palmada, last_clap_time se limpia y hay cooldown
        self.assertIsNone(cd._last_clap_time)
        self.assertGreater(cd._cooldown_until, t1)

    def test_double_clap_too_fast_ignored(self):
        t0 = time.monotonic()
        cd._register_clap(t0)
        # segunda palmada demasiado rapida (< min_window): se trata como nueva
        t1 = t0 + 0.05
        cd._register_clap(t1)
        self.assertEqual(cd._last_clap_time, t1)
        self.assertEqual(cd._cooldown_until, 0.0)

    def test_double_clap_too_slow_resets(self):
        t0 = time.monotonic()
        cd._register_clap(t0)
        # segunda palmada fuera de la ventana max: se trata como nueva
        t1 = t0 + 2.0
        cd._register_clap(t1)
        self.assertEqual(cd._last_clap_time, t1)
        self.assertEqual(cd._cooldown_until, 0.0)

    def test_cooldown_blocks_subsequent_claps(self):
        t0 = time.monotonic()
        cd._register_clap(t0)
        cd._register_clap(t0 + 0.3)  # doble -> cooldown
        # una tercera palmada dentro del cooldown no dispara otro doble
        cd._register_clap(t0 + 0.5)
        self.assertIsNone(cd._last_clap_time)  # sigue bloqueado, no registra
        # (cooldown_until sigue vigente)
        self.assertGreater(cd._cooldown_until, t0 + 0.5)

    def test_handle_chunk_rising_edge(self):
        # pico alto seguido de bajo: una sola palmada
        now = time.monotonic()
        cd._handle_chunk(25000, now)
        self.assertTrue(cd._in_clap)
        self.assertIsNotNone(cd._last_clap_time)
        cd._handle_chunk(1000, now + 0.05)
        self.assertFalse(cd._in_clap)

    def test_handle_chunk_below_threshold_does_nothing(self):
        now = time.monotonic()
        cd._handle_chunk(5000, now)
        self.assertFalse(cd._in_clap)
        self.assertIsNone(cd._last_clap_time)

    def test_handle_chunk_paused_ignored(self):
        cd._paused = True
        now = time.monotonic()
        cd._handle_chunk(25000, now)
        self.assertFalse(cd._in_clap)
        self.assertIsNone(cd._last_clap_time)

    def test_start_disabled_returns_false(self):
        with mock.patch.object(cd, "_settings", return_value={"enabled": False}):
            # reset enabled
            cd._enabled = False
            cd._running = False
            ok = cd.start_clap_listener(lambda: None)
        self.assertFalse(ok)

    def test_pause_resume_idempotent(self):
        cd._stream = None
        cd._paused = False
        cd.pause()
        self.assertTrue(cd._paused)
        # resume sin stream abierto intenta abrir; con mock de _open_stream no explota
        with mock.patch.object(cd, "_open_stream"):
            cd.resume()
        self.assertFalse(cd._paused)

    def test_stop_clears_state(self):
        cd.stop_clap_listener()
        self.assertFalse(cd._running)
        self.assertFalse(cd._enabled)
        self.assertIsNone(cd._callback)


if __name__ == "__main__":
    unittest.main()

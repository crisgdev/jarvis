import threading
import unittest
from unittest import mock

from core import jarvis as core_jarvis
from core.jarvis import State


class FakeJarvis:
    """Suficiente superficie de JARVIS para _watch_recording / start_listening."""

    def __init__(self):
        self.state = State.IDLE
        self._lock = threading.Lock()
        self._on_state_change = None
        self.stop_calls = 0

    def stop_listening(self):
        self.stop_calls += 1
        self.state = State.IDLE

    def _set_state(self, new_state):
        self.state = new_state


FakeJarvis._watch_recording = core_jarvis.JARVIS._watch_recording


class FakeThread:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def start(self):
        pass


class WatchRecordingTest(unittest.TestCase):
    def _watch(self, fake, is_recording=None, silence=False, max_seconds=0):
        is_recording = True if is_recording is None else is_recording
        with mock.patch("core.jarvis.is_recording", return_value=is_recording), \
             mock.patch("core.jarvis.is_silence_detected", return_value=silence), \
             mock.patch("core.jarvis.get_max_record_seconds", return_value=max_seconds):
            core_jarvis.JARVIS._watch_recording(fake)

    def test_stops_when_silence_detected(self):
        fake = FakeJarvis()
        fake.state = State.LISTENING
        self._watch(fake, is_recording=True, silence=True)
        self.assertEqual(fake.stop_calls, 1)
        self.assertEqual(fake.state, State.IDLE)

    def test_stops_when_recording_ended_anyway(self):
        fake = FakeJarvis()
        fake.state = State.LISTENING
        self._watch(fake, is_recording=False)
        self.assertEqual(fake.stop_calls, 1)

    def test_noop_when_no_longer_listening(self):
        fake = FakeJarvis()
        fake.state = State.IDLE
        self._watch(fake, is_recording=True, silence=False)
        self.assertEqual(fake.stop_calls, 0)


class StartListeningOneShotTest(unittest.TestCase):
    def _start(self, fake):
        started = []
        with mock.patch("core.jarvis.start_recording") as mock_rec:
            with mock.patch("core.jarvis.threading.Thread", side_effect=lambda **kw: FakeThread(**kw)):
                core_jarvis.JARVIS.start_listening(fake)
        return mock_rec, started

    def test_idle_starts_recording_and_spawns_watchdog(self):
        fake = FakeJarvis()
        mock_rec, started = self._start(fake)
        mock_rec.assert_called_once()
        self.assertEqual(fake.state, State.LISTENING)

    def test_not_idle_does_nothing(self):
        fake = FakeJarvis()
        fake.state = State.CALL
        mock_rec, started = self._start(fake)
        mock_rec.assert_not_called()
        self.assertEqual(fake.state, State.CALL)


class FakeCallState:
    """Superficie minima de JARVIS para el estado de llamada y su aviso a la GUI."""

    def __init__(self):
        self.state = State.IDLE
        self._call_active = False
        self._on_call_active = None
        self.notifications = []

    def _set_state(self, new_state):
        self.state = new_state

    def _call_loop(self):
        pass


FakeCallState._set_call_active = core_jarvis.JARVIS._set_call_active
FakeCallState.is_call_active = core_jarvis.JARVIS.is_call_active


class CallStateCallbackTest(unittest.TestCase):
    """El boton de llamada de la GUI se sincroniza con el estado real."""

    def _fake(self):
        fake = FakeCallState()
        fake._on_call_active = fake.notifications.append
        return fake

    def _stoppable(self):
        return mock.patch("core.jarvis.is_recording", return_value=False), \
            mock.patch("core.jarvis.is_speaking", return_value=False), \
            mock.patch("core.jarvis.stop_recording"), \
            mock.patch("core.jarvis.stop_speech")

    def test_notifies_only_on_change(self):
        fake = self._fake()
        core_jarvis.JARVIS._set_call_active(fake, True)
        core_jarvis.JARVIS._set_call_active(fake, True)
        self.assertEqual(fake.notifications, [True])
        self.assertTrue(fake.is_call_active())

    def test_start_call_notifies_true(self):
        fake = self._fake()
        with mock.patch("core.jarvis.threading.Thread", side_effect=lambda **kw: FakeThread(**kw)):
            core_jarvis.JARVIS.start_call(fake)
        self.assertEqual(fake.notifications, [True])
        self.assertEqual(fake.state, State.CALL)

    def test_stop_call_notifies_false(self):
        fake = self._fake()
        fake._call_active = True
        rec, speak, stop_rec, stop_sp = self._stoppable()
        with rec, speak, stop_rec, stop_sp:
            core_jarvis.JARVIS.stop_call(fake)
        self.assertEqual(fake.notifications, [False])
        self.assertFalse(fake.is_call_active())

    def test_emergency_stop_notifies_false(self):
        fake = self._fake()
        fake._call_active = True
        rec, speak, stop_rec, stop_sp = self._stoppable()
        with rec, speak, stop_rec, stop_sp:
            core_jarvis.JARVIS.emergency_stop(fake)
        self.assertEqual(fake.notifications, [False])
        self.assertEqual(fake.state, State.IDLE)

    def test_callback_error_does_not_break_state(self):
        fake = self._fake()
        fake._on_call_active = mock.Mock(side_effect=RuntimeError("GUI caida"))
        core_jarvis.JARVIS._set_call_active(fake, True)
        self.assertTrue(fake.is_call_active())


if __name__ == "__main__":
    unittest.main()
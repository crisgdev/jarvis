import unittest

from services.audio import (
    SilenceDetector,
    get_max_record_seconds,
    get_threshold_level,
    get_audio_level,
    _level_from_rms,
)


class SilenceDetectorTest(unittest.TestCase):
    def setUp(self):
        self.detector = SilenceDetector(threshold=500, timeout=1.2, min_duration=0.4)
        self.now = 1000.0

    def test_silence_without_speech_never_detected(self):
        self.detector.update(50, self.now)
        self.detector.update(60, self.now + 2)
        self.assertFalse(self.detector.is_detected(self.now + 2, 0.5))

    def test_speech_then_silence_detects_after_timeout(self):
        self.detector.update(3000, self.now)
        self.detector.update(4000, self.now + 0.1)
        self.detector.update(50, self.now + 0.2)
        # aun no pasó el timeout
        self.assertFalse(self.detector.is_detected(self.now + 0.5, 0.5))
        # pasó el timeout de 1.2s de silencio continuo
        self.assertTrue(self.detector.is_detected(self.now + 1.5, 1.5))

    def test_short_pause_does_not_detect(self):
        self.detector.update(3000, self.now)
        self.detector.update(50, self.now + 0.3)
        self.assertFalse(self.detector.is_detected(self.now + 0.5, 0.5))

    def test_resume_speaking_resets_silence(self):
        self.detector.update(3000, self.now)
        self.detector.update(50, self.now + 0.3)
        self.detector.update(3500, self.now + 0.5)
        self.detector.update(50, self.now + 0.6)
        self.assertFalse(self.detector.is_detected(self.now + 1.05, 1.1))

    def test_min_duration_guard(self):
        self.detector.update(3000, self.now)
        self.detector.update(50, self.now + 0.1)
        self.assertFalse(self.detector.is_detected(self.now + 2.0, 0.2))

    def test_long_utterance_not_cut_by_silence_within_timeout(self):
        # habla por 10 segundos con pausas < timeout y no corta
        self.detector.update(3000, self.now)
        now = self.now
        for _ in range(100):
            now += 0.1
            self.detector.update(3000, now)
            self.detector.update(50, now + 0.05)
            now += 0.05
            self.assertFalse(self.detector.is_detected(now, now - self.now))


class AdaptiveNoiseTest(unittest.TestCase):
    """El detector es adaptativo al PICO: la voz define su propio piso y
    el silencio se mide relativo a ella. Un ambiente bajo constante no
    dispara la deteccion por si solo."""

    def _hum(self, n=15, level=100):
        d = SilenceDetector(threshold=500, timeout=1.2, min_duration=0.4)
        t = 1000.0
        for _ in range(n):
            d.update(level, t)
            t += 0.1
        return d, t

    def test_constant_noise_never_triggers(self):
        # ruido ambiente constante bajo: no corta solo (nunca hay habla)
        d, t = self._hum(50)
        self.assertFalse(d.is_detected(t, 5.0))

    def test_noise_then_speech_then_silence_detects(self):
        d, t = self._hum()
        self.assertFalse(d.is_detected(t, t - 1000))
        d.update(6000, t)   # usuario habla bien por encima
        t += 0.2
        d.update(100, t)    # vuelve al ambiente -> silencio
        self.assertFalse(d.is_detected(t, t - 1000))
        # tras el timeout, corta
        self.assertTrue(d.is_detected(t + 1.5, t + 1.5 - 1000))


class SpeechFirstSecondRegressionTest(unittest.TestCase):
    """Regresion: si el usuario habla de inmediato, su voz define el piso
    y el silencio posterior se detecta. Tambien funciona hablando bajito.
    """

    def _talk_immediately(self, level):
        d = SilenceDetector(threshold=500, timeout=1.2, min_duration=0.4)
        t = 1000.0
        for _ in range(12):
            d.update(level, t)
            t += 0.1
        return d, t

    def test_moderate_voice_in_first_second_is_detected(self):
        d, t = self._talk_immediately(800)
        self.assertFalse(d.is_detected(t, t - 1000))
        d.update(800, t + 0.2)   # sigue hablando -> no silencio
        d.update(60, t + 0.4)    # ahora si calla -> silencio tras timeout
        self.assertTrue(d.is_detected(t + 1.6, t + 1.6 - 1000))

    def test_loud_voice_in_first_second_is_detected(self):
        d, t = self._talk_immediately(3000)
        d.update(60, t + 0.3)
        self.assertTrue(d.is_detected(t + 1.6, t + 1.6 - 1000))

    def test_soft_voice_detected(self):
        # voz BAJITA (300) por debajo del umbral absoluto (500): se detecta
        d = SilenceDetector(threshold=500, timeout=1.2, min_duration=0.4)
        t = 1000.0
        d.update(300, t)
        d.update(320, t + 0.2)
        d.update(290, t + 0.4)
        d.update(40, t + 0.6)    # calla bajando del 30% del pico
        self.assertTrue(d.is_detected(t + 2.0, 2.0))

    def test_tail_of_sentence_not_cut(self):
        # el final bajito de una frase (aun hablando) no se toma como corte
        d = SilenceDetector(threshold=500, timeout=1.2, min_duration=0.4)
        t = 1000.0
        d.update(3000, t)
        d.update(2800, t + 0.2)
        d.update(900, t + 0.4)   # cola bajita aun sobre el umbral relativo
        self.assertFalse(d.is_detected(t + 1.0, 1.0))
        d.update(40, t + 0.6)    # silencio real
        self.assertTrue(d.is_detected(t + 2.0, 2.0))


class AudioConfigTest(unittest.TestCase):
    def test_max_record_seconds_from_config(self):
        self.assertIsInstance(get_max_record_seconds(), int)

    def test_unlimited_record_seconds(self):
        # 0 = sin limite de tiempo: la grabacion termina solo por silencio
        self.assertEqual(get_max_record_seconds(), 0)

    def test_threshold_level_is_low(self):
        # El umbral de deteccion se ve como marca baja, no en 0
        level = get_threshold_level()
        self.assertGreater(level, 5)
        self.assertLess(level, 30)

    def test_level_scaling(self):
        self.assertEqual(_level_from_rms(0), 0.0)
        low = _level_from_rms(300)
        thr = _level_from_rms(500)
        speech = _level_from_rms(3000)
        loud = _level_from_rms(15000)
        self.assertLess(low, thr)
        self.assertGreater(speech, thr)
        self.assertGreater(loud, speech)
        self.assertLessEqual(loud, 100.0)

    def test_get_audio_level_when_idle(self):
        self.assertEqual(get_audio_level(), 0.0)


if __name__ == "__main__":
    unittest.main()
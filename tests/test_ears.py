import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from rocky.config import load
from rocky.ears import Ears


class EndLoop(BaseException):
    pass


class WakeDetectionTests(unittest.TestCase):
    def ears(self):
        ears = Ears(SimpleNamespace(state='idle'), load(), None)
        ears.np = np
        return ears

    def test_speech_does_not_raise_noise_floor(self):
        ears = self.ears()
        for _ in range(100):
            ears._calibrate_noise(1000)
        self.assertEqual(ears._noise_floor, 60)
        self.assertLess(ears._speech_gate(), 1000)

    def test_wake_recording_preserves_audio_before_trigger(self):
        ears = self.ears()
        samples = [(np.array([1], dtype=np.int16), 10),
                   (np.array([2], dtype=np.int16), 20),
                   (np.array([3], dtype=np.int16), 1000)]
        with patch.object(ears, '_read_frame', side_effect=samples), \
             patch.object(ears, '_record_utterance', side_effect=EndLoop) as record:
            with self.assertRaises(EndLoop):
                ears._listen_whisper()
        np.testing.assert_array_equal(record.call_args.args[0], [1, 2, 3])

    def test_both_wake_phrases(self):
        ears = self.ears()
        for phrase in ('Rocky.', 'Hey Rocky!'):
            self.assertEqual(ears._wake_match(phrase), (True, ''))


if __name__ == '__main__':
    unittest.main()

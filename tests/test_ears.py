import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock

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
        for phrase in ('Rocky.', 'Hey Rocky!', 'Hey Rockey!'):
            self.assertEqual(ears._wake_match(phrase), (True, ''))

    def test_wake_with_task_skips_ack_and_runs_task(self):
        ears = self.ears()
        with patch.object(ears, '_acknowledge') as ack, \
             patch.object(ears, '_run_command') as run, \
             patch.object(ears, '_record', return_value=None), \
             patch.object(ears, '_set_state'), patch.object(ears, '_flush_input'):
            ears._converse_whisper('weather in Surat')
        ack.assert_not_called()
        run.assert_called_once_with('weather in Surat')

    def test_bare_wake_only_acknowledges(self):
        ears = self.ears()
        with patch.object(ears, '_acknowledge') as ack, \
             patch.object(ears, '_run_command') as run, \
             patch.object(ears, '_record', return_value=None), \
             patch.object(ears, '_set_state'), patch.object(ears, '_flush_input'):
            ears._converse_whisper('')
        ack.assert_called_once()
        run.assert_not_called()

    def test_command_preserves_numbers_and_punctuation(self):
        ears = self.ears()
        self.assertEqual(ears._wake_match('Hey Rocky, what is 2 plus 2?'),
                         (True, 'what is 2 plus 2?'))
        self.assertEqual(ears._wake_match('Rocky, set timer for 10 minutes.'),
                         (True, 'set timer for 10 minutes.'))

    def test_background_noise_cannot_raise_gate_forever(self):
        ears = self.ears()
        for _ in range(1000):
            ears._calibrate_noise(ears._speech_gate() - 1)
        self.assertLessEqual(ears._noise_floor, 120)

    def test_empty_vad_result_retries_same_wake_audio(self):
        ears = self.ears()
        audio = np.full(16000, .02, dtype=np.float32)
        ears.whisper = SimpleNamespace(transcribe=Mock(side_effect=[
            ([], SimpleNamespace(duration_after_vad=0)),
            ([SimpleNamespace(text='Hey Rocky, weather in Surat')], SimpleNamespace())]))
        with patch.object(ears, '_set_state'):
            text = ears._transcribe(audio, wake=True)
        self.assertTrue(ears.last_asr_fallback)
        self.assertEqual(ears.last_speech_seconds, 0)
        self.assertEqual(ears._wake_match(text), (True, 'weather in Surat'))
        calls = ears.whisper.transcribe.call_args_list
        self.assertIs(calls[0].args[0], calls[1].args[0])
        self.assertTrue(calls[0].kwargs['vad_filter'])
        self.assertFalse(calls[1].kwargs['vad_filter'])

    def test_retry_does_not_make_unrelated_words_a_wake_command(self):
        ears = self.ears()
        ears.whisper = SimpleNamespace(transcribe=Mock(side_effect=[
            ([], SimpleNamespace(duration_after_vad=0)),
            ([SimpleNamespace(text='Thank you.')], SimpleNamespace())]))
        with patch.object(ears, '_set_state'):
            text = ears._transcribe(np.full(16000, .02, dtype=np.float32), wake=True)
        self.assertEqual(text, '')
        self.assertEqual(ears._wake_match(text), (False, ''))

    def test_successful_vad_transcription_is_not_repeated(self):
        ears = self.ears()
        ears.whisper = SimpleNamespace(transcribe=Mock(return_value=(
            [SimpleNamespace(text='Hey Rocky')], SimpleNamespace(duration_after_vad=.5))))
        with patch.object(ears, '_set_state'):
            self.assertEqual(ears._transcribe(np.full(16000, .02, dtype=np.float32), wake=True), 'Hey Rocky')
        ears.whisper.transcribe.assert_called_once()
        self.assertFalse(ears.last_asr_fallback)


if __name__ == '__main__':
    unittest.main()

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from rocky.config import load
from rocky.server import RockyCore
from rocky.tts import Voice


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    def core(self):
        core = RockyCore(load())
        core.voice = SimpleNamespace(speak=AsyncMock(), wait_idle=AsyncMock(),
                                     flush=AsyncMock(), feed=AsyncMock())
        core._try_geo = AsyncMock(return_value=False)
        return core

    async def test_nonstreamed_backend_errors_are_spoken(self):
        core = self.core()
        core.brain.ask = AsyncMock(return_value='ChatGPT login needs attention.')
        await core.handle_command('hello')
        core.voice.speak.assert_awaited_once_with('ChatGPT login needs attention.')
        self.assertFalse(core.busy)
        self.assertEqual(core.state, 'idle')

    async def test_complete_voice_command_does_not_insert_ack(self):
        core = self.core()
        async def reply(*args, **kwargs):
            core.voice.speak.assert_not_awaited()
            await kwargs['on_delta']('Four, friend.\n')
            return 'Four, friend.'
        core.brain.ask = reply
        await core.handle_command('what is 2 plus 2?', source='voice')
        self.assertEqual(core.voice.speak.await_count, 0)
        core.voice.feed.assert_awaited_once_with('Four, friend.\n')

    async def test_bare_wake_acknowledges_without_using_brain(self):
        core = self.core()
        core.brain.ask = AsyncMock()
        await core.wake_test()
        core.brain.ask.assert_not_awaited()
        core.voice.speak.assert_awaited_once()
        self.assertIn(core.voice.speak.await_args.args[0], core.cfg['acknowledgements'])
        self.assertEqual(core.history[-1]['role'], 'rocky')

    async def test_weather_bypasses_brain_and_restores_visuals(self):
        core = self.core()
        del core._try_geo
        core.brain.ask = AsyncMock()
        messages = [{'type': 'globe', 'action': 'focus', 'lat': 21.17, 'lng': 72.83},
                    {'type': 'window', 'kind': 'weather', 'title': 'Surat'}]
        with patch('rocky.server.geo.resolve', return_value=(messages, 'Surat weather.', None)):
            await core.handle_command('weather in Surat', source='voice')
        core.brain.ask.assert_not_awaited()
        core.voice.speak.assert_awaited_once_with('Surat weather.')
        self.assertEqual(core.snapshot()['globe']['action'], 'focus')
        self.assertEqual(core.snapshot()['windows'][0]['title'], 'Surat')

    async def test_exception_does_not_leave_core_thinking(self):
        core = self.core()
        core.brain.ask = AsyncMock(side_effect=RuntimeError('provider unavailable'))
        with self.assertLogs(level='ERROR'):
            await core.handle_command('hello')
        self.assertFalse(core.busy)
        self.assertEqual(core.state, 'idle')
        self.assertEqual(core.last_command_error, 'provider unavailable')
        core.voice.speak.assert_awaited_once_with('Something went wrong, friend. Try again.')

    async def test_failed_speech_worker_can_handle_next_utterance(self):
        voice = Voice(load())
        proc = SimpleNamespace(returncode=1,
                               communicate=AsyncMock(return_value=(b'', b'voice unavailable')))
        with patch('rocky.tts.asyncio.create_subprocess_exec', AsyncMock(return_value=proc)):
            with self.assertLogs(level='ERROR'):
                await voice.speak('First test.')
                await asyncio.wait_for(voice.wait_idle(), 1)
            self.assertEqual(voice.error, 'voice unavailable')
            proc.returncode = 0
            await voice.speak('Second test.')
            await asyncio.wait_for(voice.wait_idle(), 1)
            self.assertIsNone(voice.error)
            self.assertEqual(voice.active, 0)
        voice.worker.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await voice.worker


if __name__ == '__main__':
    unittest.main()

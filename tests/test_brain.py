import asyncio
import json
import sys
import unittest
from unittest.mock import patch

from rocky.brain import Brain
from rocky.config import load


class CodexBrainTests(unittest.IsolatedAsyncioTestCase):
    def brain(self):
        cfg = load()
        cfg['brain']['timeout_seconds'] = 5
        return Brain(cfg)

    def command(self, events, sleep=0):
        script = '\n'.join(['import sys,time', 'sys.stdin.read()'] + [
            'print(' + repr(json.dumps(e)) + ',flush=True)' for e in events
        ] + [f'time.sleep({sleep})'])
        return [sys.executable, '-c', script]

    async def test_reply_callbacks_and_own_session(self):
        brain = self.brain()
        events = [
            {'type': 'thread.started', 'thread_id': 'rocky-session'},
            {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'pwd'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'Ready.'}},
            {'type': 'turn.completed'},
        ]
        deltas, activity = [], []
        async def delta(text): deltas.append(text)
        async def tool(text): activity.append(text)
        with patch.object(brain, '_codex_cmd', return_value=self.command(events)):
            self.assertEqual(await brain.ask('hello', delta, tool), 'Ready.')
        self.assertEqual(deltas, ['Ready.\n'])
        self.assertEqual(activity, ['pwd'])
        self.assertEqual(brain.session_id, 'rocky-session')
        self.assertIn('resume', brain._codex_cmd())
        self.assertIn('rocky-session', brain._codex_cmd())
        brain.reset_session()
        self.assertIsNone(brain.session_id)
        self.assertNotIn('resume', brain._codex_cmd())

    async def test_auth_error_is_actionable(self):
        brain = self.brain()
        with patch.object(brain, '_codex_cmd', return_value=self.command([
            {'type': 'turn.failed', 'error': {'message': '401 authentication expired'}}
        ])):
            self.assertIn('codex login', await brain.ask('hello'))

    async def test_timeout_cleans_up_process(self):
        brain = self.brain()
        brain.cfg['brain']['timeout_seconds'] = 0.05
        with patch.object(brain, '_codex_cmd', return_value=self.command([], sleep=10)):
            self.assertIn('Too long', await brain.ask('hello'))
        self.assertIsNone(brain.proc)

    async def test_cancellation_cleans_up_process(self):
        brain = self.brain()
        with patch.object(brain, '_codex_cmd', return_value=self.command([], sleep=10)):
            task = asyncio.create_task(brain.ask('hello'))
            while brain.proc is None:
                await asyncio.sleep(0.01)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertIsNone(brain.proc)


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import AsyncMock

from rocky.codex_backend import CodexBackend


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    def backend(self, notifications):
        backend = CodexBackend('codex', {}, 'persona', '.')
        backend.thread_id = 'rocky'
        backend.ensure_ready = AsyncMock()
        backend._rpc = AsyncMock(return_value={'turn': {'id': 'turn'}})
        for method, payload in notifications:
            backend.pending.append({'method': method, 'params': {
                'threadId': 'rocky', 'turnId': 'turn', **payload}})
        return backend

    async def test_tokens_are_delivered_before_completion_without_duplicate(self):
        backend = self.backend([
            ('item/agentMessage/delta', {'itemId': 'answer', 'delta': 'Four'}),
            ('item/agentMessage/delta', {'itemId': 'answer', 'delta': ', friend.'}),
            ('item/completed', {'item': {'id': 'answer', 'type': 'agentMessage', 'text': 'Four, friend.'}}),
            ('turn/completed', {'turn': {'id': 'turn', 'status': 'completed'}}),
        ])
        fragments = []
        async def delta(text): fragments.append(text)
        self.assertEqual(await backend.ask('question', delta), 'Four, friend.')
        self.assertEqual(fragments, ['Four', ', friend.', '\n'])
        self.assertIsNotNone(backend.first_delta_seconds)

    async def test_completed_message_fallback(self):
        backend = self.backend([
            ('item/completed', {'item': {'id': 'answer', 'type': 'agentMessage', 'text': 'Ready.'}}),
            ('turn/completed', {'turn': {'id': 'turn', 'status': 'completed'}}),
        ])
        delta = AsyncMock()
        self.assertEqual(await backend.ask('question', delta), 'Ready.')
        delta.assert_any_await('Ready.')

    async def test_failed_turn_is_not_reported_as_done(self):
        backend = self.backend([
            ('turn/completed', {'turn': {'id': 'turn', 'status': 'failed',
                                        'error': {'message': 'Usage limit reached'}}}),
        ])
        with self.assertRaisesRegex(RuntimeError, 'Usage limit reached'):
            await backend.ask('question')

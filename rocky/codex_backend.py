"""Persistent Codex app-server connection using the local ChatGPT login."""
import asyncio
import collections
import json
import os
import signal
import time


class CodexBackend:
    def __init__(self, command, cfg, persona, cwd):
        self.command, self.cfg, self.persona, self.cwd = command, cfg, persona, cwd
        self.proc = None
        self.thread_id = None
        self.loaded = False
        self.pending = collections.deque()
        self.diagnostics = collections.deque(maxlen=20)
        self.serial = 0
        self.stderr_task = None
        self.first_delta_seconds = None
        self._killed = False

    async def _stderr(self, proc):
        while line := await proc.stderr.readline():
            self.diagnostics.append(line.decode('utf-8', 'replace').strip())

    async def _send(self, payload):
        self.proc.stdin.write((json.dumps(payload) + '\n').encode())
        await self.proc.stdin.drain()

    async def _read(self):
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                raise RuntimeError('Codex connection closed. ' + '\n'.join(self.diagnostics)[-1200:])
            try:
                message = json.loads(line)
            except (ValueError, UnicodeDecodeError):
                continue
            if 'id' in message and 'method' in message:
                await self._send({'id': message['id'], 'error': {
                    'code': -32601, 'message': 'Interactive requests unavailable in Rocky.'}})
                continue
            return message

    async def _rpc(self, method, params):
        self.serial += 1
        request_id = self.serial
        await self._send({'id': request_id, 'method': method, 'params': params})
        while True:
            message = await self._read()
            if message.get('id') == request_id:
                if message.get('error'):
                    raise RuntimeError(message['error'].get('message', 'Codex request failed.'))
                return message.get('result') or {}
            self.pending.append(message)

    async def ensure_ready(self):
        if self._killed:
            await self.close()
        if not self.proc or self.proc.returncode is not None:
            env = dict(os.environ)
            for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'AZURE_OPENAI_API_KEY'):
                env.pop(key, None)
            self.pending.clear()
            self.proc = await asyncio.create_subprocess_exec(
                self.command, 'app-server', '--stdio',
                '-c', 'forced_login_method="chatgpt"', '-c', 'mcp_servers={}',
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=self.cwd, env=env,
                start_new_session=True, limit=1024 * 1024)
            self.stderr_task = asyncio.create_task(self._stderr(self.proc))
            await self._rpc('initialize', {'clientInfo': {
                'name': 'rocky_voice', 'title': 'Rocky Voice Assistant', 'version': '0.2.0'}})
            await self._send({'method': 'initialized', 'params': {}})
            self.loaded = False
        if not self.loaded:
            params = {'cwd': self.cwd, 'approvalPolicy': 'never',
                      'sandbox': self.cfg.get('sandbox', 'workspace-write'),
                      'developerInstructions': self.persona,
                      'config': {'model_reasoning_effort': self.cfg.get('reasoning_effort', 'low')}}
            if self.cfg.get('model'):
                params['model'] = self.cfg['model']
            method = 'thread/start'
            if self.thread_id:
                method = 'thread/resume'
                params['threadId'] = self.thread_id
            result = await self._rpc(method, params)
            self.thread_id = result['thread']['id']
            self.loaded = True

    async def ask(self, text, on_delta=None, on_activity=None):
        await self.ensure_ready()
        started = time.monotonic()
        self.first_delta_seconds = None
        result = await self._rpc('turn/start', {
            'threadId': self.thread_id, 'input': [{'type': 'text', 'text': text}],
            'effort': self.cfg.get('reasoning_effort', 'low')})
        turn_id = result['turn']['id']
        streamed, completed = {}, {}
        error = None
        while True:
            message = self.pending.popleft() if self.pending else await self._read()
            method = message.get('method')
            params = message.get('params') or {}
            if params.get('threadId') != self.thread_id:
                continue
            if params.get('turnId') and params['turnId'] != turn_id:
                continue
            if method == 'item/agentMessage/delta':
                delta, item_id = params.get('delta', ''), params['itemId']
                streamed[item_id] = streamed.get(item_id, '') + delta
                if self.first_delta_seconds is None:
                    self.first_delta_seconds = round(time.monotonic() - started, 2)
                if delta and on_delta:
                    await on_delta(delta)
            elif method in ('item/started', 'item/completed'):
                item = params.get('item') or {}
                if method == 'item/completed' and item.get('type') == 'agentMessage':
                    completed[item['id']] = item.get('text', '')
                    if item['id'] not in streamed and on_delta and item.get('text'):
                        await on_delta(item['text'])
                    if on_delta:
                        await on_delta('\n')
                elif method == 'item/started' and on_activity and item.get('type') != 'agentMessage':
                    await on_activity(item.get('command') or item.get('type', 'working'))
            elif method == 'error':
                if not params.get('willRetry'):
                    error = (params.get('error') or {}).get('message')
            elif method == 'turn/completed':
                turn = params.get('turn') or {}
                if turn.get('id') != turn_id:
                    continue
                if turn.get('status') == 'failed':
                    raise RuntimeError((turn.get('error') or {}).get('message') or error or 'Codex turn failed.')
                return '\n'.join(completed.values() or streamed.values()).strip() or 'Done, friend.'

    def kill(self):
        self._killed = True
        if self.proc and self.proc.returncode is None:
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.loaded = False

    async def close(self):
        self.kill()
        if self.proc:
            await self.proc.wait()
        if self.stderr_task:
            await self.stderr_task
        self.proc = None
        self._killed = False

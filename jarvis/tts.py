"""JARVIS's voice v2: streaming sentence-by-sentence speech.

Text deltas from the brain are fed into a buffer; every time a sentence
completes it's queued and spoken immediately — Jarvis starts talking while the
rest of the reply is still being generated. A worker task plays sentences
sequentially through macOS `say` (Daniel, en_GB by default).
"""
import asyncio
import re

CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE = re.compile(r"`([^`]*)`")
LINK = re.compile(r"https?://(\S+)")
MD_NOISE = re.compile(r"[*_#>|]")
SENTENCE_END = re.compile(r"(.*?[.!?…])(?:\s+|$)", re.DOTALL)


def strip_for_speech(text: str) -> str:
    text = CODE_BLOCK.sub(" — code on your screen, sir — ", text)
    text = INLINE_CODE.sub(r"\1", text)
    text = LINK.sub(lambda m: m.group(1).split("/")[0], text)
    text = MD_NOISE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


class Voice:
    def __init__(self, cfg: dict, on_start=None, on_finish=None):
        self.cfg = cfg["voice"]
        self.on_start = on_start      # async cb: speech began
        self.on_finish = on_finish    # async cb: queue drained
        self.queue = asyncio.Queue()
        self.proc = None
        self.buffer = ""
        self.active = 0               # queued + currently-speaking count
        self.worker = None
        self._stopped = False

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", True))

    def ensure_worker(self):
        if self.worker is None or self.worker.done():
            self.worker = asyncio.ensure_future(self._run())

    # ---------- streaming input ----------

    async def feed(self, fragment: str):
        """Feed a text delta; complete sentences are spoken as they form."""
        if not self.enabled:
            return
        self.buffer += fragment
        while True:
            m = SENTENCE_END.match(self.buffer)
            if not m or len(self.buffer) <= len(m.group(1)):
                break
            sentence, self.buffer = m.group(1), self.buffer[m.end():]
            await self._enqueue(sentence)

    async def flush(self):
        """Speak whatever's left in the buffer (end of reply)."""
        rest, self.buffer = self.buffer, ""
        if rest.strip():
            await self._enqueue(rest)

    async def speak(self, text: str):
        """Queue a complete utterance (acks, one-shot lines)."""
        self.buffer = ""
        await self._enqueue(text)

    async def _enqueue(self, text: str):
        clean = strip_for_speech(text)
        if not self.enabled or not clean or not re.search(r"\w", clean):
            return
        self._stopped = False
        self.active += 1
        self.ensure_worker()
        await self.queue.put(clean)

    # ---------- playback ----------

    async def _run(self):
        while True:
            text = await self.queue.get()
            try:
                if self._stopped:
                    continue
                if self.active >= 1 and self.on_start:
                    await self.on_start()
                self.proc = await asyncio.create_subprocess_exec(
                    "say", "-v", str(self.cfg.get("name", "Daniel")),
                    "-r", str(self.cfg.get("rate", 180)),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    await self.proc.communicate(text.encode("utf-8"))
                except asyncio.CancelledError:
                    self._kill_current()
                    raise
            finally:
                self.active -= 1
                self.queue.task_done()
                if self.active <= 0:
                    self.active = 0
                    if self.on_finish and not self._stopped:
                        await self.on_finish()

    async def wait_idle(self):
        """Wait until everything queued has been spoken."""
        await self.queue.join()

    def speak_blocking(self, text: str):
        """Synchronous speech for non-async threads (the ears' acks)."""
        import subprocess
        clean = strip_for_speech(text)
        if not self.enabled or not clean:
            return
        subprocess.run(
            ["say", "-v", str(self.cfg.get("name", "Daniel")),
             "-r", str(self.cfg.get("rate", 180))],
            input=clean.encode("utf-8"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )

    def stop(self):
        """Cut speech now and drop everything queued."""
        self._stopped = True
        self.buffer = ""
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
                self.queue.task_done()
                self.active -= 1
            except asyncio.QueueEmpty:
                break
        self._kill_current()

    def _kill_current(self):
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc = None

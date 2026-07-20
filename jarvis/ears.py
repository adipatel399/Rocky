"""JARVIS's ears v3: always-on wake word + true conversation mode.

Pipeline (100% on-device):
  mic → openWakeWord "hey jarvis" → record → faster-whisper → brain

v3 fixes and behavior:
- Wake word only OPENS a conversation. After each reply Jarvis immediately
  listens again — speak naturally, no wake word needed. The conversation ends
  after `followup_seconds` of silence or a sleep phrase.
- Mic input is software-amplified (`mic_gain`) and the wake threshold is tuned
  for saying just "Jarvis" (the model was trained on "hey jarvis").
- The noise floor only calibrates while truly idle — previously it inflated
  while Jarvis himself was speaking, deafening the follow-up window.
- The input buffer is flushed after Jarvis speaks so he never hears his own
  echo, and wake-model state is reset after busy periods.
"""
import asyncio
import os
import random
import threading
import time

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms — the frame size openWakeWord expects
PREROLL_FRAMES = 8  # ~0.64 s kept before speech onset so word starts aren't clipped


class Ears(threading.Thread):
    def __init__(self, core, cfg: dict, loop: asyncio.AbstractEventLoop):
        super().__init__(daemon=True, name="jarvis-ears")
        self.core = core
        self.cfg = cfg
        self.ecfg = cfg["ears"]
        self.loop = loop
        self.muted = False
        self.ready = False
        self.error = None
        self.peak_score = 0.0  # recent best wake score — visible in /api/stats for tuning
        self.gain = float(self.ecfg.get("mic_gain", 1.5))
        self._noise_floor = 60.0

    # ---------- lifecycle ----------

    def run(self):
        try:
            import numpy as np
            import sounddevice as sd
            import openwakeword
            from openwakeword.model import Model as WakeModel
            from faster_whisper import WhisperModel
        except Exception as e:
            self.error = f"voice dependencies unavailable: {e}"
            self._notify_system(f"Ears offline — {self.error}")
            return

        try:
            model_dir = os.path.join(os.path.dirname(openwakeword.__file__),
                                     "resources", "models")
            wake_path = os.path.join(model_dir, "hey_jarvis_v0.1.onnx")
            if not os.path.exists(wake_path):
                self._notify_system("Downloading wake-word model (first run)…")
                openwakeword.utils.download_models()
            self.wake = WakeModel(wakeword_models=[wake_path],
                                  inference_framework="onnx")

            self._notify_system("Loading speech recognition model…")
            self.whisper = WhisperModel(self.ecfg.get("whisper_model", "base.en"),
                                        device="cpu", compute_type="int8")
            self.np = np

            self.stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                         dtype="int16", blocksize=FRAME)
            self.stream.start()
        except Exception as e:
            self.error = str(e)
            self._notify_system(f"Ears failed to start: {e}")
            return

        self.ready = True
        self._notify_system("Ears online — say “Jarvis” anytime.")
        self._listen_forever()

    # ---------- audio helpers ----------

    def _read_frame(self):
        frame, _ = self.stream.read(FRAME)
        pcm = self.np.frombuffer(frame, dtype=self.np.int16)
        if self.gain != 1.0:
            pcm = self.np.clip(pcm.astype(self.np.int32) * self.gain,
                               -32768, 32767).astype(self.np.int16)
        rms = float(self.np.sqrt(self.np.mean(pcm.astype(self.np.float64) ** 2)) + 1e-9)
        return pcm, rms

    def _flush_input(self):
        """Discard buffered audio (e.g. Jarvis's own voice while he spoke)."""
        try:
            while self.stream.read_available >= FRAME:
                self.stream.read(FRAME)
        except Exception:
            pass

    # ---------- main loop: wake-word watch ----------

    def _listen_forever(self):
        threshold = float(self.ecfg.get("wake_threshold", 0.28))
        was_busy = False
        while True:
            try:
                if self.muted or self.core.state != "idle":
                    was_busy = True
                    time.sleep(0.05)
                    continue
                if was_busy:
                    was_busy = False
                    self._flush_input()
                    self.wake.reset()

                pcm, rms = self._read_frame()
                self._noise_floor = 0.98 * self._noise_floor + 0.02 * rms
                score = float(max(self.wake.predict(pcm).values()))
                self.peak_score = max(score, self.peak_score * 0.995)
                if score >= threshold:
                    self.wake.reset()
                    self._converse()
                    was_busy = True  # flush + reset before watching again
            except Exception as e:
                self._notify_system(f"Ears recovered from an error: {e}")
                self._set_state("idle")
                time.sleep(0.5)

    # ---------- conversation mode ----------

    def _converse(self):
        """A full conversation: wake once, then keep exchanging turns until
        silence or a sleep phrase. No wake word needed between turns."""
        followup = float(self.ecfg.get("followup_seconds", 8))
        first = True
        while True:
            self._set_state("listening")
            if first:
                self.core.voice.speak_blocking(
                    random.choice(self.cfg["acknowledgements"]))
            self._flush_input()

            audio = self._record(wait_seconds=6.0 if first else followup)
            text = self._transcribe(audio)

            if not text:
                if first:
                    self.core.voice.speak_blocking("I didn't catch that, sir.")
                break  # silence — conversation over

            lowered = text.lower().strip(" .!?,")
            if any(p in lowered for p in self.cfg["sleep_phrases"]):
                self._notify_user(text)
                self.core.voice.speak_blocking("Very good, sir.")
                break

            future = asyncio.run_coroutine_threadsafe(
                self.core.handle_command(text, source="voice"), self.loop)
            try:
                future.result()  # returns after the reply is fully spoken
            except Exception:
                pass
            first = False  # stay in the conversation, listen again right away
        self._set_state("idle")

    def _record(self, wait_seconds: float):
        """Wait up to wait_seconds for speech, then record until silence."""
        np = self.np
        silence_limit = float(self.ecfg.get("silence_seconds", 1.4))
        max_seconds = float(self.ecfg.get("max_command_seconds", 14))
        gate = max(2.5 * self._noise_floor, 250)

        # Phase 1 — wait for speech onset, keeping a short pre-roll ring.
        ring = []
        t0 = time.monotonic()
        started = False
        while time.monotonic() - t0 < wait_seconds:
            pcm, rms = self._read_frame()
            ring.append(pcm)
            if len(ring) > PREROLL_FRAMES:
                ring.pop(0)
            self._send_level(min(rms / 3000.0, 1.0))
            if rms > gate:
                started = True
                break
        if not started:
            self._send_level(0.0)
            return None

        # Phase 2 — record until a trailing pause.
        chunks = list(ring)
        t1 = time.monotonic()
        silent = 0.0
        while time.monotonic() - t1 < max_seconds:
            pcm, rms = self._read_frame()
            chunks.append(pcm)
            self._send_level(min(rms / 3000.0, 1.0))
            if rms > gate:
                silent = 0.0
            else:
                silent += FRAME / SAMPLE_RATE
                if silent >= silence_limit:
                    break
        self._send_level(0.0)

        audio = np.concatenate(chunks).astype(np.float32) / 32768.0
        audio = np.nan_to_num(audio)
        if float(np.max(np.abs(audio))) < 1e-4:
            return None
        return audio

    def _transcribe(self, audio) -> str:
        if audio is None or len(audio) < SAMPLE_RATE // 4:
            return ""
        self._set_state("thinking")
        segments, _ = self.whisper.transcribe(audio, language="en",
                                              beam_size=1, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()

    # ---------- bridge to the event loop ----------

    def _set_state(self, state):
        asyncio.run_coroutine_threadsafe(self.core.set_state(state), self.loop)

    def _send_level(self, value):
        asyncio.run_coroutine_threadsafe(
            self.core.broadcast({"type": "level", "value": round(value, 3)}), self.loop)

    def _notify_system(self, text):
        asyncio.run_coroutine_threadsafe(
            self.core.post_message("system", text), self.loop)

    def _notify_user(self, text):
        asyncio.run_coroutine_threadsafe(
            self.core.post_message("user", text), self.loop)

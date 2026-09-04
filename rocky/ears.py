"""ROCKY's ears v3: always-on wake word + true conversation mode.

Pipeline (100% on-device):
  mic → openWakeWord "hey jarvis" → record → faster-whisper → brain

v3 fixes and behavior:
- Wake word only OPENS a conversation. After each reply Rocky immediately
  listens again — speak naturally, no wake word needed. The conversation ends
  after `followup_seconds` of silence or a sleep phrase.
- Mic input is software-amplified (`mic_gain`) and the wake threshold is tuned
  for saying just "Rocky" (the model was trained on "hey jarvis").
- The noise floor only calibrates while truly idle — previously it inflated
  while Rocky himself was speaking, deafening the follow-up window.
- The input buffer is flushed after Rocky speaks so he never hears his own
  echo, and wake-model state is reset after busy periods.
"""
import asyncio
import os
import random
import re
import threading
import time

SAMPLE_RATE = 16000
FRAME = 1280  # 80 ms — the frame size openWakeWord expects
PREROLL_FRAMES = 8  # ~0.64 s kept before speech onset so word starts aren't clipped


class Ears(threading.Thread):
    def __init__(self, core, cfg: dict, loop: asyncio.AbstractEventLoop):
        super().__init__(daemon=True, name="rocky-ears")
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
        self.wake_word = str(self.ecfg.get("wake_word", "rocky")).lower()
        self.wake_engine = str(self.ecfg.get("wake_engine", "whisper")).lower()

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
            self.wake = None
            if self.wake_engine == "openwakeword":
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
        ww = self.wake_word.title()
        self._notify_system(f"Rocky awake. Ears good, good, good. Say “{ww}” to wake me.")
        if self.wake_engine == "openwakeword":
            self._listen_forever()
        else:
            self._listen_whisper()

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
        """Discard buffered audio (e.g. Rocky's own voice while he spoke)."""
        try:
            while self.stream.read_available >= FRAME:
                self.stream.read(FRAME)
        except Exception:
            pass

    # ---------- Whisper wake word ("Rocky" / "Hey Rocky") ----------

    def _listen_whisper(self):
        """Energy-gated keyword spotting: when speech is heard, transcribe it
        and only wake if it begins with the wake word. The rest of the sentence
        becomes the first command, so "Rocky, what's the weather" works in one
        breath. No cloud, no extra model — reuses Whisper."""
        while True:
            try:
                if self.muted or self.core.state != "idle":
                    time.sleep(0.05)
                    continue
                pcm, rms = self._read_frame()
                self._noise_floor = 0.98 * self._noise_floor + 0.02 * rms
                gate = max(2.5 * self._noise_floor, 250)
                if rms <= gate:
                    continue  # silence — keep listening cheaply (no Whisper)

                audio = self._record_utterance(pcm)
                text = self._transcribe(audio)
                if not text:
                    self._set_state("idle")
                    continue
                matched, remainder = self._wake_match(text)
                self.peak_score = 1.0 if matched else 0.0
                if not matched:
                    self._set_state("idle")
                    continue
                self._converse_whisper(remainder)
            except Exception as e:
                self._notify_system(f"Ears recovered from an error: {e}")
                self._set_state("idle")
                time.sleep(0.5)

    def _wake_match(self, text: str):
        """Return (matched, remainder_command). Lenient — ASR often mishears
        'Rocky' as rock/rocket/ricky, so accept any first word starting 'rock'
        (or the configured wake word) within the first two words."""
        words = re.sub(r"[^a-z' ]", "", text.lower()).split()
        if not words:
            return False, ""
        variants = {self.wake_word, "rocky", "rock", "rockie", "rocco", "ricky", "rocketh"}
        for i in range(min(2, len(words))):
            w = words[i]
            if w in variants or w.startswith("rock"):
                rem = " ".join(words[i + 1:]).strip()
                rem = re.sub(r"^(hey|hi|hello|okay|ok|please)\b", "", rem).strip()
                return True, rem
        return False, ""

    def _record_utterance(self, preroll):
        """Record from an already-detected speech onset until a trailing pause."""
        np = self.np
        silence_limit = float(self.ecfg.get("silence_seconds", 1.4))
        max_seconds = float(self.ecfg.get("max_command_seconds", 14))
        gate = max(2.5 * self._noise_floor, 250)
        self._set_state("listening")
        chunks = [preroll]
        silent = 0.0
        t1 = time.monotonic()
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

    def _converse_whisper(self, remainder: str):
        """After the wake word: run the first command (if any) then keep the
        conversation open, no wake word needed, until silence or a sleep phrase."""
        followup = float(self.ecfg.get("followup_seconds", 8))
        if remainder and len(remainder) >= 2:
            self._run_command(remainder)          # "Rocky, <command>" in one breath
        else:
            self.core.voice.speak_blocking(random.choice(self.cfg["acknowledgements"]))
        while True:
            self._set_state("listening")
            self._flush_input()
            audio = self._record(wait_seconds=followup)
            text = self._transcribe(audio)
            if not text:
                break
            low = text.lower().strip(" .!?,")
            if any(p in low for p in self.cfg["sleep_phrases"]):
                self._notify_user(text)
                self.core.voice.speak_blocking("Good. Sleep now, friend.")
                break
            self._run_command(text)
        self._set_state("idle")

    def _run_command(self, text: str):
        future = asyncio.run_coroutine_threadsafe(
            self.core.handle_command(text, source="voice"), self.loop)
        try:
            future.result()
        except Exception:
            pass

    # ---------- main loop: wake-word watch (openWakeWord) ----------

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
                    self.core.voice.speak_blocking("I not hear, friend. Say again.")
                break  # silence — conversation over

            lowered = text.lower().strip(" .!?,")
            if any(p in lowered for p in self.cfg["sleep_phrases"]):
                self._notify_user(text)
                self.core.voice.speak_blocking("Good. Sleep now, friend.")
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

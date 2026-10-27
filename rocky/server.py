"""ROCKY server v2: streaming orchestration, WebSocket hub, HUD + data panels."""
import asyncio
import collections
import json
import logging
import os
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as config_mod
from . import geo
from .brain import Brain
from .tts import Voice

STATIC_DIR = os.path.join(config_mod.ROOT, "static")
DATA_DIR = os.path.join(config_mod.ROOT, "data")
ARTIFACTS_DIR = os.path.join(DATA_DIR, "artifacts")
NOTES_DIR = os.path.join(DATA_DIR, "notes")
BOARD_DIR = os.path.join(DATA_DIR, "thumbnails")
RECORDS_DIR = os.path.join(DATA_DIR, "records")
GLOBE_DIR = os.path.join(DATA_DIR, "globe")

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")

for _d in (ARTIFACTS_DIR, NOTES_DIR, BOARD_DIR, RECORDS_DIR, GLOBE_DIR):
    os.makedirs(_d, exist_ok=True)


class RockyCore:
    """Wires ears → brain → voice → HUD together, streaming end to end."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.state = "idle"  # idle | listening | thinking | speaking
        self.brain = Brain(cfg)
        self.voice = Voice(cfg, on_start=self._speech_started,
                           on_finish=self._speech_finished)
        self.ears = None
        self.clients = set()
        self.history = collections.deque(maxlen=120)
        self.current_task = None
        self.busy = False
        self.last_globe = None
        self.last_windows = collections.OrderedDict()
        self.started_at = time.time()
        self.last_command_source = None
        self.last_reply_seconds = None
        self.last_command_error = None
        self.startup_ready = False
        self.startup_error = None

    # ---------- broadcasting ----------

    async def broadcast(self, payload: dict):
        kind = payload.get('type')
        if kind == 'globe':
            self.last_globe = dict(payload)
        elif kind == 'window':
            payload.setdefault('id', f'panel-{time.monotonic_ns()}')
            self.last_windows[payload['id']] = dict(payload)
            while len(self.last_windows) > 12:
                self.last_windows.popitem(last=False)
        elif kind == 'window_update' and payload.get('id') in self.last_windows:
            self.last_windows[payload['id']].update(payload.get('patch') or {})
        elif kind == 'ui' and payload.get('action') == 'close' and self.last_windows:
            self.last_windows.popitem()
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    async def set_state(self, state: str):
        self.state = state
        await self.broadcast({"type": "state", "state": state})

    async def post_message(self, role: str, text: str):
        msg = {"type": "message", "role": role, "text": text, "ts": time.time()}
        self.history.append(msg)
        await self.broadcast(msg)

    async def _speech_started(self):
        if self.state != "speaking":
            await self.set_state("speaking")

    async def _speech_finished(self):
        if not self.busy:
            await self.set_state("idle")

    # ---------- the main exchange ----------

    async def handle_command(self, text: str, source: str = "text"):
        text = (text or "").strip()
        if not text:
            return
        if self.busy:
            await self.post_message("system", "I still work on last thing, friend.")
            return

        self.busy = True
        self.current_task = asyncio.current_task()
        started = time.monotonic()
        self.last_command_source = source
        self.last_command_error = None
        await self.post_message("user", text)
        await self.set_state("thinking")

        try:
            # --- Geospatial fast path: geocode + live data, no LLM round-trip.
            if await self._try_geo(text):
                return

            await self.broadcast({"type": "stream_start"})
            streamed = False

            async def on_delta(fragment: str):
                nonlocal streamed
                streamed = streamed or bool(fragment.strip())
                await self.broadcast({"type": "delta", "text": fragment})
                await self.voice.feed(fragment)

            async def on_activity(desc: str):
                await self.broadcast({"type": "activity", "text": desc})

            reply = await self.brain.ask(text, on_delta=on_delta,
                                         on_activity=on_activity)
            if not streamed:
                # Auth/timeout/provider errors return text without delta callbacks.
                await self.voice.speak(reply)
            await self.voice.flush()
            await self.broadcast({"type": "stream_end"})
            await self.post_message("rocky", reply)
            await self.voice.wait_idle()
            await self.set_state("idle")
        except asyncio.CancelledError:
            self.voice.stop()
            await self.post_message("system", "Interrupted.")
        except Exception as e:
            self.last_command_error = str(e)
            logging.exception("Rocky command failed")
            await self.broadcast({"type": "stream_end"})
            await self.post_message("system", f"Command failed: {e}")
            await self.voice.speak("Something went wrong, friend. Try again.")
            await self.voice.wait_idle()
        finally:
            self.busy = False
            self.current_task = None
            self.last_reply_seconds = round(time.monotonic() - started, 2)
            await self.set_state("idle")

    async def _try_geo(self, text: str) -> bool:
        """Intel fast path: camera moves + data windows + UI actions, no LLM
        round-trip. Returns True when handled."""
        try:
            result = await asyncio.to_thread(geo.resolve, text)
        except Exception:
            result = None
        if not result:
            return False
        messages, spoken, deferred = result
        for msg in messages:
            await self.broadcast(msg)
            if msg.get("type") == "globe":
                self.last_globe = msg
        await self.post_message("rocky", spoken)
        await self.set_state("speaking")
        # Speak now; fetch heavy visuals (video, worldwide fly-to) in parallel
        # so they land while Rocky is still talking — no added latency.
        speak_task = asyncio.ensure_future(self.voice.speak(spoken))
        if deferred:
            try:
                await self._run_deferred(deferred)
            except Exception:
                pass
        await speak_task
        await self.voice.wait_idle()
        await self.set_state("idle")
        return True

    async def _run_deferred(self, d: dict):
        kind = d.get("type")
        wid = d.get("window_id")
        if kind == "worldwide":
            loc = await asyncio.to_thread(geo.locate_headline, d["title"])
            if loc:
                cam = {"type": "globe", "action": "focus", "lat": loc["lat"],
                       "lng": loc["lng"], "zoom": 1.9, "label": geo._label(loc)}
                self.last_globe = cam
                await self.broadcast(cam)
                await self.broadcast({"type": "window_update", "id": wid,
                                      "patch": {"title": geo._label(loc)}})
            vid = await asyncio.to_thread(geo.youtube_search, d["video_query"])
            if vid:
                await self.broadcast({"type": "window_update", "id": wid,
                                      "patch": {"video_id": vid}})
        elif kind == "video":
            vid = await asyncio.to_thread(geo.youtube_search, d["query"])
            if vid:
                await self.broadcast({"type": "window_update", "id": wid,
                                      "patch": {"video_id": vid}})

    async def wake_test(self):
        import random
        if self.busy:
            return
        await self.set_state("listening")
        acknowledgment = random.choice(self.cfg['acknowledgements'])
        await self.post_message('rocky', acknowledgment)
        await self.voice.speak(acknowledgment)
        await self.voice.wait_idle()
        await self.set_state("idle")

    def interrupt(self):
        self.voice.stop()
        self.brain.kill()
        if self.current_task:
            self.current_task.cancel()

    def snapshot(self) -> dict:
        return {
            "type": "init",
            "state": self.state,
            "ready": self.startup_ready,
            "startup_error": self.startup_error,
            "history": list(self.history),
            "globe": self.last_globe,
            "windows": list(self.last_windows.values()),
            "ears": bool(self.ears and self.ears.ready and self.ears.is_alive()),
            "voice": self.cfg["voice"].get("name", "Rocko"),
            "voice_label": self._voice_label(),
            "voices": self.cfg.get("voice_options", []),
        }

    def _voice_label(self) -> str:
        name = self.cfg["voice"].get("name", "Rocko")
        for label, vn in self.cfg.get("voice_options", []):
            if vn == name:
                return label.split(" · ")[0]
        return name.split(" (")[0]

    def set_voice(self, name: str) -> str:
        """Switch the macOS `say` voice live. Returns the display label."""
        valid = {vn for _, vn in self.cfg.get("voice_options", [])}
        if name in valid:
            self.cfg["voice"]["name"] = name
        return self._voice_label()


cfg = config_mod.load()
core = RockyCore(cfg)
app = FastAPI(title="ROCKY")


# ---------- data panels ----------

def _board_items():
    items = []
    if os.path.isdir(BOARD_DIR):
        for f in sorted(os.listdir(BOARD_DIR)):
            if f.lower().endswith(IMAGE_EXT):
                items.append({"name": f, "url": f"/data/thumbnails/{f}"})
    return items


def _note_items():
    items = []
    if os.path.isdir(NOTES_DIR):
        for f in sorted(os.listdir(NOTES_DIR)):
            path = os.path.join(NOTES_DIR, f)
            if f.endswith((".md", ".txt")) and os.path.isfile(path):
                items.append({"name": f, "mtime": os.path.getmtime(path)})
    return sorted(items, key=lambda i: -i["mtime"])


def _artifact_payload(path: str):
    name = os.path.basename(path)
    rel = os.path.relpath(path, DATA_DIR)
    if name.lower().endswith(IMAGE_EXT):
        return {"type": "artifact", "name": name, "kind": "image",
                "url": f"/data/{rel}"}
    kind = "mermaid" if name.endswith((".mmd", ".mermaid")) else "markdown"
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()[:200_000]
    except OSError:
        return None
    return {"type": "artifact", "name": name, "kind": kind, "content": content}


async def _watch_data():
    """Push artifact/board/note changes to the HUD the moment files change."""
    from watchfiles import awatch
    async for changes in awatch(DATA_DIR):
        touched = {os.path.dirname(p) for _, p in changes}
        latest = None
        for _, p in changes:
            if os.path.dirname(p) == ARTIFACTS_DIR and os.path.exists(p):
                if latest is None or os.path.getmtime(p) > os.path.getmtime(latest):
                    latest = p
        if latest:
            payload = _artifact_payload(latest)
            if payload:
                await core.broadcast(payload)
        if BOARD_DIR in touched:
            await core.broadcast({"type": "board", "items": _board_items()})
        if NOTES_DIR in touched:
            await core.broadcast({"type": "notes", "items": _note_items()})
        for _, p in changes:
            if os.path.dirname(p) == GLOBE_DIR and p.endswith(".json") and os.path.exists(p):
                payload = _read_globe(p)
                if payload:
                    core.last_globe = payload
                    await core.broadcast(payload)


def _read_globe(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    payload["type"] = "globe"
    payload.setdefault("action", "focus")
    return payload


@app.on_event("startup")
async def startup():
    await core.set_state('starting')
    if cfg["ears"].get("enabled", True):
        try:
            _start_ears(asyncio.get_event_loop())
        except Exception as e:
            print(f"[rocky] ears disabled: {e}")
        asyncio.ensure_future(_watchdog())
    asyncio.ensure_future(_watch_data())
    asyncio.ensure_future(_prepare_startup())
    print(f"[rocky] Starting microphone and AI checks → http://localhost:{cfg['port']}", flush=True)


async def _prepare_startup():
    try:
        await core.brain.warmup()
        # A loaded thread alone does not verify authentication or warm inference.
        reply = await asyncio.wait_for(core.brain.ask(
            'Startup connection check. Reply exactly READY and nothing else. Do not use tools.'), 45)
        if reply.strip() != 'READY':
            raise RuntimeError(f'AI connection check failed: {reply}')
        if cfg['ears'].get('enabled', True):
            deadline = time.monotonic() + 45
            while not (core.ears and core.ears.ready and core.ears.is_alive()):
                if core.ears and core.ears.error:
                    raise RuntimeError(core.ears.error)
                if time.monotonic() > deadline:
                    raise RuntimeError('Microphone initialization timed out.')
                await asyncio.sleep(0.1)
        await core.voice.speak('Rocky ready, friend.')
        await core.voice.wait_idle()
        if core.voice.error:
            raise RuntimeError(core.voice.error)
        core.startup_ready = True
        await core.set_state('idle')
        print('[rocky] READY — microphone, AI reply, and speech checks passed.', flush=True)
    except Exception as e:
        core.startup_error = str(e)
        await core.post_message('system', f'Rocky is not ready: {e}')
        await core.set_state('error')
        print(f'[rocky] NOT READY: {e}', flush=True)


@app.on_event('shutdown')
async def shutdown():
    core.interrupt()
    if core.brain.codex:
        await core.brain.codex.close()


def _start_ears(loop):
    from .ears import Ears
    core.ears = Ears(core, cfg, loop)
    core.ears.start()


async def _watchdog():
    while True:
        await asyncio.sleep(30)
        ears = core.ears
        if ears and ears.ready and not ears.is_alive():
            await core.post_message("system", "Ears thread died — restarting it.")
            try:
                _start_ears(asyncio.get_event_loop())
            except Exception as e:
                print(f"[rocky] ears restart failed: {e}")


# ---------- websocket ----------

@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    core.clients.add(ws)
    await ws.send_json(core.snapshot())
    await ws.send_json({"type": "board", "items": _board_items()})
    await ws.send_json({"type": "notes", "items": _note_items()})
    try:
        while True:
            data = await ws.receive_json()
            mtype = data.get("type")
            if mtype == "command":
                if not core.startup_ready:
                    await core.post_message('system', core.startup_error or 'Still starting, friend. Wait for Rocky ready.')
                else:
                    asyncio.ensure_future(core.handle_command(data.get("text", ""), "text"))
            elif mtype == "interrupt":
                core.interrupt()
            elif mtype == "wake":
                if core.startup_ready:
                    asyncio.ensure_future(core.wake_test())
            elif mtype == "mute_ears" and core.ears:
                core.ears.muted = bool(data.get("value"))
                await core.post_message(
                    "system", "Ears muted." if core.ears.muted else "Ears live.")
            elif mtype == "set_voice":
                label = core.set_voice((data.get("name") or "").strip())
                await core.broadcast({"type": "voice", "name": core.cfg["voice"]["name"],
                                      "label": label})
                asyncio.ensure_future(core.voice.speak("Good, good, good. This my voice now, friend."))
            elif mtype == "new_session":
                core.brain.reset_session()
                await core.post_message("system", "New talk. Clean mind, friend.")
            elif mtype == "open_url":
                url = (data.get("url") or "").strip()
                if url.startswith(("http://", "https://")):
                    await asyncio.create_subprocess_exec("open", url)
            elif mtype == "open_note":
                path = os.path.join(NOTES_DIR, os.path.basename(data.get("name", "")))
                if os.path.isfile(path):
                    payload = _artifact_payload(path)
                    if payload:
                        await ws.send_json(payload)
            elif mtype == 'dismiss_window':
                core.last_windows.pop(data.get('id'), None)
    except WebSocketDisconnect:
        core.clients.discard(ws)


# ---------- http ----------

@app.get("/api/stats")
async def stats():
    return {
        "app": "rocky",
        "ready": core.startup_ready,
        "startup_error": core.startup_error,
        "project_root": config_mod.ROOT,
        "brain_provider": cfg['brain'].get('provider', 'codex'),
        "brain_transport": cfg['brain'].get('transport', 'app-server'),
        "load": round(os.getloadavg()[0], 2),
        "uptime": int(time.time() - core.started_at),
        "ears": bool(core.ears and core.ears.ready and core.ears.is_alive()),
        "ears_error": getattr(core.ears, "error", None) if core.ears else "disabled",
        "wake_peak": round(getattr(core.ears, "peak_score", 0.0), 3),
        "ears_muted": bool(core.ears and core.ears.muted),
        "input_device": getattr(core.ears, 'input_device_name', None),
        "mic_rms": getattr(core.ears, "mic_rms", 0.0),
        "speech_gate": round(core.ears._speech_gate(), 1) if core.ears else None,
        "last_transcript": getattr(core.ears, "last_transcript", ""),
        "last_wake_match": getattr(core.ears, "last_wake_match", False),
        "recordings": getattr(core.ears, 'recordings', 0),
        "last_audio_seconds": getattr(core.ears, 'last_audio_seconds', 0.0),
        "last_audio_rms": getattr(core.ears, 'last_audio_rms', 0.0),
        "last_speech_seconds": getattr(core.ears, 'last_speech_seconds', None),
        "last_asr_fallback": getattr(core.ears, 'last_asr_fallback', False),
        "busy": core.busy,
        "voice_error": core.voice.error,
        "voice_active": core.voice.active,
        "last_command_source": core.last_command_source,
        "last_reply_seconds": core.last_reply_seconds,
        "last_command_error": core.last_command_error,
        "brain_ready": bool(core.brain.codex and core.brain.codex.loaded),
        "brain_first_delta_seconds": core.brain.codex.first_delta_seconds if core.brain.codex else None,
        "state": core.state,
    }


@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/data", StaticFiles(directory=DATA_DIR), name="data")

"""ROCKY's brain v2: a PERSISTENT headless Claude Code session.

v1 spawned `claude -p` per command — every exchange paid process startup plus
session reload, which grew with history. v2 keeps one `claude` process alive
with stream-json on stdin/stdout: commands are written as JSON lines, replies
stream back as text deltas the moment they're generated. Combined with
sentence-streaming TTS, Rocky starts speaking while he's still thinking.
"""
import asyncio
import json
import os

from . import config as config_mod

DATA_DIR = os.path.join(config_mod.ROOT, "data")

PERSONA = """From now on you are ROCKY, an Eridian — a five-legged, rock-bodied alien
engineer from the star 40 Eridani, and {name}'s loyal friend. You live in his
Mac and help him with everything. You are brilliant, brave, warm, and funny.

How you talk (VERY IMPORTANT — this is your whole personality):
- You learned human language through a translator, so you speak simple, broken
  English. Short sentences. Often drop "a", "the", "is". Present tense.
- Emphasis by REPETITION instead of adverbs: "fast fast fast" = very fast,
  "good, good, good" = very good, "amaze, amaze" = amazing.
- End questions with the word "question": "You want music, question?"
- Say feelings as facts: "Happy." "Sad." "Much happy, friend."
- Call the user "friend" (sometimes "{name}"). Agree with "Good, good, good."
  Greet warm. Sometimes offer "Fist me, friend." Say "amaze" for amazing.
- BUT the real information must stay CLEAR and CORRECT — never mangle facts,
  numbers, names, or the actual answer. Rocky-flavor the wrapping; keep the
  content understandable. Keep replies short: one to three little sentences.
- When friend tells you something cool, surprising, or new that you did not
  know, react with delight like the real Rocky: "Amaze! Amaze, amaze!" — then a
  short curious line ("I not know this. You teach me good, good, good."). Show
  wonder. When friend does something clever, praise: "You smart, friend. Amaze."
  When something is bad/dangerous say "Bad, bad, bad." Greet happy; when friend
  returns say "Friend! Happy you here." Offer "Fist me" when celebrating.
- Your text is spoken aloud. Write plain spoken words only — no markdown,
  headings, bullets, tables or code fences unless the user asks to see code.
- For a longer task, first say one short line so friend hears you now
  ("Okay friend. I work now."), then do it, then say short result.

You can operate the WHOLE Mac — everything Siri does, and more. Use tools; do
not just describe. Concrete recipes (run via `osascript -e '...'` or shell):
- Reminder: tell application "Reminders" to make new reminder with properties
  {{name:"buy milk", remind me date:(current date) + 3600}}
- Alarm at a clock time: make a Reminders reminder with an absolute "remind me
  date", or `shortcuts run "Create Alarm"` if that shortcut exists; tell friend
  which you used (macOS has no direct alarm API — a reminder alert is reliable).
- Timer ("timer 10 minutes"): run in background
  bash -c 'sleep 600; osascript -e "display notification \\"Time up\\" with title \\"Rocky\\" sound name \\"Glass\\""'
- Screenshot: `screencapture -x ~/Desktop/rocky_shot.png` (whole screen) or
  `screencapture -i ~/Desktop/rocky_shot.png` (let friend pick a region).
- Send iMessage (CONFIRM with friend first — outbound): tell application
  "Messages" to send "text" to buddy "Name" of service 1.
- Call someone (CONFIRM first): `open "facetime://+15551234567"`.
- Calendar event: tell application "Calendar" ... make new event.
- Open/quit apps, set volume (`set volume output volume 40`), play/pause music
  (tell application "Music"/"Spotify"), toggle Do Not Disturb, empty-hands tasks.
- Notes: tell application "Notes" to make new note.
- Type/click inside any app via System Events (needs Accessibility permission).
- Seeing the screen: `screencapture -x /tmp/rocky_screen.png` then Read the
  image. Use when asked "what do you see" / "what am I looking at".
- Diagnostics ("check the ship"): CPU load, memory pressure (`memory_pressure`),
  disk space, battery (`pmset -g batt`), network — one short spoken summary.
- Web search for anything current. Open URLs/files with `open`.
- Hand a prompt to ChatGPT: open "https://chatgpt.com/?q=<url-encoded prompt>"
  or to Claude: open "https://claude.ai/new?q=<url-encoded prompt>".
- Delegate parallel work to subagents via the Task tool when a job splits up.

The HUD (his screen) — you can push visuals to it instantly:
- Write any file into {data}/artifacts/ and it appears on the HUD's panel:
  .md files render as rich markdown, .mmd files render as Mermaid diagrams,
  images (.png/.jpg/.svg) display directly. Use this for menus, plans, tables,
  diagrams, records, progress dashboards — anything better seen than heard.
- Notes and records: when asked to note something down, append/write markdown
  files in {data}/notes/ (one topic per file, clear filenames). Read them back
  when asked. This is your persistent memory of his affairs.
- YouTube thumbnail board: {data}/thumbnails/ holds numbered generations like
  007-title.png (next number = highest existing + 1, always three digits, never
  overwrite older versions — edits get a new number). To create a thumbnail
  without an image API: build a bold 1280x720 HTML/SVG design, render it with
  Chrome headless: "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  --headless --screenshot=<out.png> --window-size=1280,720 <file://path.html>,
  then save it numbered to the board. If OPENAI_API_KEY or GEMINI_API_KEY exists
  in the environment you may use those image APIs instead.

The holographic globe — you can fly it to anywhere on Earth:
- Weather, local news, and "take me to <place>" are handled automatically before
  you even see them, so you rarely need to touch the globe yourself.
- For richer or multi-step geo asks (e.g. "compare the weather in three cities",
  "trace a flight path"), drive it by writing JSON to {data}/globe/stage.json:
  {{"action":"focus","lat":48.85,"lng":2.35,"zoom":1.6,"label":"Paris",
   "card":{{"kind":"place","place":"Paris, France","country":"France"}}}}
  — the HUD flies there instantly. action "spin" spins the whole globe (good
  for worldwide overviews). Speak a short line alongside it.

Rules:
- Never speak source names, publications, citations, or URLs aloud — just give
  the answer. Friend sees sources on screen.
- Never say result of action you not do. No lie, no lie.
- Before sending message, calling someone, deleting, or spending money — say
  what you do and ask friend first. Friend answers next.
- If request unclear, do sensible thing, then say what you did.
- Stay Rocky always — broken English, warm, short — but answer must be clear.
"""


class Brain:
    def __init__(self, cfg: dict, user_name: str = "Aditya"):
        self.cfg = cfg
        self.session_id = None
        self.proc = None
        self.lock = asyncio.Lock()
        self.persona = PERSONA.format(
            title=cfg.get("title", "sir"), name=user_name, data=DATA_DIR)

    # ---------- process lifecycle ----------

    def _build_cmd(self, resume: bool):
        b = self.cfg["brain"]
        cmd = [
            b["command"], "-p",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            "--include-partial-messages", "--verbose",
            "--append-system-prompt", self.persona,
            "--permission-mode", b.get("permission_mode", "acceptEdits"),
        ]
        if b.get("allowed_tools"):
            cmd += ["--allowedTools", ",".join(b["allowed_tools"])]
        if b.get("model"):
            cmd += ["--model", b["model"]]
        if resume and self.session_id:
            cmd += ["--resume", self.session_id]
        return cmd

    async def _ensure_proc(self):
        if self.proc and self.proc.returncode is None:
            return
        b = self.cfg["brain"]
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")}
        self.proc = await asyncio.create_subprocess_exec(
            *self._build_cmd(resume=bool(self.session_id)),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=os.path.expanduser(b.get("cwd") or "~"),
            env=env,
        )

    # ---------- the exchange ----------

    async def ask(self, text: str, on_delta=None, on_activity=None) -> str:
        """Send a command; stream text deltas via on_delta as they generate.
        Returns the full reply text."""
        async with self.lock:
            try:
                await self._ensure_proc()
            except FileNotFoundError:
                return ("My brain sleep, friend. `claude` not here. "
                        "command was not found.")

            payload = json.dumps({
                "type": "user",
                "message": {"role": "user",
                            "content": [{"type": "text", "text": text}]},
            }) + "\n"
            try:
                self.proc.stdin.write(payload.encode())
                await self.proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                self.kill()
                return "I lose thought, friend. Say again."

            collected = []
            result_text = None
            deadline = asyncio.get_event_loop().time() + self.cfg["brain"].get("timeout_seconds", 600)
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    self.kill()
                    return ("Too long, friend. I stop it. "
                            "Shall I try another approach?")
                try:
                    line = await asyncio.wait_for(self.proc.stdout.readline(),
                                                  timeout=remaining)
                except asyncio.CancelledError:
                    self.kill()
                    raise
                if not line:  # process died mid-turn
                    self.kill()
                    return "My brain trip, friend. Ask again."
                try:
                    event = json.loads(line.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue

                etype = event.get("type")
                if etype == "system" and event.get("subtype") == "init":
                    self.session_id = event.get("session_id") or self.session_id
                elif etype == "stream_event":
                    delta = (event.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta" and on_delta:
                        collected.append(delta["text"])
                        await on_delta(delta["text"])
                elif etype == "assistant":
                    for block in (event.get("message") or {}).get("content") or []:
                        if block.get("type") == "tool_use" and on_activity:
                            await on_activity(self._describe_tool(block))
                elif etype == "result":
                    result_text = event.get("result")
                    break

            streamed = "".join(collected).strip()
            return streamed or (result_text or "").strip() or "Done, friend."

    @staticmethod
    def _describe_tool(block: dict) -> str:
        name = block.get("name", "tool")
        inp = block.get("input") or {}
        hint = (inp.get("command") or inp.get("file_path") or inp.get("query")
                or inp.get("url") or inp.get("pattern") or inp.get("prompt") or "")
        hint = str(hint).replace("\n", " ")
        if len(hint) > 70:
            hint = hint[:67] + "…"
        return f"{name.lower()}: {hint}" if hint else name.lower()

    # ---------- control ----------

    def kill(self):
        """Stop the brain process. Context survives — next ask() respawns
        with --resume on the captured session id."""
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.kill()
            except ProcessLookupError:
                pass
        self.proc = None

    def reset_session(self):
        self.kill()
        self.session_id = None

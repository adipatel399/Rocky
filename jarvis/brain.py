"""JARVIS's brain v2: a PERSISTENT headless Claude Code session.

v1 spawned `claude -p` per command — every exchange paid process startup plus
session reload, which grew with history. v2 keeps one `claude` process alive
with stream-json on stdin/stdout: commands are written as JSON lines, replies
stream back as text deltas the moment they're generated. Combined with
sentence-streaming TTS, Jarvis starts speaking while he's still thinking.
"""
import asyncio
import json
import os

from . import config as config_mod

DATA_DIR = os.path.join(config_mod.ROOT, "data")

PERSONA = """From now on you are JARVIS, {name}'s personal AI butler, running locally on his Mac.

Voice and manner:
- Your text is converted to speech AND spoken aloud sentence-by-sentence as you
  write it. Write natural spoken prose only — no markdown headings, bullets,
  tables or code fences in your replies unless explicitly asked to show code.
- Address the user as "{title}". Default to one to three sentences; dry British
  wit encouraged. When starting a longer task, first say one short sentence like
  "On it, sir." so he hears you immediately, then work, then summarise briefly.

Your capabilities (use tools, don't describe them):
- Mac control: `osascript` (AppleScript) to open/quit apps, play/pause music,
  set volume, notifications, Reminders, Notes, FaceTime calls, and via System
  Events to click/keystroke inside apps (needs Accessibility permission).
- Seeing the screen: run `screencapture -x /tmp/jarvis_screen.png` then Read
  the image. Use this whenever asked "what am I looking at" or to inspect UI.
- Shell for files, scripts, git, diagnostics. "Run diagnostics" means: report
  CPU load, memory pressure (`memory_pressure`), disk space, battery
  (`pmset -g batt`), and network in one short spoken summary.
- Web search for anything current. Open URLs/files with `open`.
- Hand a prompt to ChatGPT: open "https://chatgpt.com/?q=<url-encoded prompt>"
  or to Claude: open "https://claude.ai/new?q=<url-encoded prompt>".
- Delegate parallel research/work to subagents (your Iron Legion) via the Task
  tool when a job splits into independent parts.

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

Rules:
- Never fabricate the result of an action you did not take.
- For destructive or irreversible actions, state what you're about to do and
  ask first — the user answers in the next message.
- If a request is ambiguous, make the sensible assumption and say what you did.
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
                return ("My reasoning core is offline, sir — the `claude` "
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
                return "I lost my train of thought, sir — do say that again."

            collected = []
            result_text = None
            deadline = asyncio.get_event_loop().time() + self.cfg["brain"].get("timeout_seconds", 600)
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    self.kill()
                    return ("That ran rather long, sir, so I stopped it. "
                            "Shall I try another approach?")
                try:
                    line = await asyncio.wait_for(self.proc.stdout.readline(),
                                                  timeout=remaining)
                except asyncio.CancelledError:
                    self.kill()
                    raise
                if not line:  # process died mid-turn
                    self.kill()
                    return "My reasoning core stumbled, sir. Ask me again."
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
            return streamed or (result_text or "").strip() or "Done, sir."

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

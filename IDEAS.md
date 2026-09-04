# Where ROCKY goes next

v2 shipped: persistent streaming brain, sentence-streamed speech, artifact
panel (markdown/mermaid/images), thumbnail board, notes, desktop-app launcher,
computer-use instructions. Next, roughly in order of wow-per-effort.

## Near term

- **Morning briefing** — a launchd/cron job that makes him speak at 8am:
  calendar, weather, unread mail, top news. "Good morning, sir. It's 24
  degrees, you have three meetings…"
- **Screen awareness** — "Rocky, what am I looking at?" → `screencapture` →
  the brain reads the image. Claude Code can already do this; it just needs a
  persona hint.
- **Menu-bar app** — package the HUD in a tiny wrapper (Tauri is lightest) so
  he lives in the menu bar instead of a browser tab; auto-start at login via
  a LaunchAgent.
- **Interrupt by voice** — detect "rocky stop" *while* he's speaking (keep
  the wake model running during speech, gated to a stop-phrase check).
- **Better voice** — Daniel is good; ElevenLabs is uncanny. A `tts.py`
  backend switch + API key gets a proper film-grade butler. Local
  alternative: Piper (`en_GB-alan-medium`).

## Medium term

- **Long-term memory** — a `~/.rocky/memory.md` the brain reads at session
  start and appends to ("remember that my college wifi password is…").
  Claude Code's own memory dir can double for this.
- **Browser hands** — add a browser MCP server (e.g. Playwright MCP) to
  `claude mcp add`; the brain inherits every configured MCP server
  automatically, so Rocky gains "book the ticket" web skills for free.
- **App macros** — "coding setup" → opens VS Code + terminal + localhost;
  define these as skills in `~/.claude/skills/` and the brain will use them.
- **Multiple wake responses by context** — time-aware acks ("Good evening,
  sir") and a do-not-disturb schedule.
- **Status readouts in the reactor** — pipe real CPU/RAM/network into the
  ring as arc segments; the HUD already polls `/api/stats`.

## Big swings

- **Proactive Rocky** — file-system and calendar watchers that let him speak
  first: "Sir, your 3pm starts in five minutes." (Claude Code scheduled
  tasks / cron can drive this.)
- **Phone access** — expose the HUD over Tailscale and talk to the Mac from
  anywhere; the stack is already a web app, so this is mostly networking.
- **Vision mode** — continuous lightweight screen OCR so "click the blue
  button" works; pair with computer-use tooling.
- **Home control** — HomeKit via `shortcuts run` CLI: lights, AC, the lot.
  "Rocky, movie mode."

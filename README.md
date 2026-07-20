# J.A.R.V.I.S.

A local, voice-controlled AI butler for your Mac — wake word, British voice,
cinematic HUD with a live artifact panel, and real hands: its brain is a
persistent, streaming Claude Code session.

```
   your voice ──▶ ears (openWakeWord "jarvis" + Whisper — on-device)
                     │
   desktop app ──▶ core (FastAPI + WebSocket, streams everything)
   `jarvis` cmd      │
                     ▼
                  brain (ONE persistent claude process, stream-json —
                     │   replies stream out word by word)
        ┌────────────┼──────────────┐
        ▼            ▼              ▼
   voice (Daniel, artifact panel  data/ (notes ·
   speaks sentence  (markdown ·    records · thumbnail
   by sentence as   mermaid ·      board — watched live)
   text generates)  images)
```

## Launch

```bash
jarvis          # starts the server if needed + opens the desktop window
jarvis stop     # power down
jarvis logs     # tail the server log
```

(`jarvis` is symlinked into `~/.local/bin`. The window is a chromeless Chrome
app window — no tabs, no address bar, just the HUD.)

## Talk to him

- Say **"Jarvis"** → "Yes, sir?" → give your order. Keep talking within a few
  seconds of his reply — no wake word needed (follow-up window).
- He starts **speaking his first sentence while still thinking** — replies are
  streamed from the brain into the speakers sentence by sentence.
- "That's all" / "go to sleep" ends the exchange. `Esc` or STOP interrupts
  mid-sentence. NEW starts a fresh conversation (context otherwise persists).

## What he can do

- **Anything Claude Code can**: shell, files, git, AppleScript app control,
  web search, opening URLs. "Send this prompt to ChatGPT: …" opens
  chatgpt.com with your spoken prompt pre-filled (same for Claude).
- **Run diagnostics** — CPU, memory, disk, battery, network in one breath.
- **See your screen** — "Jarvis, what am I looking at?" (screencapture + vision).
- **Computer use** — clicking/typing/UI inspection via AppleScript System
  Events (grant Accessibility permission to your terminal; optionally
  `brew install cliclick` for pixel-precise clicks).
- **Project to the HUD** — anything he writes into `data/artifacts/` renders
  instantly on the panel: markdown (menus, plans, tables), `.mmd` Mermaid
  diagrams, images. His "holographic display".
- **Notes & records** — "note down…" writes markdown into `data/notes/`
  (NOTES tab); records live under `data/records/`.
- **YouTube thumbnail board** — "make me a thumbnail for…" renders a 1280×720
  design via headless Chrome into `data/thumbnails/NNN-name.png`. Generations
  are numbered and persistent; edits get a new number (BOARD tab).
- **The Iron Legion** — parallel research/work via subagents.

## Configure — `config.yaml`

| Key | What it does |
|-----|--------------|
| `title` | "sir" or "boss" |
| `voice.name` / `voice.rate` | `say` voice + speed (Daniel = British male) |
| `ears.wake_threshold` | Lower = easier wake, more false triggers |
| `ears.whisper_model` | `tiny.en` fastest · `base.en` balanced · `small.en` sharpest |
| `brain.model` | `null` = your Claude Code default · `haiku` = snappiest chat |
| `brain.allowed_tools` | His hands — trim to restrict, extend to empower |

### Full-power mode (think before enabling)

Default is `permission_mode: acceptEdits` + an explicit tool allowlist, and the
persona confirms destructive actions aloud. `bypassPermissions` removes all
friction — enable knowingly.

## Troubleshooting

- **EARS OFFLINE** — grant your terminal Microphone access, restart. Check
  `curl localhost:8765/api/stats` for `ears_error`.
- **Slow first reply after idle/interrupt** — first turn respawns the brain
  process (context is restored via the session id); later turns are faster.
- **Random wakes** — raise `ears.wake_threshold` to 0.6.
- **"Session limit" replies** — your Claude plan's 5-hour usage window; it
  resets on schedule. Voice chat burns usage like any Claude Code session.

First-time setup on a new machine: `python3 -m venv .venv &&
.venv/bin/pip install -r requirements.txt`, then `bin/jarvis`.

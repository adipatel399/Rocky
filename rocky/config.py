"""Configuration loader for ROCKY. Reads config.yaml and merges over defaults."""
import os
import copy
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yaml")

DEFAULTS = {
    "title": "friend",
    "port": 8765,
    "voice": {
        "enabled": True,
        "name": "Rocko (English (US))",   # macOS `say` voice (his namesake).
        "rate": 180,                      # pick any from the HUD dropdown.
    },
    # Voices offered in the HUD dropdown: [display label, `say` voice name].
    "voice_options": [
        ["Rocko",            "Rocko (English (US))"],
        ["Zarvox · alien",   "Zarvox"],
        ["Trinoids · choir", "Trinoids"],
        ["Cellos · musical", "Cellos"],
        ["Organ",            "Organ"],
        ["Boing",            "Boing"],
        ["Fred · robotic",   "Fred"],
        ["Daniel · British", "Daniel"],
        ["Rishi · Indian",   "Rishi"],
        ["Samantha · US",    "Samantha"],
    ],
    "ears": {
        "enabled": True,
        "wake_word": "rocky",       # say this to wake him ("rocky" / "hey rocky")
        "wake_engine": "whisper",   # "whisper" = custom word via STT · "openwakeword" = "jarvis"
        "wake_threshold": 0.28,
        "mic_gain": 1.5,
        "followup_seconds": 8,
        "silence_seconds": 1.4,
        "max_command_seconds": 14,
        "whisper_model": "base.en",
    },
    "acknowledgements": [
        "Yes, friend?",
        "I here. Talk, friend.",
        "I listen, friend.",
        "Question, friend?",
    ],
    "sleep_phrases": [
        "go to sleep", "that's all", "thats all", "stand down",
        "dismissed", "sleep now", "goodbye rocky", "bye rocky",
        "thank you rocky", "good night rocky",
    ],
    "brain": {
        "command": "claude",
        "model": None,
        "cwd": "~",
        "permission_mode": "acceptEdits",
        "allowed_tools": [
            "Bash", "Read", "Glob", "Grep", "Write", "Edit",
            "WebSearch", "WebFetch", "TodoWrite", "Task",
        ],
        "timeout_seconds": 600,
    },
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load() -> dict:
    user_cfg = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            user_cfg = yaml.safe_load(f) or {}
    return _merge(DEFAULTS, user_cfg)

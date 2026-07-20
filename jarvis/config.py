"""Configuration loader for JARVIS. Reads config.yaml and merges over defaults."""
import os
import copy
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.yaml")

DEFAULTS = {
    "title": "sir",
    "port": 8765,
    "voice": {
        "name": "Daniel",
        "rate": 178,
        "enabled": True,
    },
    "ears": {
        "enabled": True,
        "wake_threshold": 0.28,
        "mic_gain": 1.5,
        "followup_seconds": 8,
        "silence_seconds": 1.4,
        "max_command_seconds": 14,
        "whisper_model": "base.en",
    },
    "acknowledgements": [
        "Yes, sir?",
        "At your service, sir.",
        "Sir?",
        "How can I help, sir?",
    ],
    "sleep_phrases": [
        "go to sleep", "that's all", "thats all", "stand down",
        "dismissed", "thank you jarvis", "goodnight jarvis",
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

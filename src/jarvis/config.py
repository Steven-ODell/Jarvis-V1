"""Settings in ~/.config/jarvis/config.toml.

Defaults live here. The file on disk only needs the keys you changed, and the
settings panel writes the whole thing back when you flip something, so hand
edits and panel edits end up in the same place.
"""

import copy
import os
import threading
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
CONFIG_PATH = Path(os.environ.get("JARVIS_CONFIG", Path.home() / ".config/jarvis/config.toml"))
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET = RUNTIME / "jarvis.sock"
STATE_DIR = Path.home() / ".local/share/jarvis"

WAKE_MODELS = ["jarvis", "hey_jarvis", "alexa", "hey_mycroft", "hey_marvin"]
VOICES = ["bm_george", "bm_lewis", "bm_daniel", "bm_fable", "bf_emma", "bf_isabella", "am_michael", "af_heart"]
BRAIN_MODELS = ["haiku", "sonnet", "opus"]

DEFAULTS = {
    "wake": {
        "enabled": False,
        # jarvis | hey_jarvis | alexa | hey_mycroft | hey_marvin | /path/to.onnx
        "model": "hey_jarvis",
        # openWakeWord score, 0..1. Lower hears you from further away and
        # false-triggers more.
        "threshold": 0.5,
        # After the wake word fires, silence doesn't count toward
        # end-of-speech for this long, so you can take a beat before (or
        # while starting) the command.
        "grace_ms": 1200,
    },
    "brain": {
        # opus = Opus 5.5. Sonnet answers a touch faster on tool turns for
        # about a sixth of the usage, but Sao found it too dumb.
        "model": "opus",
        # Claude Code fast mode (Opus): ~1 s quicker on tool turns, roughly
        # double the usage.
        "fast": False,
        # The claude process starts when you press the hotkey (it boots while
        # you talk) and exits after this many idle minutes, so nothing sits in
        # RAM between conversations. keep_warm holds it open forever instead.
        "idle_exit_min": 5,
        "keep_warm": False,
        # Claude Code reasoning effort. low answers ~0.6 s sooner on tool
        # calls with no loss on voice-sized requests.
        "effort": "low",
    },
    "local": {
        # Ollama servers tried in order when Claude is unreachable. Put the
        # 4070 desktop first, e.g. "http://192.168.1.50:11434".
        "endpoints": ["http://localhost:11434"],
        "model": "qwen3.5:9b",
        # Ollama unloads the model this long after the last request.
        "keep_alive": "2m",
    },
    "voice": {
        "voice": "bm_george",
        "speed": 1.25,
        # Say "Opening GitHub." etc. for instant commands. Off = silent + orb.
        "acks": True,
    },
    "listen": {
        "whisper_model": "base.en",
        # Whisper + Kokoro (~800 MB) load when you press the hotkey and are
        # freed after this many idle seconds.
        "models_keep_s": 120,
        "silence_ms": 800,
        "no_speech_timeout": 5.0,
        "max_seconds": 20.0,
        # When Jarvis ends on a question, reopen the mic for the answer.
        "follow_up": True,
        # Pause whatever MPRIS player is playing while Jarvis listens/talks.
        "pause_media": True,
        # Biases whisper toward these spellings. Add names it gets wrong.
        "vocabulary": [
            "Jarvis", "GitHub", "Omarchy", "Hyprland", "Zen", "Chromium", "neovim", "lazygit",
            "ghostty", "YouTube", "Reddit", "Hacker News", "Kagi", "ChatGPT", "Claude",
            "Gmail", "Slack", "Discord", "Spotify", "Apple Music", "Wikipedia",
            "Arch Wiki", "AUR", "Quickshell", "Python", "JavaScript", "C++",
            "PETG", "PLA", "ABS", "TPU", "Bambu", "Klipper", "OrcaSlicer", "Printables",
            "Isaac Sim",
        ],
    },
    "orb": {
        # bottom | center | top
        "position": "bottom",
        "size": 230,
    },
    "search": {
        # google | kagi | duckduckgo | brave
        "engine": "google",
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(v, list):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"can't write {type(v)} to toml")


def _diff(data, base):
    """Only the keys that differ from the defaults, so a later change to a
    default (a new vocabulary word, say) still reaches you."""
    out = {}
    for section, values in data.items():
        changed = {k: v for k, v in values.items() if base.get(section, {}).get(k) != v}
        if changed:
            out[section] = changed
    return out


def dump_toml(data):
    lines = ["# Jarvis settings: only what differs from the defaults in",
             "# ~/Projects/Side/jarvis/src/jarvis/config.py. The settings panel",
             "# (jarvis settings) rewrites this file.", ""]
    for section, values in data.items():
        lines.append(f"[{section}]")
        for k, v in values.items():
            lines.append(f"{k} = {_toml_value(v)}")
        lines.append("")
    return "\n".join(lines)


class Config:
    def __init__(self, path=CONFIG_PATH):
        self.path = Path(path)
        self.lock = threading.Lock()
        self.data = self._load()

    def _load(self):
        if self.path.exists():
            with open(self.path, "rb") as f:
                return _merge(DEFAULTS, tomllib.load(f))
        return copy.deepcopy(DEFAULTS)

    def reload(self):
        with self.lock:
            self.data = self._load()

    def get(self, dotted):
        section, key = dotted.split(".", 1)
        return self.data[section][key]

    def set(self, dotted, value):
        section, key = dotted.split(".", 1)
        if section not in DEFAULTS or key not in DEFAULTS[section]:
            raise KeyError(dotted)
        # Coerce to the default's type so a panel sending "0.4" or 1 for a
        # bool doesn't poison the file.
        kind = type(DEFAULTS[section][key])
        if kind is bool and not isinstance(value, bool):
            value = str(value).lower() in ("1", "true", "on", "yes")
        elif kind in (int, float):
            value = kind(value)
        with self.lock:
            self.data[section][key] = value
            self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(dump_toml(_diff(self.data, DEFAULTS)))
        tmp.replace(self.path)

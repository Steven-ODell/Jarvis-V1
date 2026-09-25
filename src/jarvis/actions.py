"""Things Jarvis can do to the desktop without asking a model.

Shared by the fast path and the local-model fallback, so both launch apps and
open pages the same way.
"""

import configparser
import difflib
import json
import os
import re
import shlex
import subprocess
from pathlib import Path


def spawn(cmd):
    """Fire and forget, fully detached so the app outlives the daemon."""
    if isinstance(cmd, str):
        cmd = ["sh", "-c", cmd]
    subprocess.Popen(
        cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, start_new_session=True,
    )


def run(cmd, timeout=5):
    if isinstance(cmd, str):
        cmd = ["sh", "-c", cmd]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return 1, str(e)


def hypr(*args):
    return run(["hyprctl", "dispatch", *map(str, args)])


def clients():
    code, out = run(["hyprctl", "clients", "-j"])
    try:
        return json.loads(out) if code == 0 else []
    except json.JSONDecodeError:
        return []


def focus_class(pattern):
    """Focus the first window whose class matches. True if one existed."""
    rx = re.compile(pattern, re.I)
    for c in clients():
        if rx.search(c.get("class", "")) or rx.search(c.get("initialClass", "")):
            hypr("focuswindow", f"address:{c['address']}")
            return True
    return False


def open_url(url):
    if not re.match(r"^[a-z]+://", url):
        url = "https://" + url
    spawn(["xdg-open", url])
    # Zen opens the tab in its existing window without raising it, so bring
    # the browser forward ourselves.
    focus_class(r"^zen")


# ------------------------------------------------------------------ apps ---

APP_DIRS = [
    Path.home() / ".local/share/applications",
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
]

# Spoken names that don't match a .desktop Name, or where Sao's own binding
# does it better than the stock entry (these mirror ~/.config/hypr/bindings.lua).
APP_ALIASES = {
    "terminal": ("ghostty", "uwsm app -- ghostty"),
    "ghostty": ("ghostty", "uwsm app -- ghostty"),
    "browser": ("^zen", "uwsm app -- zen-browser"),
    "zen": ("^zen", "uwsm app -- zen-browser"),
    "zen browser": ("^zen", "uwsm app -- zen-browser"),
    "chromium": (None, "uwsm app -- chromium --new-window"),
    "chrome": (None, "uwsm app -- chromium --new-window"),
    "files": ("nautilus", "uwsm app -- nautilus --new-window"),
    "file manager": ("nautilus", "uwsm app -- nautilus --new-window"),
    "nautilus": ("nautilus", "uwsm app -- nautilus --new-window"),
    "claude": (None, "uwsm app -- ghostty --working-directory=$HOME -e zsh -ic 'claude; exec zsh'"),
    "claude code": (None, "uwsm app -- ghostty --working-directory=$HOME -e zsh -ic 'claude; exec zsh'"),
    "apple music": (None, "uwsm app -- zen-browser --new-window https://music.apple.com"),
    "music": (None, "uwsm app -- zen-browser --new-window https://music.apple.com"),
    "slack": ("chrome-app\\.slack\\.com", "omarchy-launch-webapp https://app.slack.com/client"),
    "neovim": (None, "omarchy-launch-editor"),
    "editor": (None, "omarchy-launch-editor"),
    "lazygit": (None, "uwsm app -- ghostty -e lazygit"),
    "btop": (None, "uwsm app -- ghostty -e btop"),
    "system monitor": (None, "uwsm app -- ghostty -e btop"),
    "gitdeck": (None, "uwsm app -- ghostty -e deck"),
    "deck": (None, "uwsm app -- ghostty -e deck"),
    "dnb radio": ("dev\\.sao\\.dnbradio", "uwsm app -- ghostty --class=dev.sao.dnbradio "
                  "--working-directory=$HOME/Projects/Side/dnb-radio "
                  "-e $HOME/.local/bin/uv run dnb-radio radio --mixes"),
    "radio": ("dev\\.sao\\.dnbradio", "uwsm app -- ghostty --class=dev.sao.dnbradio "
              "--working-directory=$HOME/Projects/Side/dnb-radio "
              "-e $HOME/.local/bin/uv run dnb-radio radio --mixes"),
}


class DesktopApps:
    """Index of installed .desktop entries by display name."""

    def __init__(self):
        self.by_name = {}
        seen = set()
        for d in APP_DIRS:
            if not d.is_dir():
                continue
            for f in sorted(d.glob("*.desktop")):
                if f.name in seen:
                    continue  # ~/.local overrides /usr, same as the launcher
                seen.add(f.name)
                entry = self._parse(f)
                if entry:
                    self.by_name.setdefault(entry["name"].lower(), entry)

    @staticmethod
    def _parse(path):
        cp = configparser.RawConfigParser(strict=False, interpolation=None)
        try:
            cp.read(path, encoding="utf-8")
            e = cp["Desktop Entry"]
        except Exception:
            return None
        if e.get("NoDisplay", "false").lower() == "true" or e.get("Type", "Application") != "Application":
            return None
        if not e.get("Name"):
            return None
        return {
            "id": path.name,
            "name": e["Name"],
            "wmclass": e.get("StartupWMClass"),
        }

    def find(self, spoken):
        spoken = spoken.lower().strip()
        if spoken in self.by_name:
            return self.by_name[spoken]
        hit = difflib.get_close_matches(spoken, self.by_name.keys(), n=1, cutoff=0.8)
        return self.by_name[hit[0]] if hit else None


_apps = None


def apps():
    global _apps
    if _apps is None:
        _apps = DesktopApps()
    return _apps


def launch_app(spoken):
    """Focus the app if it's already open, otherwise start it.
    Returns the name it resolved to, or None if nothing matched."""
    key = spoken.lower().strip()
    alias_key = key if key in APP_ALIASES else None
    if alias_key is None:
        close = difflib.get_close_matches(key, APP_ALIASES.keys(), n=1, cutoff=0.85)
        alias_key = close[0] if close else None
    if alias_key:
        wm, cmd = APP_ALIASES[alias_key]
        if wm and focus_class(wm):
            return alias_key
        spawn(os.path.expandvars(cmd))
        return alias_key
    entry = apps().find(key)
    if entry:
        wm = entry["wmclass"] or entry["id"].removesuffix(".desktop")
        if focus_class("^" + re.escape(wm) + "$"):
            return entry["name"]
        spawn(["uwsm", "app", "--", entry["id"]])
        return entry["name"]
    return None


# ------------------------------------------------------------------ media ---

def _mpris_players():
    code, out = run(["busctl", "--user", "list", "--no-legend"])
    if code:
        return []
    return [line.split()[0] for line in out.splitlines() if line.startswith("org.mpris.MediaPlayer2.")]


def _mpris_status(name):
    code, out = run(["busctl", "--user", "get-property", name, "/org/mpris/MediaPlayer2",
                     "org.mpris.MediaPlayer2.Player", "PlaybackStatus"])
    m = re.search(r'"(\w+)"', out)
    return m.group(1) if code == 0 and m else None


def media(method):
    """PlayPause / Play / Pause / Next / Previous on the most relevant player."""
    players = _mpris_players()
    if not players:
        return False
    playing = [p for p in players if _mpris_status(p) == "Playing"]
    target = (playing or players)[0]
    run(["busctl", "--user", "call", target, "/org/mpris/MediaPlayer2",
         "org.mpris.MediaPlayer2.Player", method])
    return True


def pause_playing():
    """Pause everything that's playing; return names to resume later."""
    paused = []
    for p in _mpris_players():
        if _mpris_status(p) == "Playing":
            run(["busctl", "--user", "call", p, "/org/mpris/MediaPlayer2",
                 "org.mpris.MediaPlayer2.Player", "Pause"])
            paused.append(p)
    return paused


def resume(players):
    for p in players:
        run(["busctl", "--user", "call", p, "/org/mpris/MediaPlayer2",
             "org.mpris.MediaPlayer2.Player", "Play"])


# ----------------------------------------------------------------- system ---

def volume(arg):
    """arg: 'raise' | 'lower' | 'mute-toggle' | '+N' | '-N' | 'N' (absolute %)."""
    if re.fullmatch(r"\d+", str(arg)):
        run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{int(arg)}%"])
        return
    run(["omarchy", "audio", "output", "volume", str(arg)])


def brightness(arg):
    run(["omarchy", "brightness", "display", str(arg)])


def type_text(text):
    run(["wtype", "--", text])


def notify(title, body=""):
    spawn(["notify-send", "-a", "Jarvis", title, body])


def shell_quote(s):
    return shlex.quote(s)

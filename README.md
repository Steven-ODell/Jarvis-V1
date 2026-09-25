# Jarvis

A voice assistant for this Omarchy laptop. Press SUPER+A and talk. A purple
plasma orb rises from the bottom of the screen, listens, thinks, and answers in
a British voice. It can drive the desktop, a real browser, and your Google
connectors.

## Using it

| Do | What happens |
|---|---|
| SUPER+A | Start listening. It stops by itself when you stop talking. |
| SUPER+A while listening | Stop now and answer. |
| SUPER+A while it talks | Cut it off and listen again. |
| "Hey Jarvis" | Same as the hotkey, if the wake word is on (off by default). |
| "never mind" / "stop" | Drop everything. |
| "new conversation" | Forget the context. |
| Jarvis Settings (launcher) | Wake word, voice, model, speed, orb position. |

If Jarvis ends on a question, the mic reopens for four seconds so you can just
answer.

## How a request is handled

1. **Fast path**, instant, no model: open sites and apps, search, workspaces,
   close/fullscreen, volume, brightness, media, lock, screenshot, timers,
   reminders, time and date, "type ...". About 30 patterns in
   `src/jarvis/fastpath.py`. A request is only handled here when the whole
   sentence matches, so "open GitHub and find my newest repo" goes to Claude.
2. **Claude Code**, for everything else. One `claude -p` process in
   stream-json mode, started the moment you press the hotkey so it has booted
   by the time you stop talking. It has Bash on the real desktop, a Playwright
   browser (its own Chromium profile), WebSearch, and the claude.ai Gmail,
   Calendar and Drive connectors. Permission mode is `auto`, so risky actions
   are refused, and the system prompt (`src/jarvis/prompt.py`) says to ask
   before deleting, sending or buying.
3. **Local fallback**, when Claude is unreachable or errors: an Ollama model
   with three tools (open a URL, launch an app, run a read-only command). Set
   `local.endpoints` to the 4070 desktop, e.g. `["http://192.168.1.50:11434"]`.

Speech in is faster-whisper `base.en` (~0.45 s per request) with a vocabulary
prompt so GitHub, Omarchy, PETG and friends come out spelled right. Speech out
is Kokoro, streamed sentence by sentence while Claude is still writing.

## Memory

Nothing heavy sits in RAM between conversations.

| State | Resident |
|---|---|
| Idle, wake word off | daemon ~80 MB + orb ~160 MB |
| Idle, wake word on | + ~90 MB (openWakeWord) |
| During a conversation | daemon ~870 MB (whisper + Kokoro) + claude ~300 MB |

Whisper and Kokoro load when you press the hotkey (about 1 s, hidden behind
you talking) and unload after `listen.models_keep_s` idle seconds (120). The
claude process exits after `brain.idle_exit_min` minutes (5), or after 45 s
if the fast path handled the request and Claude was never asked anything.
`jarvis status` shows the live numbers.

## Settings

`~/.config/jarvis/config.toml` holds only what differs from the defaults in
`src/jarvis/config.py`. The settings panel writes it; hand edits work too
(`jarvis reload` afterwards).

## Commands

```
jarvis toggle            what SUPER+A runs
jarvis ask "..."         typed request through the same pipeline
jarvis say "..."         speak a line
jarvis status            state, loaded models, memory
jarvis watch             live event stream (what the orb sees)
jarvis settings          open the settings panel
jarvis wake on|off       wake word
jarvis set brain.model opus
```

## Layout

```
src/jarvis/
  daemon.py     turn state machine, socket server, orb supervisor
  brain.py      Claude Code session + Ollama fallback
  speech.py     whisper, Silero VAD, wake word, Kokoro, sentence streaming
  audio.py      mic and speaker streams, loudness for the orb
  fastpath.py   instant commands
  actions.py    desktop actions shared by the fast path and fallback
  prompt.py     what Claude is told about being Jarvis
orb/
  shell.qml     Quickshell overlay: orb + captions, click-through
  Orb.qml       state -> shader uniforms, level smoothing
  Settings.qml  settings panel
  shaders/orb.frag   the plasma sphere (compile: see CLAUDE.md)
browser/        Playwright MCP server (npm)
systemd/        jarvis.service (user unit)
scripts/setup   builds everything git doesn't carry; the dotfiles call it
```

## Setup

`scripts/setup` builds the venv, downloads ~450 MB of models, installs the
browser server, links `jarvis` onto PATH and enables the service. The
Omarchy-merge `install.sh` runs it.

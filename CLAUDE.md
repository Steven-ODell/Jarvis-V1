# Jarvis: notes for Claude

Side project (Claude-built, for Sao to use). README.md covers what it is; this
covers how to work on it without breaking things.

## Run and test

- `scripts/dev-restart` stops the systemd service and runs the daemon from
  source, logging to `~/.local/share/jarvis/dev.log`. When done:
  `systemctl --user restart jarvis`.
- `scripts/speak-at-mic "text"` presses the hotkey and plays TTS out of the
  speakers: the real mic, VAD and whisper path. `--wake "hey jarvis. text"`
  tests the wake word. It makes sound.
- `jarvis inject file.npy|wav` skips the mic; `jarvis ask "..."` skips speech
  entirely. Both skip the Claude prewarm, so their first-turn latency is
  worse than the hotkey's.
- `jarvis watch` shows the event stream. Turn timings (`first text`,
  `first audio`) and per-chunk `[tts]` timings are in the log.
- `.venv/bin/python -m pytest -q tests`: fast-path routing, end-of-speech
  rules (scripted VAD + fake clock), and the offline fallback against a fake
  Ollama server.
- Look at the orb before calling a visual change done: `grim -o eDP-1` while
  it's up, then crop. The window is bottom-center, 680 x (size+150) logical
  px at scale 1.5.

## Gotchas

- The shader is compiled: after editing `orb/shaders/orb.frag` run
  `/usr/lib/qt6/bin/qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o orb/shaders/orb.frag.qsb orb/shaders/orb.frag`.
- `set` is reserved in QML; a signal named `set` breaks the whole file with
  "Expected token `:`".
- Kokoro fp32 is 4x faster than the int8 model on this CPU. Don't "optimize"
  to int8.
- Load whisper with `local_files_only=True` first; otherwise huggingface_hub
  checks for updates on every load (0.3 s became 9 s).
- Don't `import openwakeword` outside the wake-word path: it pulls in ~90 MB.
  The VAD is reimplemented in `speech.SileroVAD` for that reason.
- openWakeWord 0.4 has no `inference_framework` kwarg.
- Wake-word turns endpoint differently from hotkey turns
  (`Utterance._feed_wake`). The pre-roll holding "Hey Jarvis" is context, not
  the command starting. The command must begin 0.35 s or more after the
  trigger, and silence in the first `wake.grace_ms` doesn't count. Before this
  fix, pausing after the wake word cut the turn off (Sao reported it
  2026-09-24). `tests/test_endpointing.py` covers it; test it by ear with
  `GAP=1.5 scripts/speak-at-mic --wake "hey jarvis. ..."`.
- The wake model keeps ~2 s of spectrogram history; after pausing it must be
  flushed with silence (`need_flush`) or it re-fires on the old "Jarvis".
- Bare "Jarvis" (wake.model = "jarvis") runs the hey_jarvis model at half the
  threshold and checks the transcript for the name. It's unreliable, so the
  default is hey_jarvis. Sao said that's fine.
- Claude runs with `ENABLE_TOOL_SEARCH=false` so MCP tools skip the
  ToolSearch round-trip.
- Sao's memory rule: nothing heavy resident while idle. Whisper and Kokoro
  unload after `models_keep_s`, and claude exits when idle. Keep it that way,
  and report memory with numbers from `jarvis status`.
- `hyprctl dispatch exec` doesn't work under Lua Hyprland; use
  `hyprctl eval "hl.exec_cmd('...')"`. wtype key chords don't trigger binds.

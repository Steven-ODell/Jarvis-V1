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
  it's up, then crop. The window is 680 x (size+190) logical px at scale
  1.5, top or bottom center. To see a state without talking, point a second
  `quickshell -p orb/shell.qml` at a fake socket with `JARVIS_SOCKET` that
  sends `hello`, `state` and `level` events. Wait until the real orb is
  hidden first, or the two overlap.
- The orb design (2026-09-28) is a hologram: tick-marked dial, two
  gyroscope rings, waveform loops around a point of light. It replaced the
  plasma sphere because Sao wanted a new look, not a tweak of the old one.
  The ring phases are integrated in Orb.qml; don't go back to
  `time * speed` in the shader, which jumps when the speed changes.

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
- VAD uses hysteresis (0.5 to start, 0.35 to keep going). Soft trailing
  syllables score ~0.4 and used to end turns mid-question. Every capture is
  saved to `~/.local/share/jarvis/last-utterance.wav`; check it before
  guessing at a cut-off report.
- The mic opens before the model loads and Claude boot in `listen()`. On a
  cold start the CPU contention was enough to lose the first word.
- The service sets `MALLOC_ARENA_MAX=2`. Without it, each model
  load/unload cycle fragments the heap and idle RSS creeps up
  (212 -> 349 MB over four cycles; with it, flat at ~190).
- Model: Sonnet 5.5 by default since 2026-09-28 (Opus 5.5 before that; Sao
  found Sonnet 5 too dumb). `brain.model` is a CLI alias; since Claude Code
  2.1.284 `sonnet` resolves to `claude-sonnet-5-5`. `brain.fast` passes
  `--settings {"fastMode": true}`. Benchmarks 2026-09-24, time to first
  words: Sonnet 3.6/0.7 s (tool/simple), Opus 5.1/0.8, Opus fast 3.7/0.8.
  Fast mode is roughly double the usage.
- Voice speed 1.25 was Sao's pick from 1.1 / 1.25 / 1.4 samples.
- Claude runs with `ENABLE_TOOL_SEARCH=false` so MCP tools skip the
  ToolSearch round-trip.
- Sao's memory rule: nothing heavy resident while idle. Whisper and Kokoro
  unload after `models_keep_s`, and claude exits when idle. Keep it that way,
  and report memory with numbers from `jarvis status`.
- `hyprctl dispatch exec` doesn't work under Lua Hyprland; use
  `hyprctl eval "hl.exec_cmd('...')"`. wtype key chords don't trigger binds.
- Memory (`memory.py`, since 2026-09-28): every exchange goes to
  `memory/log.jsonl` (gitignored, kept forever by Sao's rule). A new Claude
  session gets the last `memory.recent` (10) claude/local exchanges plus
  `memory/summary.md` appended to its system prompt; fast-path turns are
  logged but left out. We chose this over `--resume`, which replays the whole
  transcript (tool output included) and gets slower every day. The summary
  is rebuilt in the background by haiku once `summarize_every` exchanges
  scroll out of the window. That call runs with `--system-prompt`,
  `--tools ""` and cwd `/tmp`: run from the project, it read CLAUDE.md
  and wrote its contents into the summary as if Sao had said them.
  "Start over" resets the live session only; memory stays.

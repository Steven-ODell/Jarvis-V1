"""The running assistant: owns the models, the mic, the brains, and the orb.

One turn = listen -> transcribe -> (fast path | Claude | local model) -> speak.
Every turn gets a number; pressing the hotkey or saying the wake word again
bumps it, and anything still running for an older number quietly stops. That
single counter is the whole interruption story.
"""

import json
import os
import re
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import numpy as np

from . import actions, audio, fastpath
from .brain import BrainError, ClaudeSession, LocalBrain, online
from .config import ROOT, SOCKET, STATE_DIR, VOICES, WAKE_MODELS, BRAIN_MODELS, Config
from .speech import Models, Speaker, Utterance, WakeWord, load_vad


WAKE_WORD = re.compile(r"\b(?:hey |ok |okay )?(?:jarvis|jervis|javis|jarvi|jarves|jarvus)\b[,.!?]?", re.I)


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def rss_mb(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    except OSError:
        pass
    return 0


TOOL_LABELS = {
    "Bash": "running a command",
    "Read": "reading",
    "Write": "writing a file",
    "Edit": "editing a file",
    "Grep": "searching files",
    "Glob": "finding files",
    "WebSearch": "searching the web",
    "WebFetch": "reading a page",
    "Agent": "delegating",
    "Task": "delegating",
    "TodoWrite": "planning",
    "ToolSearch": "loading tools",
}


def tool_label(name, inp):
    if name.startswith("local:"):
        return f"offline · {name[6:]}"
    if name == "Bash" and inp:
        return (inp.get("description") or inp.get("command", ""))[:60]
    if name == "WebSearch" and inp:
        return f"searching: {inp.get('query', '')}"[:60]
    if name.startswith("mcp__browser__"):
        return "browser · " + name.removeprefix("mcp__browser__browser_").replace("_", " ")
    if name.startswith("mcp__"):
        parts = name.split("__")
        svc = parts[1].removeprefix("claude_ai_").replace("_", " ") if len(parts) > 1 else "tool"
        return f"{svc} · {parts[-1].replace('_', ' ')}"
    if name in ("open_url", "launch_app", "run_command") and inp:
        return f"{name.replace('_', ' ')}: {next(iter(inp.values()), '')}"[:60]
    return TOOL_LABELS.get(name, name)


class Hub:
    """Fan-out of events to every subscribed socket (the orb, `jarvis watch`)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.subs = []

    def add(self, conn):
        with self.lock:
            self.subs.append(conn)

    def emit(self, ev):
        data = (json.dumps(ev) + "\n").encode()
        with self.lock:
            dead = []
            for c in self.subs:
                try:
                    c.sendall(data)
                except OSError:
                    dead.append(c)
            for c in dead:
                self.subs.remove(c)


class Daemon:
    def __init__(self, orb=True):
        self.cfg = Config()
        self.hub = Hub()
        self.lock = threading.RLock()
        self.turn = 0
        self.state = "idle"
        self.utt = None
        self.paused_media = []
        self.orb_enabled = orb
        self.orb_proc = None
        self.running = True
        self._level_t = 0.0

        self.models = Models(
            self.cfg.get("listen.whisper_model"),
            keep_s=lambda: float(self.cfg.get("listen.models_keep_s")),
            is_idle=lambda: self.state == "idle",
            log=log,
        )
        self.vad = load_vad()
        self.player = audio.Player(on_level=self._speak_level)
        self.speaker = Speaker(self.models.tts, self.player,
                               lambda: (self.cfg.get("voice.voice"), float(self.cfg.get("voice.speed"))))
        self.mic = audio.Mic()
        self.claude = ClaudeSession(self.cfg, log)
        self.local = LocalBrain(self.cfg, log)
        self.wake = None
        self._apply_wake()
        log(f"ready, rss {rss_mb(os.getpid())} MB (speech models load on first use)")

    # --------------------------------------------------------------- events

    def emit(self, ev, **kw):
        self.hub.emit({"ev": ev, **kw})

    def set_state(self, state):
        with self.lock:
            if self.state != state:
                self.state = state
                self.emit("state", state=state)

    def _mic_level(self, v):
        self.emit("level", v=round(v, 3))

    def _speak_level(self, v):
        if self.state == "speaking":
            self.emit("level", v=round(v, 3))

    # ----------------------------------------------------------------- wake

    def _apply_wake(self):
        want = bool(self.cfg.get("wake.enabled"))
        model = self.cfg.get("wake.model")
        if self.wake and (not want or self.wake.mode != model):
            self.mic.remove("wake")
            self.wake = None
            log("wake word off")
        if want and self.wake is None:
            try:
                self.wake = WakeWord(model, float(self.cfg.get("wake.threshold")), self._on_wake)
                self.wake.on_near_miss = lambda sc: log(f"wake near-miss {sc:.2f}")
                self.mic.add("wake", self.wake.feed)
                log(f"wake word on: {self.wake.mode} ({self.wake.name})")
            except Exception as e:
                log(f"wake word failed: {e!r}")
                self.emit("error", text=f"wake word: {e}")
        if self.wake:
            self.wake.threshold = float(self.cfg.get("wake.threshold"))

    def _on_wake(self, score):
        log(f"wake word ({score:.2f})")
        self.emit("wake", score=round(float(score), 2))
        self.listen(preroll=self.wake.recent(), verify=self.wake.verify)

    # --------------------------------------------------------------- turns

    def toggle(self):
        with self.lock:
            state, utt = self.state, self.utt
        if state == "idle":
            self.listen()
        elif state == "listening" and utt:
            utt.stop_now()
        else:
            self.listen()  # barge-in: drop what it was doing, listen again

    def interrupt(self):
        with self.lock:
            self.turn += 1
            utt, self.utt = self.utt, None
        self.speaker.stop()
        self.claude.interrupt()
        if utt:
            self.mic.remove("listen")

    def cancel(self):
        self.interrupt()
        self.set_state("idle")
        self._end_media_pause()
        if self.wake:
            self.wake.paused = False

    def listen(self, follow_up=False, preroll=None, verify=False):
        self.interrupt()
        with self.lock:
            turn = self.turn
        self.set_state("listening")
        self.emit("listen", follow_up=follow_up)
        if self.cfg.get("listen.pause_media") and not follow_up and not self.paused_media:
            threading.Thread(target=self._start_media_pause, daemon=True).start()
        # Load whisper/Kokoro and boot Claude while you're still talking; all
        # three are ready by the time you stop.
        self.models.warm()
        threading.Thread(target=lambda: online() and self.claude.ensure(), daemon=True).start()
        if self.wake:
            self.wake.paused = True
        timeout = 4.0 if follow_up else float(self.cfg.get("listen.no_speech_timeout"))
        utt = Utterance(
            self.vad, int(self.cfg.get("listen.silence_ms")), timeout,
            float(self.cfg.get("listen.max_seconds")), self._mic_level,
            lambda samples: self._heard(turn, samples, verify),
            preroll=preroll,
        )
        with self.lock:
            self.utt = utt
        self.mic.add("listen", utt.feed)

    def _start_media_pause(self):
        paused = actions.pause_playing()
        with self.lock:
            self.paused_media = paused

    def _end_media_pause(self):
        with self.lock:
            paused, self.paused_media = self.paused_media, []
        if paused:
            actions.resume(paused)

    def _finish(self, turn):
        with self.lock:
            if turn != self.turn:
                return
        self.set_state("idle")
        self._end_media_pause()
        if self.wake:
            self.wake.reset()
            self.wake.paused = False

    def _heard(self, turn, samples, verify=False):
        with self.lock:
            if turn != self.turn:
                return
            self.utt = None
        self.mic.remove("listen")
        if samples is None:
            self.emit("heard", text="")
            return self._finish(turn)
        self.set_state("thinking")
        t0 = time.monotonic()
        text = self.models.stt().transcribe(samples, self.cfg.get("listen.vocabulary"))
        log(f"stt {time.monotonic() - t0:.2f}s ({len(samples) / 16000:.1f}s audio): {text!r}")
        with self.lock:
            if turn != self.turn:
                return
        if verify:
            # "Jarvis" mode: the detector runs hot, so the transcript has to
            # actually contain the name near the start.
            m = WAKE_WORD.search(" ".join(text.split()[:5]))
            if not m:
                log(f"false wake, ignoring {text!r}")
                self.emit("heard", text="")
                self.emit("tool", text="")
                return self._finish(turn)
            # Anything before the name is pre-roll chatter, not the request.
            text = text[m.start():] if m.start() < 40 else text
            rest = text[m.end() - m.start():].strip(" ,.!?")
            if not rest:
                # Said "Jarvis" and paused: keep listening for the command.
                return self.listen(follow_up=True)
        if not text:
            self.emit("heard", text="")
            return self._finish(turn)
        self.handle_text(turn, text)

    def ask_text(self, text):
        """Typed or injected request, same path as a spoken one."""
        self.interrupt()
        self.models.warm()
        with self.lock:
            turn = self.turn
        self.set_state("thinking")
        threading.Thread(target=self.handle_text, args=(turn, text), daemon=True).start()

    def say(self, text):
        """Speak a line directly (voice preview in settings)."""
        self.interrupt()
        self.models.warm()
        with self.lock:
            turn = self.turn
        self.emit("listen", follow_up=False)
        self.emit("reply", text=text, done=True)

        def go():
            self._speak_and_wait(turn, text)
            self._finish(turn)
        threading.Thread(target=go, daemon=True).start()

    def handle_text(self, turn, text):
        self.emit("heard", text=text)
        t0 = time.monotonic()
        m = fastpath.match(text, self.cfg.get("search.engine"))
        if m:
            log(f"fast path: {text!r}")
            self._run_fast(turn, m)
            log(f"fast path done in {(time.monotonic() - t0) * 1000:.0f} ms")
            return
        self._run_brain(turn, text, t0)

    def _run_fast(self, turn, m):
        if m.control == "cancel":
            self.emit("reply", text="", done=True)
            return self._finish(turn)
        if m.control == "reset":
            self.claude.reset()
            self.local.history.clear()
        elif m.control == "set":
            self.set_config(*m.arg)
        elif m.control == "settings":
            self.emit("settings", open=True)
        if m.run:
            try:
                m.run()
            except Exception as e:
                log(f"fast action failed: {e!r}")
                self.emit("error", text=str(e))
        if m.keeps_media_paused:
            with self.lock:
                self.paused_media = []
        self.emit("reply", text=m.reply, done=True)
        if m.reply and self.cfg.get("voice.acks"):
            self._speak_and_wait(turn, m.reply)
        self._finish(turn)

    def _speak_and_wait(self, turn, text):
        self.speaker.say(text)
        self._wait_speech(turn)

    def _wait_speech(self, turn):
        while True:
            with self.lock:
                if turn != self.turn:
                    return False
            if self.player.busy:
                self.set_state("speaking")
            if not self.speaker.busy():
                return True
            time.sleep(0.03)

    def _run_brain(self, turn, text, t0):
        cancelled = lambda: turn != self.turn
        marks = {}

        def on_text(delta):
            if cancelled():
                return
            if "first_text" not in marks and delta.strip():
                marks["first_text"] = time.monotonic() - t0
            self.emit("reply", delta=delta)
            self.speaker.feed(delta)

        def on_tool(name, inp):
            if cancelled():
                return
            label = tool_label(name, inp)
            # Each tool arrives twice (block start, then with its input);
            # only re-emit when the label actually changed.
            if label and label != marks.get("last_tool"):
                marks["last_tool"] = label
                self.emit("tool", text=label)
            if not self.player.busy:
                self.set_state("thinking")

        # A watcher flips the orb between thinking and speaking while the
        # brain streams, since audio starts mid-reply.
        done = threading.Event()

        def watch():
            while not done.is_set() and not cancelled():
                if self.player.busy:
                    marks.setdefault("first_audio", time.monotonic() - t0)
                    self.set_state("speaking")
                elif self.state == "speaking":
                    self.set_state("thinking")
                time.sleep(0.05)
        threading.Thread(target=watch, daemon=True).start()

        reply = ""
        try:
            if not online():
                raise BrainError("offline")
            reply = self.claude.ask(text, on_text, on_tool, cancelled)
        except BrainError as e:
            log(f"claude unavailable: {e}")
            if cancelled():
                done.set()
                return
            try:
                reply = self.local.ask(text, on_text, on_tool, cancelled)
            except Exception as e2:
                log(f"local brain failed: {e2!r}")
                reply = "I can't reach Claude or a local model right now."
                on_text(reply)
        except Exception as e:
            log(f"brain crashed: {e!r}")
            reply = "Something went wrong on my end."
            on_text(reply)
        finally:
            done.set()
        if cancelled():
            return
        self.speaker.flush()
        self.emit("reply", text=reply, done=True)
        if not self._wait_speech(turn):
            return
        first_audio = marks.get("first_audio") or (self.player.started_at - t0 if self.player.started_at > t0 else -1)
        log("turn: first text {:.2f}s, first audio {:.2f}s, total {:.2f}s".format(
            marks.get("first_text", -1), first_audio, time.monotonic() - t0))
        if self.cfg.get("listen.follow_up") and reply.strip().endswith("?"):
            self.listen(follow_up=True)
        else:
            self._finish(turn)

    # --------------------------------------------------------------- config

    def set_config(self, key, value):
        self.cfg.set(key, value)
        log(f"set {key} = {self.cfg.get(key)!r}")
        if key.startswith("wake."):
            self._apply_wake()
        if key == "listen.whisper_model":
            self.models.set_whisper(value)
        self.emit("config", config=self.cfg.data, options=self.options())

    @staticmethod
    def options():
        return {"wake_models": WAKE_MODELS, "voices": VOICES, "brain_models": BRAIN_MODELS,
                "whisper_models": ["tiny.en", "base.en", "small.en"],
                "search_engines": ["google", "kagi", "duckduckgo", "brave"],
                "positions": ["bottom", "center", "top"]}

    def status(self):
        pids = {"daemon": os.getpid()}
        if self.orb_proc and self.orb_proc.poll() is None:
            pids["orb"] = self.orb_proc.pid
        if self.claude.running():
            pids["claude"] = self.claude.proc.pid
        mem = {k: rss_mb(p) for k, p in pids.items()}
        return {"state": self.state, "wake": bool(self.wake), "claude_running": self.claude.running(),
                "models_loaded": self.models.loaded,
                "model": self.cfg.get("brain.model"), "rss_mb": mem, "online": online()}

    # ------------------------------------------------------------------ orb

    def _orb_loop(self):
        qml = ROOT / "orb" / "shell.qml"
        fails = 0
        while self.running and self.orb_enabled:
            t0 = time.monotonic()
            self.orb_proc = subprocess.Popen(
                ["quickshell", "-p", str(qml)],
                stdout=subprocess.DEVNULL, stderr=open(STATE_DIR / "orb.log", "ab"),
                env={**os.environ, "JARVIS_SOCKET": str(SOCKET)},
            )
            self.orb_proc.wait()
            if not self.running:
                break
            fails = fails + 1 if time.monotonic() - t0 < 10 else 0
            log(f"orb exited ({self.orb_proc.returncode}), restarting")
            time.sleep(min(30, 1 + fails * 3))

    # --------------------------------------------------------------- socket

    def serve(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if SOCKET.exists():
            try:
                s = socket.socket(socket.AF_UNIX)
                s.connect(str(SOCKET))
                s.close()
                raise SystemExit("jarvis is already running")
            except ConnectionRefusedError:
                SOCKET.unlink()
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(SOCKET))
        os.chmod(SOCKET, 0o600)
        srv.listen(16)

        def shutdown(*_):
            self.running = False
            self.claude.stop()
            if self.orb_proc and self.orb_proc.poll() is None:
                self.orb_proc.terminate()
            try:
                SOCKET.unlink()
            except OSError:
                pass
            os._exit(0)
        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        if self.orb_enabled:
            threading.Thread(target=self._orb_loop, daemon=True, name="orb").start()
        log(f"listening on {SOCKET}")
        self._shutdown = shutdown
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self._client, args=(conn,), daemon=True).start()

    def _client(self, conn):
        f = conn.makefile("r")
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    msg = {"cmd": line}  # plain-text commands work too: `echo toggle | nc -U`
                reply = self._command(conn, msg)
                if reply is not None:
                    conn.sendall((json.dumps(reply) + "\n").encode())
        except OSError:
            pass

    def _command(self, conn, msg):
        cmd = msg.get("cmd")
        if cmd == "subscribe":
            self.hub.add(conn)
            return {"ev": "hello", "state": self.state, "config": self.cfg.data, "options": self.options()}
        if cmd == "toggle":
            self.toggle()
        elif cmd == "listen":
            self.listen()
        elif cmd == "release":
            with self.lock:
                utt = self.utt
            if utt:
                utt.stop_now()
        elif cmd == "cancel":
            self.cancel()
        elif cmd == "say":
            self.say(msg.get("text", ""))
        elif cmd == "ask":
            self.ask_text(msg.get("text", ""))
        elif cmd == "inject":
            # Test hook: run a recording through the pipeline as if spoken.
            samples = np.load(msg["path"]).astype(np.float32)
            self.interrupt()
            with self.lock:
                turn = self.turn
            self.set_state("listening")
            threading.Thread(target=self._heard, args=(turn, samples), daemon=True).start()
        elif cmd == "set":
            try:
                self.set_config(msg["key"], msg["value"])
            except (KeyError, ValueError) as e:
                return {"ok": False, "error": f"bad setting: {e}"}
        elif cmd == "reload":
            self.cfg.reload()
            self._apply_wake()
            self.emit("config", config=self.cfg.data, options=self.options())
        elif cmd == "reset":
            self.claude.reset()
            self.local.history.clear()
        elif cmd == "settings":
            self.emit("settings", open=msg.get("open", "toggle"))
        elif cmd == "status":
            return {"ok": True, **self.status()}
        elif cmd == "config":
            return {"ok": True, "config": self.cfg.data, "options": self.options()}
        elif cmd == "quit":
            threading.Thread(target=self._shutdown, daemon=True).start()
        else:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        return {"ok": True}


def run(orb=True):
    Daemon(orb=orb).serve()

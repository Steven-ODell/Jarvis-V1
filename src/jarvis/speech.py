"""Speech in (whisper, Silero VAD, openWakeWord) and speech out (Kokoro)."""

import re
import threading
import time
from pathlib import Path

import numpy as np

from . import audio
from .config import MODELS


# ------------------------------------------------------------------ STT ---

class STT:
    def __init__(self, model_name="base.en"):
        from faster_whisper import WhisperModel
        self.model_name = model_name
        kw = dict(device="cpu", compute_type="int8", download_root=str(MODELS / "whisper"), cpu_threads=8)
        try:
            # Without local_files_only, huggingface_hub phones home on every
            # load to check for updates; that turned a 0.3 s load into 9 s.
            self.model = WhisperModel(model_name, local_files_only=True, **kw)
        except Exception:
            self.model = WhisperModel(model_name, **kw)

    def transcribe(self, samples, vocabulary=()):
        # The vocabulary goes in as a fake previous sentence. Whisper leans
        # toward spellings it has just "heard", so GitHub stops coming out as
        # gethub and Omarchy stops coming out as Amarky.
        prompt = ", ".join(vocabulary) + "." if vocabulary else None
        segments, _ = self.model.transcribe(
            samples, language="en", beam_size=1, without_timestamps=True,
            initial_prompt=prompt, condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        # Whisper's stock hallucinations on near-silence.
        if text.lower().strip(" .!") in ("", "you", "thank you", "thanks for watching", "bye"):
            return ""
        return text


# ------------------------------------------------------------- model pool ---

class Models:
    """Whisper + Kokoro, loaded when a turn starts and dropped when idle.

    Together they're ~800 MB. Loading takes ~0.5 s, which happens while
    you're still talking (the hotkey kicks it off), so keeping them resident
    between conversations buys nothing. After keep_s idle seconds they're
    freed and malloc_trim hands the pages back to the kernel.
    """

    def __init__(self, whisper_name, keep_s, is_idle, log):
        self.whisper_name = whisper_name
        self.keep_s = keep_s
        self.is_idle = is_idle
        self.log = log
        self.lock = threading.Lock()
        self._stt = None
        self._tts = None
        self.stt_ready = threading.Event()
        self.tts_ready = threading.Event()
        self.loading = set()
        self.last_used = time.monotonic()
        threading.Thread(target=self._reaper, daemon=True, name="model-reaper").start()

    def warm(self):
        """Start loading anything that isn't loaded. Returns immediately."""
        with self.lock:
            self.last_used = time.monotonic()
            if self._stt is None and "stt" not in self.loading:
                self.loading.add("stt")
                threading.Thread(target=self._load_stt, daemon=True).start()
            if self._tts is None and "tts" not in self.loading:
                self.loading.add("tts")
                threading.Thread(target=self._load_tts, daemon=True).start()

    def _load_stt(self):
        t0 = time.monotonic()
        try:
            m = STT(self.whisper_name)
            with self.lock:
                self._stt = m
            self.stt_ready.set()
            self.log(f"whisper {self.whisper_name} loaded in {time.monotonic() - t0:.2f}s")
        finally:
            with self.lock:
                self.loading.discard("stt")

    def _load_tts(self):
        t0 = time.monotonic()
        try:
            m = TTS()
            m.synth("Ready.", "am_michael", 1.0)  # graph warm-up
            with self.lock:
                self._tts = m
            self.tts_ready.set()
            self.log(f"kokoro loaded in {time.monotonic() - t0:.2f}s")
        finally:
            with self.lock:
                self.loading.discard("tts")

    def stt(self):
        self.warm()
        self.stt_ready.wait(60)
        self.last_used = time.monotonic()
        return self._stt

    def tts(self):
        self.warm()
        self.tts_ready.wait(60)
        self.last_used = time.monotonic()
        return self._tts

    def set_whisper(self, name):
        with self.lock:
            self.whisper_name = name
            self._stt = None
            self.stt_ready.clear()

    def unload(self):
        import ctypes
        import gc
        with self.lock:
            if self.loading or (self._stt is None and self._tts is None):
                return False
            self._stt = self._tts = None
            self.stt_ready.clear()
            self.tts_ready.clear()
        gc.collect()
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except OSError:
            pass
        return True

    @property
    def loaded(self):
        return [n for n, m in (("whisper", self._stt), ("kokoro", self._tts)) if m is not None]

    def _reaper(self):
        while True:
            time.sleep(10)
            if self.is_idle() and time.monotonic() - self.last_used > self.keep_s():
                if self.unload():
                    self.log("speech models unloaded (idle)")


# ------------------------------------------------------------ endpointing ---

class Utterance:
    """Collects one spoken request from the mic and decides when it's over.

    Hotkey turns: wait for speech, keep 480 ms from before it started so the
    first syllable isn't clipped, end on trailing silence.

    Wake-word turns (preroll given) are different, because the wake word
    itself is speech and you usually pause for a beat after it:
      - the pre-roll (the audio holding "Hey Jarvis") is kept for whisper but
        doesn't count as the command starting;
      - speech in the first `tail_s` after the trigger is the end of the wake
        word, not the command;
      - silence during the first `grace_s` after the trigger doesn't count,
        and silence can't end the turn before the command has started;
      - no command within no_speech_timeout ends it with nothing.
    """

    def __init__(self, vad, silence_ms, no_speech_timeout, max_seconds, on_level, on_done,
                 preroll=None, grace_s=1.2, tail_s=0.35, clock=time.monotonic):
        self.vad = vad
        self.vad.reset_states()
        self.silence_blocks = max(1, int(silence_ms / 1000 * audio.MIC_RATE / audio.MIC_BLOCK))
        self.no_speech_timeout = no_speech_timeout
        self.max_seconds = max_seconds
        self.on_level = on_level
        self.on_done = on_done
        self.clock = clock
        self.blocks = []
        self.pre = []
        self.started = False
        self.quiet = 0
        self.t0 = clock()
        self.finished = False
        self.lock = threading.Lock()
        self.wake = preroll is not None and len(preroll) > 0
        self.grace_s = grace_s
        self.tail_s = tail_s
        self.command_heard = False
        self._talking = False
        if self.wake:
            self.blocks.append(preroll)
            self.started = True

    def feed(self, block):
        with self.lock:
            if self.finished:
                return
            self.on_level(audio.level_of(block))
            score = self.vad.predict((block * 32767).astype(np.int16), frame_size=480)
            # Hysteresis, as Silero recommends: 0.5 to start speech, but once
            # talking only a drop below 0.35 counts as silence. Trailing soft
            # syllables ("per second?") score ~0.4 and were ending turns early.
            speech = score > (0.35 if self._talking else 0.5)
            self._talking = speech
            elapsed = self.clock() - self.t0
            if self.wake:
                return self._feed_wake(block, speech, elapsed)
            if not self.started:
                self.pre.append(block)
                self.pre = self.pre[-8:]  # 480 ms: soft onsets ("Roughly") start below the VAD's threshold
                if speech:
                    self.started = True
                    self.blocks.extend(self.pre)
                elif elapsed > self.no_speech_timeout:
                    return self._finish(None)
                return
            self.blocks.append(block)
            self.quiet = 0 if speech else self.quiet + 1
            if self.quiet >= self.silence_blocks or self._too_long():
                self._finish(self._audio())

    def _feed_wake(self, block, speech, elapsed):
        self.blocks.append(block)
        if speech and elapsed > self.tail_s:
            self.command_heard = True
        # Silence inside the grace period doesn't count toward end-of-speech,
        # so the silence timer only starts once the beat is over.
        self.quiet = 0 if speech or elapsed < self.grace_s else self.quiet + 1
        if self._too_long():
            return self._finish(self._audio())
        if not self.command_heard:
            if elapsed > self.no_speech_timeout:
                self._finish(None)
            return
        if elapsed >= self.grace_s and self.quiet >= self.silence_blocks:
            self._finish(self._audio())

    def _too_long(self):
        return self.clock() - self.t0 > self.max_seconds

    def stop_now(self):
        """Hotkey pressed again mid-sentence: take what we have."""
        with self.lock:
            if not self.finished:
                has_speech = self.command_heard if self.wake else self.started
                self._finish(self._audio() if has_speech else None)

    def _audio(self):
        return np.concatenate(self.blocks) if self.blocks else None

    def _finish(self, samples):
        self.finished = True
        threading.Thread(target=self.on_done, args=(samples,), daemon=True).start()


class SileroVAD:
    """Silero VAD on onnxruntime, same model file openWakeWord bundles.

    Written out here rather than imported: `import openwakeword` drags in
    ~90 MB of dependencies, and the VAD is resident even with the wake word
    off.
    """

    def __init__(self):
        import importlib.util
        import onnxruntime as ort
        spec = importlib.util.find_spec("openwakeword")  # locates files, imports nothing
        path = Path(spec.origin).parent / "resources" / "models" / "silero_vad.onnx"
        so = ort.SessionOptions()
        so.inter_op_num_threads = 1
        so.intra_op_num_threads = 1
        self.model = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
        self.sr = np.array(16000, dtype=np.int64)
        self.reset_states()

    def reset_states(self):
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)

    def predict(self, x, frame_size=480):
        """x: int16-scaled samples. Mean speech probability over its frames."""
        scores = []
        for i in range(0, len(x) - frame_size + 1, frame_size):
            chunk = (x[i:i + frame_size] / 32767).astype(np.float32)[None, :]
            out, self._h, self._c = self.model.run(None, {"input": chunk, "h": self._h, "c": self._c, "sr": self.sr})
            scores.append(out[0][0])
        return float(np.mean(scores)) if scores else 0.0


def load_vad():
    return SileroVAD()


# --------------------------------------------------------------- wake word ---

class WakeWord:
    """Runs openWakeWord on the shared mic stream. Only exists while the wake
    word setting is on, so it costs nothing when you use the hotkey only."""

    CHUNK = 1280  # 80 ms, what openWakeWord's feature extractor steps by
    PREROLL_S = 1.6

    def __init__(self, model, threshold, on_wake):
        import collections
        import openwakeword
        from openwakeword.model import Model
        res = Path(openwakeword.__file__).parent / "resources" / "models"
        # There's no pretrained model for the bare word. The "hey jarvis"
        # model fires on "Jarvis" alone too, just less confidently, so
        # "jarvis" mode runs it at half the threshold and has the daemon
        # confirm the word in the transcript before acting.
        self.verify = model == "jarvis"
        self.mode = model
        if self.verify:
            model = "hey_jarvis"
        self.recent_blocks = collections.deque(maxlen=int(self.PREROLL_S * audio.MIC_RATE / audio.MIC_BLOCK))
        path = Path(model)
        if not path.exists():
            matches = sorted(res.glob(f"{model}_v*.onnx"))
            if not matches:
                raise FileNotFoundError(f"no wake word model named {model!r}")
            path = matches[-1]
        self.name = path.stem
        self.model = Model(wakeword_model_paths=[str(path)])
        self.threshold = threshold
        self.on_wake = on_wake
        self.buf = np.zeros(0, dtype=np.float32)
        self.cooldown_until = 0.0
        self.paused = False
        self.need_flush = False
        self.near_miss = 0.0
        self.on_near_miss = None

    def recent(self):
        return np.concatenate(self.recent_blocks) if self.recent_blocks else None

    def feed(self, block):
        self.recent_blocks.append(block)
        if self.paused:
            return
        if self.need_flush:
            # The model keeps ~2 s of spectrogram history internally. After a
            # pause that history still holds the last "Jarvis", which fires
            # again the moment we resume. Push silence through to clear it.
            self.need_flush = False
            silence = np.zeros(self.CHUNK, dtype=np.int16)
            for _ in range(30):
                self.model.predict(silence)
            self.model.reset()
            self.buf = np.zeros(0, dtype=np.float32)
        self.buf = np.concatenate([self.buf, block])
        while len(self.buf) >= self.CHUNK:
            chunk, self.buf = self.buf[:self.CHUNK], self.buf[self.CHUNK:]
            scores = self.model.predict((chunk * 32767).astype(np.int16))
            score = max(scores.values()) if scores else 0.0
            now = time.monotonic()
            threshold = self.threshold * (0.5 if self.verify else 1.0)
            if 0.08 < score < threshold:
                self.near_miss = max(self.near_miss, score)
            elif self.near_miss and self.on_near_miss:
                self.on_near_miss(self.near_miss)
                self.near_miss = 0.0
            if score >= threshold and now > self.cooldown_until:
                self.cooldown_until = now + 2.0
                self.model.reset()
                self.on_wake(score)

    def reset(self):
        # Runs on the daemon thread while feed() runs on the mic thread, so
        # only set a flag; feed() does the actual clearing.
        self.recent_blocks.clear()
        self.need_flush = True


# ------------------------------------------------------------------- TTS ---

_MD = [
    (re.compile(r"```.*?```", re.S), " "),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),
    (re.compile(r"https?://\S+"), "the link"),
    (re.compile(r"[*_#>|~]+"), ""),
    (re.compile(r"^\s*[-•]\s+", re.M), ""),
    (re.compile(r"\s+"), " "),
]


def speakable(text):
    """Strip the markdown and URLs Claude sometimes emits anyway."""
    for pat, rep in _MD:
        text = pat.sub(rep, text)
    return text.strip()


# Sentence end: . ! ? followed by space, or a newline. Decimal points ("3.5")
# and "e.g." don't split because they aren't followed by whitespace+capital.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])|\n+")


# A clause worth speaking on its own: 6+ chars ending at , ; : or a dash,
# or failing that, 45+ chars ending before a conjunction.
_CLAUSE = re.compile(r"^(.{6,}?[,;:\u2014])\s+|^(.{45,}?)\s+(?=(?:and|but|so|because|which|though|while)\s)")


class TTS:
    def __init__(self):
        from kokoro_onnx import Kokoro
        self.kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
        self.lock = threading.Lock()

    def synth(self, text, voice, speed):
        # b* voices are British; en-gb phonemes give them the accent, not
        # just the timbre ("schedule", "tomato", non-rhotic r's).
        lang = "en-gb" if voice.startswith("b") else "en-us"
        with self.lock:
            samples, _ = self.kokoro.create(text, voice=voice, speed=speed, lang=lang)
        return samples


class Speaker:
    """Turns a stream of text deltas into audio, sentence by sentence.

    Claude's reply arrives a few tokens at a time; waiting for the whole
    thing would add seconds. Each finished sentence is synthesized as soon as
    it completes while the previous one plays.
    """

    def __init__(self, tts, player, voice_cfg):
        self.tts = tts  # callable returning a loaded TTS (models load on demand)
        self.player = player
        self.voice_cfg = voice_cfg  # callable -> (voice, speed)
        self.buf = ""
        self.pending = []
        self.cv = threading.Condition()
        self.gen = 0
        self.synthing = False
        self.spoken = []
        self.last_feed = 0.0
        threading.Thread(target=self._worker, daemon=True, name="tts").start()
        threading.Thread(target=self._early_flush, daemon=True, name="tts-flush").start()

    def _early_flush(self):
        # A reply's last sentence has no whitespace after its period, so the
        # splitter can't see it end; it would wait for Claude's end-of-turn
        # event, which lands up to a second later. If the buffer ends like a
        # sentence and nothing new arrived for 200 ms, speak it now.
        while True:
            time.sleep(0.05)
            with self.cv:
                if (self.buf.strip() and time.monotonic() - self.last_feed > 0.2
                        and re.search(r"[.!?][\"')]?\s*$", self.buf)):
                    self._queue(self.buf)
                    self.buf = ""

    def feed(self, delta):
        with self.cv:
            self.last_feed = time.monotonic()
            self.buf += delta
            parts = _SENTENCE_END.split(self.buf)
            if len(parts) > 1:
                for p in parts[:-1]:
                    self._queue(p)
                self.buf = parts[-1]
            # Nothing queued or playing means the voice is waiting on us. A
            # long first sentence takes ~2 s to synthesize, so start on its
            # first clause instead.
            if not self.pending and not self.synthing and not self.player.busy:
                m = _CLAUSE.match(self.buf)
                if m:
                    self._queue(m.group(1) or m.group(2))
                    self.buf = self.buf[m.end():].lstrip()

    def say(self, text):
        self.feed(text)
        self.flush()

    def flush(self):
        with self.cv:
            if self.buf.strip():
                self._queue(self.buf)
            self.buf = ""

    def _queue(self, text):
        text = speakable(text)
        # Pure punctuation or a stray list number isn't worth a synth call.
        if len(re.sub(r"[^A-Za-z0-9]", "", text)) < 1:
            return
        self.pending.append((self.gen, text))
        self.cv.notify()

    def stop(self):
        with self.cv:
            self.gen += 1
            self.pending.clear()
            self.buf = ""
        self.player.stop()

    def busy(self):
        with self.cv:
            return bool(self.pending) or self.synthing or bool(self.buf.strip()) or self.player.busy

    def wait(self):
        """Block until everything fed so far has finished playing."""
        while True:
            with self.cv:
                idle = not self.pending and not self.synthing
            if idle and not self.player.busy:
                return
            time.sleep(0.05)

    def _worker(self):
        while True:
            with self.cv:
                while not self.pending:
                    self.cv.wait()
                gen, text = self.pending.pop(0)
                self.synthing = True
            try:
                voice, speed = self.voice_cfg()
                t0 = time.monotonic()
                samples = self.tts().synth(text, voice, speed)
                print(f"[tts] {time.monotonic() - t0:.2f}s for {len(samples) / 24000:.1f}s: {text[:50]!r}", flush=True)
                with self.cv:
                    if gen == self.gen:
                        self.spoken.append(text)
                        self.player.play(samples)
            except Exception as e:
                print(f"[tts] {e!r}", flush=True)
            finally:
                with self.cv:
                    self.synthing = False

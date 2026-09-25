"""Microphone in, speaker out, and a loudness number for the orb.

Both streams open only while something needs them. The mic stays open all the
time only when the wake word is on, since that is the one case where Jarvis
has to hear you without being asked first.
"""

import collections
import queue
import threading
import time

import numpy as np
import sounddevice as sd

MIC_RATE = 16000
# 60 ms. A multiple of Silero's 480-sample frame, and short enough that the
# orb's level feed looks continuous.
MIC_BLOCK = 960
TTS_RATE = 24000


def level_of(block):
    """0..1 loudness for animation: RMS on a dB scale, -55 dB floor."""
    rms = float(np.sqrt(np.mean(np.square(block)) + 1e-12))
    db = 20 * np.log10(rms + 1e-9)
    return float(np.clip((db + 55) / 45, 0.0, 1.0))


class Mic:
    """Shared input stream. Consumers register a callback; the stream runs
    while at least one consumer is registered."""

    def __init__(self):
        self.lock = threading.Lock()
        self.consumers = {}
        self.stream = None
        self.q = queue.Queue(maxsize=200)
        threading.Thread(target=self._pump, daemon=True, name="mic-pump").start()

    def _callback(self, indata, frames, t, status):
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # consumer fell behind; dropping beats blocking the audio thread

    def _pump(self):
        # Consumers run ONNX models, which is too slow for PortAudio's
        # realtime callback, so blocks are handed off to this thread.
        while True:
            block = self.q.get()
            with self.lock:
                consumers = list(self.consumers.values())
            for fn in consumers:
                try:
                    fn(block)
                except Exception as e:  # one bad consumer must not kill the mic
                    print(f"[mic] consumer error: {e!r}", flush=True)

    def add(self, name, fn):
        with self.lock:
            self.consumers[name] = fn
            if self.stream is None:
                self.stream = sd.InputStream(
                    samplerate=MIC_RATE, channels=1, dtype="float32",
                    blocksize=MIC_BLOCK, callback=self._callback,
                )
                self.stream.start()

    def remove(self, name):
        with self.lock:
            self.consumers.pop(name, None)
            if not self.consumers and self.stream is not None:
                self.stream.stop()
                self.stream.close()
                self.stream = None
                # Stale blocks from this session must not leak into the next.
                while not self.q.empty():
                    try:
                        self.q.get_nowait()
                    except queue.Empty:
                        break

    @property
    def active(self):
        return self.stream is not None


class Player:
    """Plays queued float32 chunks at 24 kHz and reports loudness while it
    does. stop() drops everything queued, which is how barge-in works."""

    def __init__(self, on_level=None):
        self.on_level = on_level
        self.lock = threading.Lock()
        self.chunks = collections.deque()
        self.pos = 0
        self.stream = None
        self.last_audio = 0.0
        self.idle = threading.Event()
        self.idle.set()
        self.started_at = 0.0  # when the current burst of audio was queued
        self._level_t = 0.0
        threading.Thread(target=self._closer, daemon=True, name="player-closer").start()

    def _callback(self, outdata, frames, t, status):
        out = np.zeros(frames, dtype=np.float32)
        filled = 0
        with self.lock:
            while filled < frames and self.chunks:
                chunk = self.chunks[0]
                take = min(frames - filled, len(chunk) - self.pos)
                out[filled:filled + take] = chunk[self.pos:self.pos + take]
                filled += take
                self.pos += take
                if self.pos >= len(chunk):
                    self.chunks.popleft()
                    self.pos = 0
            if filled:
                self.last_audio = time.monotonic()
            if not self.chunks:
                self.idle.set()
        outdata[:, 0] = out
        now = time.monotonic()
        if self.on_level and now - self._level_t > 0.03:
            self._level_t = now
            self.on_level(level_of(out[:filled]) if filled else 0.0)

    def play(self, audio):
        with self.lock:
            if self.idle.is_set():
                self.started_at = time.monotonic()
            self.chunks.append(np.asarray(audio, dtype=np.float32))
            self.idle.clear()
            if self.stream is None:
                self.stream = sd.OutputStream(
                    samplerate=TTS_RATE, channels=1, dtype="float32",
                    blocksize=720, callback=self._callback,
                )
                self.stream.start()

    def stop(self):
        with self.lock:
            self.chunks.clear()
            self.pos = 0
            self.idle.set()

    def wait(self, timeout=None):
        return self.idle.wait(timeout)

    @property
    def busy(self):
        return not self.idle.is_set()

    def _closer(self):
        # Close the output after a quiet second so PipeWire can suspend the
        # sink; an open stream playing silence keeps the codec powered.
        while True:
            time.sleep(0.5)
            with self.lock:
                quiet = not self.chunks and time.monotonic() - self.last_audio > 1.2
                if quiet and self.stream is not None:
                    stream, self.stream = self.stream, None
                else:
                    stream = None
            if stream is not None:
                stream.stop()
                stream.close()

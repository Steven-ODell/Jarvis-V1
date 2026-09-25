"""End-of-speech rules, driven by a scripted VAD and a fake clock.

Each fed block is 60 ms of mic audio; the script says whether the VAD calls
it speech.
"""

import threading

import numpy as np

from jarvis import audio
from jarvis.speech import Utterance

BLOCK_S = audio.MIC_BLOCK / audio.MIC_RATE  # 0.06


class ScriptedVAD:
    def __init__(self):
        self.next = False

    def reset_states(self):
        pass

    def predict(self, x, frame_size=480):
        return 0.9 if self.next else 0.1


def run(script, preroll=False, grace_s=1.2, silence_ms=800, timeout=5.0):
    """script: list of (is_speech, seconds). Returns (samples or None, seconds fed when it ended)."""
    vad = ScriptedVAD()
    now = [0.0]
    done = threading.Event()
    result = {}

    def on_done(samples):
        result["samples"] = samples
        done.set()

    utt = Utterance(vad, silence_ms, timeout, 20.0, lambda v: None, on_done,
                    preroll=np.ones(16000, np.float32) if preroll else None,
                    grace_s=grace_s, clock=lambda: now[0])
    block = np.zeros(audio.MIC_BLOCK, np.float32)
    for is_speech, seconds in script:
        for _ in range(round(seconds / BLOCK_S)):
            if utt.finished:
                break
            vad.next = is_speech
            now[0] += BLOCK_S
            utt.feed(block)
    assert done.wait(1), "utterance never ended"
    return result["samples"], round(now[0], 2)


def test_hotkey_ends_after_trailing_silence():
    samples, t = run([(False, 0.5), (True, 1.0), (False, 2.0)])
    assert samples is not None
    assert 2.2 <= t <= 2.4  # 0.5 wait + 1.0 speech + ~0.8 silence


def test_wake_pause_before_command_is_not_cut():
    # "Hey Jarvis" tail, a 1.5 s beat, then the command. Before the fix this
    # ended 0.8 s into the pause with only the wake word.
    samples, t = run([(True, 0.2), (False, 1.5), (True, 1.2), (False, 2.0)], preroll=True)
    assert samples is not None
    assert t > 2.9  # didn't end before the command finished (0.2 + 1.5 + 1.2)
    assert len(samples) > 16000 + 2.5 * audio.MIC_RATE  # pre-roll + pause + command


def test_wake_one_breath_waits_for_grace():
    # "Hey Jarvis stop" said fast: speech ends at 0.6 s, but the silence
    # timer only starts at the 1.2 s grace mark, so it ends near 2.0 s.
    samples, t = run([(True, 0.6), (False, 3.0)], preroll=True)
    assert samples is not None
    assert 1.9 <= t <= 2.1


def test_wake_hesitation_inside_grace_is_kept():
    # Starts the command, hesitates 0.9 s (longer than the 0.8 s silence
    # rule) across the grace mark, continues. Grace covers it.
    samples, t = run([(False, 0.4), (True, 0.3), (False, 0.9), (True, 1.0), (False, 2.0)], preroll=True)
    assert t > 2.6


def test_wake_without_command_times_out_empty():
    samples, t = run([(True, 0.2), (False, 6.0)], preroll=True)
    assert samples is None
    assert 5.0 <= t <= 5.2

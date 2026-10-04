"""Expression timeline shared by every face concept.

No bpy in here. A face is driven by the same small set of controls whatever
it looks like; each concept maps them onto its own geometry. Poses are
targets, and every control chases its target with a damped spring, so a
change of expression is always smooth no matter when it happens. That is
also how the live orb would run it: set a new target, let the springs
settle.
"""

import math
import random
import wave

import numpy as np

FPS = 30


def hex_rgb(h):
    """sRGB hex to linear RGB, which is what Blender colors want."""
    h = h.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return out


DEFAULTS = {
    "look_x": 0.0, "look_y": 0.0,      # gaze, -1..1
    "lid_L": 0.06, "lid_R": 0.06,      # upper lid closure, 0 open .. 1 shut
    "squint_L": 0.0, "squint_R": 0.0,  # lower lid raise, 1 = happy arcs
    "slant_L": 0.0, "slant_R": 0.0,    # lid slant, + angry .. - sad
    "brow_L": 0.0, "brow_R": 0.0,      # brow height, -1..1
    "worry_L": 0.0, "worry_R": 0.0,    # inner brow up (+) or down (-)
    "eye_size": 1.0,
    "mouth_open": 0.0, "smile": 0.1, "mouth_wide": 0.0, "mouth_skew": 0.0,
    "head_roll": 0.0, "head_yaw": 0.0, "head_pitch": 0.0,  # degrees
    "glow": 1.0,
    "col_r": 0.0, "col_g": 0.0, "col_b": 0.0,  # filled from the pose color
}


def both(name, v):
    return {name + "_L": v, name + "_R": v}


POSES = {
    "idle": dict(color="#b07cf5"),
    "listening": dict(
        color="#6ee7ff", eye_size=1.08, **both("lid", -0.04), **both("brow", 0.3),
        head_roll=5, head_pitch=-3, smile=0.15),
    "thinking": dict(
        color="#d07cff", look_x=0.55, look_y=0.5, **both("lid", 0.18), **both("squint", 0.25),
        brow_L=0.45, brow_R=-0.15, worry_R=-0.3, mouth_skew=0.5, smile=-0.05,
        mouth_wide=-0.2, head_roll=-6, head_yaw=8),
    "speaking": dict(color="#c084fc", smile=0.3, **both("brow", 0.15), **both("lid", 0.04)),
    "happy": dict(
        color="#f0abfc", **both("squint", 0.85), **both("lid", 0.0), smile=1.0, mouth_open=0.3,
        mouth_wide=0.35, **both("brow", 0.35), head_roll=6, head_pitch=-4, glow=1.25),
    "confused": dict(
        color="#a78bfa", brow_L=0.75, brow_R=-0.35, worry_R=-0.4, lid_R=0.3, lid_L=-0.05,
        slant_R=0.3, mouth_skew=-0.7, smile=-0.25, mouth_wide=-0.2, head_roll=-12,
        head_yaw=-6, look_x=-0.2, look_y=0.15),
    "sad": dict(
        color="#7c8cff", **both("lid", 0.35), **both("slant", -0.6), **both("worry", 0.8),
        **both("brow", -0.1), look_y=-0.45, smile=-0.7, head_pitch=8, head_roll=4, glow=0.7),
    "surprised": dict(
        color="#c7f9ff", eye_size=1.3, **both("lid", -0.25), **both("brow", 1.0),
        mouth_open=0.7, mouth_wide=-0.55, smile=0.0, head_pitch=-6, glow=1.35),
    "sleepy": dict(
        color="#6d3fd9", **both("lid", 0.93), look_y=-0.3, **both("brow", -0.25), smile=0.0,
        head_pitch=10, head_roll=-5, glow=0.35),
}

# The reel: every pose once, talking with a real Jarvis line in the middle.
SCRIPT = [
    ("idle", 2.2), ("listening", 1.8), ("thinking", 2.4), ("speaking", None),
    ("happy", 1.8), ("confused", 1.9), ("sad", 1.9), ("surprised", 1.6),
    ("sleepy", 2.6), ("idle", 1.4),
]
SPEECH_LEAD = 0.25  # seconds into the speaking pose before the voice starts

# (omega, damping ratio) per control. Eyes are quick, the head is heavy and
# overshoots a touch, color drifts.
SPRINGS = [
    (("look_",), (30, 1.0)),
    (("lid_", "squint_", "slant_", "eye_size"), (20, 0.9)),
    (("brow_", "worry_"), (15, 0.85)),
    (("mouth_open",), (38, 1.0)),
    (("smile", "mouth_"), (16, 0.9)),
    (("head_",), (7, 0.62)),
    (("glow", "col_"), (6, 1.0)),
]


def spring_for(name):
    for prefixes, s in SPRINGS:
        if name.startswith(prefixes):
            return s
    return (12, 1.0)


def pose_target(name):
    t = dict(DEFAULTS)
    p = dict(POSES[name])
    r, g, b = hex_rgb(p.pop("color"))
    t.update(p)
    t["col_r"], t["col_g"], t["col_b"] = r, g, b
    return t


def speech_envelope(path, fps=FPS):
    """Mouth-open curve from a wav: RMS per frame, gated and normalized."""
    w = wave.open(path)
    sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    hop = sr // fps
    n = len(a) // hop
    rms = np.sqrt(np.mean(a[:n * hop].reshape(n, hop) ** 2, axis=1))
    env = np.clip((rms - 0.01) / (np.percentile(rms, 95) - 0.01), 0, 1) ** 0.7
    return env, len(a) / sr


def blink_curve(dt):
    """0 -> 1 -> 0 over 0.17 s: shut fast, open slower."""
    if dt < 0 or dt > 0.17:
        return 0.0
    if dt < 0.06:
        return math.sin(dt / 0.06 * math.pi / 2)
    return math.cos((dt - 0.06) / 0.11 * math.pi / 2) ** 2


def build(wav=None, seed=7, fps=FPS):
    """Returns (frames, segments, speech_start_s).

    frames: list of control dicts, one per frame.
    segments: (pose, first_frame, last_frame) for picking stills.
    """
    rng = random.Random(seed)
    env, speech_len = (speech_envelope(wav, fps) if wav else (np.zeros(1), 3.0))

    segs, t = [], 0.0
    speech_start = None
    for pose, hold in SCRIPT:
        if hold is None:
            hold = speech_len + SPEECH_LEAD + 0.5
            speech_start = t + SPEECH_LEAD
        segs.append((pose, t, t + hold))
        t += hold
    total = int(round(t * fps))

    # Blinks: random gaps, plus one at most pose changes (people blink when
    # they shift attention).
    blinks, bt = [], 0.8
    while bt < t:
        blinks.append(bt)
        bt += rng.uniform(2.2, 4.8)
    for _, s, _ in segs[1:]:
        if rng.random() < 0.6:
            blinks.append(s + 0.05)
    # Saccades: small gaze hops while idle, listening or talking.
    sacc, st = [], 0.0
    while st < t:
        sacc.append((st, rng.uniform(-0.14, 0.14), rng.uniform(-0.08, 0.08)))
        st += rng.uniform(0.6, 1.9)

    names = list(DEFAULTS)
    pos = pose_target(segs[0][0])
    vel = {k: 0.0 for k in names}
    frames, out_segs = [], []
    sub = 8
    dt = 1 / fps / sub
    for f in range(total):
        tm = f / fps
        si = max(i for i, (_, s, _) in enumerate(segs) if s <= tm + 1e-9)
        pose = segs[si][0]
        tgt = pose_target(pose)

        if pose in ("idle", "listening", "speaking"):
            sx, sy = next((x, y) for (s0, x, y) in reversed(sacc) if s0 <= tm)
            tgt["look_x"] += sx
            tgt["look_y"] += sy
        if pose == "thinking":
            tgt["look_x"] += 0.12 * math.cos(tm * 1.3)
            tgt["look_y"] += 0.10 * math.sin(tm * 1.7)
        talk = 0.0
        if pose == "speaking" and speech_start is not None:
            i = int((tm - speech_start) * fps)
            if 0 <= i < len(env):
                talk = float(env[i])
            tgt["mouth_open"] = 0.85 * talk
            tgt["mouth_wide"] = 0.25 * math.sin(tm * 9.0) * talk
            tgt["brow_L"] += 0.25 * talk
            tgt["brow_R"] += 0.25 * talk
            tgt["head_pitch"] += -2.5 * talk

        for k in names:
            w, z = spring_for(k)
            x, v = pos[k], vel[k]
            for _ in range(sub):
                v += (w * w * (tgt[k] - x) - 2 * z * w * v) * dt
                x += v * dt
            pos[k], vel[k] = x, v

        out = dict(pos)
        # Overlays that ride on top of the springs.
        breath = 4.5 if pose != "sleepy" else 6.5
        out["head_pitch"] += (0.8 if pose != "sleepy" else 1.6) * math.sin(2 * math.pi * tm / breath)
        out["glow"] *= 1 + 0.04 * math.sin(2 * math.pi * tm / breath)
        b = max((blink_curve(tm - b0) for b0 in blinks), default=0.0)
        if pose != "sleepy":
            for s in ("L", "R"):
                out["lid_" + s] += (1 - out["lid_" + s]) * b
        out["blink"] = b
        out["talk"] = talk
        out["time"] = tm
        frames.append(out)

    for pose, s, e in segs:
        out_segs.append((pose, int(s * fps), int(e * fps) - 1))
    return frames, out_segs, speech_start


if __name__ == "__main__":
    import sys
    fr, sg, sp = build(sys.argv[1] if len(sys.argv) > 1 else None)
    print(len(fr), "frames", sp, sg)

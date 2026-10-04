"""Flat eye and mouth shapes as morphable meshes.

Every shape is a band: for each x column there is a top and a bottom edge.
Rounded rectangles, circles, lid cuts, happy arcs and open mouths are all
bands over the same columns, so blending two shapes is just blending their
top/bottom numbers and the morph never tears. Each shape becomes a shape
key, which also exports to glTF as a morph target for the live orb.
"""

import math

from common import mesh_from

N = 41  # columns


def columns():
    # Cosine spacing packs columns into the ends, where the corners curve.
    return [-math.cos(math.pi * i / (N - 1)) for i in range(N)]


def rr_top(x, h=1.15, r=0.55):
    ax = abs(x)
    if ax <= 1 - r:
        return h
    return h - r + math.sqrt(max(0.0, r * r - (ax - (1 - r)) ** 2))


def clamp_band(top, bot, gap=0.02):
    return [max(t, b + gap) for t, b in zip(top, bot)], bot


# --- eye shapes, local coords: x in -1..1, +x is the outer corner ----------

def eye_shapes():
    xs = columns()
    base_t = [rr_top(x) for x in xs]
    base_b = [-t for t in base_t]
    s = {"Basis": (xs, base_t, base_b)}

    # Shut: a thin line that sags a little, like a content closed eye.
    c = [-0.32 - 0.12 * (1 - x * x) for x in xs]
    th = [0.035 + 0.06 * math.sqrt(1 - x * x) for x in xs]
    s["close"] = (xs, [a + b for a, b in zip(c, th)], [a - b for a, b in zip(c, th)])

    # Half lid: flat cut through the middle (sleepy, unimpressed).
    s["lid_flat"] = (xs, *clamp_band([min(t, 0.12) for t in base_t], base_b))

    # Happy: an upturned arc, the bottom pushed up into the eye.
    arc_t = [-0.25 + 1.35 * math.sqrt(1 - x * x) ** 0.9 for x in xs]
    arc_th = [0.1 + 0.5 * math.sqrt(1 - x * x) for x in xs]
    s["happy"] = (xs, arc_t, [a - b for a, b in zip(arc_t, arc_th)])

    # Lid slants. Sad droops at the outer corner, angry at the inner one.
    s["sad"] = (xs, *clamp_band([min(t, 0.5 - 0.8 * x) for t, x in zip(base_t, xs)], base_b))
    s["angry"] = (xs, *clamp_band([min(t, 0.5 + 0.8 * x) for t, x in zip(base_t, xs)], base_b))

    # Round: surprised.
    rt = [1.2 * math.sqrt(max(0.0, 1 - x * x)) for x in xs]
    s["round"] = (xs, rt, [-t for t in rt])
    return s


# --- mouth shapes: x in -1..1 ----------------------------------------------

def mouth_shapes():
    xs = columns()
    th = [0.035 + 0.09 * math.sqrt(1 - x * x) ** 0.5 for x in xs]
    base_t, base_b = th, [-t for t in th]
    s = {"Basis": (xs, base_t, base_b)}

    def shifted(d):
        return (xs, [t + dy for t, dy in zip(base_t, d)], [b + dy for b, dy in zip(base_b, d)])

    s["smile"] = shifted([0.42 * x * x - 0.12 for x in xs])
    s["frown"] = shifted([-0.34 * x * x + 0.1 for x in xs])
    s["skew"] = shifted([0.16 * x + 0.22 * max(0.0, x) ** 2 - 0.04 for x in xs])
    # Open: mostly the bottom drops, like a jaw.
    sq = [math.sqrt(1 - x * x) for x in xs]
    s["open"] = (xs, [t + 0.1 * q for t, q in zip(base_t, sq)], [b - 0.75 * q for b, q in zip(base_b, sq)])
    s["narrow"] = ([0.5 * x for x in xs], base_t, base_b)
    s["wide"] = ([1.25 * x for x in xs], base_t, base_b)
    return s


def band_object(name, shapes, z=0.0):
    xs, top, bot = shapes["Basis"]
    verts = [(x, t, z) for x, t in zip(xs, top)] + [(x, b, z) for x, b in zip(xs, bot)]
    faces = [(i, i + 1, N + i + 1, N + i) for i in range(N - 1)]
    ob = mesh_from(name, verts, faces)
    ob.shape_key_add(name="Basis")
    for key, (kx, kt, kb) in shapes.items():
        if key == "Basis":
            continue
        sk = ob.shape_key_add(name=key)
        sk.slider_min = -1.0
        for i in range(N):
            sk.data[i].co = (kx[i], kt[i], z)
            sk.data[N + i].co = (kx[i], kb[i], z)
    return ob


def key_path(name):
    return f'key_blocks["{name}"].value'


def clamp01(v):
    return min(1.0, max(0.0, v))


def eye_weights(c, s):
    """Controls -> eye shape key weights for side s ("L" or "R")."""
    lid = c["lid_" + s]
    li = clamp01(lid)
    return {
        "lid_flat": li * 2 if li < 0.5 else 2 - li * 2,
        "close": clamp01(li * 2 - 1),
        "happy": clamp01(c["squint_" + s]),
        "sad": clamp01(-c["slant_" + s] + 0.6 * c["worry_" + s]),
        "angry": clamp01(c["slant_" + s] - 0.6 * c["worry_" + s]),
        "round": clamp01((c["eye_size"] - 1) * 2.5),
    }


def mouth_weights(c):
    return {
        "smile": clamp01(c["smile"]),
        "frown": clamp01(-c["smile"]),
        "open": clamp01(c["mouth_open"]),
        "narrow": clamp01(-c["mouth_wide"]),
        "wide": clamp01(c["mouth_wide"]),
        "skew": max(-1.0, min(1.0, c["mouth_skew"])),
    }

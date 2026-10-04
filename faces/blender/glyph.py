"""Concept: glyph. A flat robot display face, two morphing eyes and a
mouth line, neon on black. The most robot of the set and the cheapest to
run live: it could be a QML shader with no assets at all."""

import math

import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common
from common import empty, emission_material
from shapes2d import band_object, eye_shapes, mouth_shapes, eye_weights, mouth_weights, key_path

P = {}


def build():
    common.camera(loc=(0, 0, 10), ortho=2.3)
    mat = emission_material("Neon", strength=2.4, scanlines=0.35)
    P["mat"] = mat
    root = empty("Face")
    P["root"] = root
    for s, side in (("L", 1), ("R", -1)):
        e = band_object("Eye" + s, eye_shapes())
        e.parent = root
        e.data.materials.append(mat)
        P["eye" + s] = e
    m = band_object("Mouth", mouth_shapes())
    m.parent = root
    m.data.materials.append(mat)
    P["mouth"] = m


def drive(bk, c):
    root = P["root"]
    bk.set(root, "rotation_euler", (0, 0, math.radians(-c["head_roll"])))
    bk.set(root, "location", (c["head_yaw"] * 0.012, -c["head_pitch"] * 0.01, 0))
    for s, side in (("L", 1), ("R", -1)):
        e = P["eye" + s]
        # Screen-left eye is the face's right. Outer corner points away
        # from the middle, so the left one is mirrored.
        sx = 1 if s == "L" else -1
        wide = 1 - 0.6 * min(c["lid_" + s], 0)
        persp = 1 + 0.08 * c["look_x"] * sx
        size = 0.25 * c["eye_size"] * persp
        bk.set(e, "location", (sx * 0.6 + c["look_x"] * 0.12, 0.14 + c["look_y"] * 0.09 + c["brow_" + s] * 0.05, 0))
        bk.set(e, "scale", (sx * size * 0.95, size * wide * (1 + 0.08 * c["brow_" + s]), 1))
        for k, v in eye_weights(c, s).items():
            bk.set(e.data.shape_keys, key_path(k), v)
    m = P["mouth"]
    bk.set(m, "location", (c["look_x"] * 0.05, -0.43 + c["look_y"] * 0.03, 0))
    bk.set(m, "scale", (0.18, 0.18, 1))
    for k, v in mouth_weights(c).items():
        bk.set(m.data.shape_keys, key_path(k), v)
    nt = P["mat"].node_tree
    bk.set(nt, 'nodes["Color"].outputs[0].default_value', (c["col_r"], c["col_g"], c["col_b"], 1))
    bk.set(nt, 'nodes["Emission"].inputs[1].default_value', 1.15 * c["glow"])



if __name__ == "__main__":
    common.run(build, drive, "glyph", bloom_kw=dict(strength=0.9, size=0.3, threshold=0.45), view="Standard")

"""Concept: android. A porcelain face mask on a dark metal head, glowing
irises in black glass eyes, light inside the mouth when it talks. The
most human of the set: the face moves like a face."""

import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common
import facemesh
from common import empty, emission_material, principled, studio_lights
from shapes2d import key_path

P = {}
S = 0.12


def build():
    common.camera(loc=(0, 0.1, 7.0), lens=58, target=(0, 0.0, 0))
    sc = bpy.context.scene
    sc.view_settings.look = "AgX - Punchy"
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.005, 0.012, 1)

    pivot = empty("Neck")
    pivot.location = (0, -1.1, -0.4)
    root = empty("FaceRoot", pivot)
    root.location = (0, 1.1, 0.4)
    root.scale = (S, S, S)
    P["pivot"] = pivot

    porcelain = principled("Porcelain", (0.62, 0.61, 0.67), 0.32, coat=0.6, sss=0.05)
    metal = principled("Graphite", (0.05, 0.05, 0.07), 0.25, metal=1.0)
    glass = principled("EyeGlass", (0.003, 0.003, 0.005), 0.04, coat=1.0)
    cavity = principled("Cavity", (0.01, 0.01, 0.012), 0.6)
    glow = emission_material("Glow", strength=6)
    P["glow"] = glow

    mask = facemesh.build("Mask")
    mask.parent = root
    mask.data.materials.append(porcelain)
    P["mesh"] = mask.data
    sub = mask.modifiers.new("Smooth", "SUBSURF")
    sub.levels = sub.render_levels = 2
    sol = mask.modifiers.new("Shell", "SOLIDIFY")
    sol.thickness = 0.3
    sol.offset = -1

    # Cranium behind the mask.
    bpy.ops.mesh.primitive_uv_sphere_add(segments=96, ring_count=48, radius=1.0, location=(0, 1.5, -4.5))
    head = bpy.context.object
    head.parent = root
    # Flattened front to back so it stays behind the eyes.
    head.scale = (7.2, 9.5, 5.0)
    head.data.materials.append(metal)
    bpy.ops.object.shade_smooth()

    # Neck.
    bpy.ops.mesh.primitive_cylinder_add(radius=3.0, depth=8, location=(0, -9.5, -4.0))
    neck = bpy.context.object
    neck.parent = root
    neck.data.materials.append(metal)
    bpy.ops.object.shade_smooth()

    # Eyes: black glass balls with a glowing iris ring and pupil.
    for s in ("L", "R"):
        cx, cy, cz = facemesh.eye_center(s)
        ball = empty("Ball" + s, root)
        ball.location = (cx, cy - 0.05, cz - 1.75)
        bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=1.6)
        eb = bpy.context.object
        eb.parent = ball
        eb.data.materials.append(glass)
        bpy.ops.object.shade_smooth()
        bpy.ops.mesh.primitive_torus_add(major_radius=0.62, minor_radius=0.1, location=(0, 0, 1.5))
        ring = bpy.context.object
        ring.parent = ball
        ring.data.materials.append(glow)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.18, location=(0, 0, 1.6))
        dot = bpy.context.object
        dot.parent = ball
        dot.data.materials.append(glow)
        P["ball" + s] = ball

    # Mouth: dark cavity with a light at the back that brightens with speech.
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, -4.4, 3.2))
    cav = bpy.context.object
    cav.parent = root
    cav.scale = (2.6, 1.5, 1.2)
    cav.data.materials.append(cavity)
    mouth_glow = emission_material("MouthGlow", strength=3)
    P["mouth_glow"] = mouth_glow
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, -4.5, 2.6))
    mg = bpy.context.object
    mg.parent = root
    mg.scale = (1.8, 0.9, 0.5)
    mg.data.materials.append(mouth_glow)

    # Glowing rims around the eye openings.
    liner = common.link(bpy.data.objects.new("Liner", mask.data))
    liner.parent = root
    facemesh.lines_modifier(liner, glow, "eyes", 0.06)
    # And a seam of light where the mask meets the head.
    seam = common.link(bpy.data.objects.new("Seam", mask.data))
    seam.parent = root
    facemesh.lines_modifier(seam, glow, "oval", 0.07)

    studio_lights(pivot, key=500, fill=150, rims=(1100, 900))


def drive(bk, c):
    bk.set(P["pivot"], "rotation_euler", (math.radians(c["head_pitch"]), math.radians(c["head_yaw"] * 1.3),
                                          math.radians(-c["head_roll"])))
    for k, v in facemesh.weights(c).items():
        bk.set(P["mesh"].shape_keys, key_path(k), v)
    for s in ("L", "R"):
        bk.set(P["ball" + s], "rotation_euler", (math.radians(-20 * c["look_y"]), math.radians(26 * c["look_x"]), 0))
    col = (c["col_r"], c["col_g"], c["col_b"], 1)
    nt = P["glow"].node_tree
    bk.set(nt, 'nodes["Emission"].inputs[0].default_value', col)
    bk.set(nt, 'nodes["Emission"].inputs[1].default_value', 7 * c["glow"])
    nt = P["mouth_glow"].node_tree
    bk.set(nt, 'nodes["Emission"].inputs[0].default_value', col)
    bk.set(nt, 'nodes["Emission"].inputs[1].default_value', (0.6 + 9 * c["talk"]) * c["glow"])



if __name__ == "__main__":
    common.run(build, drive, "android", bloom_kw=dict(strength=0.5, size=0.3, threshold=1.0))

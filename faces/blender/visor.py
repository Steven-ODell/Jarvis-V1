"""Concept: visor. A sleek robot head, white shell and a black glass
visor, with the glyph eyes and mouth glowing on the glass. The head itself
tilts, turns and nods, so it reads as a body and not just a screen."""

import math
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common
from common import empty, emission_material, link
from shapes2d import band_object, eye_shapes, mouth_shapes, eye_weights, mouth_weights, key_path

P = {}


def principled(name, color, rough, metal=0.0, coat=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    return m


VIS_T, VIS_P, VIS_OFF = math.radians(56), math.radians(33), math.radians(-5)


def on_sphere(theta, phi, r):
    return (r * math.cos(phi) * math.sin(theta), r * math.sin(phi), r * math.cos(phi) * math.cos(theta))


def visor_cutter(n=160):
    """Closed cone from the head centre out through a rounded-rectangle
    window (a superellipse in angle space). Booleans with it give the
    shell its opening and the glass its outline, both with smooth edges."""
    ring = []
    for i in range(n):
        a = 2 * math.pi * i / n
        ca, sa = math.cos(a), math.sin(a)
        x = math.copysign(abs(ca) ** 0.5, ca)
        y = math.copysign(abs(sa) ** 0.5, sa)
        ring.append(on_sphere(VIS_T * x, VIS_P * y + VIS_OFF, 2.5))
    verts = [(0, 0, 0)] + ring + [on_sphere(0, VIS_OFF, 2.6)]
    cap = n + 1
    faces = []
    for i in range(n):
        j = i % n + 1
        k = (i + 1) % n + 1
        faces.append((0, k, j))
        faces.append((cap, j, k))
    ob = common.mesh_from("Cutter", verts, faces)
    ob.hide_render = True
    ob.display_type = "WIRE"
    return ob


def sphere(name, r, cut, op):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=128, ring_count=64, radius=r)
    ob = bpy.context.object
    ob.name = name
    bpy.ops.object.shade_smooth()
    b = ob.modifiers.new("Cut", "BOOLEAN")
    b.object = cut
    b.operation = op
    b.solver = "EXACT"
    return ob


def build():
    common.camera(loc=(0, 0.15, 7.2), lens=70, target=(0, -0.05, 0))
    sc = bpy.context.scene
    sc.view_settings.look = "AgX - Punchy"
    sc.world.node_tree.nodes["Background"].inputs[0].default_value = (0.006, 0.005, 0.012, 1)

    pivot = empty("Neck")
    pivot.location = (0, -1.05, 0)
    head = empty("Head", pivot)
    head.location = (0, 1.05, 0)
    P["pivot"] = pivot

    shell_m = principled("Shell", (0.82, 0.80, 0.88), 0.32, coat=0.6)
    glass_m = principled("Glass", (0.004, 0.004, 0.007), 0.06, coat=1.0)
    metal_m = principled("Metal", (0.08, 0.075, 0.1), 0.28, metal=1.0)

    cutter = visor_cutter()
    shell = sphere("Shell", 1.0, cutter, "DIFFERENCE")
    shell.parent = head
    cutter.parent = head
    shell.scale = (1.0, 1.06, 0.96)
    cutter.scale = shell.scale
    shell.data.materials.append(shell_m)
    sol = shell.modifiers.new("Solid", "SOLIDIFY")
    sol.thickness = 0.05
    sol.offset = -1
    bev = shell.modifiers.new("Bevel", "BEVEL")
    bev.width = 0.015
    bev.segments = 3
    bev.limit_method = "ANGLE"

    glass = sphere("Visor", 0.975, cutter, "INTERSECT")
    glass.parent = head
    glass.scale = shell.scale
    glass.data.materials.append(glass_m)
    # Shrinkwrap targets need the final glass, so apply its boolean now.
    bpy.context.view_layer.objects.active = glass
    bpy.ops.object.modifier_apply(modifier="Cut")

    # Chin cap closing the bottom of the shell.
    bpy.ops.mesh.primitive_cylinder_add(radius=0.62, depth=0.05, location=(0, -0.86, -0.02))
    cap = bpy.context.object
    cap.parent = head
    cap.data.materials.append(metal_m)

    # Neck and collar.
    bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.7, location=(0, -1.25, -0.05))
    neck = bpy.context.object
    neck.data.materials.append(metal_m)
    bpy.ops.mesh.primitive_torus_add(major_radius=0.34, minor_radius=0.05, location=(0, -0.98, -0.05))
    bpy.context.object.data.materials.append(metal_m)
    bpy.context.object.parent = head

    # Ear pods with light rings.
    glow_m = emission_material("Glow", strength=6)
    P["ring"] = glow_m
    for sx in (-1, 1):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.28, depth=0.16, location=(sx * 0.98, 0.0, -0.05),
                                            rotation=(0, math.pi / 2, 0))
        pod = bpy.context.object
        pod.parent = head
        pod.data.materials.append(metal_m)
        bpy.ops.object.shade_smooth()
        bpy.ops.mesh.primitive_torus_add(major_radius=0.2, minor_radius=0.022, location=(sx * 1.065, 0.0, -0.05),
                                         rotation=(0, math.pi / 2, 0))
        r = bpy.context.object
        r.parent = head
        r.data.materials.append(glow_m)

    # Face on the glass: flat bands, densified and projected onto the visor.
    face_m = emission_material("Face", strength=6)
    P["face"] = face_m
    for s in ("L", "R"):
        e = band_object("Eye" + s, eye_shapes(), z=0.0)
        P["eye" + s] = e
    P["mouth"] = band_object("Mouth", mouth_shapes(), z=0.0)
    face = empty("FaceRoot", head)
    face.location = (0, 0, 1.6)
    for ob in (P["eyeL"], P["eyeR"], P["mouth"]):
        ob.parent = face
        ob.data.materials.append(face_m)
        sub = ob.modifiers.new("Dense", "SUBSURF")
        sub.subdivision_type = "SIMPLE"
        sub.levels = sub.render_levels = 3
        sw = ob.modifiers.new("Wrap", "SHRINKWRAP")
        sw.wrap_method = "PROJECT"
        sw.use_project_z = True
        sw.use_negative_direction = True
        sw.use_positive_direction = False
        sw.target = glass
        sw.offset = 0.004

    # Lights: soft key, cool fill, purple and cyan rims behind.
    def area(name, loc, energy, color, size):
        l = bpy.data.lights.new(name, "AREA")
        l.energy, l.color, l.size = energy, color, size
        l.shape = "DISK"
        o = link(bpy.data.objects.new(name, l))
        o.location = loc
        c = o.constraints.new("TRACK_TO")
        c.target = head
        return o

    area("Key", (-3.0, 5.0, 3.0), 800, (1, 0.97, 1), 3.0)
    area("Fill", (6.0, -1.5, 1.5), 200, (0.8, 0.85, 1), 3.0)
    area("RimP", (-3.0, 1.5, -3.5), 600, (0.69, 0.49, 0.96), 2.0)
    area("RimC", (3.2, 1.0, -3.0), 450, (0.37, 0.95, 1.0), 2.0)
    area("Top", (0, 5, 0.5), 200, (1, 1, 1), 4.0)


def drive(bk, c):
    piv = P["pivot"]
    bk.set(piv, "rotation_euler", (math.radians(c["head_pitch"] * 0.8), math.radians(c["head_yaw"] * 1.4),
                                   math.radians(-c["head_roll"] * 0.8)))
    for s in ("L", "R"):
        e = P["eye" + s]
        sx = 1 if s == "L" else -1
        wide = 1 - 0.6 * min(c["lid_" + s], 0)
        size = 0.15 * c["eye_size"] * (1 + 0.08 * c["look_x"] * sx)
        bk.set(e, "location", (sx * 0.34 + c["look_x"] * 0.09, 0.12 + c["look_y"] * 0.07 + c["brow_" + s] * 0.035, 0))
        bk.set(e, "scale", (sx * size * 0.95, size * wide * (1 + 0.08 * c["brow_" + s]), 1))
        for k, v in eye_weights(c, s).items():
            bk.set(e.data.shape_keys, key_path(k), v)
    m = P["mouth"]
    bk.set(m, "location", (c["look_x"] * 0.04, -0.3 + c["look_y"] * 0.02, 0))
    bk.set(m, "scale", (0.14, 0.14, 1))
    for k, v in mouth_weights(c).items():
        bk.set(m.data.shape_keys, key_path(k), v)
    col = (c["col_r"], c["col_g"], c["col_b"], 1)
    for mat, k in ((P["face"], 5.0), (P["ring"], 4.0 + 6.0 * c["talk"])):
        nt = mat.node_tree
        bk.set(nt, 'nodes["Emission"].inputs[0].default_value', col)
        bk.set(nt, 'nodes["Emission"].inputs[1].default_value', k * c["glow"])



if __name__ == "__main__":
    common.run(build, drive, "visor", bloom_kw=dict(strength=0.5, size=0.3, threshold=1.0))

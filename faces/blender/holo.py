"""Concept: holo. A human face as a hologram: vertex points, the triangle
wireframe and a faint rim-lit skin, with scanlines sweeping through it.
Human expressions, clearly not a human. Closest to the current orb."""

import math
import os
import random
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common
import facemesh
from common import empty, link
from shapes2d import key_path

P = {}
S = 0.12  # face mesh units -> scene units


def holo_material(name, rim=False, base=1.0):
    """Additive emission with scanlines and a sweeping band.
    Animated through the Color, Glow, Time and Band nodes."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m.surface_render_method = "BLENDED"
    nt = m.node_tree
    nt.nodes.clear()
    N = nt.nodes.new
    L = nt.links.new

    def math_node(op, a=None, b=None):
        n = N("ShaderNodeMath")
        n.operation = op
        for i, v in enumerate((a, b)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[i].default_value = v
            else:
                L(v, n.inputs[i])
        return n.outputs[0]

    def value(nm, v):
        n = N("ShaderNodeValue")
        n.name = nm
        n.outputs[0].default_value = v
        return n.outputs[0]

    col = N("ShaderNodeRGB")
    col.name = "Color"
    glow, time, band = value("Glow", 1.0), value("Time", 0.0), value("Band", 0.0)
    tc = N("ShaderNodeTexCoord")
    sep = N("ShaderNodeSeparateXYZ")
    L(tc.outputs["Object"], sep.inputs[0])
    y = sep.outputs["Y"]
    lines = math_node("SINE", math_node("ADD", math_node("MULTIPLY", y, 9.0), math_node("MULTIPLY", time, -5.0)))
    scan = math_node("MULTIPLY_ADD", lines, 0.22)
    scan.node.inputs[2].default_value = 0.78
    dy = math_node("SUBTRACT", y, band)
    bandv = math_node("EXPONENT", math_node("MULTIPLY", math_node("MULTIPLY", dy, dy), -0.6))
    k = math_node("ADD", scan, math_node("MULTIPLY", bandv, 1.4))
    k = math_node("MULTIPLY", math_node("MULTIPLY", k, glow), base)
    if rim:
        lw = N("ShaderNodeLayerWeight")
        lw.inputs["Blend"].default_value = 0.35
        f = math_node("ADD", math_node("POWER", lw.outputs["Facing"], 2.0), 0.05)
        k = math_node("MULTIPLY", k, f)
    em = N("ShaderNodeEmission")
    L(col.outputs[0], em.inputs["Color"])
    L(k, em.inputs["Strength"])
    tr = N("ShaderNodeBsdfTransparent")
    add = N("ShaderNodeAddShader")
    L(em.outputs[0], add.inputs[0])
    L(tr.outputs[0], add.inputs[1])
    out = N("ShaderNodeOutputMaterial")
    L(add.outputs[0], out.inputs["Surface"])
    return m


def points_modifier(ob, mat, radius):
    ng = bpy.data.node_groups.new("Points", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gi = ng.nodes.new("NodeGroupInput")
    go = ng.nodes.new("NodeGroupOutput")
    mp = ng.nodes.new("GeometryNodeMeshToPoints")
    mp.inputs["Radius"].default_value = radius
    sm = ng.nodes.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    ng.links.new(gi.outputs[0], mp.inputs["Mesh"])
    ng.links.new(mp.outputs[0], sm.inputs["Geometry"])
    ng.links.new(sm.outputs[0], go.inputs[0])
    mod = ob.modifiers.new("Points", "NODES")
    mod.node_group = ng


def build():
    common.camera(loc=(0, 0.0, 6.4), lens=62, target=(0, -0.05, 0))
    pivot = empty("Neck")
    pivot.location = (0, -1.0, -0.4)
    root = empty("FaceRoot", pivot)
    root.location = (0, 1.0, 0.4)
    root.scale = (S, S, S)
    P["pivot"], P["root"] = pivot, root

    skin = facemesh.build("Skin")
    skin.parent = root
    P["mesh"] = skin.data
    mats = {
        "skin": holo_material("HoloSkin", rim=True, base=1.1),
        "line": holo_material("HoloLine", base=2.6),
        "wire": holo_material("HoloWire", base=0.9),
        "pts": holo_material("HoloPoints", base=3.0),
        "eye": holo_material("HoloEye", base=3.5),
    }
    P["mats"] = mats
    skin.data.materials.append(mats["skin"])

    wire = link(bpy.data.objects.new("Wire", skin.data))
    wire.parent = root
    wm = wire.modifiers.new("Wire", "WIREFRAME")
    wm.thickness = 0.035
    wm.use_replace = True
    wm.material_offset = 1
    wire.data.materials.append(mats["wire"])  # slot 2, used through material_offset

    pts = link(bpy.data.objects.new("Points", skin.data))
    pts.parent = root
    points_modifier(pts, mats["pts"], 0.07)

    lines = link(bpy.data.objects.new("Lines", skin.data))
    lines.parent = root
    facemesh.lines_modifier(lines, mats["line"], "feature", 0.07)

    # Irises: a ring and a pupil dot, swung around an eyeball centre so
    # gaze is a rotation.
    for s in ("L", "R"):
        cx, cy, cz = facemesh.eye_center(s)
        ball = empty("Ball" + s, root)
        ball.location = (cx, cy, cz - 1.4)
        bpy.ops.mesh.primitive_torus_add(major_radius=0.5, minor_radius=0.07, location=(0, 0, 1.5))
        ring = bpy.context.object
        ring.parent = ball
        ring.data.materials.append(mats["eye"])
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.16, location=(0, 0, 1.55))
        dot = bpy.context.object
        dot.parent = ball
        dot.data.materials.append(mats["eye"])
        P["ball" + s] = ball

    # Projector ring under the chin.
    bpy.ops.mesh.primitive_torus_add(major_radius=0.75, minor_radius=0.012, location=(0, -1.45, 0))
    base = bpy.context.object
    base.scale = (1, 1, 0.3)
    base.rotation_euler = (math.pi / 2, 0, 0)
    base.data.materials.append(mats["wire"])

    rng = random.Random(3)
    P["glitch"] = [rng.uniform(1, 22) for _ in range(4)]


def drive(bk, c):
    t = c["time"]
    piv = P["pivot"]
    # A short horizontal tear now and then sells it as projected light.
    g = max((1.0 if 0 <= t - g0 < 0.07 else 0.0) for g0 in P["glitch"])
    bk.set(piv, "rotation_euler", (math.radians(c["head_pitch"]), math.radians(c["head_yaw"] * 1.3),
                                   math.radians(-c["head_roll"])))
    bk.set(piv, "location", (0.04 * g, -1.0, -0.4))
    for k, v in facemesh.weights(c).items():
        bk.set(P["mesh"].shape_keys, key_path(k), v)
    for s in ("L", "R"):
        bk.set(P["ball" + s], "rotation_euler", (math.radians(-22 * c["look_y"]), math.radians(28 * c["look_x"]), 0))
        # Squash the iris as the lid comes down; there is no lid to hide it.
        lid = min(1.0, max(0.0, c["lid_" + s]))
        sc = c["eye_size"]
        bk.set(P["ball" + s], "scale", (sc, sc * max(0.04, 1 - lid ** 1.5), 1))
    col = (c["col_r"], c["col_g"], c["col_b"], 1)
    band = 9.5 - ((t / 2.6) % 1.0) * 22
    for m in P["mats"].values():
        nt = m.node_tree
        bk.set(nt, 'nodes["Color"].outputs[0].default_value', col)
        bk.set(nt, 'nodes["Glow"].outputs[0].default_value', c["glow"] * (1 + 0.8 * g + 0.25 * c["talk"]))
        bk.set(nt, 'nodes["Time"].outputs[0].default_value', t)
        bk.set(nt, 'nodes["Band"].outputs[0].default_value', band)



if __name__ == "__main__":
    common.run(build, drive, "holo", bloom_kw=dict(strength=0.7, size=0.3, threshold=0.5), view="Standard")

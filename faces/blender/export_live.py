"""Export the 3D faces for the live orb (Qt Quick 3D).

    blender -b --factory-startup --python faces/blender/export_live.py -- visor holo android

Builds each concept's scene, then flattens it into a few "parts" (one mesh
per material, positioned relative to the head pivot) and bakes every
modifier (wireframe, subdivision, line tubes) into the expression shape
keys, so the orb only has to blend morph targets. Writes
orb/face/<concept>/<concept>.glb and parts.json; balsam turns the .glb into
the .mesh files Quick3D loads.
"""

import json
import math
import os
import subprocess
import sys

import bpy
from mathutils import Vector

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import common  # noqa: E402

ROOT = os.path.dirname(common.FACES)
OUT = os.path.join(ROOT, "orb", "face")


def evaluated(ob):
    dg = bpy.context.evaluated_depsgraph_get()
    e = ob.evaluated_get(dg)
    me = e.to_mesh()
    verts = [(e.matrix_world @ v.co) for v in me.vertices]
    faces = [tuple(p.vertices) for p in me.polygons]
    e.to_mesh_clear()
    return verts, faces


def part(name, objs, pivot, key_mesh=None, uv=None):
    """Join objs (evaluated, world space) into one mesh relative to pivot.
    With key_mesh, bake one shape key per key of that mesh: the evaluated
    result with only that key at 1."""
    keys = [k.name for k in key_mesh.shape_keys.key_blocks[1:]] if key_mesh else []

    def snapshot(active):
        if key_mesh:
            for k in key_mesh.shape_keys.key_blocks[1:]:
                k.value = 1.0 if k.name == active else 0.0
            bpy.context.view_layer.update()
        V, F = [], []
        for ob in objs:
            v, f = evaluated(ob)
            off = len(V)
            V += [tuple(p - Vector(pivot)) for p in v]
            F += [tuple(i + off for i in face) for face in f]
        return V, F

    V, F = snapshot(None)
    me = bpy.data.meshes.new(name)
    me.from_pydata(V, [], F)
    for p in me.polygons:
        p.use_smooth = True
    if uv:
        layer = me.uv_layers.new(name="UVMap")
        for loop in me.loops:
            layer.data[loop.index].uv = uv(V[loop.vertex_index])
    ob = common.link(bpy.data.objects.new(name, me))
    if keys:
        ob.shape_key_add(name="Basis")
        for k in keys:
            kv, kf = snapshot(k)
            assert len(kv) == len(V), f"{name}/{k}: topology changed"
            sk = ob.shape_key_add(name=k)
            for i, co in enumerate(kv):
                sk.data[i].co = co
        snapshot("")  # all keys back to 0
    return ob, keys


def points_as_mesh(ob, radius):
    """The render draws vertices as a point cloud; Quick3D wants triangles,
    so swap in small icospheres."""
    ng = bpy.data.node_groups.new("PointsMesh", "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")
    mp, ico, inst, real = (N("GeometryNodeMeshToPoints"), N("GeometryNodeMeshIcoSphere"),
                           N("GeometryNodeInstanceOnPoints"), N("GeometryNodeRealizeInstances"))
    ico.inputs["Radius"].default_value = radius
    ico.inputs["Subdivisions"].default_value = 1
    L = ng.links.new
    L(gi.outputs[0], mp.inputs["Mesh"])
    L(mp.outputs[0], inst.inputs["Points"])
    L(ico.outputs[0], inst.inputs["Instance"])
    L(inst.outputs[0], real.inputs[0])
    L(real.outputs[0], go.inputs[0])
    ob.modifiers.clear()
    ob.modifiers.new("PointsMesh", "NODES").node_group = ng


def world(ob):
    return tuple(ob.matrix_world.translation)


def export_visor():
    import visor
    visor.build()
    P = visor.P
    piv = world(P["pivot"])
    obs = {o.name: o for o in bpy.data.objects}
    rings = [o for o in obs.values() if o.type == "MESH" and o.data.materials and o.data.materials[0].name == "Glow"]
    metal = [o for o in obs.values() if o.type == "MESH" and o.data.materials and o.data.materials[0].name == "Metal"]
    neck = [o for o in metal if o.parent is None]
    head_metal = [o for o in metal if o.parent is not None]
    # Visor UVs: a front projection lined up with the glyph face texture
    # (eyes at x = +-0.34 here vs +-0.6 in glyph units, so 1.15 * 0.58).
    half = 1.15 * 0.575

    def uv(p):
        # p is relative to the neck pivot, which sits 1.05 below the head centre.
        return (0.5 + p[0] / (2 * half), 0.5 + (p[1] - 1.05 - 0.035) / (2 * half))

    parts = [
        part("shell", [obs["Shell"]], piv),
        part("glass", [obs["Visor"]], piv, uv=uv),
        part("metal", head_metal, piv),
        part("rings", rings, piv),
        part("neck", neck, piv),
    ]
    return piv, parts, {}


def export_holo():
    import holo
    holo.build()
    P = holo.P
    piv = world(P["pivot"])
    obs = {o.name: o for o in bpy.data.objects}
    key_mesh = obs["Skin"].data
    points_as_mesh(obs["Points"], 0.07)
    parts = [
        part("skin", [obs["Skin"]], piv, key_mesh),
        part("wire", [obs["Wire"]], piv, key_mesh),
        part("points", [obs["Points"]], piv, key_mesh),
        part("lines", [obs["Lines"]], piv, key_mesh),
        part("base", [o for o in obs.values() if o.name.startswith("Torus") and o.parent is None], piv),
    ]
    balls = {}
    for s in ("L", "R"):
        b = P["ball" + s]
        c = world(b)
        parts.append(part("eye" + s, list(b.children), c))
        balls["eye" + s] = [c[i] - piv[i] for i in range(3)]
    return piv, parts, balls


def export_android():
    import android
    android.build()
    P = android.P
    piv = world(P["pivot"])
    obs = {o.name: o for o in bpy.data.objects}
    key_mesh = obs["Mask"].data

    def by_mat(name):
        return [o for o in obs.values() if o.type == "MESH" and o.data.materials
                and o.data.materials[0].name == name and not o.parent.name.startswith("Ball")]

    parts = [
        part("mask", [obs["Mask"]], piv, key_mesh),
        part("liner", [obs["Liner"]], piv, key_mesh),
        part("seam", [obs["Seam"]], piv, key_mesh),
        part("metal", by_mat("Graphite"), piv),
        part("cavity", by_mat("Cavity"), piv),
        part("mouthglow", by_mat("MouthGlow"), piv),
    ]
    balls = {}
    for s in ("L", "R"):
        b = P["ball" + s]
        c = world(b)
        kids = list(b.children)
        parts.append(part("ball" + s, [k for k in kids if k.data.materials[0].name == "EyeGlass"], c))
        parts.append(part("iris" + s, [k for k in kids if k.data.materials[0].name == "Glow"], c))
        balls["ball" + s] = balls["iris" + s] = [c[i] - piv[i] for i in range(3)]
    return piv, parts, balls


EXPORTERS = {"visor": export_visor, "holo": export_holo, "android": export_android}


def main():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else list(EXPORTERS)
    for name in a:
        common.reset()
        common.setup_scene(res=64, samples=1)
        piv, parts, offsets = EXPORTERS[name]()
        out = os.path.join(OUT, name)
        os.makedirs(out, exist_ok=True)
        bpy.ops.object.select_all(action="DESELECT")
        for ob, _ in parts:
            ob.select_set(True)
        glb = os.path.join(out, name + ".glb")
        bpy.ops.export_scene.gltf(filepath=glb, use_selection=True, export_format="GLB", export_yup=False,
                                  export_morph=True, export_morph_normal=True, export_materials="NONE",
                                  export_apply=False, export_texcoords=True, export_normals=True)
        manifest = {
            "pivot": list(piv),
            "parts": {ob.name: {"keys": keys, "offset": offsets.get(ob.name, [0, 0, 0]),
                                "verts": len(ob.data.vertices)} for ob, keys in parts},
        }
        with open(os.path.join(out, "parts.json"), "w") as fh:
            json.dump(manifest, fh, indent=1)
        print("exported", name, {k: v["verts"] for k, v in manifest["parts"].items()})


main()

"""Blender plumbing shared by the face concepts: scene, bloom, baking the
expression timeline into keyframes, and rendering.

Run a concept as:
    blender -b --factory-startup --python faces/blender/<concept>.py -- [--stills] [--frames A-B]
"""

import math
import os
import subprocess
import sys

import bpy

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import expr  # noqa: E402

FACES = os.path.dirname(HERE)
WAV = os.path.join(FACES, "assets", "line.wav")


def args():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"stills": "--stills" in a, "frames": None, "res": 640, "blend": "--blend" in a}
    if "--frames" in a:
        lo, hi = a[a.index("--frames") + 1].split("-")
        opts["frames"] = (int(lo), int(hi))
    if "--res" in a:
        opts["res"] = int(a[a.index("--res") + 1])
    return opts


def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def setup_scene(res=640, samples=32, bg=(0, 0, 0), view="AgX"):
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.render.fps = expr.FPS
    sc.eevee.taa_render_samples = samples
    sc.render.image_settings.file_format = "PNG"
    sc.view_settings.view_transform = view
    world = bpy.data.worlds.new("World")
    sc.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (*bg, 1)
    return sc


def bloom(strength=0.6, size=0.5, threshold=0.6, smooth=0.3):
    sc = bpy.context.scene
    ng = bpy.data.node_groups.new("Bloom", "CompositorNodeTree")
    ng.interface.new_socket("Image", in_out="OUTPUT", socket_type="NodeSocketColor")
    rl = ng.nodes.new("CompositorNodeRLayers")
    g = ng.nodes.new("CompositorNodeGlare")
    out = ng.nodes.new("NodeGroupOutput")
    g.inputs["Type"].default_value = "Bloom"
    g.inputs["Quality"].default_value = "High"
    g.inputs["Threshold"].default_value = threshold
    g.inputs["Smoothness"].default_value = smooth
    g.inputs["Strength"].default_value = strength
    g.inputs["Size"].default_value = size
    ng.links.new(rl.outputs["Image"], g.inputs["Image"])
    ng.links.new(g.outputs["Image"], out.inputs[0])
    sc.compositing_node_group = ng
    return g


def camera(loc=(0, 0, 10), ortho=None, lens=50, target=(0, 0, 0)):
    """Looks down -Z with +Y up (our faces are built Y-up, facing +Z).
    No Track To: looking straight down Blender's Z axis leaves its up
    vector undefined and the picture can come out upside down."""
    cam = bpy.data.objects.new("Camera", bpy.data.cameras.new("Camera"))
    bpy.context.scene.collection.objects.link(cam)
    cam.location = loc
    if ortho:
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = ortho
    else:
        cam.data.lens = lens
    dy, dz = loc[1] - target[1], loc[2] - target[2]
    dx = loc[0] - target[0]
    cam.rotation_euler = (-math.atan2(dy, dz), math.atan2(dx, dz), 0)
    bpy.context.scene.camera = cam
    return cam


def link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def empty(name, parent=None):
    e = link(bpy.data.objects.new(name, None))
    e.parent = parent
    return e


def emission_material(name, color=(1, 1, 1), strength=4.0, scanlines=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    em = nt.nodes.new("ShaderNodeEmission")
    em.name = "Emission"
    em.inputs["Color"].default_value = (*color, 1)
    em.inputs["Strength"].default_value = strength
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    if scanlines:
        # Screen-space lines every few pixels, like an LED panel.
        tc = nt.nodes.new("ShaderNodeTexCoord")
        sep = nt.nodes.new("ShaderNodeSeparateXYZ")
        mul = nt.nodes.new("ShaderNodeMath")
        mul.operation = "MULTIPLY"
        mul.inputs[1].default_value = bpy.context.scene.render.resolution_y * math.pi / 3
        sin = nt.nodes.new("ShaderNodeMath")
        sin.operation = "SINE"
        mad = nt.nodes.new("ShaderNodeMath")
        mad.operation = "MULTIPLY_ADD"
        mad.inputs[1].default_value = scanlines / 2
        mad.inputs[2].default_value = 1 - scanlines / 2
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = "RGBA"
        mix.blend_type = "MULTIPLY"
        mix.inputs["Factor"].default_value = 1
        nt.links.new(tc.outputs["Window"], sep.inputs[0])
        nt.links.new(sep.outputs["Y"], mul.inputs[0])
        nt.links.new(mul.outputs[0], sin.inputs[0])
        nt.links.new(sin.outputs[0], mad.inputs[0])
        rgb = nt.nodes.new("ShaderNodeRGB")
        rgb.name = "Color"
        rgb.outputs[0].default_value = (*color, 1)
        nt.links.new(rgb.outputs[0], mix.inputs[6])
        nt.links.new(mad.outputs[0], mix.inputs[7])
        nt.links.new(mix.outputs[2], em.inputs["Color"])
    return m


def mesh_from(name, verts, faces):
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.update()
    return link(bpy.data.objects.new(name, me))


# --- baking -----------------------------------------------------------------

class Baker:
    """Collects per-frame values for any animatable property, then writes
    them as one keyframe per frame in a single pass (keyframe_insert per
    frame is far too slow for ~700 frames x dozens of channels)."""

    def __init__(self):
        self.chan = {}

    def set(self, id_data, path, value, index=-1):
        if isinstance(value, (tuple, list)):
            for i, v in enumerate(value):
                self.set(id_data, path, v, i)
            return
        self.chan.setdefault((id_data, path, index), []).append(float(value))

    def write(self):
        for (idd, path, index), vals in self.chan.items():
            if idd.animation_data is None:
                idd.animation_data_create()
            if idd.animation_data.action is None:
                idd.animation_data.action = bpy.data.actions.new(idd.name + "Action")
            fc = idd.animation_data.action.fcurve_ensure_for_datablock(idd, path, index=max(index, 0))
            fc.keyframe_points.add(len(vals))
            co = []
            for f, v in enumerate(vals):
                co += [f + 1, v]
            fc.keyframe_points.foreach_set("co", co)
            fc.update()


def run(build_face, drive, name, res=640, bloom_kw=None, samples=32, view="AgX"):
    """build_face() makes the scene; drive(baker, controls) maps one frame of
    controls onto it. Renders the reel (or stills) into faces/concepts/<name>."""
    opts = args()
    reset()
    setup_scene(res=opts["res"] or res, samples=samples, view=view)
    build_face()
    if bloom_kw is not None:
        bloom(**bloom_kw)

    frames, segs, speech = expr.build(WAV)
    bk = Baker()
    for c in frames:
        drive(bk, c)
    bk.write()

    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, len(frames)
    out = os.path.join(FACES, "concepts", name)
    os.makedirs(out, exist_ok=True)
    if opts["blend"]:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, name + ".blend"))

    if opts["stills"]:
        sdir = os.path.join(out, "stills")
        os.makedirs(sdir, exist_ok=True)
        for i, (pose, f0, f1) in enumerate(segs):
            f = f0 + int((f1 - f0) * (0.45 if pose == "speaking" else 0.75))
            sc.frame_set(f + 1)
            sc.render.filepath = os.path.join(sdir, f"{i:02d}-{pose}.png")
            bpy.ops.render.render(write_still=True)
        return

    fdir = os.path.join(out, "frames")
    os.makedirs(fdir, exist_ok=True)
    if opts["frames"]:
        sc.frame_start, sc.frame_end = opts["frames"]
    sc.render.filepath = os.path.join(fdir, "f")
    bpy.ops.render.render(animation=True)
    with open(os.path.join(out, "timing.txt"), "w") as fh:
        fh.write(f"speech_start {speech}\n")
        for pose, f0, f1 in segs:
            fh.write(f"{pose} {f0 + 1} {f1 + 1}\n")


def principled(name, color, rough, metal=0.0, coat=0.0, sss=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    b.inputs["Coat Weight"].default_value = coat
    b.inputs["Subsurface Weight"].default_value = sss
    return m


def studio_lights(target, key=800, fill=200, rims=(600, 450), top=200):
    """Soft key, cool fill, purple and cyan rims behind. Disk-shaped so
    their reflections in glossy parts read as soft highlights."""
    def area(name, loc, energy, color, size):
        l = bpy.data.lights.new(name, "AREA")
        l.energy, l.color, l.size = energy, color, size
        l.shape = "DISK"
        o = link(bpy.data.objects.new(name, l))
        o.location = loc
        c = o.constraints.new("TRACK_TO")
        c.target = target
        return o

    area("Key", (-3.0, 5.0, 3.0), key, (1, 0.97, 1), 3.0)
    area("Fill", (6.0, -1.0, 0.5), fill, (0.8, 0.85, 1), 4.0)
    area("RimP", (-3.0, 1.5, -3.5), rims[0], (0.69, 0.49, 0.96), 2.0)
    area("RimC", (3.2, 1.0, -3.0), rims[1], (0.37, 0.95, 1.0), 2.0)
    area("Top", (0, 5, 0.5), top, (1, 1, 1), 4.0)

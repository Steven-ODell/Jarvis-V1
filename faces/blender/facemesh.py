"""A human face rig built from MediaPipe's canonical face mesh.

assets/canonical_face_model.obj (Apache-2.0, from google-ai-edge/mediapipe)
is a neutral 468-vertex face, Y up, facing +Z, about 15 units wide. Its
vertex numbers are the MediaPipe landmark ids, so lips, lids and brows can
be picked out by number. The expression shape keys are sculpted here in
code: each moves a set of landmarks and lets the surrounding skin follow
with a smooth falloff. Shape keys are what glTF calls morph targets, so
the same rig can drive a live 3D face later.
"""

import math
import os

import bpy

import common

OBJ = os.path.join(common.FACES, "assets", "canonical_face_model.obj")

# Landmark ids. "L" is +x: the face's own left, screen right.
LIPS_IN_UP = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308]
LIPS_IN_LO = [78, 95, 88, 178, 87, 14, 317, 402, 318, 324, 308]
LIPS_OUT_LO = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291]
EYE = {
    "R": dict(up=[33, 246, 161, 160, 159, 158, 157, 173, 133], lo=[33, 7, 163, 144, 145, 153, 154, 155, 133]),
    "L": dict(up=[263, 466, 388, 387, 386, 385, 384, 398, 362], lo=[263, 249, 390, 373, 374, 380, 381, 382, 362]),
}
BROW = {"R": [46, 53, 52, 65, 55, 70, 63, 105, 66, 107], "L": [276, 283, 282, 295, 285, 300, 293, 334, 296, 336]}
BROW_INNER = {"R": [55, 65, 107, 66], "L": [285, 295, 336, 296]}
CORNER = {"R": 61, "L": 291}


# Feature contours as landmark pairs, from MediaPipe's face_mesh_connections.py.
LIPS = [(61, 146), (146, 91), (91, 181), (181, 84), (84, 17), (17, 314), (314, 405), (405, 321), (321, 375), (375, 291), (61, 185), (185, 40), (40, 39), (39, 37), (37, 0), (0, 267), (267, 269), (269, 270), (270, 409), (409, 291), (78, 95), (95, 88), (88, 178), (178, 87), (87, 14), (14, 317), (317, 402), (402, 318), (318, 324), (324, 308), (78, 191), (191, 80), (80, 81), (81, 82), (82, 13), (13, 312), (312, 311), (311, 310), (310, 415), (415, 308)]
LEFT_EYE = [(263, 249), (249, 390), (390, 373), (373, 374), (374, 380), (380, 381), (381, 382), (382, 362), (263, 466), (466, 388), (388, 387), (387, 386), (386, 385), (385, 384), (384, 398), (398, 362)]
RIGHT_EYE = [(33, 7), (7, 163), (163, 144), (144, 145), (145, 153), (153, 154), (154, 155), (155, 133), (33, 246), (246, 161), (161, 160), (160, 159), (159, 158), (158, 157), (157, 173), (173, 133)]
LEFT_EYEBROW = [(276, 283), (283, 282), (282, 295), (295, 285), (300, 293), (293, 334), (334, 296), (296, 336)]
RIGHT_EYEBROW = [(46, 53), (53, 52), (52, 65), (65, 55), (70, 63), (63, 105), (105, 66), (66, 107)]
FACE_OVAL = [(10, 338), (338, 297), (297, 332), (332, 284), (284, 251), (251, 389), (389, 356), (356, 454), (454, 323), (323, 361), (361, 288), (288, 397), (397, 365), (365, 379), (379, 378), (378, 400), (400, 377), (377, 152), (152, 148), (148, 176), (176, 149), (149, 150), (150, 136), (136, 172), (172, 58), (58, 132), (132, 93), (93, 234), (234, 127), (127, 162), (162, 21), (21, 54), (54, 103), (103, 67), (67, 109), (109, 10)]
FEATURES = LIPS + LEFT_EYE + RIGHT_EYE + LEFT_EYEBROW + RIGHT_EYEBROW


def load():
    V, F = [], []
    with open(OBJ) as fh:
        for line in fh:
            p = line.split()
            if not p:
                continue
            if p[0] == "v":
                V.append(tuple(float(x) for x in p[1:4]))
            elif p[0] == "f":
                F.append([int(x.split("/")[0]) - 1 for x in p[1:]])
    return V, F


def holes(F):
    """Drop the faces filling the eyes and the gap between the lips, so
    lids can close and the jaw can open without a skin across the hole."""
    sets = [set(LIPS_IN_UP + LIPS_IN_LO)] + [set(e["up"] + e["lo"]) for e in EYE.values()]
    return [f for f in F if not any(all(i in s for i in f) for s in sets)]


def smoothstep(e0, e1, x):
    t = min(1.0, max(0.0, (x - e0) / (e1 - e0)))
    return t * t * (3 - 2 * t)


def gauss(d2, s):
    return math.exp(-d2 / (2 * s * s))


def d2(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b))


def interp_y(pts, x):
    """y of a lid contour at x (pts sorted by x)."""
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def sculpt(V):
    """name -> list of per-vertex deltas."""
    n = len(V)
    keys = {}

    def new():
        return [[0.0, 0.0, 0.0] for _ in range(n)]

    # Jaw: rotate the lower face about a hinge near the ears. The band
    # between moving and still skin widens away from the mouth so the
    # cheeks stretch instead of creasing.
    jaw = new()
    lower = set(LIPS_IN_LO + LIPS_OUT_LO) - {78, 308, 61, 291}
    ym = -4.27
    hinge = (0.0, 0.2, -2.5)
    ang = math.radians(15)
    for i, v in enumerate(V):
        ax = abs(v[0])
        k = 0.12 + 0.55 * max(0.0, ax - 2.3)
        w = 1.0 if i in lower else smoothstep(ym + k, ym - 0.3 - k, v[1])
        w *= 1 - smoothstep(4.5, 7.5, ax)
        y, z = v[1] - hinge[1], v[2] - hinge[2]
        ny = y * math.cos(ang) - z * math.sin(ang)
        nz = y * math.sin(ang) + z * math.cos(ang)
        jaw[i] = [0.0, w * (ny - y), w * (nz - z)]
    keys["jaw_open"] = jaw

    for s, sx in (("L", 1), ("R", -1)):
        c = V[CORNER[s]]
        cheek = (sx * 3.6, -1.6, 4.6)

        def corner_key(dx, dy, dz, sig=1.25, cheek_dy=0.0):
            k = new()
            for i, v in enumerate(V):
                g = gauss(d2(v, c), sig)
                gc = gauss(d2(v, cheek), 1.5)
                k[i] = [sx * dx * g, dy * g + cheek_dy * gc, dz * g + 0.4 * cheek_dy * gc]
            return k

        keys["smile_" + s] = corner_key(0.6, 1.1, -0.45, cheek_dy=0.55)
        keys["frown_" + s] = corner_key(-0.1, -0.85, -0.05)
        keys["wide_" + s] = corner_key(0.55, 0.05, -0.15)
        keys["pucker_" + s] = corner_key(-0.75, 0.0, 0.35, sig=1.4)

        brow = [V[i] for i in BROW[s]]
        inner = [V[i] for i in BROW_INNER[s]]

        def region_key(pts, dx, dy, sig):
            k = new()
            for i, v in enumerate(V):
                g = max(gauss(d2(v, p), sig) for p in pts)
                k[i] = [sx * dx * g, dy * g, 0.0]
            return k

        keys["brow_up_" + s] = region_key(brow, 0.0, 1.25, 1.1)
        keys["brow_down_" + s] = region_key(inner, -0.4, -0.9, 0.95)
        keys["brow_worry_" + s] = region_key(inner, 0.05, 1.1, 0.9)

        # Lids. The upper lid drops most of the way to the lower one; skin
        # above follows less the further it is from the lid edge.
        up = sorted((V[i][0], V[i][1]) for i in EYE[s]["up"])
        lo = sorted((V[i][0], V[i][1]) for i in EYE[s]["lo"])
        x0, x1 = up[0][0], up[-1][0]
        ecx = (x0 + x1) / 2
        half = (x1 - x0) / 2
        blink, wide, squint = new(), new(), new()
        for i, v in enumerate(V):
            x, y = v[0], v[1]
            lat = gauss(max(0.0, abs(x - ecx) - half) ** 2, 0.35)
            if lat < 1e-3:
                continue
            yu, yl = interp_y(up, x), interp_y(lo, x)
            mid = (yu + yl) / 2
            shut = yl * 0.75 + yu * 0.25
            if y >= mid - 1e-6:
                fall = gauss(max(0.0, y - yu) ** 2, 0.45)
                blink[i] = [0.0, (shut - yu) * fall * lat, 0.18 * fall * lat]
                wide[i] = [0.0, 0.45 * fall * lat, 0.05 * fall * lat]
            else:
                fall = gauss(max(0.0, yl - y) ** 2, 0.3)
                blink[i] = [0.0, (shut - yl) * fall * lat, 0.0]
                fall2 = gauss(max(0.0, yl - y) ** 2, 0.9)
                squint[i] = [0.0, 0.45 * (yu - yl) * fall2 * lat * (0.5 + 0.5 * fall), 0.1 * fall2 * lat]
        keys["blink_" + s] = blink
        keys["eye_wide_" + s] = wide
        keys["squint_" + s] = squint
    return keys


def build(name="Face"):
    V, F = load()
    F = holes(F)
    ob = common.mesh_from(name, V, F)
    for p in ob.data.polygons:
        p.use_smooth = True
    ob.shape_key_add(name="Basis")
    for k, deltas in sculpt(V).items():
        sk = ob.shape_key_add(name=k)
        sk.slider_min = -1.0
        for i, (d, v) in enumerate(zip(deltas, V)):
            sk.data[i].co = (v[0] + d[0], v[1] + d[1], v[2] + d[2])
    # Mark contour edges so a geometry-nodes pass can draw them as lines.
    groups = {"feature": FEATURES, "oval": FACE_OVAL, "eyes": LEFT_EYE + RIGHT_EYE}
    for attr, pairs in groups.items():
        want = {tuple(sorted(p)) for p in pairs}
        a = ob.data.attributes.new(attr, "BOOLEAN", "EDGE")
        for e in ob.data.edges:
            a.data[e.index].value = tuple(sorted(e.vertices)) in want
    return ob


def eye_center(s):
    V, _ = load()
    pts = [V[i] for i in EYE[s]["up"] + EYE[s]["lo"]]
    return tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))


def weights(c):
    """Controls -> shape key weights."""
    w = {}
    pos = lambda v: max(0.0, v)  # noqa: E731
    for s in ("L", "R"):
        w["blink_" + s] = min(1.0, pos(c["lid_" + s]))
        w["eye_wide_" + s] = min(1.0, pos(-c["lid_" + s]) * 3 + pos(c["eye_size"] - 1) * 1.5)
        w["squint_" + s] = min(1.0, c["squint_" + s] * 0.9)
        w["brow_up_" + s] = pos(c["brow_" + s])
        w["brow_down_" + s] = min(1.0, pos(-c["brow_" + s]) + 0.8 * pos(-c["worry_" + s]) + 0.5 * pos(c["slant_" + s]))
        w["brow_worry_" + s] = min(1.0, pos(c["worry_" + s]) + 0.4 * pos(-c["slant_" + s]))
        sm = c["smile"] + (0.6 if s == "L" else -0.6) * c["mouth_skew"]
        w["smile_" + s] = pos(sm)
        w["frown_" + s] = pos(-sm)
        w["wide_" + s] = pos(c["mouth_wide"])
        w["pucker_" + s] = pos(-c["mouth_wide"])
    w["jaw_open"] = min(1.0, c["mouth_open"])
    return w


def lines_modifier(ob, mat, attr="feature", radius=0.06):
    """Draw the edges flagged with `attr` as tubes. Runs after the shape
    keys, so the lines follow the expression."""
    ng = bpy.data.node_groups.new("Lines_" + attr, "GeometryNodeTree")
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N = ng.nodes.new
    gi, go = N("NodeGroupInput"), N("NodeGroupOutput")
    na = N("GeometryNodeInputNamedAttribute")
    na.data_type = "BOOLEAN"
    na.inputs["Name"].default_value = attr
    m2c = N("GeometryNodeMeshToCurve")
    circ = N("GeometryNodeCurvePrimitiveCircle")
    circ.inputs["Resolution"].default_value = 6
    circ.inputs["Radius"].default_value = radius
    c2m = N("GeometryNodeCurveToMesh")
    sm = N("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = mat
    L = ng.links.new
    L(gi.outputs[0], m2c.inputs["Mesh"])
    L(na.outputs[0], m2c.inputs["Selection"])
    L(m2c.outputs[0], c2m.inputs["Curve"])
    L(circ.outputs[0], c2m.inputs["Profile Curve"])
    L(c2m.outputs[0], sm.inputs["Geometry"])
    L(sm.outputs[0], go.inputs[0])
    ob.modifiers.new("Lines", "NODES").node_group = ng

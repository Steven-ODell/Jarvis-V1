import QtQuick
import QtQuick.Shapes
import QtQuick.Effects
import "bands.js" as Bands
import "rig.js" as Rig

// The glyph face: two morphing neon eyes and a mouth line. Same rig and
// shapes as faces/concepts/glyph, drawn live.
Item {
    id: face

    property string mode: "idle"
    property string mood: "neutral"
    property real target: 0          // voice loudness 0..1
    property real appear: 1
    property bool animate: visible
    // bare: no backdrop, driven from outside (the visor shows this face as
    // a texture on its glass and steps the shared rig itself).
    property bool bare: false

    property var rig: new Rig.Rig()
    property var c: rig.c
    property color col: "#b07cf5"
    property real glow: 1
    property var eyeL: []
    property var eyeR: []
    property var mouth: []

    readonly property var eyeShapes: Bands.eyeShapes()
    readonly property var mouthShapes: Bands.mouthShapes()
    readonly property real k: width / 2.3   // face units -> px

    opacity: bare ? 1 : Math.min(1, appear)
    scale: bare ? 1 : 0.6 + 0.4 * Math.min(1, appear)

    function rebuild() {
        const c = face.c;
        const a = -c.head_roll * Math.PI / 180, ca = Math.cos(a), sa = Math.sin(a);
        const rx = c.head_yaw * 0.012, ry = -c.head_pitch * 0.01;
        const w = width / 2, h = height / 2, k = face.k;
        function toPx(fx, fy) {
            return Qt.point(w + (fx * ca - fy * sa + rx) * k, h - (fx * sa + fy * ca + ry) * k);
        }
        function eye(s, sx) {
            const wide = 1 - 0.6 * Math.min(c["lid_" + s], 0);
            const size = 0.25 * c.eye_size * (1 + 0.08 * c.look_x * sx);
            const lx = sx * 0.6 + c.look_x * 0.12, ly = 0.14 + c.look_y * 0.09 + c["brow_" + s] * 0.05;
            const scx = sx * size * 0.95, scy = size * wide * (1 + 0.08 * c["brow_" + s]);
            const b = Bands.blend(face.eyeShapes, Bands.eyeWeights(c, s));
            return Bands.outline(b, (x, y) => toPx(lx + x * scx, ly + y * scy));
        }
        eyeL = eye("L", 1);
        eyeR = eye("R", -1);
        const mb = Bands.blend(face.mouthShapes, Bands.mouthWeights(c));
        const mx = c.look_x * 0.05, my = -0.43 + c.look_y * 0.03;
        mouth = Bands.outline(mb, (x, y) => toPx(mx + x * 0.18, my + y * 0.18));
        col = Qt.rgba(Math.min(1, c.col_r * 1.05), Math.min(1, c.col_g * 1.05), Math.min(1, c.col_b * 1.05), 1);
        glow = c.glow;
    }

    FrameAnimation {
        running: face.animate && !face.bare
        onTriggered: {
            face.rig.step(frameTime, face.mode, face.mood, face.target);
            face.rebuild();
        }
    }

    Backdrop {
        anchors.fill: parent
        visible: !face.bare
    }

    // Halo first (a blurred copy of the shapes), crisp shapes on top.
    MultiEffect {
        source: shapes
        anchors.fill: shapes
        autoPaddingEnabled: true
        blurEnabled: true
        blur: 1.0
        blurMax: 40
        brightness: 0.35
        saturation: 0.3
        opacity: Math.min(1, face.glow)
    }

    Shape {
        id: shapes
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: face.col
            strokeColor: "transparent"
            PathPolyline { path: face.eyeL }
        }
        ShapePath {
            fillColor: face.col
            strokeColor: "transparent"
            PathPolyline { path: face.eyeR }
        }
        ShapePath {
            fillColor: face.col
            strokeColor: "transparent"
            PathPolyline { path: face.mouth }
        }
    }
}

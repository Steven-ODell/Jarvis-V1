import QtQuick
import QtQuick3D
import "rig.js" as Rig

// The holo face live: points, wireframe, feature lines and a rim-lit skin,
// all morphing together. Meshes come from faces/blender/export_live.py.
Item {
    id: face

    property string mode: "idle"
    property string mood: "neutral"
    property real target: 0
    property real appear: 1
    property bool animate: visible

    property var rig: new Rig.Rig()
    property var c: ({})
    property color col: "#b07cf5"
    property real glowK: 1
    property real time: 0
    property real band: 0
    property real glitch: 0
    property real nextGlitch: 4

    opacity: Math.min(1, appear)
    scale: 0.6 + 0.4 * Math.min(1, appear)

    FaceMorphs { id: morphs }

    component HoloMat: CustomMaterial {
        property color tint: face.col
        property real glow: face.glowK
        property real time: face.time
        property real band: face.band
        property real base: 1
        property real rim: 0
        shadingMode: CustomMaterial.Unshaded
        sourceBlend: CustomMaterial.One
        destinationBlend: CustomMaterial.One
        cullMode: Material.NoCulling
        depthDrawMode: Material.NeverDepthDraw
        vertexShader: "holo/holo.vert"
        fragmentShader: "holo/holo.frag"
    }

    Backdrop { anchors.fill: parent }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            tonemapMode: SceneEnvironment.TonemapModeNone
        }

        PerspectiveCamera {
            position: Qt.vector3d(0, 0, 640)
            eulerRotation.x: -Math.atan2(5, 640) * 180 / Math.PI
            fieldOfView: 2 * Math.atan(18 / 62) * 180 / Math.PI
            fieldOfViewOrientation: PerspectiveCamera.Horizontal
            clipNear: 10
            clipFar: 3000
        }

        // Meshes are in meters (Blender units); the scene is in cm.
        Node {
        scale: Qt.vector3d(100, 100, 100)

        Model {
            source: "holo/meshes/base_mesh.mesh"
            position: Qt.vector3d(0, -1, -0.4)
            materials: HoloMat { base: 0.9 }
        }

        Node {
            id: head
            position: Qt.vector3d(face.glitch * 0.04, -1, -0.4)
            eulerRotation: Qt.vector3d(face.c.head_pitch || 0, (face.c.head_yaw || 0) * 1.3, -(face.c.head_roll || 0))

            Model {
                source: "holo/meshes/skin_mesh.mesh"
                morphTargets: morphs.targets
                materials: HoloMat { base: 1.1; rim: 1 }
            }
            Model {
                source: "holo/meshes/wire_mesh.mesh"
                morphTargets: morphs.targets
                materials: HoloMat { base: 0.9 }
            }
            Model {
                source: "holo/meshes/points_mesh.mesh"
                morphTargets: morphs.targets
                materials: HoloMat { base: 3.0 }
            }
            Model {
                source: "holo/meshes/lines_mesh.mesh"
                morphTargets: morphs.targets
                materials: HoloMat { base: 2.6 }
            }
            Node {
                id: eyeL
                property var off: face.parts ? face.parts.eyeL : [0, 0, 0]
                position: Qt.vector3d(off[0], off[1], off[2])
                eulerRotation: Qt.vector3d(-22 * (face.c.look_y || 0), 28 * (face.c.look_x || 0), 0)
                scale: Qt.vector3d(face.eyeScale("L"), face.eyeScale("L") * face.eyeSquash("L"), 1)
                Model { source: "holo/meshes/eyeL_mesh.mesh"; materials: HoloMat { base: 3.5 } }
            }
            Node {
                id: eyeR
                property var off: face.parts ? face.parts.eyeR : [0, 0, 0]
                position: Qt.vector3d(off[0], off[1], off[2])
                eulerRotation: Qt.vector3d(-22 * (face.c.look_y || 0), 28 * (face.c.look_x || 0), 0)
                scale: Qt.vector3d(face.eyeScale("R"), face.eyeScale("R") * face.eyeSquash("R"), 1)
                Model { source: "holo/meshes/eyeR_mesh.mesh"; materials: HoloMat { base: 3.5 } }
            }
        }
        }
    }

    // Eyeball centres relative to the head pivot, from parts.json.
    property var parts: ({ eyeL: [0.379, 1.317, 0.665], eyeR: [-0.379, 1.317, 0.665] })
    function eyeScale(s) { return face.c.eye_size || 1; }
    function eyeSquash(s) {
        const lid = Math.min(1, Math.max(0, face.c["lid_" + s] || 0));
        return Math.max(0.04, 1 - Math.pow(lid, 1.5));
    }

    FrameAnimation {
        running: face.animate
        onTriggered: {
            const c = face.rig.step(frameTime, face.mode, face.mood, face.target);
            morphs.apply(Rig.faceWeights(c));
            face.time += Math.min(frameTime, 0.05);
            face.band = 9.5 - ((face.time / 2.6) % 1.0) * 22;
            // A short horizontal tear now and then sells it as projected light.
            if (face.time > face.nextGlitch) {
                face.glitch = Math.random() < 0.5 ? 1 : -1;
                face.nextGlitch = face.time + 4 + Math.random() * 7;
            } else if (face.glitch !== 0 && face.time > face.nextGlitch - 3.93) {
                face.glitch = 0;
            }
            face.col = Qt.rgba(c.col_r, c.col_g, c.col_b, 1);
            face.glowK = c.glow * (1 + 0.8 * Math.abs(face.glitch) + 0.25 * c.talk);
            face.c = Object.assign({}, c);
        }
    }
}

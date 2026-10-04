import QtQuick
import QtQuick3D
import "rig.js" as Rig

// The android live: porcelain mask on a dark head, black glass eyes with
// glowing irises, light in the mouth that brightens with the voice.
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
    // Eyeball centres relative to the head pivot, from android/parts.json.
    readonly property var eyeL: [0.379, 1.411, 0.623]
    readonly property var eyeR: [-0.379, 1.411, 0.623]

    opacity: Math.min(1, appear)
    scale: 0.6 + 0.4 * Math.min(1, appear)

    FaceMorphs { id: morphs }

    Backdrop { anchors.fill: parent }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            position: Qt.vector3d(0, 10, 700)
            eulerRotation.x: -Math.atan2(10, 700) * 180 / Math.PI
            fieldOfView: 2 * Math.atan(18 / 58) * 180 / Math.PI
            fieldOfViewOrientation: PerspectiveCamera.Horizontal
            clipNear: 10
            clipFar: 3000
        }

        Studio { key: 0.8 }

        Node {
            scale: Qt.vector3d(100, 100, 100)
            Node {
                position: Qt.vector3d(0, -1.1, -0.4)
                eulerRotation: Qt.vector3d(face.c.head_pitch || 0, (face.c.head_yaw || 0) * 1.3, -(face.c.head_roll || 0))

                Model {
                    source: "android/meshes/mask_mesh.mesh"
                    morphTargets: morphs.targets
                    materials: PrincipledMaterial { baseColor: "#cfcdd6"; roughness: 0.32; clearcoatAmount: 0.6 }
                }
                Model {
                    source: "android/meshes/liner_mesh.mesh"
                    morphTargets: morphs.targets
                    materials: glow
                }
                Model {
                    source: "android/meshes/seam_mesh.mesh"
                    morphTargets: morphs.targets
                    materials: glow
                }
                Model {
                    source: "android/meshes/metal_mesh.mesh"
                    materials: PrincipledMaterial { baseColor: "#3a3946"; roughness: 0.25; metalness: 0.3 }
                }
                Model {
                    source: "android/meshes/cavity_mesh.mesh"
                    materials: PrincipledMaterial { baseColor: "#060608"; roughness: 0.6 }
                }
                Model {
                    source: "android/meshes/mouthglow_mesh.mesh"
                    materials: PrincipledMaterial {
                        lighting: PrincipledMaterial.NoLighting
                        baseColor: Qt.rgba(face.col.r * k, face.col.g * k, face.col.b * k, 1)
                        property real k: Math.min(1, 0.12 + 1.2 * (face.c.talk || 0))
                    }
                }
                Node {
                    position: Qt.vector3d(face.eyeL[0], face.eyeL[1], face.eyeL[2])
                    eulerRotation: Qt.vector3d(-20 * (face.c.look_y || 0), 26 * (face.c.look_x || 0), 0)
                    Model { source: "android/meshes/ballL_mesh.mesh"; materials: glass }
                    Model { source: "android/meshes/irisL_mesh.mesh"; materials: glow }
                }
                Node {
                    position: Qt.vector3d(face.eyeR[0], face.eyeR[1], face.eyeR[2])
                    eulerRotation: Qt.vector3d(-20 * (face.c.look_y || 0), 26 * (face.c.look_x || 0), 0)
                    Model { source: "android/meshes/ballR_mesh.mesh"; materials: glass }
                    Model { source: "android/meshes/irisR_mesh.mesh"; materials: glow }
                }
            }
        }
    }

    PrincipledMaterial { id: glow; lighting: PrincipledMaterial.NoLighting; baseColor: face.col }
    PrincipledMaterial { id: glass; baseColor: "#030304"; roughness: 0.05; clearcoatAmount: 1 }

    FrameAnimation {
        running: face.animate
        onTriggered: {
            const c = face.rig.step(frameTime, face.mode, face.mood, face.target);
            morphs.apply(Rig.faceWeights(c));
            face.col = Qt.rgba(c.col_r, c.col_g, c.col_b, 1);
            face.c = Object.assign({}, c);
        }
    }
}

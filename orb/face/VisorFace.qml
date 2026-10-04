import QtQuick
import QtQuick3D
import "rig.js" as Rig

// The visor head live. The glyph face is drawn offscreen and used as the
// glass's emissive texture, so the eyes are the same shapes, on a head that
// tilts, turns and nods.
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

    opacity: Math.min(1, appear)
    scale: 0.6 + 0.4 * Math.min(1, appear)

    Backdrop { anchors.fill: parent }

    View3D {
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
        }

        PerspectiveCamera {
            position: Qt.vector3d(0, 15, 720)
            eulerRotation.x: -Math.atan2(20, 720) * 180 / Math.PI
            fieldOfView: 2 * Math.atan(18 / 70) * 180 / Math.PI
            fieldOfViewOrientation: PerspectiveCamera.Horizontal
            clipNear: 10
            clipFar: 3000
        }

        Studio {}

        Node {
            scale: Qt.vector3d(100, 100, 100)
            Node {
                position: Qt.vector3d(0, -1.05, 0)
                Model {
                    source: "visor/meshes/neck_mesh.mesh"
                    materials: metal
                }
                Node {
                    eulerRotation: Qt.vector3d((face.c.head_pitch || 0) * 0.8, (face.c.head_yaw || 0) * 1.4, -(face.c.head_roll || 0) * 0.8)
                    Model {
                        source: "visor/meshes/shell_mesh.mesh"
                        materials: PrincipledMaterial { baseColor: "#f4f2fa"; roughness: 0.3; clearcoatAmount: 0.6 }
                    }
                    Model {
                        source: "visor/meshes/metal_mesh.mesh"
                        materials: metal
                    }
                    Model {
                        source: "visor/meshes/rings_mesh.mesh"
                        materials: PrincipledMaterial { lighting: PrincipledMaterial.NoLighting; baseColor: face.col }
                    }
                    Model {
                        source: "visor/meshes/glass_mesh.mesh"
                        materials: PrincipledMaterial {
                            baseColor: "#040406"
                            roughness: 0.07
                            clearcoatAmount: 1
                            emissiveFactor: Qt.vector3d(1.4, 1.4, 1.4)
                            emissiveMap: Texture {
                                flipV: true
                                sourceItem: GlyphFace {
                                    id: glyph
                                    width: 512
                                    height: 512
                                    bare: true
                                    rig: face.rig
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    PrincipledMaterial { id: metal; baseColor: "#2a2833"; roughness: 0.3; metalness: 0.2 }

    FrameAnimation {
        running: face.animate
        onTriggered: {
            const c = face.rig.step(frameTime, face.mode, face.mood, face.target);
            glyph.rebuild();
            face.col = Qt.rgba(c.col_r, c.col_g, c.col_b, 1);
            face.c = Object.assign({}, c);
        }
    }
}

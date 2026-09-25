import QtQuick

// The shader orb. Set `mode` and feed `target` (0..1 loudness); everything
// else eases on its own so state changes never snap.
ShaderEffect {
    id: orb

    property string mode: "idle"      // idle | listening | thinking | speaking | error
    property real target: 0
    property bool animate: visible

    // Uniforms (names must match orb.frag).
    property real time: 0
    property real level: 0
    property real appear: 1
    property real swirl: mode === "thinking" ? 3.2 : mode === "speaking" ? 1.7 : mode === "listening" ? 1.2 : 0.7
    property real think: mode === "thinking" ? 1 : 0
    property real ripple: mode === "listening" ? 1 : 0
    property color colA: (palette[mode] || palette.idle)[0]
    property color colB: (palette[mode] || palette.idle)[1]
    property color colC: (palette[mode] || palette.idle)[2]

    readonly property var palette: ({
        "idle":      ["#2a1466", "#7c4dff", "#b9a4ff"],
        "listening": ["#3b0f9e", "#a855f7", "#7dd3fc"],
        "thinking":  ["#1b1f8a", "#3b82f6", "#e879f9"],
        "speaking":  ["#4c0f99", "#d946ef", "#e9d5ff"],
        "error":     ["#5c0f2a", "#f43f5e", "#fecdd3"]
    })

    Behavior on swirl { NumberAnimation { duration: 700; easing.type: Easing.InOutQuad } }
    Behavior on think { NumberAnimation { duration: 450 } }
    Behavior on ripple { NumberAnimation { duration: 350 } }
    Behavior on colA { ColorAnimation { duration: 550 } }
    Behavior on colB { ColorAnimation { duration: 550 } }
    Behavior on colC { ColorAnimation { duration: 550 } }

    blending: true
    fragmentShader: Qt.resolvedUrl("shaders/orb.frag.qsb")

    FrameAnimation {
        running: orb.animate
        onTriggered: {
            const dt = Math.min(frameTime, 0.05);
            orb.time += dt;
            // Fast attack, slower release: syllables punch, silence settles.
            const goal = orb.mode === "thinking" ? 0.12 + 0.08 * Math.sin(orb.time * 3.0) : orb.target;
            const rate = goal > orb.level ? 22 : 7;
            orb.level += (goal - orb.level) * (1 - Math.exp(-dt * rate));
        }
    }
}

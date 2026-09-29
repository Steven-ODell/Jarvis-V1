import QtQuick

// The hologram orb. Set `mode` and feed `target` (0..1 loudness); everything
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
    property real dial: 0
    property real gyro: 0
    property real wave: 0
    property real listen: mode === "listening" ? 1 : 0
    property real think: mode === "thinking" ? 1 : 0
    property real speak: mode === "speaking" ? 1 : 0
    property color colA: (palette[mode] || palette.idle)[0]
    property color colB: (palette[mode] || palette.idle)[1]
    property color colC: (palette[mode] || palette.idle)[2]

    // Speeds in rad/s. The frame loop integrates them into dial/gyro/wave,
    // so easing a speed changes the pace without the rings jumping.
    property real dialSpeed: mode === "thinking" ? 1.4 : mode === "speaking" ? 0.3 : mode === "listening" ? 0.22 : 0.08
    property real gyroSpeed: mode === "thinking" ? 2.6 : mode === "speaking" ? 0.9 : mode === "listening" ? 0.6 : 0.28
    property real waveSpeed: mode === "thinking" ? 3.0 : mode === "speaking" ? 5.0 : mode === "listening" ? 3.5 : 1.2

    // [ring base, bright lines, accent]
    readonly property var palette: ({
        "idle":      ["#6d3fd9", "#b07cf5", "#c29cf8"],
        "listening": ["#7c4dff", "#b07cf5", "#5ef1ff"],
        "thinking":  ["#5b3fe0", "#8b5cf6", "#e879f9"],
        "speaking":  ["#8b3fe8", "#c084fc", "#f0abfc"],
        "error":     ["#9f1239", "#ff5ea0", "#fecdd3"]
    })

    Behavior on dialSpeed { NumberAnimation { duration: 800; easing.type: Easing.InOutQuad } }
    Behavior on gyroSpeed { NumberAnimation { duration: 800; easing.type: Easing.InOutQuad } }
    Behavior on waveSpeed { NumberAnimation { duration: 600 } }
    Behavior on listen { NumberAnimation { duration: 400 } }
    Behavior on think { NumberAnimation { duration: 450 } }
    Behavior on speak { NumberAnimation { duration: 400 } }
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
            orb.dial += dt * orb.dialSpeed;
            orb.gyro += dt * orb.gyroSpeed;
            orb.wave += dt * orb.waveSpeed;
            // Fast attack, slower release: syllables punch, silence settles.
            const goal = orb.mode === "thinking" ? 0.12 + 0.08 * Math.sin(orb.time * 3.0) : orb.target;
            const rate = goal > orb.level ? 22 : 7;
            orb.level += (goal - orb.level) * (1 - Math.exp(-dt * rate));
        }
    }
}

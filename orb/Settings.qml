import QtQuick
import Quickshell
import Quickshell.Wayland

// Settings panel. Every control sends one `set` to the daemon, which saves
// ~/.config/jarvis/config.toml and echoes the new config back, so the panel
// always shows what's actually on disk.
PanelWindow {
    id: panel

    property bool open: false
    property var cfg: ({})
    property var opts: ({})
    property var status: ({})
    property string font: "JetBrainsMono Nerd Font"

    signal dismissed
    signal changed(string key, var value)
    signal command(var obj)

    function val(section, key, fallback) {
        return cfg[section] && cfg[section][key] !== undefined ? cfg[section][key] : fallback;
    }

    readonly property color accent: "#a855f7"
    readonly property color fg: "#ede9fe"
    readonly property color dim: "#8b7fb0"
    readonly property color card: "#f0110b1f"

    visible: open
    color: "transparent"
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "jarvis-settings"
    WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None

    // ---------------------------------------------------------- components

    component SectionTitle: Text {
        color: panel.accent
        font.family: panel.font
        font.pixelSize: 11
        font.bold: true
        font.letterSpacing: 2
        topPadding: 10
    }

    component Label: Text {
        color: panel.fg
        font.family: panel.font
        font.pixelSize: 13
    }

    component Hint: Text {
        color: panel.dim
        font.family: panel.font
        font.pixelSize: 11
        wrapMode: Text.Wrap
    }

    component Switch: Rectangle {
        id: sw
        property bool checked: false
        signal toggled(bool value)
        width: 42
        height: 22
        radius: 11
        color: checked ? panel.accent : "#2a2440"
        border.color: checked ? "#c084fc" : "#3d3558"
        Behavior on color { ColorAnimation { duration: 150 } }
        Rectangle {
            width: 16
            height: 16
            radius: 8
            y: 3
            x: sw.checked ? sw.width - width - 3 : 3
            color: "white"
            Behavior on x { NumberAnimation { duration: 150; easing.type: Easing.OutCubic } }
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: sw.toggled(!sw.checked)
        }
    }

    component Pills: Flow {
        id: pills
        property var model: []
        property string current: ""
        property var labels: ({})
        signal picked(string value)
        spacing: 6
        Repeater {
            model: pills.model
            Rectangle {
                required property string modelData
                readonly property bool on: modelData === pills.current
                width: pillText.implicitWidth + 22
                height: 26
                radius: 13
                color: on ? "#3b1d6e" : "#1c1830"
                border.color: on ? panel.accent : "#342c4f"
                Behavior on color { ColorAnimation { duration: 120 } }
                Text {
                    id: pillText
                    anchors.centerIn: parent
                    text: pills.labels[parent.modelData] || parent.modelData.replace(/_/g, " ")
                    color: parent.on ? "white" : panel.dim
                    font.family: panel.font
                    font.pixelSize: 12
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: pills.picked(parent.modelData)
                }
            }
        }
    }

    component Slider: Item {
        id: sl
        property real from: 0
        property real to: 1
        property real value: 0
        property real step: 0.05
        signal moved(real value)
        width: 200
        height: 22
        readonly property real frac: Math.max(0, Math.min(1, (value - from) / (to - from)))
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: 4
            radius: 2
            color: "#2a2440"
            Rectangle {
                width: parent.width * sl.frac
                height: parent.height
                radius: 2
                color: panel.accent
            }
        }
        Rectangle {
            x: sl.frac * (sl.width - width)
            anchors.verticalCenter: parent.verticalCenter
            width: 16
            height: 16
            radius: 8
            color: "white"
            border.color: panel.accent
            border.width: 2
        }
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            property real pending: sl.value
            function at(mx) {
                const raw = sl.from + Math.max(0, Math.min(1, mx / sl.width)) * (sl.to - sl.from);
                return Math.round(raw / sl.step) * sl.step;
            }
            onPressed: mouse => { pending = at(mouse.x); sl.value = pending }
            onPositionChanged: mouse => { if (pressed) { pending = at(mouse.x); sl.value = pending } }
            onReleased: sl.moved(Number(pending.toFixed(2)))
        }
    }

    component SettingRow: Item {
        default property alias content: slot.data
        property alias label: lbl.text
        property alias hint: hintText.text
        width: parent ? parent.width : 400
        height: Math.max(slot.childrenRect.height, lbl.implicitHeight + (hintText.text ? hintText.implicitHeight + 2 : 0)) + 6
        Label { id: lbl; y: 3 }
        Hint { id: hintText; anchors.top: lbl.bottom; anchors.topMargin: 2; width: parent.width * 0.5; visible: text !== "" }
        Item {
            id: slot
            anchors.right: parent.right
            y: 1
            width: childrenRect.width
            height: childrenRect.height
        }
    }

    // --------------------------------------------------------------- layout

    Rectangle {
        anchors.fill: parent
        color: "#80050309"
        MouseArea {
            anchors.fill: parent
            onClicked: panel.dismissed()
        }
    }

    Rectangle {
        id: cardRect
        anchors.centerIn: parent
        width: 560
        height: Math.min(parent.height - 80, body.implicitHeight + 48)
        radius: 22
        color: panel.card
        border.color: "#4d7c4dff"
        border.width: 1
        focus: panel.open
        Keys.onEscapePressed: panel.dismissed()

        MouseArea { anchors.fill: parent }  // swallow clicks so the backdrop doesn't close us

        Flickable {
            anchors.fill: parent
            anchors.margins: 24
            contentHeight: body.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds

            Column {
                id: body
                width: parent.width
                spacing: 10

                Row {
                    spacing: 14
                    Orb {
                        width: 54
                        height: 54
                        mode: "speaking"
                        target: 0.15
                        animate: panel.visible
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 2
                        Text {
                            text: "Jarvis"
                            color: "white"
                            font.family: panel.font
                            font.pixelSize: 20
                            font.bold: true
                        }
                        Hint {
                            text: {
                                const s = panel.status;
                                if (!s.rss_mb) return "SUPER + A to talk";
                                const total = Object.values(s.rss_mb).reduce((a, b) => a + b, 0);
                                return (s.online ? "online" : "offline") + " · " + s.model + (s.fast ? " fast" : "") +
                                       (s.claude_running ? " (warm)" : "") + " · " + total + " MB resident";
                            }
                        }
                    }
                }

                SectionTitle { text: "WAKE WORD" }
                SettingRow {
                    label: "Listen for a wake word"
                    hint: "Keeps the mic open. The hotkey always works."
                    Switch {
                        checked: panel.val("wake", "enabled", false)
                        onToggled: v => panel.changed("wake.enabled", v)
                    }
                }
                Pills {
                    width: parent.width
                    model: panel.opts.wake_models || []
                    current: panel.val("wake", "model", "hey_jarvis")
                    onPicked: v => panel.changed("wake.model", v)
                    opacity: panel.val("wake", "enabled", false) ? 1 : 0.45
                }
                SettingRow {
                    label: "Sensitivity"
                    hint: "Higher hears you from further away, false-triggers more."
                    Slider {
                        from: 0.2
                        to: 0.9
                        // Shown as sensitivity, stored as threshold: they run opposite ways.
                        value: 1.1 - panel.val("wake", "threshold", 0.5)
                        onMoved: v => panel.changed("wake.threshold", Number((1.1 - v).toFixed(2)))
                    }
                }
                SettingRow {
                    label: "Beat after wake word  " + (panel.val("wake", "grace_ms", 1200) / 1000).toFixed(1) + " s"
                    hint: "Silence this soon after \"Hey Jarvis\" won't end your turn."
                    Slider {
                        from: 0.5
                        to: 3.0
                        step: 0.1
                        value: panel.val("wake", "grace_ms", 1200) / 1000
                        onMoved: v => panel.changed("wake.grace_ms", Math.round(v * 1000))
                    }
                }

                SectionTitle { text: "BRAIN" }
                SettingRow {
                    label: "Claude model"
                    Pills {
                        model: panel.opts.brain_models || []
                        current: panel.val("brain", "model", "sonnet")
                        onPicked: v => panel.changed("brain.model", v)
                    }
                }
                SettingRow {
                    label: "Fast mode"
                    hint: "Opus only. About 1 s quicker with tools, roughly double the usage."
                    Switch {
                        checked: panel.val("brain", "fast", false)
                        onToggled: v => panel.changed("brain.fast", v)
                    }
                }
                SettingRow {
                    label: "Keep Claude warm"
                    hint: "Off: starts on the hotkey, exits after " + panel.val("brain", "idle_exit_min", 5) + " idle min."
                    Switch {
                        checked: panel.val("brain", "keep_warm", false)
                        onToggled: v => panel.changed("brain.keep_warm", v)
                    }
                }
                SettingRow {
                    label: "Offline fallback"
                    hint: (panel.val("local", "endpoints", []) || []).join(", ")
                    Label { text: panel.val("local", "model", ""); color: panel.dim }
                }

                SectionTitle { text: "VOICE" }
                Pills {
                    width: parent.width
                    model: panel.opts.voices || []
                    current: panel.val("voice", "voice", "am_michael")
                    onPicked: v => {
                        panel.changed("voice.voice", v);
                        panel.command({ cmd: "say", text: "This is how I sound." });
                    }
                }
                SettingRow {
                    label: "Speed  " + Number(panel.val("voice", "speed", 1.25)).toFixed(2) + "×"
                    Slider {
                        from: 0.8
                        to: 1.7
                        value: panel.val("voice", "speed", 1.25)
                        onMoved: v => panel.changed("voice.speed", v)
                    }
                }
                SettingRow {
                    label: "Speak confirmations"
                    hint: "\"Opening GitHub.\" for instant commands."
                    Switch {
                        checked: panel.val("voice", "acks", true)
                        onToggled: v => panel.changed("voice.acks", v)
                    }
                }

                SectionTitle { text: "LISTENING" }
                SettingRow {
                    label: "Speech model"
                    hint: "base.en is ~0.4 s, small.en ~1.2 s and a bit sharper."
                    Pills {
                        model: panel.opts.whisper_models || []
                        current: panel.val("listen", "whisper_model", "base.en")
                        onPicked: v => panel.changed("listen.whisper_model", v)
                    }
                }
                SettingRow {
                    label: "Listen for follow-ups"
                    hint: "Reopens the mic when Jarvis asks a question."
                    Switch {
                        checked: panel.val("listen", "follow_up", true)
                        onToggled: v => panel.changed("listen.follow_up", v)
                    }
                }
                SettingRow {
                    label: "Pause media while talking"
                    Switch {
                        checked: panel.val("listen", "pause_media", true)
                        onToggled: v => panel.changed("listen.pause_media", v)
                    }
                }

                SectionTitle { text: "CODING" }
                SettingRow {
                    label: "\"Let's code\" opens"
                    hint: "Neovim starts with recently worked-on files as buffers. Say \"with Claude\" or \"in Neovim\" to override once."
                    Pills {
                        model: panel.opts.code_opens || []
                        labels: ({ "nvim": "Neovim", "claude": "Claude Code" })
                        current: panel.val("code", "open", "nvim")
                        onPicked: v => panel.changed("code.open", v)
                    }
                }

                SectionTitle { text: "LOOK" }
                SettingRow {
                    label: "Orb style"
                    Pills {
                        model: panel.opts.orb_styles || []
                        current: panel.val("orb", "style", "hologram")
                        onPicked: v => panel.changed("orb.style", v)
                    }
                }
                SettingRow {
                    label: "Orb position"
                    Pills {
                        model: panel.opts.positions || []
                        current: panel.val("orb", "position", "bottom")
                        onPicked: v => panel.changed("orb.position", v)
                    }
                }
                SettingRow {
                    label: "Search engine"
                    Pills {
                        model: panel.opts.search_engines || []
                        current: panel.val("search", "engine", "google")
                        onPicked: v => panel.changed("search.engine", v)
                    }
                }

                Item { width: 1; height: 6 }
                Row {
                    spacing: 8
                    anchors.horizontalCenter: parent.horizontalCenter
                    Repeater {
                        model: [
                            { label: "New conversation", cmd: { cmd: "reset" } },
                            { label: "Close", cmd: null }
                        ]
                        Rectangle {
                            required property var modelData
                            width: btnText.implicitWidth + 28
                            height: 30
                            radius: 15
                            color: btnMouse.containsMouse ? "#3b1d6e" : "#1c1830"
                            border.color: "#4d7c4dff"
                            Text {
                                id: btnText
                                anchors.centerIn: parent
                                text: parent.modelData.label
                                color: panel.fg
                                font.family: panel.font
                                font.pixelSize: 12
                            }
                            MouseArea {
                                id: btnMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: parent.modelData.cmd ? panel.command(parent.modelData.cmd) : panel.dismissed()
                            }
                        }
                    }
                }
            }
        }
    }
}

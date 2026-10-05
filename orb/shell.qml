//@ pragma Env QS_NO_RELOAD_POPUP=1
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Hyprland
import "face"

// Jarvis's face: the orb overlay plus the settings panel. All state comes
// from the daemon over its unix socket; this file only draws it.
ShellRoot {
    id: root

    property string mode: "idle"
    property string mood: "neutral"
    property real level: 0
    property string heard: ""
    property string reply: ""
    property string tool: ""
    property bool shown: false
    property bool settingsOpen: false
    property var cfg: ({})
    property var opts: ({})
    property var status: ({})

    readonly property string position: (cfg.orb && cfg.orb.position) || "bottom"
    readonly property int orbSize: (cfg.orb && cfg.orb.size) || 230
    readonly property string orbStyle: (cfg.orb && cfg.orb.style) || "hologram"
    readonly property string font: "JetBrainsMono Nerd Font"

    function send(obj) {
        if (sock.connected) {
            sock.write(JSON.stringify(obj) + "\n");
            sock.flush();
        }
    }

    function handle(m) {
        if (m.ev === undefined) {
            if (m.rss_mb !== undefined) root.status = m;
            return;
        }
        switch (m.ev) {
        case "hello":
            root.mode = m.state;
            root.cfg = m.config;
            root.opts = m.options;
            break;
        case "state":
            root.mode = m.state;
            if (m.state === "idle") {
                const len = root.reply.length + root.heard.length;
                hideTimer.interval = len ? Math.min(9000, 1800 + root.reply.length * 45) : 500;
                hideTimer.restart();
            } else {
                hideTimer.stop();
                root.shown = true;
            }
            break;
        case "listen":
            root.mood = "neutral";
            moodTimer.stop();
            root.heard = "";
            root.reply = "";
            root.tool = "";
            root.level = 0;
            break;
        case "level":
            root.level = m.v;
            break;
        case "mood":
            // A reaction to what he said has a hold time; Claude's own
            // tags last until the next one or the end of the turn.
            root.mood = m.mood;
            if (m.hold) {
                moodTimer.interval = m.hold * 1000;
                moodTimer.restart();
            } else {
                moodTimer.stop();
            }
            break;
        case "heard":
            root.heard = m.text;
            if (m.text === "") root.tool = "didn't catch that";
            break;
        case "reply":
            if (m.delta !== undefined) root.reply += m.delta;
            else if (m.done && m.text) root.reply = m.text;
            break;
        case "tool":
            root.tool = m.text;
            break;
        case "error":
            root.tool = "⚠ " + m.text;
            break;
        case "config":
            root.cfg = m.config;
            root.opts = m.options;
            break;
        case "settings":
            root.settingsOpen = m.open === "toggle" ? !root.settingsOpen : !!m.open;
            break;
        }
    }

    Socket {
        id: sock
        path: Quickshell.env("JARVIS_SOCKET") || (Quickshell.env("XDG_RUNTIME_DIR") + "/jarvis.sock")
        connected: true
        onConnectedChanged: {
            if (connected) {
                write('{"cmd":"subscribe"}\n');
                flush();
            }
        }
        parser: SplitParser {
            onRead: line => {
                try {
                    root.handle(JSON.parse(line));
                } catch (e) {
                    console.warn("bad line from daemon:", line);
                }
            }
        }
    }

    // The daemon may start after us or restart under us; keep dialing.
    Timer {
        interval: 1000
        running: !sock.connected
        repeat: true
        onTriggered: sock.connected = true
    }

    Timer {
        id: hideTimer
        onTriggered: {
            root.shown = false;
            root.mood = "neutral";
        }
    }

    Timer {
        id: moodTimer
        onTriggered: root.mood = "neutral"
    }

    Timer {
        interval: 2000
        running: root.settingsOpen
        repeat: true
        triggeredOnStart: true
        onTriggered: root.send({ cmd: "status" })
    }

    function focusedScreen() {
        const name = Hyprland.focusedMonitor ? Hyprland.focusedMonitor.name : "";
        for (let i = 0; i < Quickshell.screens.length; i++)
            if (Quickshell.screens[i].name === name) return Quickshell.screens[i];
        return Quickshell.screens[0];
    }

    // ------------------------------------------------------------------ orb

    PanelWindow {
        id: orbWin

        property real appear: root.shown ? 1 : 0
        Behavior on appear {
            NumberAnimation {
                duration: root.shown ? 520 : 380
                easing.type: root.shown ? Easing.OutBack : Easing.InCubic
                easing.overshoot: 2.2
            }
        }

        // The window stays mapped. Hiding a layer-shell window destroys its
        // surface and showing it builds a new one, which moves the content
        // into a new QQuickWindow, and Qt Quick 3D segfaults on that move
        // (QQuick3DSceneManager::setWindow; crashed 2026-10-03 and 10-04).
        // So the content hides instead; the empty mask lets clicks through.
        readonly property bool showing: appear > 0.002
        visible: true
        // A screen change rebuilds the window the same way, so it only
        // happens while hidden, with the 3D face unloaded first.
        property bool moving: false
        Component.onCompleted: screen = root.focusedScreen()
        function follow() {
            if (root.focusedScreen() === screen) return;
            moving = true;
            moveTimer.start();
        }
        Timer {
            id: moveTimer
            interval: 60
            onTriggered: {
                orbWin.screen = root.focusedScreen();
                Qt.callLater(() => orbWin.moving = false);
            }
        }
        Connections {
            target: root
            function onShownChanged() {
                if (root.shown) orbWin.follow();
            }
        }
        color: "transparent"
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "jarvis-orb"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        // Clicks go straight through to whatever is underneath.
        mask: Region {}

        anchors.bottom: root.position === "bottom"
        anchors.top: root.position === "top"
        margins.bottom: 40
        margins.top: 40

        implicitWidth: 680
        implicitHeight: root.orbSize + 190

        Item {
            anchors.fill: parent
            visible: orbWin.showing

            Item {
                id: orb
                // How far out from the center the captions sit, as a
                // fraction of the quad: past the dial ring, or hugging the
                // sphere (the plasma glow needs the extra room).
                readonly property real rim: root.orbStyle === "plasma" ? 0.26 : root.orbStyle === "glyph" ? 0.36 : 0.45
                // The 3D faces load by URL so a machine without Qt Quick 3D
                // (pacman -S qt6-quick3d) only loses those styles; the
                // hologram stands in if one fails to load.
                readonly property string url: ({ visor: "face/VisorFace.qml", holo: "face/HoloFace.qml", android: "face/AndroidFace.qml",
                                                 clawd: "face/ClawdFace.qml" })[root.orbStyle] || ""
                width: root.orbSize
                height: root.orbSize
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.position === "top" ? 0 : parent.height - height

                Loader {
                    anchors.fill: parent
                    active: orb.url === "" || face3d.status === Loader.Error
                    sourceComponent: root.orbStyle === "plasma" ? plasmaOrb : root.orbStyle === "glyph" ? glyphFace : hologramOrb
                }

                Loader {
                    id: face3d
                    anchors.fill: parent
                    source: orbWin.moving ? "" : orb.url
                    onLoaded: {
                        item.mode = Qt.binding(() => root.mode);
                        item.mood = Qt.binding(() => root.mood);
                        item.target = Qt.binding(() => root.level);
                        item.appear = Qt.binding(() => Math.max(0, orbWin.appear));
                        item.animate = Qt.binding(() => orbWin.showing);
                    }
                }
            }

            Component {
                id: hologramOrb
                Orb {
                    mode: root.mode
                    target: root.level
                    appear: Math.max(0, orbWin.appear)
                    animate: orbWin.showing
                }
            }

            Component {
                id: glyphFace
                GlyphFace {
                    mode: root.mode
                    mood: root.mood
                    target: root.level
                    appear: Math.max(0, orbWin.appear)
                    animate: orbWin.showing
                }
            }

            Component {
                id: plasmaOrb
                PlasmaOrb {
                    mode: root.mode
                    target: root.level
                    appear: Math.max(0, orbWin.appear)
                    animate: orbWin.showing
                }
            }

            Rectangle {
                id: captions
                readonly property bool hasText: root.heard !== "" || root.reply !== "" || root.tool !== ""
                anchors.horizontalCenter: parent.horizontalCenter
                y: root.position === "top" ? orb.y + orb.height * (0.5 + orb.rim) + 8 : orb.y + orb.height * (0.5 - orb.rim) - height - 8
                width: Math.min(620, Math.max(textCol.implicitWidth + 44, 180))
                height: textCol.implicitHeight + 24
                radius: 18
                color: "#c80d0819"
                border.color: "#337c4dff"
                border.width: 1
                opacity: hasText ? Math.min(1, orbWin.appear) : 0
                Behavior on opacity { NumberAnimation { duration: 220 } }

                Column {
                    id: textCol
                    anchors.centerIn: parent
                    width: Math.min(576, implicitWidth)
                    spacing: 6

                    Text {
                        visible: text !== ""
                        width: Math.min(576, implicitWidth)
                        anchors.horizontalCenter: parent.horizontalCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        maximumLineCount: 2
                        elide: Text.ElideRight
                        text: root.heard
                        color: "#b9a4ff"
                        font.family: root.font
                        font.pixelSize: 13
                        font.italic: true
                    }

                    Text {
                        visible: text !== ""
                        width: Math.min(576, implicitWidth)
                        anchors.horizontalCenter: parent.horizontalCenter
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        maximumLineCount: 5
                        elide: Text.ElideRight
                        text: {
                            const r = root.reply.trim();
                            return r.length > 300 ? "…" + r.slice(-300) : r;
                        }
                        color: "#f5f0ff"
                        font.family: root.font
                        font.pixelSize: 15
                    }

                    Row {
                        visible: root.tool !== ""
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 7

                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: "#e879f9"
                            SequentialAnimation on opacity {
                                running: root.mode === "thinking"
                                loops: Animation.Infinite
                                NumberAnimation { to: 0.2; duration: 450 }
                                NumberAnimation { to: 1; duration: 450 }
                            }
                        }
                        Text {
                            text: root.tool
                            color: "#a78bfa"
                            font.family: root.font
                            font.pixelSize: 11
                            font.letterSpacing: 0.5
                        }
                    }
                }
            }
        }
    }

    // ------------------------------------------------------------- settings

    Settings {
        open: root.settingsOpen
        screen: root.focusedScreen()
        cfg: root.cfg
        opts: root.opts
        status: root.status
        font: root.font
        onDismissed: root.settingsOpen = false
        onChanged: (key, value) => root.send({ cmd: "set", key: key, value: value })
        onCommand: obj => root.send(obj)
    }
}

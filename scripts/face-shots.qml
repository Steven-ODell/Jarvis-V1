import QtQuick
import QtQuick.Window

// Off-screen face snapshots: no layer-shell window, nothing on screen.
//   QT_QPA_PLATFORM=offscreen qml scripts/face-shots.qml -- <Face.qml> <outdir> [size]
// Steps through states and moods and saves one PNG per shot.
Window {
    id: win
    readonly property var args: Qt.application.arguments.slice(Qt.application.arguments.indexOf("--") + 1)
    readonly property string faceUrl: Qt.resolvedUrl("../orb/face/" + args[0])
    readonly property string out: args[1]
    width: Number(args[2] || 400)
    height: width
    visible: true
    color: "#0b0910"
    title: "jarvis-facetest"

    // [name, mode, mood, level, settle seconds]
    readonly property var shots: [
        ["idle", "idle", "neutral", 0, 1.6],
        ["listening", "listening", "neutral", 0, 1.2],
        ["thinking", "thinking", "neutral", 0, 1.4],
        ["speaking", "speaking", "neutral", 0.7, 0.6],
        ["happy", "speaking", "happy", 0.2, 1.4],
        ["sad", "speaking", "sad", 0.0, 1.4],
        ["surprised", "speaking", "surprised", 0.0, 1.2],
        ["confused", "speaking", "confused", 0.0, 1.2],
        ["sleepy", "idle", "sleepy", 0, 1.6],
    ]
    property int i: 0

    Loader {
        id: face
        anchors.fill: parent
        source: win.faceUrl
        onStatusChanged: if (status === Loader.Error) { console.log("load failed"); Qt.exit(2) }
        onLoaded: next.start()
    }

    Timer {
        id: next
        interval: 10
        onTriggered: {
            const s = win.shots[win.i];
            face.item.mode = s[1];
            if ("mood" in face.item) face.item.mood = s[2];
            face.item.target = s[3];
            shoot.interval = s[4] * 1000;
            shoot.start();
        }
    }
    Timer {
        id: shoot
        onTriggered: face.grabToImage(r => {
            const name = win.shots[win.i][0];
            r.saveToFile(win.out + "/" + name + ".png");
            console.log("shot", name);
            if (++win.i >= win.shots.length) Qt.exit(0); else next.start();
        })
    }
}

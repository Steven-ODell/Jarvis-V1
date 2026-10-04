import QtQuick

// Dark glass behind a face so it reads over any wallpaper: stacked discs,
// each a little wider and fainter, for a soft edge.
Item {
    id: bd
    property real size: 0.92
    Repeater {
        model: 8
        Rectangle {
            required property int index
            anchors.centerIn: parent
            width: bd.width * (bd.size + index * 0.035)
            height: width
            radius: width / 2
            color: "#07040f"
            opacity: index === 0 ? 0.82 : 0.12
        }
    }
}

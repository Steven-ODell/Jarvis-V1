import QtQuick
import QtQuick3D

// The Blender studio rig as directional lights: soft key upper left, cool
// fill right, purple and cyan rims behind (Quick3D allows four).
Node {
    function aim(x, y, z) {
        return Qt.vector3d(-Math.atan2(y, Math.hypot(x, z)) * 180 / Math.PI, Math.atan2(x, z) * 180 / Math.PI, 0);
    }
    property real key: 1.0
    DirectionalLight { eulerRotation: aim(-3, 5, 3); brightness: 1.9 * key; ambientColor: "#2a2433" }
    DirectionalLight { eulerRotation: aim(6, -1, 0.5); brightness: 0.45; color: "#ccd9ff" }
    DirectionalLight { eulerRotation: aim(-3, 1.5, -3.5); brightness: 1.6; color: "#b07cf5" }
    DirectionalLight { eulerRotation: aim(3.2, 1, -3); brightness: 1.3; color: "#5ef1ff" }
}

import QtQuick
import QtQuick3D
import "rig.js" as Rig

// One MorphTarget per face-mesh shape key, in export order, shared by every
// model built from the face mesh so a single apply() moves them all.
QtObject {
    id: m
    property var targets: []

    Component.onCompleted: {
        const t = [];
        for (const k of Rig.FACE_KEYS)
            t.push(Qt.createQmlObject("import QtQuick3D; MorphTarget { attributes: MorphTarget.Position | MorphTarget.Normal }", m, k));
        targets = t;
    }

    function apply(w) {
        for (let i = 0; i < targets.length; i++)
            targets[i].weight = w[Rig.FACE_KEYS[i]] || 0;
    }
}

#!/usr/bin/env bash
# Rebuild the live 3D faces: Blender export, then balsam into Quick3D meshes.
#   faces/blender/export-live.sh [visor holo android]
# balsam ships with qt6-quick3d and needs assimp (pacman -S assimp) to read
# glTF; only this step needs it, the orb itself loads the .mesh files.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
face=$(cd "$here/../../orb/face" && pwd)
balsam=${BALSAM:-/usr/lib/qt6/bin/balsam}
[ $# -eq 0 ] && set -- visor holo android
nice blender -b --factory-startup --python "$here/export_live.py" -- "$@" 2>&1 | grep -E "^exported|Error|Traceback" || true
for c in "$@"; do
  rm -rf "${face:?}/$c/meshes"
  "$balsam" -o "$face/$c" "$face/$c/$c.glb" >/dev/null
  # balsam also writes a demo QML scene; the face components replace it.
  rm -f "$face/$c/"[A-Z]*.qml
done

# Jarvis faces (concept round)

Four face designs, each acting out the same reel: idle, listening,
thinking, speaking (with a real Jarvis voice line), happy, confused, sad,
surprised, sleepy, back to idle. Pick one or mix parts and say what to change.

| Concept | Look | Feel |
|---|---|---|
| `concepts/glyph` | Flat neon eyes and a mouth line on black | Most robot, cartoon-cute; could run live as a QML shader with no assets |
| `concepts/visor` | White robot head with the glyph face on a black glass visor | Robot with a body: the head tilts, turns and nods |
| `concepts/holo` | Human face as a hologram: points, wireframe, scanlines | Human expressions, clearly digital; closest to the current orb |
| `concepts/android` | Porcelain mask on a dark head, glowing eyes, light in the mouth | Most human; the face moves like a face |

Each folder has `reel.mp4` (about 23 s, with sound) and `sheet.jpg` (one
frame per expression). `compare.mp4` plays all four side by side.

`voices/` has the same line in other Kokoro voices, for a face that
doesn't suit the British butler.

## How it works

- `blender/expr.py` holds the expressions. Every face is driven by the same
  ~25 controls (gaze, lids, brows, mouth, head angle, glow, color). A pose
  is a set of targets, and each control chases its target with a damped
  spring, so changing expression mid-transition is always smooth. Eyes are
  fast, the head is heavy and overshoots a touch. Blinks, glances and
  breathing ride on top. The live orb would run the same loop.
- `blender/shapes2d.py`: glyph and visor eyes/mouths as morphable bands.
- `blender/facemesh.py`: holo and android are built on MediaPipe's
  canonical face mesh (Apache-2.0) with expression shape keys sculpted in
  code. Shape keys export to glTF as morph targets.
- `blender/render-all.sh [concept ...]` renders, encodes and builds the
  sheets. About 12 minutes per concept on the laptop.
- One concept's stills only: `blender -b --factory-startup --python
  faces/blender/<concept>.py -- --stills`. Add `--blend` to save the
  .blend and open it in Blender.

## Live faces

The orb runs these for real: `jarvis set orb.style glyph` (or `visor`,
`holo`, `android`, back to `hologram`). The face follows Jarvis's state and
mood: Claude tags its sentences with a mood as it writes, the tags are
stripped before the voice reads them, and what you say gets an instant
reaction ("no way" looks surprised). The 3D styles need
`sudo pacman -S qt6-quick3d`; without it they show the hologram.
After changing a 3D face in Blender, rebuild its meshes with
`faces/blender/export-live.sh <face>`.

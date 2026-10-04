#!/usr/bin/env bash
# Render each concept's reel, then encode it with the voice line and build
# a labelled contact sheet. One concept at a time; EEVEE uses the GPU.
#   faces/blender/render-all.sh [concept ...]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
faces=$(dirname "$here")
concepts=("$@")
[ ${#concepts[@]} -eq 0 ] && concepts=(glyph visor holo android)
for c in "${concepts[@]}"; do
  out="$faces/concepts/$c"
  rm -rf "$out/frames"
  start=$(date +%s)
  nice blender -b --factory-startup --python "$here/$c.py" -- >"$out.log" 2>&1
  echo "$c: rendered in $(( $(date +%s) - start ))s"
  speech=$(awk '/^speech_start/ {print $2}' "$out/timing.txt")
  ffmpeg -loglevel error -y -framerate 30 -i "$out/frames/f%04d.png" \
    -itsoffset "$speech" -i "$faces/assets/line.wav" \
    -map 0:v -map 1:a -c:v libx264 -crf 18 -preset slow -pix_fmt yuv420p \
    -c:a aac -b:a 128k "$out/reel.mp4"
  # Contact sheet: one frame from each pose (75% through its hold).
  args=()
  while read -r pose f0 f1; do
    [ "$pose" = speech_start ] && continue
    f=$(( f0 + (f1 - f0) * 3 / 4 ))
    [ "$pose" = speaking ] && f=$(( f0 + (f1 - f0) * 45 / 100 ))
    args+=(-label "$pose" "$(printf "$out/frames/f%04d.png" "$f")")
  done < <(head -n 10 "$out/timing.txt" | tail -n 9)
  magick montage "${args[@]}" -tile 3x3 -geometry 400x400+6+6 -background '#111' \
    -fill '#c29cf8' -pointsize 22 -quality 88 "$out/sheet.jpg"
  rm -rf "$out/frames" "$out/stills"
done

# All four side by side, once every reel exists.
c="$faces/concepts"
if [ -f "$c/glyph/reel.mp4" ] && [ -f "$c/visor/reel.mp4" ] && [ -f "$c/holo/reel.mp4" ] && [ -f "$c/android/reel.mp4" ]; then
  font=$(fc-match -f '%{file}' "sans:bold")
  lab() { echo "scale=480:480,drawtext=fontfile=$font:text=$1:x=14:y=12:fontsize=22:fontcolor=0xc29cf8"; }
  ffmpeg -loglevel error -y -i "$c/glyph/reel.mp4" -i "$c/visor/reel.mp4" -i "$c/holo/reel.mp4" -i "$c/android/reel.mp4" \
    -filter_complex "[0:v]$(lab glyph)[a];[1:v]$(lab visor)[b];[2:v]$(lab holo)[c];[3:v]$(lab android)[d];[a][b][c][d]xstack=inputs=4:layout=0_0|w0_0|0_h0|w0_h0[v]" \
    -map "[v]" -map 0:a -c:v libx264 -crf 20 -pix_fmt yuv420p -c:a aac "$faces/compare.mp4"
  echo "compare.mp4 written"
fi

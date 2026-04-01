#!/usr/bin/env bash
set -euo pipefail

SRC_DIR="/home/Python_Files/us_army_drone_team_webpage/static/img/Drone_Pics"
OUT_DIR="Drone_Pics_jpg"
QUALITY=92

mkdir -p "$OUT_DIR"

# Pick available ImageMagick command
if command -v magick >/dev/null 2>&1; then
  IM_CMD="magick"
elif command -v convert >/dev/null 2>&1; then
  IM_CMD="convert"
else
  echo "Error: Neither 'magick' nor 'convert' found in PATH."
  echo "Try: which magick && which convert"
  exit 1
fi

echo "Using ImageMagick command: $IM_CMD"

i=1
while IFS= read -r f; do
  out="$OUT_DIR/$(printf "%04d" "$i").jpg"
  echo "Converting: $f -> $out"

  if [[ "$IM_CMD" == "magick" ]]; then
    magick "$f" -auto-orient -background black -alpha remove -alpha off \
      -strip -sampling-factor 4:2:0 -quality "$QUALITY" "$out"
  else
    convert "$f" -auto-orient -background black -alpha remove -alpha off \
      -strip -sampling-factor 4:2:0 -quality "$QUALITY" "$out"
  fi

  i=$((i+1))
done < <(
  find "$SRC_DIR" -maxdepth 1 -type f \( \
    -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.heic' -o -iname '*.heif' \
  \) | sort
)

echo "Done. Converted files in: $OUT_DIR"
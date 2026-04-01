#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Drone Showcase Builder
# - Takes all images from static/img/Drone_Pics
# - Builds a Ken Burns slideshow
# - Prepends drone_intro.mp4
# - Optionally adds background music if provided
# ============================================

# -------- Config (edit if you want) --------
IMG_DIR="static/img/Drone_Pics"
INTRO_VIDEO="drone_intro.mp4"
OUT_VIDEO="drone_showcase.mp4"

# Optional: set to a music file path, or leave empty ("")
# MUSIC_FILE="soundtrack.mp3"
MUSIC_FILE=""

# Per-image duration in seconds
DURATION_PER_IMAGE="2.5"

# Output video settings
WIDTH=1920
HEIGHT=1080
FPS=30

# ------------------------------------------

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: '$1' is required but not installed."
    exit 1
  }
}

need_cmd ffmpeg
need_cmd ffprobe
need_cmd find
need_cmd sort
need_cmd awk
need_cmd mktemp

if [[ ! -f "$INTRO_VIDEO" ]]; then
  echo "Error: Intro video not found: $INTRO_VIDEO"
  exit 1
fi

if [[ ! -d "$IMG_DIR" ]]; then
  echo "Error: Image directory not found: $IMG_DIR"
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

slides_txt="$tmpdir/slides.txt"
concat_txt="$tmpdir/concat.txt"
slideshow_mp4="$tmpdir/slides.mp4"
intro_norm_mp4="$tmpdir/intro_norm.mp4"
joined_mp4="$tmpdir/joined.mp4"

echo "Collecting images from: $IMG_DIR"

# Collect supported image types, sorted
mapfile -t images < <(
  find "$IMG_DIR" -maxdepth 1 -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.bmp' \) \
    | sort
)

if [[ "${#images[@]}" -eq 0 ]]; then
  echo "Error: No images found in $IMG_DIR"
  exit 1
fi

echo "Found ${#images[@]} image(s). Building slideshow list..."

# Build ffmpeg concat list with duration per image
: > "$slides_txt"
for img in "${images[@]}"; do
  # Escape single quotes for ffmpeg concat file syntax
  esc_img="${img//\'/\'\\\'\'}"
  printf "file '%s'\n" "$esc_img" >> "$slides_txt"
  printf "duration %s\n" "$DURATION_PER_IMAGE" >> "$slides_txt"
done
# Repeat last image once (required by concat demuxer duration behavior)
last_img="${images[-1]}"
last_esc="${last_img//\'/\'\\\'\'}"
printf "file '%s'\n" "$last_esc" >> "$slides_txt"

echo "Rendering slideshow..."
ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$slides_txt" \
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,\
pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2,\
zoompan=z='min(zoom+0.0008,1.12)':d=$(awk "BEGIN{printf \"%d\", $DURATION_PER_IMAGE*$FPS}"):s=${WIDTH}x${HEIGHT}:fps=${FPS},\
format=yuv420p" \
  -r "$FPS" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  "$slideshow_mp4"

echo "Normalizing intro video format..."
ffmpeg -y -hide_banner -loglevel error \
  -i "$INTRO_VIDEO" \
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,\
pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
  -r "$FPS" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  "$intro_norm_mp4"

echo "Concatenating intro + slideshow..."
printf "file '%s'\n" "$intro_norm_mp4" > "$concat_txt"
printf "file '%s'\n" "$slideshow_mp4" >> "$concat_txt"

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$concat_txt" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$joined_mp4"

if [[ -n "$MUSIC_FILE" ]]; then
  if [[ ! -f "$MUSIC_FILE" ]]; then
    echo "Warning: MUSIC_FILE set but not found: $MUSIC_FILE"
    echo "Writing video without background music."
    cp "$joined_mp4" "$OUT_VIDEO"
  else
    echo "Adding background music..."
    ffmpeg -y -hide_banner -loglevel error \
      -stream_loop -1 -i "$MUSIC_FILE" \
      -i "$joined_mp4" \
      -map 1:v:0 -map 0:a:0 \
      -filter:a "volume=0.20" \
      -shortest \
      -c:v copy -c:a aac -b:a 192k \
      -movflags +faststart \
      "$OUT_VIDEO"
  fi
else
  cp "$joined_mp4" "$OUT_VIDEO"
fi

echo "Done! Output video: $OUT_VIDEO"
#!/usr/bin/env bash
set -euo pipefail

# =========================================================
# FINAL Drone Showcase Script
# - Normalizes mixed images to a clean numbered JPG sequence
# - Builds slideshow with fixed per-image duration
# - Normalizes intro video
# - Concatenates intro + title card + slideshow
# - Optionally overlays background music
# =========================================================

# ---------------- CONFIG ----------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Put your source images here (mixed jpg/jpeg/png/heic/heif are okay if IM supports them)
SRC_IMG_DIR="$SCRIPT_DIR/Drone_Pics_jpg"

# Temp normalized sequence will be written here
SEQ_IMG_DIR="$SCRIPT_DIR/.drone_seq"

INTRO_VIDEO="$SCRIPT_DIR/drone_intro.mp4"
OUT_VIDEO="$SCRIPT_DIR/drone_showcase.mp4"

# Optional music (leave empty to skip)
MUSIC_FILE="$SCRIPT_DIR/soundtrack.mp3"
#MUSIC_FILE=""

# Seconds each image stays on screen
DURATION_PER_IMAGE="2.5"

# Output format
WIDTH=1920
HEIGHT=1080
FPS=30
# ----------------------------------------

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Error: '$1' is required but not installed."
    exit 1
  }
}

need_cmd ffmpeg
need_cmd find
need_cmd sort
need_cmd realpath
need_cmd mktemp

# Pick ImageMagick command
if command -v magick >/dev/null 2>&1; then
  IM_CMD="magick"
elif command -v convert >/dev/null 2>&1; then
  IM_CMD="convert"
else
  echo "Error: Need ImageMagick ('magick' or 'convert') to normalize images."
  exit 1
fi

# Resolve absolute paths
SRC_IMG_DIR="$(realpath "$SRC_IMG_DIR")"
INTRO_VIDEO="$(realpath "$INTRO_VIDEO")"
OUT_VIDEO="$(realpath -m "$OUT_VIDEO")"
SEQ_IMG_DIR="$(realpath -m "$SEQ_IMG_DIR")"

if [[ ! -d "$SRC_IMG_DIR" ]]; then
  echo "Error: Source image directory not found: $SRC_IMG_DIR"
  exit 1
fi

if [[ ! -f "$INTRO_VIDEO" ]]; then
  echo "Error: Intro video not found: $INTRO_VIDEO"
  exit 1
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

intro_norm_mp4="$tmpdir/intro_norm.mp4"
slideshow_mp4="$tmpdir/slideshow.mp4"
joined_mp4="$tmpdir/joined.mp4"
concat_txt="$tmpdir/concat.txt"

echo "Using ImageMagick command: $IM_CMD"
echo "Source images: $SRC_IMG_DIR"
echo "Intro video:   $INTRO_VIDEO"

# ---------------------------------------------------------
# 1) Normalize all source images into contiguous sequence
# ---------------------------------------------------------
echo "Normalizing images into sequence..."
mkdir -p "$SEQ_IMG_DIR"
rm -f "$SEQ_IMG_DIR"/*.jpg

mapfile -t src_images < <(
  find "$SRC_IMG_DIR" -maxdepth 1 -type f \
    \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' -o -iname '*.bmp' -o -iname '*.heic' -o -iname '*.heif' \) \
    | sort
)

if [[ "${#src_images[@]}" -eq 0 ]]; then
  echo "Error: No images found in $SRC_IMG_DIR"
  exit 1
fi

i=1
for f in "${src_images[@]}"; do
  out="$SEQ_IMG_DIR/$(printf "%04d.jpg" "$i")"
  echo "  [$i/${#src_images[@]}] $(basename "$f") -> $(basename "$out")"

  if [[ "$IM_CMD" == "magick" ]]; then
    magick "$f" -auto-orient -background black -alpha remove -alpha off \
      -strip -colorspace sRGB -quality 95 "$out"
  else
    convert "$f" -auto-orient -background black -alpha remove -alpha off \
      -strip -colorspace sRGB -quality 95 "$out"
  fi

  i=$((i+1))
done

total_frames=$((i-1))
echo "Built normalized sequence: $total_frames frame(s) in $SEQ_IMG_DIR"

# Adding split 
SPLIT_AFTER_PHOTO=11
split_time="$(awk "BEGIN {print $SPLIT_AFTER_PHOTO * $DURATION_PER_IMAGE}")"

# ---------------------------------------------------------
# 2) Build slideshow from numbered sequence
# ---------------------------------------------------------
echo "Rendering slideshow..."
ffmpeg -y -hide_banner -loglevel error \
  -framerate "1/${DURATION_PER_IMAGE}" \
  -start_number 1 \
  -i "$SEQ_IMG_DIR/%04d.jpg" \
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,\
pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
  -r "$FPS" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  "$slideshow_mp4"

part_a_mp4="$tmpdir/slideshow_part_a.mp4"
part_b_mp4="$tmpdir/slideshow_part_b.mp4"

# Part A: start -> split_time
ffmpeg -y -hide_banner -loglevel error \
  -i "$slideshow_mp4" \
  -t "$split_time" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  "$part_a_mp4"

# Part B: split_time -> end
ffmpeg -y -hide_banner -loglevel error \
  -i "$slideshow_mp4" \
  -ss "$split_time" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  "$part_b_mp4"

# ---------------------------------------------------------
# 3) Normalize intro video to same format
# ---------------------------------------------------------
echo "Normalizing intro video..."
ffmpeg -y -hide_banner -loglevel error \
  -i "$INTRO_VIDEO" \
  -vf "scale=${WIDTH}:${HEIGHT}:force_original_aspect_ratio=decrease,\
pad=${WIDTH}:${HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=yuv420p" \
  -r "$FPS" \
  -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p \
  -c:a aac -b:a 192k \
  "$intro_norm_mp4"

# ---------------------------------------------------------
# 4) Create Title Cards
# ---------------------------------------------------------
echo "Creating Title Card..."
title_mp4="$tmpdir/title_card.mp4"
ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "color=c=black:s=${WIDTH}x${HEIGHT}:d=3.5:r=${FPS}" \
  -vf "drawtext=text='US Army Drone Team':fontcolor=white:fontsize=72:x=(w-text_w)/2:y=(h-text_h)/2-40,\
drawtext=text='December 2025':fontcolor=white:fontsize=46:x=(w-text_w)/2:y=(h-text_h)/2+40,\
format=yuv420p" \
  -c:v libx264 -pix_fmt yuv420p \
  "$title_mp4"

title2_mp4="$tmpdir/title_card_2.mp4"

ffmpeg -y -hide_banner -loglevel error \
  -f lavfi -i "color=c=black:s=${WIDTH}x${HEIGHT}:d=3.0:r=${FPS}" \
  -vf "drawtext=text='US Army Best Drone Operator Competition':fontcolor=white:fontsize=68:x=(w-text_w)/2:y=(h-text_h)/2-20,\
drawtext=text='February 2026':fontcolor=white:fontsize=42:x=(w-text_w)/2:y=(h-text_h)/2+50,\
format=yuv420p" \
  -c:v libx264 -pix_fmt yuv420p \
  "$title2_mp4"

# ---------------------------------------------------------
# 5) Concatenate intro + title card + slideshow
# ---------------------------------------------------------
echo "Concatenating..."

printf "file '%s'\n" "$intro_norm_mp4" > "$concat_txt"
printf "file '%s'\n" "$title_mp4" >> "$concat_txt"
printf "file '%s'\n" "$part_a_mp4" >> "$concat_txt"
printf "file '%s'\n" "$title2_mp4" >> "$concat_txt"
printf "file '%s'\n" "$part_b_mp4" >> "$concat_txt"

ffmpeg -y -hide_banner -loglevel error \
  -f concat -safe 0 -i "$concat_txt" \
  -c:v libx264 -preset medium -crf 18 \
  -c:a aac -b:a 192k \
  -movflags +faststart \
  "$joined_mp4"

# ---------------------------------------------------------
# 6) Optional background music
# ---------------------------------------------------------
if [[ -n "$MUSIC_FILE" ]]; then
  MUSIC_FILE="$(realpath "$MUSIC_FILE")"
  if [[ ! -f "$MUSIC_FILE" ]]; then
    echo "Warning: MUSIC_FILE set but not found: $MUSIC_FILE"
    echo "Writing video without background music."
    cp "$joined_mp4" "$OUT_VIDEO"
  else
    echo "Adding background music..."
    ffmpeg -y -hide_banner -loglevel warning \
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

echo
echo "Done!"
echo "Output video: $OUT_VIDEO"
echo "Slides used:  $total_frames"
echo "Approx slideshow duration (sec): $(awk "BEGIN {print $total_frames * $DURATION_PER_IMAGE}")"


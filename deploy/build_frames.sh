#!/usr/bin/env bash
# Build the runtime frames/ directory the app reads (config.FRAME_DIR) from the
# committed original_frames/ assets, mapping bare names -> the _01 names that
# frames_metadata/frames.json references. Idempotent.
set -e
cd "$(dirname "$0")/.."   # repo root
mkdir -p frames
while read -r dst src; do
  [ -z "$dst" ] && continue
  if [ -f "original_frames/$src" ]; then
    cp -f "original_frames/$src" "frames/$dst"
  else
    echo "WARN: source missing: original_frames/$src"
  fi
done <<'MAP'
diwali_01.png diwali.png
christmas_01.png christmas.png
onam_01.png onam.png
independence_day_01.png independence_day.png
dussehra_01.png dussehra.png
lohri_01.png lohri.png
eid_01.png edi.png
ganesh_chaturthi_01.png ganesh_chaturthi.png
MAP
echo "Frames built:"; ls -1 frames

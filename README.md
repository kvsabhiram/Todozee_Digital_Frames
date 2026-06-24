# v4 patch — face-centric crop ("glow the face")

## What this fixes
- Family photos appearing tiny inside the slot — now the face area is the
  focal point (head + shoulders), no more tiny figures lost in the middle.
- Single-person photos in small slots (Independence Day, Eid, etc.) — the
  face now fills the slot prominently instead of sitting small at the top.
- Multi-face support: for group/family photos the crop is computed from
  the union of all detected faces, so everyone stays in shot.

## What's new
- Adds a face-detection step before cropping.
- Uses RetinaFace if it's installed; otherwise falls back to MediaPipe
  Face Detection (already shipped with the `mediapipe` package — no extra
  install needed for the fallback).

## How to apply

```bash
cd ~/Documents/Digital_Frame

# (optional) backup current processor
cp app/frame_processor.py app/frame_processor.py.v3.bak

# replace the processor
cp /path/to/v4_patch/frame_processor.py app/frame_processor.py

# (optional) update requirements with the new commented retina-face line
cp /path/to/v4_patch/requirements.txt requirements.txt
```

Slot coords and the original frames stay the same as v3 — no changes
needed there.

## Optional: install RetinaFace for slightly higher accuracy

RetinaFace is more robust on side profiles, occluded faces, and low-light
photos than MediaPipe Face Detection. But it pulls TensorFlow (~500 MB).

```bash
source .venv/bin/activate   # or whatever your venv is called
pip install retina-face==0.0.17
```

The code auto-detects RetinaFace at import time. If installed, it uses
it; if not, it silently falls back to MediaPipe Face Detection. You'll
see in `logs/` which path it took:

```
INFO  RetinaFace import OK — using it for face detection
```
or
```
WARN  RetinaFace not available (No module named 'retinaface'); will use MediaPipe
```

## Restart and test

```bash
# Ctrl+C the server, then
bash run.sh
python test_client.py selfie.jpg ganesh_chaturthi_01
python test_client.py family.jpg eid_01
```

You should see the face take up roughly 35–45% of the cropped region's
height, with head + shoulders + a little chest visible.

## Tuning (if needed)

If you want the face even bigger or smaller, edit these three numbers
in `_face_centric_crop()` in `frame_processor.py`:

```python
pad_top    = int(avg_face_h * 0.65)   # increase = more headroom above face
pad_bottom = int(avg_face_h * 2.20)   # decrease = less of the chest visible
pad_sides  = int(avg_face_w * 0.65)   # decrease = tighter side framing
```

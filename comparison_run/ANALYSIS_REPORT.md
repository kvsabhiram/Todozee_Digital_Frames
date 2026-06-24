# Pipeline A/B Analysis Report

**Date:** 2026-05-27
**Run:** 4 photos × 2 pipelines × 8 frames = **64 renders**
**Pipelines:** MediaPipe Selfie Segmentation vs rembg / U²-Net (`u2net_human_seg`)
**Output:** `comparison_run/<resolution>/<pipeline>/<frame_id>.jpg` + `stats.csv` / `stats.json`

> Reconstructed from the surviving `outputs/` renders + run log after the folder was
> deleted. The MediaPipe pipeline/env has since been removed (project is now rembg-only).
>
> Note: the 4 photos are the **same portrait at 4 resolutions** (aspect ratio 1.50 in all
> of them). That makes this a clean controlled experiment — resolution is the only
> variable, so any clarity difference is purely about pixels.

---

## 1. Quantitative summary

| Photo | Dimensions | MP | Face height | Resize scale (8 frames) | Verdict |
|---|---|---|---|---|---|
| 600px  | 640×427   | 0.27 | 205 px | **1.07× – 2.71× (upscale)** | soft → blurry on big slots |
| 1920px | 1920×1281 | 2.46 | 581 px | 0.36× – 0.90× (downscale) | **sharp** |
| 2400px | 2400×1602 | 3.84 | 580 px | 0.29× – 0.72× (downscale) | **sharp** |
| 7360px | 7360×4912 | 36.2 | *0 px (not detected)* | 0.08× – 0.18× (downscale) | tack-sharp |

`resize_scale` = how much the cropped person is stretched to fill the slot.
**>1 = upscaling = blur.** **<1 = downscaling = detail preserved.**

Per-frame demand (biggest slots upscale the most at low res): Ganesh & Lohri are the
most demanding (scale 2.6–2.7× at 600px), Independence Day the least (1.07×, small slot).

---

## 2. Finding #1 — Clarity is driven by RESOLUTION, not the pipeline

This is the dominant result.

- **600px (0.27 MP):** the person is upscaled 2.3–2.7× into the larger slots → visibly
  soft. Only the small Independence-Day slot (≈1×) holds up.
- **1920px (2.46 MP) and up:** every slot now *downscales* the person → consistently
  sharp. The jump from 600px → 1920px is night-and-day.
- **2400px → 7360px:** no visible clarity gain — you're just downscaling more. Beyond
  ~2400px you pay bandwidth/CPU for zero benefit.

**Recommended input: ≥ 1920px on the long side (~2 MP). Sweet spot 1920–2400px.**

---

## 3. Finding #2 — MediaPipe vs rembg is negligible on these photos

Measured alpha-mask coverage on the source:

| Pipeline | Kept (subject) | Removed (background) | Corners |
|---|---|---|---|
| rembg     | 30.4% | 69.0% | all transparent |
| mediapipe | 30.7% | 68.9% | all transparent |

- **Both remove the background cleanly** (corners fully transparent). There is **no
  leftover-background box** — what looks like a box on the Ganesh frame is the frame's
  own gold border + red vignette, not an artifact.
- On these **plain studio backgrounds**, the two pipelines are visually indistinguishable.
- rembg's known edge advantage (fine hair, glasses) only shows up on **busy or
  low-contrast real-world backgrounds** — not present in this test set.

**Verdict:** pipeline choice does **not** affect clarity. We chose **rembg** because it is
more robust when a user's background is unpredictable. (MediaPipe has since been removed.)

---

## 4. Finding #3 — BUG: face detection fails at very high resolution

At **7360px (36 MP), YuNet detected 0 faces** (`max_face_h_px = 0`), so the pipeline
silently fell back to a full-person crop. It looked fine here only because the photo is a
tight head-and-shoulders portrait. On a **full-body or group photo at high resolution**,
losing face detection would break the face-centric framing.

**Fix:** downscale the image to ~1920px *for the detection pass only*, then map the
bounding box back to full resolution. (See recommendations.)

---

## 5. Finding #4 — Cosmetic: torso is cut by a straight bottom edge

The source is a mid-chest portrait, so the segmented person ends in a hard horizontal
line at the bottom. It's invisible on white-slot frames (Diwali) and slightly visible on
dark-slot frames (Ganesh/Eid). Minor; fixable by feathering the bottom or choosing slot
coordinates where the frame art covers the cut.

---

## 6. Recommendations (in priority order)

1. **Enforce a minimum input resolution** — reject/warn if long side < ~1000px or detected
   face < ~150px. The `stats.clarity_hint` field already flags this per request.
2. **Cap very large uploads** — downscale anything over ~2500px (long side) on the server
   before processing. This (a) fixes the 36 MP face-detection bug, (b) cuts CPU/time, and
   (c) costs **zero** quality since everything is downscaled into ≤1300px slots anyway.
3. **Fix YuNet** — run face detection on the capped/downscaled image.
4. **Pipeline = rembg** (done — MediaPipe removed). Don't expect clarity gains from the
   segmenter; that's purely a resolution lever.
5. **(Optional)** feather the torso bottom edge for dark-slot frames.

## 7. Bottom line

> Feed the pipeline a **~2 MP (1920px) photo** and the output is sharp regardless of which
> segmenter is used. The thumbnail blur seen earlier was 100% a resolution problem.
> The pipeline only matters for *edge cleanliness on messy backgrounds* — so we ship rembg,
> and the next wins are: cap oversized uploads at ~2500px and enforce a minimum input size.

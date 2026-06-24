"""
Core image-processing pipeline (v5 — rembg + YuNet + per-frame anchor/fill).

CHANGES vs v4
-------------
1.  Segmentation: replaced MediaPipe Selfie Segmentation with `rembg`
    (U²-Net family). Edges around hair, glasses, shoulders are MUCH
    sharper. No more soft halos against the slot's background colour.

2.  Face detection: replaced MediaPipe / RetinaFace with OpenCV's
    YuNet (cv2.FaceDetectorYN). It's ~230 KB, ships as a single ONNX
    file in models/, has zero extra Python deps, and avoids the
    TensorFlow ↔ protobuf ↔ MediaPipe dependency nightmare entirely.

3.  Per-frame placement: each frame in frames.json can specify
    "anchor": "top" | "center" | "bottom" and "fill": 0.0 – 1.0
    so each festival frame is framed naturally.

4.  Image quality: LANCZOS4 resize, JPEG quality 95, no double-blur
    on the alpha mask.

Pipeline
--------
1. Load user photo (BGR)
2. YuNet face detection           → list of face bboxes
3. rembg segmentation             → BGRA with crisp alpha
4. Face-centric crop              → head + shoulders region
5. Resize to fit slot (per-frame anchor + fill)
6. Alpha composite onto frame
7. Watermark
8. Save as JPG (q=95)
"""

import io   
import json
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any, Tuple, Optional

from PIL import Image

from app.config import settings
from app.logger import setup_logger
from app.schemas import FrameInfo
from app.segmenter import get_segmenter

logger = setup_logger("todozee.processor")


class FrameProcessor:
    def __init__(self):
        self.pipeline = settings.PIPELINE
        logger.info(f"Initializing FrameProcessor (pipeline={self.pipeline}, YuNet faces)")

        # ---- Segmentation backend (rembg / U²-Net) ----
        model_name = getattr(settings, "REMBG_MODEL", "u2net_human_seg")
        self._segmenter = get_segmenter(self.pipeline, model_name)
        # Reflect the backend that actually loaded (factory may have fallen back)
        self.pipeline = getattr(self._segmenter, "name", self.pipeline)

        # ---- YuNet face detector ----
        self._face_detector = self._init_face_detector()

        # ---- frame metadata ----
        self._metadata: Dict[str, Any] = {}
        self._load_metadata()

    # ------------------------------------------------------------------
    # YuNet face detector init
    # ------------------------------------------------------------------
    def _init_face_detector(self) -> Optional[cv2.FaceDetectorYN]:
        model_path = settings.MODELS_DIR / "face_detection_yunet_2023mar.onnx"
        if not model_path.exists():
            logger.error(
                f"YuNet model NOT FOUND at {model_path}. "
                f"Face-centric crop will be disabled (falls back to alpha bbox)."
            )
            return None
        try:
            det = cv2.FaceDetectorYN.create(
                str(model_path), "",
                (320, 320),       # placeholder input size; reset per image
                0.6,              # score threshold
                0.3,              # nms threshold
                5000,             # top-k
            )
            logger.info(f"YuNet face detector loaded ({model_path.name})")
            return det
        except Exception as e:
            logger.exception(f"YuNet failed to initialize: {e}")
            return None

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------
    def _load_metadata(self):
        path = settings.METADATA_FILE
        if not path.exists():
            logger.warning(f"Metadata file missing at {path}.")
            self._metadata = {}
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._metadata = json.load(f)
            logger.info(f"Loaded {len(self._metadata)} frame definitions")
        except Exception as e:
            logger.exception(f"Failed to load metadata: {e}")
            self._metadata = {}

    def reload_metadata(self):
        self._load_metadata()

    def list_frames(self) -> List[FrameInfo]:
        frames = []
        for frame_id, meta in self._metadata.items():
            frames.append(
                FrameInfo(
                    id=frame_id,
                    file=meta["file"],
                    category=meta.get("category", "general"),
                    slot=meta["slot"],
                    preview_url=f"/static/frames/{meta['file']}",
                )
            )
        return frames

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def process(
        self,
        user_image_path: Path,
        frame_id: str,
        request_id: str,
        add_watermark: bool = True,
    ) -> Path:
        logger.info(f"[{request_id}] Starting pipeline (v5)")

        # ---- 1. Validate frame_id ----
        if frame_id not in self._metadata:
            raise FileNotFoundError(
                f"Unknown frame_id '{frame_id}'. Available: {list(self._metadata.keys())}"
            )
        meta = self._metadata[frame_id]
        frame_path = settings.FRAME_DIR / meta["file"]
        if not frame_path.exists():
            raise FileNotFoundError(f"Frame PNG missing: {frame_path}")
        slot = meta["slot"]
        anchor = meta.get("anchor", "center")
        fill = float(meta.get("fill", 0.88))
        logger.info(
            f"[{request_id}] frame={frame_path.name} slot={slot} "
            f"anchor={anchor} fill={fill:.2f}"
        )

        # ---- 2. Load user image ----
        user_img = cv2.imread(str(user_image_path), cv2.IMREAD_COLOR)
        if user_img is None:
            raise ValueError("Could not read uploaded image.")
        logger.info(f"[{request_id}] photo {user_img.shape[1]}x{user_img.shape[0]}")

        # ---- 3. Face detection ----
        faces = self._detect_faces(user_img, request_id)

        # ---- 3a. Reject non-human inputs (no detectable human face) ----
        if not faces:
            logger.info(f"[{request_id}] Rejecting: no human face detected")
            raise ValueError(
                "No human face detected. Please upload a photo with a clearly visible human face."
            )

        # ---- 4. Segmentation (rembg) ----
        person_bgra = self._segment_person(user_img, request_id)

        # ---- 5. Face-centric crop ----
        person_cropped = self._face_centric_crop(person_bgra, faces, request_id)
        crop_h, crop_w = person_cropped.shape[:2]

        # ---- 6. Fit into slot (per-frame anchor + fill) ----
        person_fitted = self._fit_into_slot(
            person_cropped, slot["w"], slot["h"], anchor, fill, request_id
        )

        # ---- Clarity stats (the resize factor is what drives sharpness) ----
        scale = min((slot["w"] * fill) / max(1, crop_w),
                    (slot["h"] * fill) / max(1, crop_h))
        max_face_h = max((f[3] for f in faces), default=0)
        stats = {
            "pipeline": self.pipeline,
            "photo_w": int(user_img.shape[1]),
            "photo_h": int(user_img.shape[0]),
            "faces_detected": len(faces),
            "max_face_h_px": int(max_face_h),
            "person_crop_w": int(crop_w),
            "person_crop_h": int(crop_h),
            "resize_scale": round(float(scale), 3),   # >1 = upscaling = blur risk
            "upscaled": bool(scale > 1.0),
            "clarity_hint": self._clarity_hint(scale, max_face_h),
        }
        logger.info(f"[{request_id}] clarity stats={stats}")

        # ---- 7. Load original frame ----
        frame_img = cv2.imread(str(frame_path), cv2.IMREAD_COLOR)
        if frame_img is None:
            raise ValueError(f"Could not read frame: {frame_path}")

        # ---- 8. Composite ----
        final = self._composite_person_onto_frame(
            person_fitted, frame_img, slot, request_id
        )

        # ---- 9. Watermark ----
        if add_watermark:
            final = self._add_watermark_bgr(final, request_id)

        # ---- 10. Save (filename tagged with pipeline for easy A/B comparison) ----
        out_name = f"{request_id}_{self.pipeline}_{frame_id}.{settings.OUTPUT_FORMAT}"
        out_path = settings.OUTPUT_DIR / out_name
        if settings.OUTPUT_FORMAT.lower() in ("jpg", "jpeg"):
            cv2.imwrite(
                str(out_path), final,
                [cv2.IMWRITE_JPEG_QUALITY, settings.OUTPUT_QUALITY],
            )
        else:
            cv2.imwrite(str(out_path), final)
        logger.info(f"[{request_id}] Wrote final → {out_path}")
        return out_path, stats

    @staticmethod
    def _clarity_hint(scale: float, face_h: float) -> str:
        """Plain-language read on whether the input had enough pixels."""
        if scale > 2.5 or (0 < face_h < 120):
            return "LOW — input too small; output will look blurry"
        if scale > 1.3 or (120 <= face_h < 250):
            return "MEDIUM — slightly soft; a larger photo is recommended"
        return "GOOD — enough resolution for a sharp result"

    # ------------------------------------------------------------------
    # YuNet face detection
    # ------------------------------------------------------------------
    def _detect_faces(self, bgr_img: np.ndarray,
                      request_id: str) -> List[Tuple[int, int, int, int]]:
        if self._face_detector is None:
            return []
        H, W = bgr_img.shape[:2]

        # YuNet becomes unreliable on very large images (we saw 0 faces at 36 MP).
        # Run detection on a copy capped at 1920px on the long side, then scale
        # bboxes back to the original resolution.
        MAX_SIDE = 1920
        if max(H, W) > MAX_SIDE:
            scale = MAX_SIDE / max(H, W)
            small = cv2.resize(
                bgr_img, (int(W * scale), int(H * scale)),
                interpolation=cv2.INTER_AREA,
            )
        else:
            scale = 1.0
            small = bgr_img

        sh, sw = small.shape[:2]
        self._face_detector.setInputSize((sw, sh))
        try:
            _, faces = self._face_detector.detect(small)
        except Exception as e:
            logger.warning(f"[{request_id}] YuNet detect error: {e}")
            return []
        if faces is None:
            logger.info(f"[{request_id}] YuNet: no faces (detect_scale={scale:.2f})")
            return []

        inv = 1.0 / scale
        bboxes: List[Tuple[int, int, int, int]] = []
        for face in faces:
            x = max(0, int(face[0] * inv))
            y = max(0, int(face[1] * inv))
            fw = min(W - x, int(face[2] * inv))
            fh = min(H - y, int(face[3] * inv))
            if fw > 0 and fh > 0:
                bboxes.append((x, y, fw, fh))
        logger.info(
            f"[{request_id}] YuNet: {len(bboxes)} face(s) "
            f"(detect_scale={scale:.2f})"
        )
        return bboxes

    # ------------------------------------------------------------------
    # rembg segmentation
    # ------------------------------------------------------------------
    def _segment_person(self, bgr_img: np.ndarray,
                        request_id: str) -> np.ndarray:
        """Cut out the person → BGRA numpy array (alpha = subject mask)."""
        logger.info(f"[{request_id}] Running {self.pipeline} segmentation")
        bgra = self._segmenter.segment(bgr_img)
        person_px = int((bgra[:, :, 3] > 50).sum())
        logger.info(
            f"[{request_id}] Segmented; person px={person_px:,}, "
            f"shape={bgra.shape[1]}x{bgra.shape[0]}"
        )
        return bgra

    # ------------------------------------------------------------------
    # Face-centric crop
    # ------------------------------------------------------------------
    def _face_centric_crop(
        self,
        bgra: np.ndarray,
        faces: List[Tuple[int, int, int, int]],
        request_id: str,
    ) -> np.ndarray:
        H, W = bgra.shape[:2]

        if not faces:
            return self._crop_to_alpha_bbox(bgra, request_id)

        # Union of all face bboxes
        fx1 = min(f[0] for f in faces)
        fy1 = min(f[1] for f in faces)
        fx2 = max(f[0] + f[2] for f in faces)
        fy2 = max(f[1] + f[3] for f in faces)
        avg_face_h = sum(f[3] for f in faces) / len(faces)
        avg_face_w = sum(f[2] for f in faces) / len(faces)

        # Expand around face union: head + shoulders + upper chest
        pad_top    = int(avg_face_h * 0.65)
        pad_bottom = int(avg_face_h * 2.20)
        pad_sides  = int(avg_face_w * 0.65)

        cx1 = max(0, fx1 - pad_sides)
        cy1 = max(0, fy1 - pad_top)
        cx2 = min(W, fx2 + pad_sides)
        cy2 = min(H, fy2 + pad_bottom)

        # Intersect with alpha bbox so we don't carry empty strips
        alpha = bgra[:, :, 3]
        ys_a, xs_a = np.where(alpha > 30)
        if len(xs_a) > 0:
            ax1, ax2 = int(xs_a.min()), int(xs_a.max())
            ay1, ay2 = int(ys_a.min()), int(ys_a.max())
            cx1 = max(cx1, ax1)
            cy1 = max(cy1, ay1)
            cx2 = min(cx2, ax2 + 1)
            cy2 = min(cy2, ay2 + 1)

        if cx2 <= cx1 or cy2 <= cy1:
            logger.warning(f"[{request_id}] Empty face crop; using alpha bbox")
            return self._crop_to_alpha_bbox(bgra, request_id)

        cropped = bgra[cy1:cy2, cx1:cx2]
        logger.info(
            f"[{request_id}] Face-centric crop {cropped.shape[1]}x{cropped.shape[0]} "
            f"(face_h≈{int(avg_face_h)}, faces={len(faces)})"
        )
        return cropped

    def _crop_to_alpha_bbox(self, bgra: np.ndarray,
                            request_id: str) -> np.ndarray:
        alpha = bgra[:, :, 3]
        ys, xs = np.where(alpha > 30)
        if len(xs) == 0 or len(ys) == 0:
            raise ValueError("No person detected in the photo.")
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        pad = 10
        x0 = max(0, x0 - pad); y0 = max(0, y0 - pad)
        x1 = min(bgra.shape[1] - 1, x1 + pad)
        y1 = min(bgra.shape[0] - 1, y1 + pad)
        cropped = bgra[y0:y1 + 1, x0:x1 + 1]
        logger.info(f"[{request_id}] Alpha-bbox crop {cropped.shape[1]}x{cropped.shape[0]}")
        return cropped

    # ------------------------------------------------------------------
    # Fit into slot — per-frame anchor + fill
    # ------------------------------------------------------------------
    def _fit_into_slot(
        self,
        person_bgra: np.ndarray,
        slot_w: int,
        slot_h: int,
        anchor: str,
        fill: float,
        request_id: str,
    ) -> np.ndarray:
        ph, pw = person_bgra.shape[:2]
        fill = max(0.1, min(1.0, float(fill)))
        max_w = int(slot_w * fill)
        max_h = int(slot_h * fill)
        scale = min(max_w / pw, max_h / ph)
        new_w = max(1, int(pw * scale))
        new_h = max(1, int(ph * scale))

        # LANCZOS4 = sharper down/upscale than INTER_AREA for portraits
        resized = cv2.resize(person_bgra, (new_w, new_h),
                             interpolation=cv2.INTER_LANCZOS4)

        canvas = np.zeros((slot_h, slot_w, 4), dtype=np.uint8)
        off_x = (slot_w - new_w) // 2
        margin = int(slot_h * 0.03)
        if anchor == "top":
            off_y = margin
        elif anchor == "bottom":
            off_y = slot_h - new_h - margin
        else:                                # center (default)
            off_y = (slot_h - new_h) // 2
        off_y = max(0, off_y)

        canvas[off_y:off_y + new_h, off_x:off_x + new_w] = resized
        logger.info(
            f"[{request_id}] Fitted {new_w}x{new_h} into {slot_w}x{slot_h} "
            f"(anchor={anchor}, off_y={off_y})"
        )
        return canvas

    # ------------------------------------------------------------------
    # Composite onto original frame
    # ------------------------------------------------------------------
    def _composite_person_onto_frame(
        self,
        person_bgra: np.ndarray,
        frame_bgr: np.ndarray,
        slot: Dict[str, int],
        request_id: str,
    ) -> np.ndarray:
        fh, fw = frame_bgr.shape[:2]
        x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
        if x + w > fw or y + h > fh or x < 0 or y < 0:
            raise ValueError(f"Slot {slot} outside frame {fw}x{fh}")

        final = frame_bgr.copy()
        frame_slot = final[y:y + h, x:x + w, :].astype(np.float32)
        p_bgr = person_bgra[:, :, :3].astype(np.float32)
        p_a = person_bgra[:, :, 3:4].astype(np.float32) / 255.0
        out = (p_bgr * p_a + frame_slot * (1 - p_a)).astype(np.uint8)
        final[y:y + h, x:x + w, :] = out
        return final

    # ------------------------------------------------------------------
    # Watermark
    # ------------------------------------------------------------------
    def _add_watermark_bgr(self, bgr: np.ndarray,
                           request_id: str) -> np.ndarray:
        text = settings.WATERMARK_TEXT
        font = cv2.FONT_HERSHEY_SIMPLEX
        scale = settings.WATERMARK_FONT_SCALE
        thickness = settings.WATERMARK_THICKNESS

        (tw, th), baseline = cv2.getTextSize(text, font, scale, thickness)
        h, w = bgr.shape[:2]
        margin = 15
        x = w - tw - margin
        y = h - margin

        overlay = bgr.copy()
        cv2.rectangle(
            overlay,
            (x - 8, y - th - 8),
            (x + tw + 8, y + baseline + 4),
            (0, 0, 0),
            -1,
        )
        bgr = cv2.addWeighted(overlay, 0.6, bgr, 0.4, 0)
        cv2.putText(bgr, text, (x, y), font, scale,
                    (255, 255, 255), thickness, cv2.LINE_AA)
        return bgr

"""
Background removal via rembg (U²-Net family).

Takes a BGR image and returns a BGRA image (original colours + an alpha channel
that is the subject mask). rembg is imported lazily so module import stays cheap.
"""

import cv2
import numpy as np

from app.logger import setup_logger

logger = setup_logger("todozee.segmenter")


class RembgSegmenter:
    """U²-Net via rembg. Crisp edges; robust to messy backgrounds.

    `self.name` is set to the active model name (e.g. "u2net_human_seg") so it
    flows through to the pipeline label, stats, and output filenames.
    """

    def __init__(self, model_name: str = "u2net_human_seg"):
        from rembg import new_session  # lazy
        self.name = model_name
        try:
            self._session = new_session(model_name)
            logger.info(f"rembg session ready (model={model_name})")
        except Exception as e:
            logger.warning(f"rembg '{model_name}' failed ({e}); falling back to u2net")
            self._session = new_session("u2net")
            self.name = "u2net"

    def segment(self, bgr: np.ndarray) -> np.ndarray:
        from rembg import remove  # lazy
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgba = remove(rgb, session=self._session)  # numpy in → RGBA out
        if rgba.ndim == 3 and rgba.shape[2] == 4:
            return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
        # Defensive: got RGB back → assume opaque
        b, g, r = cv2.split(cv2.cvtColor(rgba, cv2.COLOR_RGB2BGR))
        return cv2.merge([b, g, r, np.full_like(b, 255)])


def get_segmenter(name: str = "rembg", rembg_model: str = "u2net_human_seg"):
    """Single backend now (rembg). Kept as a factory for a stable call site."""
    return RembgSegmenter(rembg_model)

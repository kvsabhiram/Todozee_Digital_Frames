"""
Application configuration (v5).

Notable additions vs v4:
- MODELS_DIR     : directory holding the YuNet ONNX face detector
- REMBG_MODEL    : which rembg model to use (u2net_human_seg is best for people)
- OUTPUT_QUALITY : raised from 85 → 95 for sharper JPGs
"""

from pathlib import Path
from pydantic_settings import BaseSettings


BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    # ---- Paths ----
    BASE_DIR: Path = BASE_DIR
    FRAME_DIR: Path = BASE_DIR / "frames"
    UPLOAD_DIR: Path = BASE_DIR / "uploads"
    OUTPUT_DIR: Path = BASE_DIR / "outputs"
    METADATA_FILE: Path = BASE_DIR / "frames_metadata" / "frames.json"
    LOG_DIR: Path = BASE_DIR / "logs"
    MODELS_DIR: Path = BASE_DIR / "models"   # NEW: holds YuNet .onnx

    # ---- Server ----
    HOST: str = "0.0.0.0"
    PORT: int = 5016
    DEBUG: bool = True

    # Segmentation backend. rembg (U²-Net) is the only pipeline; kept as a
    # setting so output filenames / stats stay labelled.
    PIPELINE: str = "rembg"

    # ---- Image processing ----
    SEGMENTATION_MODEL: int = 1              # legacy, unused in v5
    REMBG_MODEL: str = "isnet-general-use"   # general-purpose; works on humans, animals, objects
    OUTPUT_FORMAT: str = "jpg"
    OUTPUT_QUALITY: int = 95                 # bumped 85 → 95

    # ---- Watermark ----
    WATERMARK_TEXT: str = "Created with Todozee"
    WATERMARK_FONT_SCALE: float = 1.4
    WATERMARK_THICKNESS: int = 3

    # ---- Misc ----
    MAX_UPLOAD_SIZE: int = 15 * 1024 * 1024  # 15 MB

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

# Ensure runtime directories exist
for d in (settings.UPLOAD_DIR, settings.OUTPUT_DIR, settings.LOG_DIR,
          settings.MODELS_DIR):
    d.mkdir(parents=True, exist_ok=True)

"""
Todozee Digital Festival Frame Service
======================================
FastAPI service that:
  1. Accepts a user photo + frame_id
  2. Removes the background with rembg (U²-Net)
  4. Composites onto a pre-defined PNG festival frame
  5. Adds Todozee branding watermark
  6. Returns the final image
"""

import os
import sys
import uuid
import shutil
import logging
import base64
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Allow running this file directly: `python app/main.py` — put the project
# root on sys.path so the `app` package is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.logger import setup_logger
from app.frame_processor import FrameProcessor
from app.schemas import FrameListResponse, ProcessResponse, ErrorResponse

# ---------- Logger ----------
logger = setup_logger("todozee.main")

# ---------- FastAPI App ----------
app = FastAPI(
    title="Todozee Digital Festival Frame API",
    description="Upload a photo → get a festival-framed image ready for WhatsApp/Insta status.",
    version="1.0.0",
)

# CORS (open during dev; tighten for prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve generated outputs as static files (optional convenience)
app.mount("/static/outputs", StaticFiles(directory=str(settings.OUTPUT_DIR)), name="outputs")
app.mount("/static/frames", StaticFiles(directory=str(settings.FRAME_DIR)), name="frames")

# ---------- Singleton processor ----------
processor = FrameProcessor()


# ============================================================
# ROUTES
# ============================================================

@app.get("/", tags=["Health"])
def root():
    """Health check."""
    logger.info("Health check hit")
    return {
        "service": "Todozee Festival Frame API",
        "status": "ok",
        "version": "1.0.0",
        "model": processor.pipeline,
        "port": settings.PORT,
    }


@app.get("/frames", response_model=FrameListResponse, tags=["Frames"])
def list_frames():
    """List all available festival frames with metadata."""
    logger.info("Listing available frames")
    frames = processor.list_frames()
    return {"count": len(frames), "frames": frames}


@app.post(
    "/process",
    response_model=ProcessResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    tags=["Process"],
)
async def process_image(
    frame_id: str = Form(..., description="ID of the festival frame, e.g. 'diwali_01'"),
    file: UploadFile = File(..., description="User photo (jpg/png)"),
    add_watermark: bool = Form(True, description="Add 'Created with Todozee' branding"),
):
    """
    Main endpoint:
      1. Saves uploaded photo
      2. Removes background
      3. Composites onto selected frame
      4. Adds Todozee watermark
      5. Returns URL + file path of final image
    """
    request_id = uuid.uuid4().hex[:10]
    logger.info(f"[{request_id}] /process called | frame_id={frame_id} | filename={file.filename}")

    # ---- 1. Validate file type ----
    if file.content_type not in {"image/jpeg", "image/jpg", "image/png"}:
        logger.warning(f"[{request_id}] Rejected file type: {file.content_type}")
        raise HTTPException(status_code=400, detail="Only JPG/PNG images are supported.")

    # ---- 2. Save upload ----
    upload_path = settings.UPLOAD_DIR / f"{request_id}_{file.filename}"
    try:
        with open(upload_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        logger.info(f"[{request_id}] Saved upload at {upload_path}")
    except Exception as e:
        logger.exception(f"[{request_id}] Failed to save upload")
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # ---- 3. Process ----
    try:
        output_path, stats = processor.process(
            user_image_path=upload_path,
            frame_id=frame_id,
            request_id=request_id,
            add_watermark=add_watermark,
        )
        with open(output_path, "rb") as img_file:
            image_base64 = base64.b64encode(img_file.read()).decode("utf-8")


    except FileNotFoundError as e:
        logger.error(f"[{request_id}] Frame not found: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        logger.error(f"[{request_id}] Processing error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"[{request_id}] Unexpected processing failure")
        raise HTTPException(status_code=500, detail=f"Processing failed: {e}")

    logger.info(f"[{request_id}] Success | output={output_path}")
    return {
        "request_id": request_id,
        "frame_id": frame_id,
        "pipeline": stats.get("pipeline"),
        "output_path": str(output_path),
        "output_url": f"/static/outputs/{output_path.name}",
        "download_url": f"/download/{output_path.name}",
        "image": image_base64,
        "mime_type": "image/jpeg",
        "stats": stats,
    }


@app.get("/logs", response_class=PlainTextResponse, tags=["Logs"])
def view_logs(lines: int = 200):
    """
    View the most recent server log lines (newest at the bottom).

    Use `?lines=N` to control how many lines to return (default 200).
    Handy for checking when requests hit the server without SSHing in.
    """
    log_file: Path = settings.LOG_DIR / "todozee_digital_frames.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found yet.")

    lines = max(1, min(lines, 5000))  # clamp to a sane range
    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        all_lines = f.readlines()
    tail = all_lines[-lines:]
    return "".join(tail)


@app.get("/logs/download", tags=["Logs"])
def download_logs():
    """Download the full current log file (todozee_digital_frames.log)."""
    log_file: Path = settings.LOG_DIR / "todozee_digital_frames.log"
    if not log_file.exists():
        raise HTTPException(status_code=404, detail="Log file not found yet.")
    logger.info("Log file downloaded")
    return FileResponse(
        path=str(log_file),
        media_type="text/plain",
        filename="todozee_digital_frames.log",
    )


@app.get("/download/{filename}", tags=["Process"])
def download(filename: str):
    """Download a generated image by filename."""
    file_path = settings.OUTPUT_DIR / filename
    if not file_path.exists():
        logger.warning(f"Download miss: {filename}")
        raise HTTPException(status_code=404, detail="File not found.")
    logger.info(f"Downloading {filename}")
    return FileResponse(
        path=str(file_path),
        media_type="image/png",
        filename=filename,
    )


# ============================================================
# Startup / Shutdown
# ============================================================

@app.on_event("startup")
def on_startup():
    logger.info("=" * 60)
    logger.info("Todozee Festival Frame Service starting up")
    logger.info(f"FRAME_DIR     : {settings.FRAME_DIR}")
    logger.info(f"UPLOAD_DIR    : {settings.UPLOAD_DIR}")
    logger.info(f"OUTPUT_DIR    : {settings.OUTPUT_DIR}")
    logger.info(f"METADATA_FILE : {settings.METADATA_FILE}")
    logger.info("=" * 60)


@app.on_event("shutdown")
def on_shutdown():
    logger.info("Service shutting down. Bye!")


# ============================================================
# Run directly:  python app/main.py   (or  python -m app.main)
# Serves on the port from config (PORT, default 5015).
# ============================================================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)

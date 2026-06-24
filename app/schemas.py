"""
Pydantic schemas for API responses.
"""

from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class FrameSlot(BaseModel):
    x: int = Field(..., description="Top-left X of the face slot on the frame")
    y: int = Field(..., description="Top-left Y of the face slot on the frame")
    w: int = Field(..., description="Width of the face slot")
    h: int = Field(..., description="Height of the face slot")


class FrameInfo(BaseModel):
    id: str
    file: str
    category: str
    slot: FrameSlot
    preview_url: Optional[str] = None


class FrameListResponse(BaseModel):
    count: int
    frames: List[FrameInfo]


class ProcessResponse(BaseModel):
    request_id: str
    frame_id: str
    pipeline: Optional[str] = None
    output_path: str
    output_url: str
    download_url: str
    image: Optional[str] = None          # base64-encoded final image
    mime_type: Optional[str] = None      # e.g. "image/jpeg"
    stats: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    detail: str

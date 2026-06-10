from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime


class CreateAvatarRequest(BaseModel):
    video_url: str
    mode: Literal["head", "full_body"] = "head"


class ProcessPhotoRequest(BaseModel):
    photo_url: str  # URL returned by POST /avatar/upload or any accessible photo URL


class GenerateAvatarRequest(BaseModel):
    description: str          # e.g. "a friendly robot" or "talking monkey"
    style: str = "Cartoon"    # Cartoon | Realistic | Anime | 3D Render


class AnimateAvatarRequest(BaseModel):
    avatar_id: str
    audio_url: str


class Avatar(BaseModel):
    id: str
    gaussians_url: str
    rig: dict = {}
    type: Literal["head", "full_body"]
    created_at: datetime


class Animation(BaseModel):
    id: str
    avatar_id: str
    stream_url: str


class JobStatus(BaseModel):
    id: str
    status: Literal["pending", "processing", "done", "failed"]
    progress: float = 0.0
    result: Optional[dict] = None
    error: Optional[str] = None

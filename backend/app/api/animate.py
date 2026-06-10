from fastapi import APIRouter, HTTPException, UploadFile, File
import uuid

from ..models import AnimateAvatarRequest, Animation, JobStatus
from ..services.queue import queue_service
from ..services.storage import storage_service
from ..services.runpod_client import runpod_client

router = APIRouter(prefix="/animate", tags=["animation"])


@router.post("/", response_model=JobStatus)
async def animate_avatar(request: AnimateAvatarRequest):
    """
    Animate avatar with audio

    Flow:
    1. Audio preprocessing
    2. GaussianSpeech inference
    3. Generate deformation stream
    """
    try:
        # Submit animation job
        job_id = queue_service.submit_job("animation", {
            "avatar_id": request.avatar_id,
            "audio_url": request.audio_url
        })

        # Submit to RunPod
        runpod_job_id = runpod_client.submit_job("animation", {
            "avatar_id": request.avatar_id,
            "audio_url": request.audio_url,
            "job_id": job_id
        })

        # Store RunPod job ID
        queue_service.update_job_status(
            job_id,
            "processing",
            progress=0.1,
            result={"runpod_job_id": runpod_job_id}
        )

        return JobStatus(
            id=job_id,
            status="processing",
            progress=0.1
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...)):
    """Upload audio file"""
    try:
        file_id = f"audio/{uuid.uuid4()}.wav"
        url = storage_service.upload_fileobj(file.file, file_id)

        return {"audio_url": url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{animation_id}", response_model=Animation)
async def get_animation(animation_id: str):
    """Get animation details and stream URL"""
    # TODO: Implement database lookup
    raise HTTPException(status_code=501, detail="Not implemented")

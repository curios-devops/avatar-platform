from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional
import io
import time
import uuid
from datetime import datetime

import httpx

from ..config import settings
from ..models import CreateAvatarRequest, ProcessPhotoRequest, GenerateAvatarRequest, Avatar, JobStatus
from ..services.queue import queue_service
from ..services.storage import storage_service
from ..services.runpod_client import runpod_client
from ..workers.pipeline_worker import run_avatar_pipeline
from ..workers.generate_worker import run_generate_pipeline

router = APIRouter(prefix="/avatar", tags=["avatar"])

# Last time we pinged the LAM endpoint awake (monotonic seconds).
# The endpoint's idleTimeout is 600 s, so re-pinging sooner than ~8 min
# just burns a request; the throttle keeps page reloads free.
_WARMUP_THROTTLE_S = 8 * 60
_last_warmup = 0.0


@router.post("/warmup")
async def warmup_lam():
    """Boot a LAM worker ahead of time (fire-and-forget).

    Called by the frontend when the upload page mounts, so the GPU worker
    cold-starts while the user is still picking a photo. The worker handler
    answers unknown job_types with a fast error — that's enough to boot it,
    and the endpoint's 600 s idleTimeout keeps it warm afterwards.
    """
    global _last_warmup
    from ..config import settings

    if not settings.RUNPOD_LAM_ENDPOINT_ID or settings.MOCK_PIPELINE:
        return {"warmed": False, "reason": "LAM not configured"}
    now = time.monotonic()
    if now - _last_warmup < _WARMUP_THROTTLE_S:
        return {"warmed": False, "reason": "recently warmed"}
    _last_warmup = now

    import httpx
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"https://api.runpod.ai/v2/{settings.RUNPOD_LAM_ENDPOINT_ID}/run",
                json={"input": {"job_type": "warmup"}},
                headers={"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"},
            )
        return {"warmed": True}
    except Exception as exc:  # warmup is best-effort — never block the UI
        _last_warmup = 0.0
        return {"warmed": False, "reason": str(exc)}


@router.post("/create", response_model=JobStatus)
async def create_avatar(request: CreateAvatarRequest):
    """
    Create a new Gaussian avatar from video

    Flow:
    1. Download video
    2. Extract frames (ffmpeg)
    3. RunPod job: COLMAP + SplattingAvatar + gsplat
    4. Export gaussian .ply + metadata
    """
    try:
        # Submit reconstruction job
        job_id = queue_service.submit_job("reconstruction", {
            "video_url": request.video_url,
            "mode": request.mode
        })

        # Submit to RunPod
        runpod_job_id = runpod_client.submit_job("reconstruction", {
            "video_url": request.video_url,
            "mode": request.mode,
            "job_id": job_id
        })

        # Store RunPod job ID reference
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


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload video file directly"""
    try:
        file_id = f"videos/{uuid.uuid4()}.mp4"
        url = storage_service.upload_fileobj(file.file, file_id)

        return {"video_url": url}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process", response_model=JobStatus)
async def process_photo(
    request: ProcessPhotoRequest,
    background_tasks: BackgroundTasks,
):
    """
    Start the photo → gaussian avatar pipeline for the requested tier:
    "head" (LAM), "half" or "full" (LHM body worker).

    Accepts a photo_url from the /avatar/upload endpoint (or any accessible URL).
    Returns job_id immediately; pipeline runs in the background.

    Poll GET /avatar/job/{job_id}/status for progress.
    When status == "done", result contains the full AvatarBundle including preview_url.
    """
    if request.tier not in ("head", "half", "full"):
        raise HTTPException(status_code=422, detail=f"invalid tier: {request.tier}")
    if request.tier != "head" and not settings.RUNPOD_LHM_ENDPOINT_ID:
        raise HTTPException(
            status_code=503,
            detail="Body avatars not available yet (RUNPOD_LHM_ENDPOINT_ID unset)",
        )
    job_id = queue_service.submit_job(
        "avatar_pipeline", {"photo_url": request.photo_url, "tier": request.tier}
    )
    background_tasks.add_task(
        run_avatar_pipeline, job_id, request.photo_url, tier=request.tier
    )
    return JobStatus(id=job_id, status="processing", progress=0.0)


class AnalyzePhotoRequest(BaseModel):
    photo_url: str


class ReframePhotoRequest(BaseModel):
    photo_url: str
    target: str  # head | half | full


@router.post("/analyze")
async def analyze_photo_endpoint(request: AnalyzePhotoRequest):
    """
    Gemini-vision intake check for an uploaded photo: detected framing
    (head / half / full), quality flags, and which tiers this deployment
    can generate. The UI uses it to offer "generate as-is" vs "convert".
    """
    from ..services.photo_analysis import analyze_photo

    if not settings.gemini_enabled:
        raise HTTPException(status_code=503, detail="Gemini not configured")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(request.photo_url)
            resp.raise_for_status()
        analysis = await analyze_photo(resp.content)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"analysis failed: {exc}") from exc

    analysis["tiers_available"] = {
        "head": bool(settings.RUNPOD_LAM_ENDPOINT_ID) or settings.MOCK_PIPELINE,
        "half": bool(settings.RUNPOD_LHM_ENDPOINT_ID),
        "full": bool(settings.RUNPOD_LHM_ENDPOINT_ID),
    }
    return analysis


@router.post("/reframe")
async def reframe_photo_endpoint(request: ReframePhotoRequest):
    """
    Nano Banana edit: convert the uploaded photo to the target framing
    (head / half / full) preserving identity. Returns the new photo_url,
    ready for /avatar/process with the matching tier.
    """
    from ..services.photo_analysis import reframe_photo

    if not settings.gemini_enabled:
        raise HTTPException(status_code=503, detail="Gemini not configured")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(request.photo_url)
            resp.raise_for_status()
        jpeg = await reframe_photo(resp.content, request.target)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"reframe failed: {exc}") from exc

    key = f"uploads/reframed/{uuid.uuid4()}_{request.target}.jpg"
    url = storage_service.upload_fileobj(io.BytesIO(jpeg), key)
    return {"photo_url": url, "target": request.target}


@router.get("/job/{job_id}/preview")
async def get_avatar_preview(job_id: str):
    """
    Return the neutral-front preview URL for a completed avatar job.
    Intended for the UI to display a head-asset preview without parsing the full bundle.
    """
    job = queue_service.get_job_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] == "failed":
        raise HTTPException(status_code=422, detail=job.get("error", "Pipeline failed"))
    if job["status"] != "done":
        raise HTTPException(
            status_code=202,
            detail=f"Job not ready yet (status: {job['status']}, "
                   f"progress: {job.get('progress', 0):.0%})",
        )
    bundle = job.get("result", {})
    preview_url = bundle.get("preview")
    if not preview_url:
        raise HTTPException(status_code=500, detail="Preview URL missing from bundle")
    return {"preview_url": preview_url, "job_id": job_id}


@router.post("/generate", response_model=JobStatus)
async def generate_avatar_from_prompt(
    request: GenerateAvatarRequest,
    background_tasks: BackgroundTasks,
):
    """
    Generate an avatar from a text description.

    Uses an image generation model (or mock in dev) to create a face image
    from the description, then runs the full photo → FLAME pipeline on it.

    Poll GET /avatar/job/{job_id}/status for progress.
    """
    job_id = queue_service.submit_job(
        "generate_pipeline",
        {"description": request.description, "style": request.style},
    )
    background_tasks.add_task(run_generate_pipeline, job_id, request.description, request.style)
    return JobStatus(id=job_id, status="processing", progress=0.0)


@router.get("/{avatar_id}", response_model=Avatar)
async def get_avatar(avatar_id: str):
    """Get avatar details"""
    # TODO: Implement database lookup
    raise HTTPException(status_code=501, detail="Not implemented")


@router.get("/job/{job_id}/status", response_model=JobStatus)
async def get_job_status(job_id: str):
    """Poll job status"""
    job = queue_service.get_job_status(job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatus(**job)

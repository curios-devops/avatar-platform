"""
Background worker: text description → face image → full FLAME-rigged avatar pipeline.

Stages:
  generating  — OpenAI gpt-image-1 creates a face image from the prompt
  + all stages from pipeline_worker (ingest → publish)

Falls back to the deterministic mock generator when OPENAI_API_KEY is not set.
"""
from __future__ import annotations

import io
import logging

from ..services.queue import queue_service
from ..workers.pipeline_worker import run_avatar_pipeline

logger = logging.getLogger(__name__)


async def run_generate_pipeline(job_id: str, description: str, style: str) -> None:
    queue_service.update_job_status(
        job_id, "processing", progress=0.02, result={"stage": "generating"}
    )
    try:
        image_bytes = await _generate_image(description, style)
        photo_url   = await _save_temp_image(image_bytes, job_id)
    except Exception as exc:
        logger.exception("job=%s image generation failed", job_id)
        queue_service.update_job_status(job_id, "failed", error=str(exc))
        return

    # Hand off to the existing photo pipeline; reuse job_id so callers keep
    # polling the same job. First 15 % of progress already consumed above.
    await run_avatar_pipeline(job_id, photo_url, _progress_offset=0.15)


async def _generate_image(description: str, style: str) -> bytes:
    from ..config import settings

    if settings.OPENAI_API_KEY:
        logger.info("job: using OpenAI gpt-image-1 for %r (style=%s)", description[:40], style)
        from ..services.openai_image import generate_face_image
        return await generate_face_image(description, style)

    logger.info("job: OPENAI_API_KEY not set — using mock image generator")
    from ..mocks.mock_image_generator import generate_image
    import asyncio
    return await asyncio.get_event_loop().run_in_executor(
        None, generate_image, description, style
    )


async def _save_temp_image(image_bytes: bytes, job_id: str) -> str:
    from ..services.storage import storage_service
    key = f"generated/{job_id}/source.jpg"
    url = storage_service.upload_fileobj(io.BytesIO(image_bytes), key)
    return url

"""
Google Gemini — photo enhancement / editing before the FLAME pipeline.

Used as an optional pre-processing step on uploaded photos when GEMINI_API_KEY
is set. It prompts the Gemini image model (settings.GEMINI_IMAGE_MODEL,
Nano Banana 2 Lite) to clean up the photo (even lighting, forward face,
remove busy backgrounds) to improve FLAME fitting accuracy.

If the API is not configured the raw photo is passed through unchanged.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_EDIT_INSTRUCTION = (
    "Enhance this portrait for 3D face reconstruction: "
    "ensure the face looks directly at the camera, "
    "apply even neutral studio lighting, "
    "remove distracting background elements, "
    "keep the person's exact appearance and identity unchanged."
)


async def enhance_photo(image_bytes: bytes) -> bytes:
    """
    Send the photo to Gemini for enhancement.
    Returns improved JPEG bytes, or the original bytes if the API is unavailable.
    """
    from ..config import settings

    if not settings.gemini_enabled:
        return image_bytes

    try:
        return await _call_gemini(image_bytes)
    except Exception as exc:
        logger.warning("Gemini enhance failed (%s) — using original photo", exc)
        return image_bytes


async def _call_gemini(image_bytes: bytes) -> bytes:
    import httpx

    from ..config import settings
    from ..pipeline.multiview_generator import _to_jpeg, gemini_edit

    jpeg = _to_jpeg(image_bytes, quality=95)
    async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
        out = await gemini_edit(client, jpeg, _EDIT_INSTRUCTION, settings.GEMINI_IMAGE_MODEL)
    if out is None:
        logger.warning("Gemini returned no image part; using original photo")
        return image_bytes
    return out

"""
Google Gemini Imagen — photo enhancement / editing before the FLAME pipeline.

Used as an optional pre-processing step on uploaded photos when GEMINI_API_KEY
is set. It prompts Imagen to clean up the photo (even lighting, forward face,
remove busy backgrounds) to improve FLAME fitting accuracy.

If the API is not configured the raw photo is passed through unchanged.
"""
from __future__ import annotations

import base64
import io
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
    Send the photo to Gemini Imagen for enhancement.
    Returns improved JPEG bytes, or the original bytes if the API is unavailable.
    """
    from ..config import settings

    if not settings.GEMINI_API_KEY:
        return image_bytes

    try:
        return await _call_gemini(image_bytes, settings.GEMINI_API_KEY)
    except Exception as exc:
        logger.warning("Gemini enhance failed (%s) — using original photo", exc)
        return image_bytes


async def _call_gemini(image_bytes: bytes, api_key: str) -> bytes:
    import google.generativeai as genai
    import asyncio
    from PIL import Image as PILImage

    genai.configure(api_key=api_key)

    # Gemini SDK is sync; run in thread pool to avoid blocking the event loop
    def _sync_edit() -> bytes:
        model = genai.GenerativeModel("gemini-2.0-flash-exp")

        # Encode image as inline data
        b64 = base64.b64encode(image_bytes).decode()
        response = model.generate_content(
            [
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": b64,
                    }
                },
                _EDIT_INSTRUCTION,
            ],
        )

        # Extract image from response if Gemini returned one
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data.mime_type.startswith("image/"):
                raw = base64.b64decode(part.inline_data.data)
                img = PILImage.open(io.BytesIO(raw)).convert("RGB")
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=95)
                return buf.getvalue()

        # Gemini returned text only (no image) — fall back to original
        logger.warning("Gemini returned no image part; using original photo")
        return image_bytes

    return await asyncio.get_event_loop().run_in_executor(None, _sync_edit)

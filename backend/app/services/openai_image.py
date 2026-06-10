"""
OpenAI gpt-image-1 (Image-2) — text-to-face-image generation.

Wraps the images.generate endpoint and returns raw JPEG bytes.
The prompt is automatically enriched to produce a portrait suitable
for the FLAME face pipeline (forward-facing, neutral expression, even lighting).
"""
from __future__ import annotations

import base64
import logging

logger = logging.getLogger(__name__)

_PORTRAIT_SUFFIX = (
    ", portrait, facing forward, neutral expression, even studio lighting, "
    "plain background, photorealistic, high detail"
)

_STYLE_HINTS: dict[str, str] = {
    "Cartoon":   "cartoon style, cel-shaded, vibrant colours, ",
    "Realistic":  "photorealistic, skin texture, subsurface scattering, ",
    "Anime":      "anime style, clean linework, large expressive eyes, ",
    "3D Render":  "3D render, octane render, smooth surfaces, ",
}


async def generate_face_image(description: str, style: str = "Cartoon") -> bytes:
    """
    Generate a face image from a text description using OpenAI gpt-image-1.
    Returns raw JPEG bytes.
    """
    from openai import AsyncOpenAI
    from ..config import settings

    hint = _STYLE_HINTS.get(style, "")
    prompt = f"{hint}{description}{_PORTRAIT_SUFFIX}"
    logger.info("OpenAI image gen: style=%s prompt=%r", style, prompt[:80])

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    response = await client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        n=1,
        size="1024x1024",
        response_format="b64_json",
    )

    b64 = response.data[0].b64_json
    png_bytes = base64.b64decode(b64)

    # Convert PNG → JPEG so downstream (Pillow, ingest) can handle it uniformly
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(png_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

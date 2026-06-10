"""
Multi-view synthesis from a single frontal portrait.

Generates up to 9 synthetic views using OpenAI gpt-image-1 (images.edit)
so MICA/EMOCA can reconstruct a stable 3-D identity from multiple angles.

Important — these images are reconstruction aids ONLY.
They are never texture-mapped onto the final avatar.

Angle scheme
────────────
  ("left_90",  -90,  0)   full left profile
  ("left_60",  -60,  0)   three-quarter left
  ("left_30",  -30,  0)   slight left
  ("front",      0,  0)   original frontal (not re-generated)
  ("right_30",  30,  0)   slight right
  ("right_60",  60,  0)   three-quarter right
  ("right_90",  90,  0)   full right profile
  ("up",         0, 15)   slightly upward tilt
  ("down",       0,-15)   slightly downward tilt
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
from dataclasses import dataclass

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# (angle_key, yaw_deg, pitch_deg)
VIEW_ANGLES: list[tuple[str, int, int]] = [
    ("left_90",  -90,  0),
    ("left_60",  -60,  0),
    ("left_30",  -30,  0),
    ("right_30",  30,  0),
    ("right_60",  60,  0),
    ("right_90",  90,  0),
    ("up",          0, 15),
    ("down",        0,-15),
]

_YAW_DESCRIPTIONS = {
    -90: "full left profile, ear clearly visible",
    -60: "three-quarter turn to the left, nose clearly visible",
    -30: "slight turn to the left",
     30: "slight turn to the right",
     60: "three-quarter turn to the right, nose clearly visible",
     90: "full right profile, ear clearly visible",
}
_PITCH_DESCRIPTIONS = {
     15: "head tilted slightly upward, looking up",
    -15: "head tilted slightly downward, looking down",
}

_BASE_SUFFIX = (
    "Same person, identical facial features, skin tone, hair colour, "
    "eye colour, and expression. Neutral expression. "
    "Even studio lighting, plain background. "
    "Photorealistic portrait, high resolution."
)


def _angle_prompt(yaw: int, pitch: int) -> str:
    if pitch != 0:
        return f"The exact same person, {_PITCH_DESCRIPTIONS[pitch]}. {_BASE_SUFFIX}"
    return (
        f"The exact same person, head turned: {_YAW_DESCRIPTIONS[yaw]}. "
        f"{_BASE_SUFFIX}"
    )


def _mirror_fallback(frontal: bytes, yaw: int) -> bytes:
    """Simple horizontal mirror for ±90° profiles when API fails."""
    img = Image.open(io.BytesIO(frontal)).convert("RGB")
    if yaw < 0:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _png_from_jpeg(jpeg_bytes: bytes) -> bytes:
    """Convert to RGBA PNG (required by images.edit)."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGBA").resize((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def _generate_one(
    client,
    frontal_png: bytes,
    angle_key: str,
    yaw: int,
    pitch: int,
) -> tuple[str, bytes]:
    """Call images.edit for one angle; return (angle_key, jpeg_bytes)."""
    prompt = _angle_prompt(yaw, pitch)
    logger.info("MultiView: generating %s  yaw=%d pitch=%d", angle_key, yaw, pitch)

    try:
        resp = await client.images.edit(
            model="gpt-image-1",
            image=("frontal.png", frontal_png, "image/png"),
            prompt=prompt,
            n=1,
            size="1024x1024",
            response_format="b64_json",
        )
        png = base64.b64decode(resp.data[0].b64_json)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        return angle_key, buf.getvalue()

    except Exception as exc:
        logger.warning("MultiView: API failed for %s (%s) — using fallback", angle_key, exc)
        return angle_key, _mirror_fallback(frontal_png, yaw)


class MultiViewGenerator:
    """
    Generate ~9 synthetic views from a frontal portrait.

    Usage::

        gen = MultiViewGenerator()
        views = await gen.generate(frontal_jpeg_bytes)
        # views = {"front": <bytes>, "left_30": <bytes>, ...}

    The returned dict always contains "front" (= the original image untouched).
    Other keys are present only if generation succeeds or fallback produces them.

    If OPENAI_API_KEY is not set, the method returns only {"front": frontal_bytes}.
    """

    async def generate(
        self,
        frontal_bytes: bytes,
        angles: list[tuple[str, int, int]] | None = None,
        max_concurrent: int = 3,
    ) -> dict[str, bytes]:
        """
        Args:
            frontal_bytes:   JPEG/PNG bytes of the frontal portrait.
            angles:          Override default angle list (for testing).
            max_concurrent:  Max parallel OpenAI requests (default 3 to
                             avoid rate-limit on free tier).

        Returns:
            dict mapping angle key → JPEG bytes.
            "front" is always included (original image, not re-generated).
        """
        from openai import AsyncOpenAI
        from ..config import settings

        results: dict[str, bytes] = {"front": frontal_bytes}

        api_key = settings.OPENAI_API_KEY
        if not api_key:
            logger.warning("MultiView: OPENAI_API_KEY not set — returning frontal only")
            return results

        client = AsyncOpenAI(api_key=api_key)
        frontal_png = _png_from_jpeg(frontal_bytes)
        target_angles = angles if angles is not None else VIEW_ANGLES

        # Throttle with a semaphore to respect rate limits
        sem = asyncio.Semaphore(max_concurrent)

        async def _throttled(key: str, yaw: int, pitch: int):
            async with sem:
                return await _generate_one(client, frontal_png, key, yaw, pitch)

        tasks = [
            asyncio.create_task(_throttled(key, yaw, pitch))
            for key, yaw, pitch in target_angles
        ]

        done = await asyncio.gather(*tasks, return_exceptions=True)
        for result in done:
            if isinstance(result, Exception):
                logger.error("MultiView: unexpected error: %s", result)
                continue
            key, jpeg = result
            results[key] = jpeg

        logger.info("MultiView: generated %d / %d views", len(results) - 1, len(target_angles))
        return results

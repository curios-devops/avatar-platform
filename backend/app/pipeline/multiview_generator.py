"""
Multi-view synthesis from a single frontal portrait.

Generates 8 synthetic views so MICA can reconstruct a stable 3-D identity
from multiple angles, and so the texture bake has angular coverage.

Generator chain (first available wins per view):
  1. Nano Banana (gemini-2.5-flash-image) — best identity/geometric consistency
  2. OpenAI images.edit (gpt-image-2, degrades to gpt-image-1 if unavailable)
  3. Local horizontal mirror (±90° profiles only, last resort)

Important — these images are reconstruction aids ONLY.
They are never texture-mapped onto the final avatar directly.

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

from PIL import Image

logger = logging.getLogger(__name__)

GEMINI_IMAGE_MODEL = "gemini-2.5-flash-image"
GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_IMAGE_MODEL}:generateContent"
)

# OpenAI fallback — tried in order until one model is accepted by the account
OPENAI_IMAGE_MODELS = ["gpt-image-2", "gpt-image-1"]

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
    "Same person, identical facial features, skin tone, hair colour and style, "
    "eye colour, and expression. Neutral expression. "
    "Keep the exact same head size and framing as the input photo. "
    "Even studio lighting, plain neutral background. "
    "Photorealistic portrait photograph, high resolution."
)


def _angle_prompt(yaw: int, pitch: int) -> str:
    if pitch != 0:
        return (
            f"Rotate this person's head: {_PITCH_DESCRIPTIONS[pitch]}. "
            f"{_BASE_SUFFIX}"
        )
    return (
        f"Rotate this person's head: {_YAW_DESCRIPTIONS[yaw]}. "
        f"{_BASE_SUFFIX}"
    )


def _to_jpeg(image_bytes: bytes, quality: int = 90) -> bytes:
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _mirror_fallback(frontal: bytes, yaw: int) -> bytes:
    """Simple horizontal mirror for ±90° profiles when all APIs fail."""
    img = Image.open(io.BytesIO(frontal)).convert("RGB")
    if yaw < 0:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


# ── Nano Banana (Gemini) ──────────────────────────────────────────────────────

async def _gemini_edit(
    client, api_key: str, frontal_jpeg: bytes, prompt: str
) -> bytes | None:
    """One Nano Banana image edit. Returns JPEG bytes or None on failure."""
    payload = {
        "contents": [{
            "parts": [
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(frontal_jpeg).decode(),
                }},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    resp = await client.post(
        GEMINI_URL,
        json=payload,
        headers={"x-goog-api-key": api_key},
    )
    resp.raise_for_status()
    data = resp.json()

    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("mimeType", inline.get("mime_type", "")).startswith("image/"):
                return _to_jpeg(base64.b64decode(inline["data"]))
    return None


# ── OpenAI fallback ───────────────────────────────────────────────────────────

async def _openai_edit(
    openai_client, frontal_png: bytes, prompt: str
) -> bytes | None:
    """OpenAI images.edit, trying newest model first. JPEG bytes or None."""
    for model in OPENAI_IMAGE_MODELS:
        try:
            resp = await openai_client.images.edit(
                model=model,
                image=("frontal.png", frontal_png, "image/png"),
                prompt=prompt,
                n=1,
                size="1024x1024",
            )
            b64 = resp.data[0].b64_json
            if b64:
                return _to_jpeg(base64.b64decode(b64))
        except Exception as exc:
            msg = str(exc).lower()
            if "model" in msg and ("not found" in msg or "does not exist" in msg or "invalid" in msg):
                logger.info("MultiView: OpenAI model %s unavailable, trying next", model)
                continue
            logger.warning("MultiView: OpenAI edit failed (%s): %s", model, exc)
            return None
    return None


def _png_from_jpeg(jpeg_bytes: bytes) -> bytes:
    """Convert to RGBA PNG (required by OpenAI images.edit)."""
    img = Image.open(io.BytesIO(jpeg_bytes)).convert("RGBA").resize((1024, 1024))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class MultiViewGenerator:
    """
    Generate 8 synthetic views from a frontal portrait.

    Usage::

        gen = MultiViewGenerator()
        views = await gen.generate(frontal_jpeg_bytes)
        # views = {"front": <bytes>, "left_30": <bytes>, ...}

    The returned dict always contains "front" (= the original image untouched).
    Per-view generator chain: Nano Banana → OpenAI → mirror (±90° only).
    """

    async def generate(
        self,
        frontal_bytes: bytes,
        angles: list[tuple[str, int, int]] | None = None,
        max_concurrent: int = 4,
    ) -> dict[str, bytes]:
        import httpx
        from ..config import settings

        results: dict[str, bytes] = {"front": frontal_bytes}

        gemini_key = settings.GEMINI_API_KEY
        openai_key = settings.OPENAI_API_KEY
        if not gemini_key and not openai_key:
            logger.warning("MultiView: no GEMINI/OPENAI key — returning frontal only")
            return results

        frontal_jpeg = _to_jpeg(frontal_bytes, quality=95)
        frontal_png = _png_from_jpeg(frontal_bytes) if openai_key else b""
        target_angles = angles if angles is not None else VIEW_ANGLES

        openai_client = None
        if openai_key:
            from openai import AsyncOpenAI
            openai_client = AsyncOpenAI(api_key=openai_key)

        sem = asyncio.Semaphore(max_concurrent)

        async def _one(http: httpx.AsyncClient, key: str, yaw: int, pitch: int):
            prompt = _angle_prompt(yaw, pitch)
            async with sem:
                # 1. Nano Banana
                if gemini_key:
                    try:
                        jpeg = await _gemini_edit(http, gemini_key, frontal_jpeg, prompt)
                        if jpeg:
                            return key, jpeg
                        logger.warning("MultiView: Nano Banana returned no image for %s", key)
                    except Exception as exc:
                        logger.warning("MultiView: Nano Banana failed for %s: %s", key, exc)

                # 2. OpenAI
                if openai_client:
                    jpeg = await _openai_edit(openai_client, frontal_png, prompt)
                    if jpeg:
                        return key, jpeg

                # 3. Mirror (profiles only)
                if abs(yaw) == 90:
                    logger.warning("MultiView: using mirror fallback for %s", key)
                    return key, _mirror_fallback(frontal_bytes, yaw)
                return key, None

        async with httpx.AsyncClient(timeout=httpx.Timeout(90, read=90)) as http:
            tasks = [
                asyncio.create_task(_one(http, key, yaw, pitch))
                for key, yaw, pitch in target_angles
            ]
            done = await asyncio.gather(*tasks, return_exceptions=True)

        for result in done:
            if isinstance(result, Exception):
                logger.error("MultiView: unexpected error: %s", result)
                continue
            key, jpeg = result
            if jpeg is not None:
                results[key] = jpeg

        logger.info(
            "MultiView: generated %d / %d views", len(results) - 1, len(target_angles)
        )
        return results

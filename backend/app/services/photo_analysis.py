"""
Photo analysis + reframing for the tiered avatar flow (2026-07-17 UX):

1. analyze_photo — Gemini vision classifies the uploaded photo's framing
   (head / half / full) and flags quality problems, so the UI can offer
   "generate as-is" or "convert to another framing".
2. reframe_photo — Nano Banana image edit turns the photo into the target
   framing (outpainting body / tightening to a portrait) while preserving
   identity, so each 3D tier gets the input it expects:
     head → LAM worker, half|full → LHM worker.

Both reuse the Vertex-express plumbing in multiview_generator
(gemini_endpoint / gemini_edit) — see docs/vertex-express-connection.md.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re

import httpx

from ..config import settings
from ..pipeline.multiview_generator import _to_jpeg  # shared JPEG normalizer

logger = logging.getLogger(__name__)

FRAMINGS = ("head", "half", "full")

_ANALYZE_PROMPT = """You are a photo intake validator for a 3D avatar generator.
Look at the image and answer in pure JSON (no markdown fences, no prose):

{"framing": "head|half|full",
 "person_count": <int>,
 "quality_ok": true|false,
 "issues": ["<short issue>", ...]}

Decide "framing" mechanically, in this order:
1. If the person's legs (thighs or below) are visible → "full".
2. Else if the waist/belt line or hips are visible in frame → "half".
3. Else (face/neck/shoulders/upper-chest only, waist NOT visible) → "head".
A typical head-and-shoulders portrait or selfie is "head", never "half".

quality_ok is false when: no person, more than one person, face heavily
occluded (mask/sunglasses covering it), extreme blur, or very low light.
List issues in Spanish, short (max 6 words each). If the photo is fine,
issues must be [].
"""

_REFRAME_PROMPTS = {
    "head": (
        "Reframe this photo as a professional head-and-shoulders portrait of the "
        "same person: face centered, frontal, shoulders visible at the bottom. "
        "Keep the exact same identity, facial features, hairstyle and clothing. "
        "Plain neutral light-gray studio background, soft even lighting, "
        "photorealistic."
    ),
    "half": (
        "Extend/reframe this photo into a half-body shot of the same person, "
        "visible from head to just below the waist, standing, facing the camera, "
        "with both arms and hands fully visible at their sides. Keep the exact "
        "same identity, facial features, hairstyle and clothing (invent matching "
        "clothing continuation only where needed). Plain neutral light-gray "
        "studio background, soft even lighting, photorealistic."
    ),
    "full": (
        "Extend/reframe this photo into a full-body shot of the same person, "
        "standing upright facing the camera, whole body visible from head to "
        "feet (shoes included), both arms and hands visible. Keep the exact same "
        "identity, facial features, hairstyle and clothing (invent a matching "
        "lower body / shoes continuation only where needed). Plain neutral "
        "light-gray studio background, soft even lighting, photorealistic."
    ),
}


async def analyze_photo(image_bytes: bytes) -> dict:
    """Classify framing + quality. Returns
    {framing, person_count, quality_ok, issues} — raises on API failure."""
    from ..pipeline.multiview_generator import gemini_endpoint

    url, headers = await asyncio.to_thread(gemini_endpoint, settings.GEMINI_VISION_MODEL)
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(_to_jpeg(image_bytes)).decode(),
                }},
                {"text": _ANALYZE_PROMPT},
            ],
        }],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    text = ""
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                text += part["text"]
    # tolerate ```json fences despite the prompt
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"Gemini returned no JSON: {text[:200]!r}")
    parsed = json.loads(m.group(0))

    framing = parsed.get("framing")
    if framing not in FRAMINGS:
        raise ValueError(f"invalid framing from Gemini: {framing!r}")
    return {
        "framing": framing,
        "person_count": int(parsed.get("person_count", 1)),
        "quality_ok": bool(parsed.get("quality_ok", False)),
        "issues": [str(i) for i in parsed.get("issues", [])][:5],
    }


async def reframe_photo(image_bytes: bytes, target: str) -> bytes:
    """Nano Banana edit → photo adjusted to the target framing. JPEG bytes."""
    from ..pipeline.multiview_generator import gemini_edit

    if target not in FRAMINGS:
        raise ValueError(f"target must be one of {FRAMINGS}, got {target!r}")
    async with httpx.AsyncClient(timeout=120) as client:
        out = await gemini_edit(
            client, _to_jpeg(image_bytes), _REFRAME_PROMPTS[target],
            settings.GEMINI_IMAGE_MODEL,
        )
    if out is None:
        raise RuntimeError("Gemini returned no image for the reframe request")
    return out

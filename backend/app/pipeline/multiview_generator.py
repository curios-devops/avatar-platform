"""
Multi-view synthesis from a single frontal portrait.

Generates 8 synthetic views so MICA can reconstruct a stable 3-D identity
from multiple angles, and so the texture bake has angular coverage.

Generator chain (first available wins per view):
  1. Nano Banana 2 Lite (gemini-3.1-flash-lite-image, settings.GEMINI_IMAGE_MODEL)
     — falls back to legacy gemini-2.5-flash-image if the model ID 404s
  2. OpenAI images.edit (gpt-image-2, degrades to gpt-image-1 if unavailable)
     — fallback only, runs outside the Gemini concurrency gate
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
import time
from typing import Callable

from PIL import Image

logger = logging.getLogger(__name__)

# Legacy model tried when the configured model is not available on the account
GEMINI_LEGACY_IMAGE_MODEL = "gemini-2.5-flash-image"

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
#
# Three transports, tried in order when GCP_PROJECT_ID is set:
#   1. Vertex AI, service account (GOOGLE_APPLICATION_CREDENTIALS / ADC)
#   2. Vertex AI EXPRESS mode — GEMINI_API_KEY against aiplatform.googleapis.com
#      (an "AQ." Vertex key; billed to the key's project)
#   3. AI Studio (generativelanguage) — free-tier keys have NO image quota

_VERTEX_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_vertex_creds = None
_vertex_broken = False  # set when credentials can't be loaded; fall back to API key


def _vertex_token() -> str:
    """Cached OAuth2 access token for Vertex AI (blocking — call in a thread)."""
    global _vertex_creds
    from ..config import settings

    if _vertex_creds is None:
        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            from google.oauth2 import service_account
            _vertex_creds = service_account.Credentials.from_service_account_file(
                settings.GOOGLE_APPLICATION_CREDENTIALS, scopes=[_VERTEX_SCOPE]
            )
        else:
            import google.auth
            _vertex_creds, _ = google.auth.default(scopes=[_VERTEX_SCOPE])
    if not _vertex_creds.valid:
        import google.auth.transport.requests
        _vertex_creds.refresh(google.auth.transport.requests.Request())
    return _vertex_creds.token


def gemini_endpoint(model: str) -> tuple[str, dict]:
    """(url, headers) for a generateContent call — Vertex when configured,
    AI Studio otherwise. Blocking on first call (token refresh)."""
    global _vertex_broken
    from ..config import settings

    if settings.GCP_PROJECT_ID:
        if not _vertex_broken:
            try:
                token = _vertex_token()
                loc = settings.GCP_LOCATION
                host = ("aiplatform.googleapis.com" if loc == "global"
                        else f"{loc}-aiplatform.googleapis.com")
                url = (
                    f"https://{host}/v1/projects/{settings.GCP_PROJECT_ID}"
                    f"/locations/{loc}/publishers/google/models/{model}:generateContent"
                )
                return url, {"Authorization": f"Bearer {token}"}
            except Exception:
                _vertex_broken = True
                logger.info(
                    "Vertex service-account credentials not configured — "
                    "using express mode with the API key"
                )
        if settings.GEMINI_API_KEY:
            url = (
                "https://aiplatform.googleapis.com/v1/publishers/google/models/"
                f"{model}:generateContent"
            )
            return url, {"x-goog-api-key": settings.GEMINI_API_KEY}

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model}:generateContent"
    )
    return url, {"x-goog-api-key": settings.GEMINI_API_KEY or ""}


async def gemini_edit(
    client, image_jpeg: bytes, prompt: str, model: str
) -> bytes | None:
    """One Gemini image edit. Returns JPEG bytes or None if no image came back.

    Raises httpx.HTTPStatusError on non-2xx (callers use 404 to detect an
    unavailable model ID).
    """
    url, headers = await asyncio.to_thread(gemini_endpoint, model)
    payload = {
        "contents": [{
            "role": "user",  # required by Vertex, accepted by AI Studio
            "parts": [
                {"inline_data": {
                    "mime_type": "image/jpeg",
                    "data": base64.b64encode(image_jpeg).decode(),
                }},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    resp = await client.post(url, json=payload, headers=headers)
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
        views = await gen.generate(frontal_jpeg_bytes, on_progress=cb)
        # views = {"front": <bytes>, "left_30": <bytes>, ...}

    The returned dict always contains "front" (= the original image untouched).
    Per-view generator chain: Nano Banana 2 Lite → OpenAI → mirror (±90° only).

    ``on_view(angle_key, jpeg_or_none, done, total)`` is called on the event
    loop each time a view settles (success or failure), so callers can upload
    and surface views incrementally.
    """

    async def generate(
        self,
        frontal_bytes: bytes,
        angles: list[tuple[str, int, int]] | None = None,
        max_concurrent: int = 8,
        on_view: Callable[[str, bytes | None, int, int], None] | None = None,
    ) -> dict[str, bytes]:
        import httpx
        from ..config import settings

        results: dict[str, bytes] = {"front": frontal_bytes}

        gemini_on = settings.gemini_enabled
        # OpenAI fallback is opt-in (OPENAI_IMAGE_FALLBACK=true) — it is slow
        # and burns paid credits on every Gemini failure.
        openai_key = settings.OPENAI_API_KEY if settings.OPENAI_IMAGE_FALLBACK else None
        if settings.OPENAI_API_KEY and not settings.OPENAI_IMAGE_FALLBACK:
            logger.info("MultiView: OpenAI fallback disabled (OPENAI_IMAGE_FALLBACK=false)")
        if not gemini_on and not openai_key:
            logger.warning("MultiView: no Gemini/OpenAI configured — returning frontal only")
            return results
        if gemini_on:
            logger.info(
                "MultiView: Gemini via %s",
                f"Vertex AI ({settings.GCP_PROJECT_ID}/{settings.GCP_LOCATION})"
                if settings.GCP_PROJECT_ID else "AI Studio API key",
            )

        frontal_jpeg = _to_jpeg(frontal_bytes, quality=95)
        frontal_png = _png_from_jpeg(frontal_bytes) if openai_key else b""
        target_angles = angles if angles is not None else VIEW_ANGLES
        total = len(target_angles)

        gemini_models = [settings.GEMINI_IMAGE_MODEL, GEMINI_LEGACY_IMAGE_MODEL]
        unavailable_models: set[str] = set()

        openai_client = None
        if openai_key:
            from openai import AsyncOpenAI
            openai_client = AsyncOpenAI(api_key=openai_key)

        gemini_sem = asyncio.Semaphore(max_concurrent)
        openai_sem = asyncio.Semaphore(4)

        done_count = 0

        def _tick(key: str, jpeg: bytes | None) -> None:
            nonlocal done_count
            done_count += 1
            if on_view is not None:
                try:
                    on_view(key, jpeg, done_count, total)
                except Exception:
                    logger.debug("MultiView: on_view raised", exc_info=True)

        async def _one(http: httpx.AsyncClient, key: str, yaw: int, pitch: int):
            prompt = _angle_prompt(yaw, pitch)
            started = time.monotonic()
            jpeg: bytes | None = None

            # 1. Gemini (Nano Banana 2 Lite, legacy model on 404/no-quota)
            if gemini_on:
                async with gemini_sem:
                    for model in gemini_models:
                        if model in unavailable_models:
                            continue
                        try:
                            jpeg = await gemini_edit(http, frontal_jpeg, prompt, model)
                            if jpeg:
                                break
                            logger.warning("MultiView: %s returned no image for %s", model, key)
                        except httpx.HTTPStatusError as exc:
                            code = exc.response.status_code
                            if code == 404:
                                hint = (
                                    " (Vertex: image models usually need GCP_LOCATION=global)"
                                    if settings.GCP_PROJECT_ID and settings.GCP_LOCATION != "global"
                                    else ""
                                )
                                logger.warning(
                                    "MultiView: model %s unavailable (404), trying next%s",
                                    model, hint,
                                )
                                unavailable_models.add(model)
                                continue
                            if code == 429:
                                if "limit: 0" in exc.response.text:
                                    # Free-tier API key: image models have ZERO
                                    # quota — no point retrying any view.
                                    if model not in unavailable_models:
                                        unavailable_models.add(model)
                                        logger.warning(
                                            "MultiView: %s has no quota on this API key "
                                            "(free tier). Configure Vertex AI "
                                            "(GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS) "
                                            "for fast multiview. Falling back.", model,
                                        )
                                    continue
                                logger.warning(
                                    "MultiView: %s rate-limited for %s — retrying once in 2s",
                                    model, key,
                                )
                                await asyncio.sleep(2)
                                try:
                                    jpeg = await gemini_edit(http, frontal_jpeg, prompt, model)
                                    if jpeg:
                                        break
                                except Exception as exc2:
                                    logger.warning("MultiView: %s retry failed for %s: %s", model, key, exc2)
                                continue
                            logger.warning("MultiView: %s failed for %s: %s", model, key, exc)
                            break
                        except Exception as exc:
                            logger.warning("MultiView: %s failed for %s: %s", model, key, exc)
                            break

            # 2. OpenAI — fallback only, outside the Gemini gate so a slow
            #    fallback never stalls other views' Gemini slots
            if jpeg is None and openai_client:
                async with openai_sem:
                    jpeg = await _openai_edit(openai_client, frontal_png, prompt)

            # 3. Mirror (profiles only)
            if jpeg is None and abs(yaw) == 90:
                logger.warning("MultiView: using mirror fallback for %s", key)
                jpeg = _mirror_fallback(frontal_bytes, yaw)

            _tick(key, jpeg)
            logger.info(
                "MultiView: %s %s in %.1fs",
                key, "ok" if jpeg else "FAILED", time.monotonic() - started,
            )
            return key, jpeg

        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as http:
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

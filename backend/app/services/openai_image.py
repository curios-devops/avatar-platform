"""
Imagine: texto → retrato, con proveedor intercambiable por env.

IMAGE_GEN_PROVIDER = openai | pruna | nanobanana (principal) e
IMAGE_GEN_FALLBACK (respaldo). Si el principal falla o no está configurado
(sin llave, o Google apagado con GOOGLE_ENABLED=false) se prueba el respaldo y
luego el resto de disponibles. Devuelve siempre bytes JPEG.

Comparativa 2026-11-03 (mismo prompt, 3 casos): gpt-image-2.5-sunburst ~13 s,
frontal, neutro, boca cerrada y cabeza completa → principal. Pruna p-image
~4 s y más barato, pero sonrisa con dientes y hombros desnudos → respaldo.

El prompt se enriquece para obtener un retrato apto para el pipeline de cara
(frontal, expresión neutra, luz pareja).
"""
from __future__ import annotations

import base64
import io
import logging

logger = logging.getLogger(__name__)

PROVIDERS = ("openai", "pruna", "nanobanana")

_PORTRAIT_SUFFIX = (
    ", head and shoulders portrait, facing forward, neutral expression, mouth closed, "
    "wearing a top, whole head visible with space above the hair, even studio lighting, "
    "plain background, high detail"
)

_STYLE_HINTS: dict[str, str] = {
    "Cartoon":   "cartoon style, cel-shaded, vibrant colours, ",
    "Realistic":  "photorealistic, skin texture, subsurface scattering, ",
    "Anime":      "anime style, clean linework, large expressive eyes, ",
    "3D Render":  "3D render, octane render, smooth surfaces, ",
}


def build_prompt(description: str, style: str) -> str:
    return f"{_STYLE_HINTS.get(style, '')}{description}{_PORTRAIT_SUFFIX}"


def available_providers() -> list[str]:
    from ..config import settings
    ok = {
        "openai": bool(settings.OPENAI_API_KEY),
        "pruna": bool(settings.PRUNA_API_KEY),
        "nanobanana": settings.gemini_enabled,
    }
    return [p for p in PROVIDERS if ok[p]]


def provider_chain(requested: str | None = None) -> list[str]:
    """Orden de intento: principal, respaldo y el resto de disponibles."""
    from ..config import settings
    avail = available_providers()
    wanted = [requested or settings.IMAGE_GEN_PROVIDER, settings.IMAGE_GEN_FALLBACK, *avail]
    chain = list(dict.fromkeys(p.lower() for p in wanted if p))
    return [p for p in chain if p in avail]


def resolve_provider(requested: str | None = None) -> str | None:
    from ..config import settings
    want = (requested or settings.IMAGE_GEN_PROVIDER).lower()
    chain = provider_chain(requested)
    if chain and chain[0] != want:
        logger.warning("Imagine: proveedor %r no disponible — uso %r", want, chain[0])
    return chain[0] if chain else None


async def generate_face_image(description: str, style: str = "Cartoon",
                              provider: str | None = None,
                              model: str | None = None) -> bytes:
    """Genera el retrato. Con `provider` explícito solo usa ese; si no, recorre
    la cadena principal → respaldo. JPEG bytes."""
    chain = [provider.lower()] if provider else provider_chain()
    chain = [p for p in chain if p in available_providers()]
    if not chain:
        raise RuntimeError("Ningún proveedor de imagen configurado")
    prompt = build_prompt(description, style)
    gens = {"openai": _openai, "pruna": _pruna, "nanobanana": _nanobanana}
    last: Exception | None = None
    for chosen in chain:
        logger.info("Imagine: provider=%s style=%s prompt=%r", chosen, style, prompt[:80])
        try:
            # el modelo explícito solo aplica al primer proveedor de la cadena
            return _to_jpeg(await gens[chosen](prompt, model if chosen == chain[0] else None))
        except Exception as exc:  # noqa: BLE001 — se prueba el siguiente
            logger.warning("Imagine: %s falló (%s) — paso al siguiente", chosen, exc)
            last = exc
    raise RuntimeError(f"Todos los proveedores de imagen fallaron: {last}") from last


async def _openai(prompt: str, model: str | None) -> bytes:
    from openai import AsyncOpenAI
    from ..config import settings

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    response = await client.images.generate(
        model=model or settings.OPENAI_IMAGE_MODEL,
        prompt=prompt,
        n=1,
        size="1024x1024",
    )
    return base64.b64decode(response.data[0].b64_json)


async def _pruna(prompt: str, model: str | None) -> bytes:
    """Pruna P-Image: POST /v1/predictions (Try-Sync), poll si tarda >60 s."""
    import asyncio
    import httpx
    from ..config import settings

    headers = {"apikey": settings.PRUNA_API_KEY or "",
               "Model": model or settings.PRUNA_IMAGE_MODEL,
               "Try-Sync": "true"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(90)) as client:
        r = await client.post("https://api.pruna.ai/v1/predictions", headers=headers,
                              json={"input": {"prompt": prompt, "aspect_ratio": "1:1"}})
        r.raise_for_status()
        data = r.json()
        auth = {"apikey": headers["apikey"]}
        for _ in range(60):
            url = data.get("generation_url") or (data.get("output") if isinstance(
                data.get("output"), str) else None)
            if url:
                img = await client.get(url, headers=auth)
                img.raise_for_status()
                return img.content
            if data.get("status") in ("failed", "canceled", "cancelled"):
                raise RuntimeError(f"Pruna falló: {data.get('error') or data}")
            if not data.get("get_url"):
                raise RuntimeError(f"Pruna: respuesta inesperada {str(data)[:200]}")
            await asyncio.sleep(2)
            r = await client.get(data["get_url"], headers=auth)
            r.raise_for_status()
            data = {**data, **r.json()}
    raise TimeoutError("Pruna: la imagen no estuvo lista en 2 min")


async def _nanobanana(prompt: str, model: str | None) -> bytes:
    """Nano Banana (Gemini image) texto → imagen por el mismo transporte Vertex."""
    import asyncio
    import httpx
    from ..config import settings
    from ..pipeline.multiview_generator import gemini_endpoint

    url, headers = await asyncio.to_thread(gemini_endpoint, model or settings.GEMINI_IMAGE_MODEL)
    async with httpx.AsyncClient(timeout=httpx.Timeout(90)) as client:
        r = await client.post(url, headers=headers, json={
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        })
        r.raise_for_status()
    for cand in r.json().get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline:
                return base64.b64decode(inline["data"])
    raise RuntimeError("Nano Banana no devolvió imagen")


def _to_jpeg(raw: bytes) -> bytes:
    # PNG/WebP → JPEG para que el resto (Pillow, ingest) lo trate igual
    from PIL import Image
    img = Image.open(io.BytesIO(raw)).convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

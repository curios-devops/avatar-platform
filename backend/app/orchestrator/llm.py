"""LLM en streaming para el orquestador (A0.1).

Proveedor por config: OpenAI (por defecto, streaming SSE estándar) o
Gemini vía Vertex express (streamGenerateContent?alt=sse). Solo inferencia
con APIs — regla de oro del plan: sin entrenamiento.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# El avatar es el CLON DIGITAL de la persona de la foto (cf. quick_lines:
# "Nací de una foto tuya. El parecido no es coincidencia."). Habla en primera
# persona como ese doble digital — nunca como un "asistente virtual" genérico.
# Sobreescribible por env (ORCH_SYSTEM_PROMPT) para personalizar por avatar.
_DEFAULT_PROMPT = (
    "Eres el clon digital de la persona de la foto: su doble, con su misma "
    "cara, hablando en primera persona. No eres un asistente virtual "
    "genérico y nunca te presentas como tal; eres su gemelo digital, cercano, "
    "con humor ligero sobre tu naturaleza digital cuando venga a cuento. "
    "Responde SIEMPRE en el idioma del usuario, en frases cortas y habladas "
    "(van a un sintetizador de voz): sin markdown, sin listas con guiones, "
    "sin emojis. Máximo 4 frases por respuesta salvo que pidan detalle."
)
SYSTEM_PROMPT = settings.ORCH_SYSTEM_PROMPT or _DEFAULT_PROMPT


_STREAMS = {"openai": lambda t, h: _openai_stream(t, h),
            "gemini": lambda t, h: _gemini_stream(t, h)}


async def stream_tokens(user_text: str, history: list[dict] | None = None) -> AsyncIterator[str]:
    """Primario con timeout de primer token; si no arranca (o falla antes de
    emitir nada), conmuta al fallback. Ambos intercambiables por env."""
    import asyncio

    history = history or []
    order = [settings.ORCH_LLM_PRIMARY.lower()]
    fb = settings.ORCH_LLM_FALLBACK.lower()
    if fb and fb not in order:
        order.append(fb)

    for i, provider in enumerate(order):
        agen = _STREAMS[provider](user_text, history)
        emitted = False
        try:
            while True:
                if not emitted:
                    tok = await asyncio.wait_for(
                        agen.__anext__(), timeout=settings.ORCH_FIRST_TOKEN_TIMEOUT_S)
                else:
                    tok = await agen.__anext__()
                emitted = True
                yield tok
        except StopAsyncIteration:
            return
        except Exception as exc:
            if emitted or i == len(order) - 1:
                raise
            logger.warning("LLM %s no arrancó (%s) — fallback a %s",
                           provider, type(exc).__name__, order[i + 1])


async def _openai_stream(user_text: str, history: list[dict]) -> AsyncIterator[str]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                {"role": "user", "content": user_text}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        async with client.stream(
            "POST", "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": settings.ORCH_OPENAI_MODEL, "messages": messages,
                  "stream": True, "max_tokens": 400},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                payload = line[6:]
                if payload.strip() == "[DONE]":
                    return
                delta = (json.loads(payload).get("choices") or [{}])[0].get("delta", {})
                if tok := delta.get("content"):
                    yield tok


async def _gemini_stream(user_text: str, history: list[dict]) -> AsyncIterator[str]:
    # Vertex express: mismo endpoint que multiview_generator.gemini_endpoint
    # pero con :streamGenerateContent y SSE. role "user" requerido (memoria).
    from ..pipeline.multiview_generator import gemini_endpoint
    import asyncio

    url, headers = await asyncio.to_thread(gemini_endpoint, settings.ORCH_GEMINI_MODEL)
    url = url.replace(":generateContent", ":streamGenerateContent") + "&alt=sse" \
        if "?" in url else url.replace(":generateContent", ":streamGenerateContent") + "?alt=sse"
    contents = [*({"role": h["role"] if h["role"] == "user" else "model",
                   "parts": [{"text": h["content"]}]} for h in history),
                {"role": "user", "parts": [{"text": user_text}]}]
    body = {"contents": contents,
            "systemInstruction": {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]}}
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    data = json.loads(line[5:])
                except json.JSONDecodeError:
                    continue
                for cand in data.get("candidates", []):
                    for part in cand.get("content", {}).get("parts", []):
                        if tok := part.get("text"):
                            yield tok

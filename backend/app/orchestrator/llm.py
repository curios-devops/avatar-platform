"""LLM en streaming para el orquestador (A0.1).

Proveedor por config: OpenAI (streaming SSE estándar), Gemini vía Vertex
express (streamGenerateContent?alt=sse) y Claude como último respaldo. El
modelo sale del nivel (Luna, Sol o Astra) y cada nivel tiene su par de Claude
(Haiku, Sonnet, Opus), como en animation-studio. Solo inferencia con APIs —
regla de oro del plan: sin entrenamiento.
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
            "gemini": lambda t, h: _gemini_stream(t, h),
            "claude": lambda t, h: _claude_stream(t, h)}


def tier_models(tier: str) -> tuple[str, str]:
    """(modelo OpenAI, modelo Claude) de un nivel: luna, sol o astra."""
    pair = {"luna": (settings.MODEL_LUNA, settings.MODEL_HAIKU),
            "sol": (settings.MODEL_SOL, settings.MODEL_SONNET),
            "astra": (settings.MODEL_ASTRA, settings.MODEL_OPUS)}
    return pair.get(tier.lower(), pair["luna"])


def _order(primary: str, fallback: str) -> list[str]:
    order = [p for p in dict.fromkeys([primary.lower(), fallback.lower(), "claude"]) if p]
    if not settings.gemini_enabled:  # GOOGLE_ENABLED=false o sin credenciales
        order = [p for p in order if p != "gemini"]
    if not settings.CLAUDE_API_KEY:
        order = [p for p in order if p != "claude"]
    return order or ["openai"]


async def stream_tokens(user_text: str, history: list[dict] | None = None) -> AsyncIterator[str]:
    """Primario con timeout de primer token; si no arranca (o falla antes de
    emitir nada), conmuta al fallback. Ambos intercambiables por env."""
    import asyncio

    history = history or []
    order = _order(settings.ORCH_LLM_PRIMARY, settings.ORCH_LLM_FALLBACK)

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


async def complete_json(system: str, user_text: str, tier: str = "sol") -> dict:
    """Una respuesta JSON (sin streaming): el modelo OpenAI del nivel y, si falla, su par de Claude."""
    order = _order("openai", "claude")
    for i, provider in enumerate(order):
        try:
            text = await {"openai": _openai_json, "gemini": _gemini_json, "claude": _claude_json}[provider](system, user_text, tier)
            return json.loads(text[text.find("{"):text.rfind("}") + 1])
        except Exception as exc:
            if i == len(order) - 1:
                raise
            logger.warning("LLM %s falló en JSON (%s) — fallback a %s", provider, type(exc).__name__, order[i + 1])
    return {}


# Los modelos GPT-6 razonan: "low" deja el primer token en ~0,7-0,9 s (Luna) y ya acierta el editor (Sol).
# No aceptan max_tokens ni temperature distinta de 1.
async def _openai_json(system: str, user_text: str, tier: str) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": tier_models(tier)[0], "max_completion_tokens": 2000, "reasoning_effort": "low",
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}]})
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def _claude_json(system: str, user_text: str, tier: str) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY, timeout=30)
    resp = await client.messages.create(
        model=tier_models(tier)[1], max_tokens=2000, system=system,
        messages=[{"role": "user", "content": user_text}],
        extra_body={"output_config": {"effort": "low"}})
    if resp.stop_reason == "refusal":
        raise RuntimeError("Claude rechazó la petición")
    return "".join(b.text for b in resp.content if b.type == "text")


async def _gemini_json(system: str, user_text: str, tier: str = "") -> str:
    from ..pipeline.multiview_generator import gemini_endpoint
    import asyncio

    url, headers = await asyncio.to_thread(gemini_endpoint, settings.ORCH_GEMINI_MODEL)
    body = {"contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "systemInstruction": {"role": "user", "parts": [{"text": system}]},
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2}}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        return resp.json()["candidates"][0]["content"]["parts"][0]["text"]


async def _openai_stream(user_text: str, history: list[dict]) -> AsyncIterator[str]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history,
                {"role": "user", "content": user_text}]
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        async with client.stream(
            "POST", "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": tier_models(settings.ORCH_LLM_TIER)[0], "messages": messages,
                  "stream": True, "max_completion_tokens": 400, "reasoning_effort": "low"},
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


async def _claude_stream(user_text: str, history: list[dict]) -> AsyncIterator[str]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.CLAUDE_API_KEY, timeout=60)
    messages = [*({"role": h["role"], "content": h["content"]} for h in history),
                {"role": "user", "content": user_text}]
    async with client.messages.stream(
        model=tier_models(settings.ORCH_LLM_TIER)[1], max_tokens=1000, system=SYSTEM_PROMPT,
        messages=messages, extra_body={"output_config": {"effort": "low"}},
    ) as stream:
        async for tok in stream.text_stream:
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

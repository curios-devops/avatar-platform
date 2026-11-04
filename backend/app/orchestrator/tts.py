"""TTS streaming con timestamps por carácter (A0.2).

ElevenLabs `stream/with-timestamps` emite JSON por líneas: cada objeto trae
`audio_base64` (MP3) y `alignment` (caracteres + tiempos) del tramo. De ahí
salen visemas con timing real SIN latencia extra (sustituye a Azure visemes
del plan; Rhubarb queda como alternativa offline).
"""
from __future__ import annotations

import base64
import json
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from ..config import settings
from ..services.elevenlabs import DEFAULT_VOICE
from .contract import Visema
from .visemes import visemes_from_alignment

logger = logging.getLogger(__name__)


@dataclass
class AudioChunk:
    audio_b64: str                       # MP3 base64 de este tramo
    # línea de tiempo ACUMULADA de la frase (t_ms desde el inicio del audio
    # de la frase) — ver contract.py; el último chunk lleva la completa
    visemas: list[Visema] = field(default_factory=list)


# ElevenLabs caído: hasta este instante (monotonic) se salta
_eleven_down_until = 0.0


async def stream_sentence_tts(
    text: str, voice_id: str = DEFAULT_VOICE
) -> AsyncIterator[AudioChunk]:
    """Primer proveedor que funcione de ORCH_TTS_PROVIDERS. Un fallo a mitad de
    frase (audio ya emitido) no se reintenta: repetiría lo ya dicho."""
    global _eleven_down_until
    providers = [p.strip() for p in settings.ORCH_TTS_PROVIDERS.split(",") if p.strip()]
    last: Exception | None = None
    for provider in providers:
        if provider == "elevenlabs":
            if not settings.ELEVENLAB_API_KEY or time.monotonic() < _eleven_down_until:
                continue
            emitted = False
            try:
                async for chunk in _elevenlabs(text, voice_id):
                    emitted = True
                    yield chunk
                return
            except Exception as exc:
                if emitted:
                    raise
                _eleven_down_until = time.monotonic() + settings.ORCH_TTS_COOLDOWN_S
                logger.warning("TTS ElevenLabs falló (%s) — respaldo durante %.0fs",
                               exc, settings.ORCH_TTS_COOLDOWN_S)
                last = exc
        elif provider == "openai":
            if not settings.OPENAI_API_KEY:
                continue
            try:
                yield await _openai(text)
                return
            except Exception as exc:
                logger.warning("TTS OpenAI falló (%s)", exc)
                last = exc
    raise RuntimeError(f"Ningún proveedor de voz disponible ({last})")


def _estimated_visemes(text: str, duration_s: float) -> list[Visema]:
    """Sin alignment: caracteres repartidos de forma uniforme en la duración."""
    chars = list(text)
    if not chars:
        return [Visema(t_ms=0, id="sil", peso=1.0)]
    step = duration_s / len(chars)
    starts = [i * step for i in range(len(chars))]
    return visemes_from_alignment(chars, starts, [t + step for t in starts]) or [
        Visema(t_ms=0, id="sil", peso=1.0)]


async def _openai(text: str) -> AudioChunk:
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": settings.OPENAI_TTS_MODEL, "voice": settings.OPENAI_TTS_VOICE,
                  "input": text, "response_format": "mp3"},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAI TTS {resp.status_code}: {resp.text[:300]!r}")
    # MP3 de OpenAI a 128 kbps (medido con ffprobe) → 16000 bytes/s
    duration_s = max(0.3, len(resp.content) / 16000)
    return AudioChunk(audio_b64=base64.b64encode(resp.content).decode(),
                      visemas=_estimated_visemes(text, duration_s))


async def _elevenlabs(text: str, voice_id: str) -> AsyncIterator[AudioChunk]:
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        "/stream/with-timestamps?output_format=mp3_44100_128"
        "&optimize_streaming_latency=3"
    )
    body = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.50, "similarity_boost": 0.75},
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        async with client.stream(
            "POST", url, json=body,
            headers={"xi-api-key": settings.ELEVENLAB_API_KEY or ""},
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread())[:300]
                raise RuntimeError(f"ElevenLabs TTS {resp.status_code}: {detail!r}")
            buffer = ""
            cumulative: list[Visema] = []   # timeline de la frase, crece con cada alignment
            async for raw in resp.aiter_text():
                buffer += raw
                # objetos JSON separados por '\n' (el último puede venir partido)
                *lines, buffer = buffer.split("\n")
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    obj = json.loads(line)
                    audio_b64 = obj.get("audio_base64")
                    if not audio_b64:
                        continue
                    align = obj.get("alignment")
                    if align and align.get("characters"):
                        cumulative += visemes_from_alignment(
                            align["characters"],
                            align["character_start_times_seconds"],
                            align["character_end_times_seconds"],
                            t0_s=0.0,   # tiempos ya en escala de la frase
                        )
                    # todo mensaje lleva visemas: como mínimo 'sil' hasta que
                    # llegue el primer alignment (criterio de aceptación A0)
                    visemas = list(cumulative) or [Visema(t_ms=0, id="sil", peso=1.0)]
                    yield AudioChunk(audio_b64=audio_b64, visemas=visemas)

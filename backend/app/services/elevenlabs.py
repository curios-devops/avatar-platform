import logging
import httpx
from ..config import settings

logger = logging.getLogger(__name__)

# Current premade voices (verified against GET /v1/voices 2026-07-14 — the
# 2023-era set: Rachel/Domi/Antoni/Josh no longer exists on this account).
VOICES = {
    "Sarah":   "EXAVITQu4vr4xnSDxMaL",
    "Roger":   "CwhRBWXzGAHq8TQ4Fs17",
    "Laura":   "FGY2WhTYpPnrIDTdsKH5",
    "George":  "JBFqnCBsd6RMkjVDRZzb",
    "Charlie": "IKne3meq5aSn9XLyUdCD",
}
DEFAULT_VOICE = VOICES["Sarah"]


async def text_to_speech(text: str, voice_id: str = DEFAULT_VOICE) -> bytes:
    """
    Call ElevenLabs TTS API and return raw MP3 bytes.
    Raises httpx.HTTPStatusError on API errors (caller should handle).
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
        resp = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": settings.ELEVENLAB_API_KEY or "",
                "Accept": "audio/mpeg",
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                # monolingual_v1/multilingual_v1 were retired by ElevenLabs
                # (API now 400s with "unsupported_model"); multilingual_v2
                # also handles Spanish input.
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.50,
                    "similarity_boost": 0.75,
                },
            },
        )
        resp.raise_for_status()
        logger.info("ElevenLabs TTS: %d chars → %d bytes MP3", len(text), len(resp.content))
        return resp.content

import logging
import httpx
from ..config import settings

logger = logging.getLogger(__name__)

# Free voices available on all ElevenLabs plans
VOICES = {
    "Rachel": "21m00Tcm4TlvDq8ikWAM",
    "Domi":   "AZnzlk1XvdvUeBnXmlld",
    "Antoni": "ErXwobaYiN019PkySvjV",
    "Josh":   "TxGEqnHWrfWFTfGW9XjX",
    "Bella":  "EXAVITQu4vr4xnSDxMaL",
}
DEFAULT_VOICE = VOICES["Rachel"]


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
                "model_id": "eleven_monolingual_v1",
                "voice_settings": {
                    "stability": 0.50,
                    "similarity_boost": 0.75,
                },
            },
        )
        resp.raise_for_status()
        logger.info("ElevenLabs TTS: %d chars → %d bytes MP3", len(text), len(resp.content))
        return resp.content

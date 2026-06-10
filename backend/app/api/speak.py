import io
import logging
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..services.elevenlabs import VOICES, DEFAULT_VOICE, text_to_speech
from ..services.storage import storage_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/avatar", tags=["speak"])


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    voice_id: str = DEFAULT_VOICE


class SpeakResponse(BaseModel):
    audio_url: str
    voice_id: str
    char_count: int


@router.get("/voices")
async def list_voices():
    """Return the available ElevenLabs voice options."""
    return [{"name": name, "voice_id": vid} for name, vid in VOICES.items()]


@router.post("/{job_id}/speak", response_model=SpeakResponse)
async def speak(job_id: str, body: SpeakRequest):
    """
    Generate speech audio for an avatar via ElevenLabs TTS.
    Returns a URL to the MP3 file stored in R2 / local dev storage.
    """
    if not settings.ELEVENLAB_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="ElevenLabs API key not configured (set ELEVENLAB_API_KEY in .env)",
        )

    try:
        audio_bytes = await text_to_speech(body.text.strip(), body.voice_id)
    except Exception as exc:
        logger.exception("ElevenLabs TTS failed for job %s", job_id)
        raise HTTPException(status_code=502, detail=f"TTS service error: {exc}") from exc

    key = f"avatars/{job_id}/speech/{uuid.uuid4()}.mp3"
    audio_url = storage_service.upload_fileobj(io.BytesIO(audio_bytes), key)

    return SpeakResponse(
        audio_url=audio_url,
        voice_id=body.voice_id,
        char_count=len(body.text),
    )

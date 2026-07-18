"""STT con faster-whisper (A0.1) — carga perezosa, CPU.

El navegador manda audio webm/opus (MediaRecorder); ffmpeg lo pasa a WAV
16 kHz mono y faster-whisper transcribe. El modelo se carga en el primer
uso (int8, ~145 MB para "base") y queda residente.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..config import settings

logger = logging.getLogger(__name__)

_model = None
_lock = asyncio.Lock()


def _ffmpeg() -> str:
    """uvicorn lanzado desde .venv puede no llevar /opt/homebrew/bin en PATH."""
    for cand in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if cand and Path(cand).exists():
            return cand
    raise RuntimeError("ffmpeg no encontrado — instala con `brew install ffmpeg`")


def _load_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel  # import pesado — diferido
        logger.info("cargando faster-whisper %s (int8, cpu)…", settings.ORCH_WHISPER_MODEL)
        _model = WhisperModel(settings.ORCH_WHISPER_MODEL, device="cpu", compute_type="int8")
    return _model


def _transcribe_wav(wav_path: str) -> str:
    model = _load_model()
    segments, _info = model.transcribe(wav_path, vad_filter=True, beam_size=1)
    return " ".join(s.text.strip() for s in segments).strip()


async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """audio (webm/ogg/mp3/wav) → texto. Serializado: whisper no es reentrante."""
    async with _lock:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / f"in{suffix}"
            wav = Path(td) / "in.wav"
            src.write_bytes(audio_bytes)
            proc = await asyncio.create_subprocess_exec(
                _ffmpeg(), "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(wav),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )
            _, err = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"ffmpeg fallo decodificando audio: {err[-200:]!r}")
            return await asyncio.to_thread(_transcribe_wav, str(wav))

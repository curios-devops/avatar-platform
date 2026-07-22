"""WS del orquestador conversacional (ETAPA A — A0).

Protocolo cliente→servidor (JSON):
  {"type": "user_text",  "text": "...", "voice_id": "..."?}
  {"type": "user_audio", "audio_b64": "...", "mime": "audio/webm"?}
  {"type": "interrupt"}

Servidor→cliente: mensajes del contrato (orchestrator.contract) como JSON.
Además, tras un user_audio se emite {"type": "transcript", "text": ...}
para que el cliente pinte la pregunta (A4) — no forma parte del contrato.
"""
from __future__ import annotations

import base64
import glob
import logging
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from ..config import settings
from ..orchestrator.contract import MensajeContrato
from ..orchestrator.session import ConversationSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/converse", tags=["converse"])

_MIME_SUFFIX = {"audio/webm": ".webm", "audio/ogg": ".ogg",
                "audio/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav"}


@router.get("/share/{session_id}")
async def share_response(session_id: str):
    """A4 — concatena los video_chunk de la última respuesta en un solo MP4
    para compartir/exportar (ya renderizado; solo un concat sin re-encode)."""
    safe = "".join(c for c in session_id if c.isalnum())
    sess_dir = Path("/tmp/avatar-dev/speak") / safe
    chunks = sorted(glob.glob(str(sess_dir / "*.mp4")))
    if not chunks:
        raise HTTPException(404, "sin clips para esta sesión")
    out = sess_dir / "shared.mp4"
    if len(chunks) == 1:
        out = Path(chunks[0])
    else:
        listf = sess_dir / "concat.txt"
        listf.write_text("".join(f"file '{c}'\n" for c in chunks))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat",
                        "-safe", "0", "-i", str(listf), "-c", "copy",
                        "-movflags", "+faststart", str(out)], check=True)
    return FileResponse(str(out), media_type="video/mp4", filename="mi-avatar.mp4")


@router.websocket("/ws")
async def converse_ws(ws: WebSocket):
    await ws.accept()
    session_id = uuid.uuid4().hex[:12]

    async def emit(msg: MensajeContrato) -> None:
        await ws.send_text(msg.model_dump_json(exclude_none=True))

    session = ConversationSession(session_id, emit)
    logger.info("[%s] sesión conversacional abierta", session_id)

    # Calentar el worker MuseTalk en cuanto se abre la sesión (fire-and-forget):
    # el modelo carga (~16 s en frío) mientras el usuario escribe/habla, para que
    # el primer speak sea ~5 s y no ~14 s.
    if settings.RUNPOD_MUSETALK_ENDPOINT_ID:
        async def _warm():
            try:
                import httpx as _hx
                async with _hx.AsyncClient(timeout=10) as _c:
                    await _c.post(
                        f"https://api.runpod.ai/v2/{settings.RUNPOD_MUSETALK_ENDPOINT_ID}/run",
                        json={"input": {"job_type": "warmup"}},
                        headers={"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"})
            except Exception:
                pass
        import asyncio as _a
        _a.create_task(_warm())
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind == "user_text":
                session.voice_id = data.get("voice_id") or session.voice_id
                session.avatar_id = data.get("avatar_id") or session.avatar_id
                await session.handle_user_text(str(data.get("text", ""))[:2000])
            elif kind == "user_audio":
                from ..orchestrator.stt import transcribe  # diferido: peso whisper
                audio = base64.b64decode(data.get("audio_b64", ""))
                suffix = _MIME_SUFFIX.get(data.get("mime", "audio/webm"), ".webm")
                try:
                    text = await transcribe(audio, suffix)
                except Exception as exc:
                    await ws.send_json({"type": "error", "detail": f"STT: {exc}"})
                    continue
                await ws.send_json({"type": "transcript", "text": text})
                if text:
                    session.voice_id = data.get("voice_id") or session.voice_id
                    session.avatar_id = data.get("avatar_id") or session.avatar_id
                    await session.handle_user_text(text)
            elif kind == "interrupt":
                await session.interrupt()
            else:
                await ws.send_json({"type": "error", "detail": f"tipo desconocido: {kind}"})
    except WebSocketDisconnect:
        pass
    finally:
        await session.interrupt(emit_state=False)
        logger.info("[%s] sesión cerrada", session_id)

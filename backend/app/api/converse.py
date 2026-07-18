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
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..orchestrator.contract import MensajeContrato
from ..orchestrator.session import ConversationSession

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/converse", tags=["converse"])

_MIME_SUFFIX = {"audio/webm": ".webm", "audio/ogg": ".ogg",
                "audio/mp4": ".mp4", "audio/mpeg": ".mp3", "audio/wav": ".wav"}


@router.websocket("/ws")
async def converse_ws(ws: WebSocket):
    await ws.accept()
    session_id = uuid.uuid4().hex[:12]

    async def emit(msg: MensajeContrato) -> None:
        await ws.send_text(msg.model_dump_json(exclude_none=True))

    session = ConversationSession(session_id, emit)
    logger.info("[%s] sesión conversacional abierta", session_id)
    try:
        while True:
            data = await ws.receive_json()
            kind = data.get("type")
            if kind == "user_text":
                session.voice_id = data.get("voice_id") or session.voice_id
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

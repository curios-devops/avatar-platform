"""Sesión conversacional del orquestador (A0.3).

Encadena en streaming: texto del usuario → LLM (tokens) → troceo por
frases → TTS con timestamps → mensajes del contrato. Soporta interrupción
(barge-in A3): cancelar la respuesta en curso salta el estado a
"escuchando" con gesto `listen`.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable

from .contract import Gesto, MensajeContrato
from .llm import stream_tokens
from .sentences import sentence_stream
from .tts import stream_sentence_tts

logger = logging.getLogger(__name__)

Emit = Callable[[MensajeContrato], Awaitable[None]]

_ENUM_HINT = re.compile(r"\b(primero|segundo|tercero|luego|después|first|then|second)\b|\d+[.)°]", re.I)
_OPEN_HINT = re.compile(r"[?¿!¡]")


def _gesto_for(sentence: str, idx: int) -> Gesto:
    """Heurística mínima A0 — el scheduler real vive en A2/clip_graph."""
    if _ENUM_HINT.search(sentence):
        return "gesture_enum"
    if _OPEN_HINT.search(sentence):
        return "gesture_open"
    return "idle_a" if idx % 2 == 0 else "idle_b"


class ConversationSession:
    def __init__(self, session_id: str, emit: Emit, voice_id: str | None = None,
                 avatar_id: str | None = None):
        self.session_id = session_id
        self.emit = emit
        self.voice_id = voice_id
        # A2: si hay avatar con clips preparados y endpoint MuseTalk, cada
        # frase produce además un video_chunk con lip-sync (pipelined).
        self.avatar_id = avatar_id
        self.seq = 0
        self.history: list[dict] = []          # memoria corta de la conversación
        self._task: asyncio.Task | None = None

    def _lipsync_enabled(self) -> bool:
        from ..config import settings
        return bool(self.avatar_id and settings.RUNPOD_MUSETALK_ENDPOINT_ID)

    def _msg(self, **kw) -> MensajeContrato:
        m = MensajeContrato(session_id=self.session_id, seq=self.seq, **kw)
        self.seq += 1
        return m

    # ── API ──────────────────────────────────────────────────────────────
    async def handle_user_text(self, text: str) -> None:
        await self.interrupt(emit_state=False)  # una respuesta a la vez
        self._task = asyncio.create_task(self._respond(text))

    async def interrupt(self, emit_state: bool = True) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        if emit_state:
            await self.emit(self._msg(estado="escuchando", gesto="listen"))

    # ── pipeline de una respuesta ────────────────────────────────────────
    async def _respond(self, user_text: str) -> None:
        t_first_token: float | None = None
        t_first_audio: float | None = None
        full_reply: list[str] = []
        try:
            # "pensando" = idle + indicador sutil (A3); el contrato usa idle
            await self.emit(self._msg(estado="idle", gesto="idle_a"))

            async def tokens_with_t0():
                nonlocal t_first_token
                async for tok in stream_tokens(user_text, self.history):
                    if t_first_token is None:
                        t_first_token = time.monotonic()
                    yield tok

            # Lipsync pipelined (A2.4): la frase N se procesa en MuseTalk
            # mientras la N-1 se reproduce; los video_chunk se emiten en orden.
            lipsync_tasks: list[asyncio.Task] = []
            emitter: asyncio.Task | None = None
            if self._lipsync_enabled():
                async def _emit_videos():
                    i = 0
                    while True:
                        while i >= len(lipsync_tasks):
                            await asyncio.sleep(0.05)
                        url, sent, gest = await lipsync_tasks[i]
                        if url:
                            await self.emit(self._msg(
                                estado="hablando", gesto=gest, texto_frase=sent,
                                video_chunk=url))
                        i += 1
                emitter = asyncio.create_task(_emit_videos())

            idx = 0
            async for sentence in sentence_stream(tokens_with_t0()):
                gesto = _gesto_for(sentence, idx)
                full_reply.append(sentence)
                sentence_audio = bytearray()
                tts_kwargs = {"voice_id": self.voice_id} if self.voice_id else {}
                lipsync = self._lipsync_enabled()
                async for chunk in stream_sentence_tts(sentence, **tts_kwargs):
                    import base64 as _b64
                    sentence_audio += _b64.b64decode(chunk.audio_b64)
                    lat = None
                    if t_first_audio is None:
                        t_first_audio = time.monotonic()
                        lat = int((t_first_audio - (t_first_token or t_first_audio)) * 1000)
                        logger.info("[%s] primer chunk de audio: %s ms tras primer token",
                                    self.session_id, lat)
                    if lipsync:
                        # con lip-sync el vídeo lleva su propio audio → no emitir
                        # audio_chunk (evita que el audio suene y luego el vídeo
                        # lo reinicie). El TTS igual se acumula para MuseTalk.
                        continue
                    await self.emit(self._msg(
                        estado="hablando", gesto=gesto, texto_frase=sentence,
                        audio_chunk=chunk.audio_b64, visemas=chunk.visemas,
                        lat_primer_chunk_ms=lat,
                    ))
                if self._lipsync_enabled():
                    lipsync_tasks.append(asyncio.create_task(
                        self._lipsync_sentence(bytes(sentence_audio), sentence, gesto, idx)))
                idx += 1

            if emitter is not None:
                # esperar a que todos los videos pendientes se emitan
                while lipsync_tasks and not all(t.done() for t in lipsync_tasks):
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.15)
                emitter.cancel()

            self.history += [{"role": "user", "content": user_text},
                             {"role": "assistant", "content": " ".join(full_reply)}]
            self.history = self.history[-12:]  # ventana corta
            await self.emit(self._msg(estado="idle", gesto="idle_a", fin_de_respuesta=True))
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[%s] fallo en la respuesta", self.session_id)
            await self.emit(self._msg(estado="idle", gesto="idle_a", fin_de_respuesta=True))

    async def _lipsync_sentence(self, audio: bytes, sentence: str, gesto: str,
                                idx: int) -> tuple[str | None, str, str]:
        """Frase → MuseTalk → guarda MP4 en dev-storage → URL relativa."""
        import pathlib
        try:
            from ..pipeline.runpod_musetalk import RunPodMuseTalkClient
            t0 = time.monotonic()
            video = await RunPodMuseTalkClient().speak(self.avatar_id, gesto, audio)
            rel = f"speak/{self.session_id}/{idx:03d}.mp4"
            out = pathlib.Path("/tmp/avatar-dev") / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(video)
            logger.info("[%s] lipsync frase %d: %.1fs", self.session_id, idx,
                        time.monotonic() - t0)
            return f"/dev-storage/{rel}", sentence, gesto
        except Exception as exc:
            logger.warning("[%s] lipsync frase %d falló (%s) — solo audio",
                           self.session_id, idx, exc)
            return None, sentence, gesto

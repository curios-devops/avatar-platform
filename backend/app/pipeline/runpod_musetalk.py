"""Cliente del worker A2 (MuseTalk serverless) — lip-sync por frase.

Uso desde el orquestador (A3 lo cablea al WS):
    client = RunPodMuseTalkClient()
    await client.prepare_avatar(avatar_id, {"idle_a": mp4_bytes, ...})
    video = await client.speak(avatar_id, "idle_a", mp3_bytes)  # MP4 H.264
"""
from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from ..config import settings

logger = logging.getLogger(__name__)

_POLL_S = 2
_MAX_WAIT_S = 300


class RunPodMuseTalkClient:
    def __init__(self, endpoint_id: str | None = None):
        self.endpoint_id = endpoint_id or settings.RUNPOD_MUSETALK_ENDPOINT_ID
        if not self.endpoint_id:
            raise RuntimeError("RUNPOD_MUSETALK_ENDPOINT_ID no configurado")
        self.base = f"https://api.runpod.ai/v2/{self.endpoint_id}"
        self.headers = {"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"}

    async def _run(self, payload: dict, max_wait_s: int = _MAX_WAIT_S) -> dict:
        async with httpx.AsyncClient(timeout=60) as c:
            r = await c.post(f"{self.base}/run", json={"input": payload}, headers=self.headers)
            r.raise_for_status()
            jid = r.json()["id"]
            waited = 0.0
            while waited < max_wait_s:
                await asyncio.sleep(_POLL_S)
                waited += _POLL_S
                s = await c.get(f"{self.base}/status/{jid}", headers=self.headers)
                d = s.json()
                if d.get("status") == "COMPLETED":
                    out = d.get("output") or {}
                    if out.get("error"):
                        raise RuntimeError(f"musetalk job error: {out['error'][:500]}")
                    return out
                if d.get("status") in ("FAILED", "CANCELLED", "TIMED_OUT"):
                    raise RuntimeError(f"musetalk job {d.get('status')}: {str(d.get('error'))[:500]}")
            raise TimeoutError(f"musetalk job {jid} no completó en {max_wait_s}s")

    async def bootstrap(self) -> dict:
        return await self._run({"job_type": "bootstrap"}, max_wait_s=3000)

    async def warmup(self) -> dict:
        return await self._run({"job_type": "warmup"}, max_wait_s=900)

    async def prepare_avatar(self, avatar_id: str, clips: dict[str, bytes]) -> dict:
        # Un clip por request: el /run síncrono de RunPod limita el payload
        # (~10 MB) y 5 clips en base64 lo exceden.
        prepared = []
        for name, data in clips.items():
            out = await self._run({
                "job_type": "prepare_avatar", "avatar_id": avatar_id,
                "clips": {name: base64.b64encode(data).decode()},
            }, max_wait_s=1800)
            prepared += out.get("prepared", [])
        return {"prepared": prepared}

    async def speak(self, avatar_id: str, gesto: str, audio: bytes,
                    audio_mime: str = "audio/mpeg") -> bytes:
        out = await self._run({
            "job_type": "speak", "avatar_id": avatar_id, "gesto": gesto,
            "audio_b64": base64.b64encode(audio).decode(), "audio_mime": audio_mime,
        })
        logger.info("musetalk speak: %.2fs worker", out.get("seconds", -1))
        return base64.b64decode(out["video_b64"])

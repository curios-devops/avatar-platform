from __future__ import annotations

import asyncio
import base64
import logging

import httpx

from .interfaces import FlameFitter
from .schemas import FlameParams

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2       # seconds between status checks
_MAX_WAIT = 5 * 60      # 5-minute ceiling for FLAME fitting
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodFlameFitter(FlameFitter):
    """
    Async FLAME fitter that delegates to a RunPod Serverless endpoint running DECA/EMOCA.

    RunPod endpoint contract (see worker/avatar_worker/handler.py):
      INPUT  { "job_type": "flame_fit", "image_b64": "<base64 JPEG>" }
      OUTPUT { "shape": [...300], "expression": [...100], "pose": [...6], "tex": [...50] }

    Raises RuntimeError on RunPod failure; raises TimeoutError after _MAX_WAIT seconds.
    """

    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def fit(self, image_bytes: bytes) -> FlameParams:
        image_b64 = base64.b64encode(image_bytes).decode()
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            job_id = await self._submit(client, image_b64)
            logger.info("RunPod FLAME fit job submitted: %s", job_id)
            output = await self._poll(client, job_id, timeout=_MAX_WAIT)
        return FlameParams(
            shape=output["shape"],
            expression=output["expression"],
            pose=output["pose"],
            tex=output["tex"],
        )

    async def _submit(self, client: httpx.AsyncClient, image_b64: str) -> str:
        resp = await client.post(
            f"{self._url}/run",
            json={"input": {"job_type": "flame_fit", "image_b64": image_b64}},
            headers=self._headers,
        )
        resp.raise_for_status()
        return resp.json()["id"]

    async def _poll(
        self, client: httpx.AsyncClient, job_id: str, timeout: float
    ) -> dict:
        elapsed = 0.0
        while elapsed < timeout:
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL

            resp = await client.get(
                f"{self._url}/status/{job_id}", headers=self._headers
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status", "")
            logger.debug("RunPod FLAME %s status=%s elapsed=%.0fs", job_id, status, elapsed)

            if status == "COMPLETED":
                return data["output"]
            if status in _TERMINAL:
                raise RuntimeError(
                    f"RunPod FLAME job {job_id} ended with {status}: "
                    f"{data.get('error', 'no error message')}"
                )

        raise TimeoutError(
            f"RunPod FLAME job {job_id} did not complete within {timeout}s"
        )

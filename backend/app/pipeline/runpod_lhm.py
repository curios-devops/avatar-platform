"""
LHM (Large Animatable Human Model) client — photo → half/full-body gaussian
avatar on RunPod. Avatar tiers 2 (half body w/ hands) and 3 (full body);
tier 1 (talking head) is the LAM worker (runpod_lam.py).

Worker contract: see worker/lhm_worker/handler.py. The LHM-500M-HF model
handles both framings from the input photo alone.
Raises on any worker error — callers decide how to degrade.
"""
from __future__ import annotations

import asyncio
import base64
import gzip
import logging

import httpx

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2
_MAX_WAIT = 10 * 60
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodLHMClient:
    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def reconstruct(self, image_bytes: bytes) -> bytes:
        """Photo (half or full body) → standard 3DGS PLY bytes."""
        payload = {
            "job_type": "lhm_reconstruct",
            "image_b64": base64.b64encode(image_bytes).decode(),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            resp = await client.post(
                f"{self._url}/run", json={"input": payload}, headers=self._headers
            )
            resp.raise_for_status()
            job_id = resp.json()["id"]
            logger.info("LHM job submitted: %s", job_id)

            elapsed = 0.0
            while elapsed < _MAX_WAIT:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL
                r = await client.get(
                    f"{self._url}/status/{job_id}", headers=self._headers
                )
                r.raise_for_status()
                data = r.json()
                status = data.get("status", "")
                if status == "COMPLETED":
                    output = data.get("output") or {}
                    if "error" in output:
                        raise RuntimeError(f"LHM worker error: {output['error']}")
                    b64 = output.get("gaussians_ply_gz_b64")
                    if not b64:
                        raise RuntimeError(
                            f"LHM returned no PLY (keys: {list(output)})"
                        )
                    logger.info(
                        "LHM done in %.0fs (worker inference %.1fs, %s raw bytes)",
                        elapsed, output.get("inference_s", -1),
                        output.get("ply_bytes", "?"),
                    )
                    return gzip.decompress(base64.b64decode(b64))
                if status in _TERMINAL:
                    raise RuntimeError(
                        f"LHM job {job_id} ended {status}: {data.get('error')}"
                    )
        raise TimeoutError(f"LHM job {job_id} timed out after {_MAX_WAIT}s")

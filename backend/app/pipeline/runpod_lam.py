"""
LAM (Large Avatar Model) client — photo → gaussian-head avatar on RunPod.

Replaces the multiview→MICA→texture-bake→FlameMeshReconstructor core with a
single GPU call (POC decision 2026-07-06, docs/lam-migration.md).

Worker contract: see worker/lam_worker/handler.py.
Raises on any worker error — the caller decides whether to fall back to the
legacy CPU pipeline.
"""
from __future__ import annotations

import asyncio
import base64
import logging

import httpx

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2
_MAX_WAIT = 6 * 60
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodLAMClient:
    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def reconstruct(self, image_bytes: bytes) -> bytes:
        """Photo → standard 3DGS PLY bytes of the gaussian head."""
        payload = {
            "job_type": "lam_reconstruct",
            "image_b64": base64.b64encode(image_bytes).decode(),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            resp = await client.post(
                f"{self._url}/run", json={"input": payload}, headers=self._headers
            )
            resp.raise_for_status()
            job_id = resp.json()["id"]
            logger.info("LAM job submitted: %s", job_id)

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
                        raise RuntimeError(f"LAM worker error: {output['error']}")
                    b64 = output.get("gaussians_ply_b64")
                    if not b64:
                        raise RuntimeError(
                            f"LAM returned no PLY (keys: {list(output)})"
                        )
                    logger.info(
                        "LAM done in %.0fs (worker inference %.1fs)",
                        elapsed, output.get("inference_s", -1),
                    )
                    # Worker patches LAM to save with rgb2sh=True → standard SH
                    # PLY, already facing +z (canonical) — verified against a
                    # reference viewer 2026-07-09; no data transform needed.
                    return base64.b64decode(b64)
                if status in _TERMINAL:
                    raise RuntimeError(
                        f"LAM job {job_id} ended {status}: {data.get('error')}"
                    )
        raise TimeoutError(f"LAM job {job_id} timed out after {_MAX_WAIT}s")

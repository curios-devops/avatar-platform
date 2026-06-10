from __future__ import annotations

import asyncio
import base64
import io
import logging

import httpx
import numpy as np

from .interfaces import Reconstructor
from .schemas import FlameParams, GaussianSet, GaussianSplat

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 3
_MAX_WAIT = 10 * 60      # 10-minute ceiling (LAM inference is heavier)
_TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodReconstructor(Reconstructor):
    """
    Async Gaussian reconstructor via RunPod Serverless (LAM model).

    RunPod endpoint contract (see worker/avatar_worker/handler.py):
      INPUT  { "job_type": "reconstruct",
               "image_b64": "<base64 JPEG>",
               "flame_params": { "shape": [...], "expression": [...], "pose": [...], "tex": [...] } }
      OUTPUT { "gaussians_npz_b64": "<base64 NPZ>" }

    The NPZ must contain arrays:
      position   float32  (N, 3)
      opacity    float32  (N,)
      scale      float32  (N, 3)
      rotation   float32  (N, 4)   quaternion [w, x, y, z]
      sh_dc      float32  (N, 3)   DC spherical harmonics
      triangle_idx int32  (N,)     FLAME triangle index per Gaussian
      barycentric  float32 (N, 3)  barycentric coords summing to 1

    Raises RuntimeError on RunPod failure; TimeoutError after _MAX_WAIT seconds.
    """

    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def reconstruct(
        self, image_bytes: bytes, flame_params: FlameParams
    ) -> GaussianSet:
        image_b64 = base64.b64encode(image_bytes).decode()
        payload = {
            "job_type": "reconstruct",
            "image_b64": image_b64,
            "flame_params": flame_params.model_dump(),
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            job_id = await self._submit(client, payload)
            logger.info("RunPod reconstruct job submitted: %s", job_id)
            output = await self._poll(client, job_id, timeout=_MAX_WAIT)

        return self._parse_output(output)

    async def _submit(self, client: httpx.AsyncClient, payload: dict) -> str:
        resp = await client.post(
            f"{self._url}/run",
            json={"input": payload},
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
            logger.debug(
                "RunPod reconstruct %s status=%s elapsed=%.0fs", job_id, status, elapsed
            )

            if status == "COMPLETED":
                return data["output"]
            if status in _TERMINAL:
                raise RuntimeError(
                    f"RunPod reconstruct job {job_id} ended with {status}: "
                    f"{data.get('error', 'no error message')}"
                )

        raise TimeoutError(
            f"RunPod reconstruct job {job_id} did not complete within {timeout}s"
        )

    @staticmethod
    def _parse_output(output: dict) -> GaussianSet:
        """Decode the base64 NPZ returned by the RunPod worker into a GaussianSet."""
        npz_bytes = base64.b64decode(output["gaussians_npz_b64"])
        arrays = np.load(io.BytesIO(npz_bytes))

        positions = arrays["position"].tolist()
        opacities = arrays["opacity"].tolist()
        scales = arrays["scale"].tolist()
        rotations = arrays["rotation"].tolist()
        sh_dcs = arrays["sh_dc"].tolist()
        tri_indices = arrays["triangle_idx"].tolist()
        barycentric = arrays["barycentric"].tolist()

        splats = [
            GaussianSplat(
                position=positions[i],
                opacity=float(opacities[i]),
                scale=scales[i],
                rotation=rotations[i],
                sh_dc=sh_dcs[i],
                triangle_idx=int(tri_indices[i]),
                barycentric=barycentric[i],
            )
            for i in range(len(positions))
        ]
        return GaussianSet(gaussians=splats)

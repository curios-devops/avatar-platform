"""
MICA identity reconstruction client — Phase 2.

Sends a frontal image (plus up to 5 generated side views) to a RunPod
Serverless endpoint running MICA (https://github.com/Zielon/MICA).

MICA produces highly stable FLAME identity shape coefficients from multiple
views — much better than single-image DECA, especially for unusual face shapes.

RunPod worker contract
──────────────────────
INPUT:
  {
    "job_type": "mica_fit",
    "frontal_b64":    "<base64 JPEG>",          # required, 512×512 aligned crop
    "side_views_b64": {                          # optional, from multiview_generator
        "left_30":  "<base64 JPEG>",
        "left_60":  "<base64 JPEG>",
        "right_30": "<base64 JPEG>",
        "right_60": "<base64 JPEG>",
        "up":       "<base64 JPEG>"
    }
  }

OUTPUT:
  {
    "shape": [<300 floats>]   # stable FLAME identity coefficients
  }

Fallback behaviour (no endpoint / endpoint error):
  Returns neutral shape (all zeros) so the pipeline can continue with
  LocalReconstructor or the existing DECA fitter.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Optional

import httpx

from .interfaces import FlameFitter
from .schemas import FlameParams, MICAResult

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 2        # seconds between status checks
_MAX_WAIT      = 4 * 60   # 4-minute ceiling (MICA is lighter than EMOCA)
_TERMINAL      = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}

# Maximum number of side views sent to MICA (more doesn't help much, saves bandwidth)
_MAX_SIDE_VIEWS = 5

# Keys preferred for MICA (horizontally spread, no up/down tilt)
_PREFERRED_VIEWS = ["left_60", "right_60", "left_30", "right_30", "left_90"]


class RunPodMICAFitter(FlameFitter):
    """
    FLAME identity fitter backed by MICA on RunPod.

    Implements FlameFitter for single-image compatibility, plus
    fit_multiview() for the richer multi-view path used by pipeline_worker.

    Priority:
      fit_multiview(frontal, side_views)  ← pipeline_worker uses this
      fit(frontal_bytes)                  ← single-image fallback
    """

    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url     = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }

    # ── public API ────────────────────────────────────────────────────────────

    async def fit(self, image_bytes: bytes) -> FlameParams:
        """Single-image fit — wraps fit_multiview with no side views."""
        result = await self.fit_multiview(image_bytes, {})
        return FlameParams(
            shape=result.shape,
            expression=[0.0] * 100,
            pose=[0.0] * 6,
            tex=[0.0] * 50,
        )

    async def fit_multiview(
        self,
        frontal_bytes: bytes,
        side_views: dict[str, bytes],
    ) -> MICAResult:
        """
        Full MICA multi-view identity fit.

        Parameters
        ----------
        frontal_bytes : aligned 512×512 JPEG
        side_views    : {angle_key: jpeg_bytes} from multiview_generator
                        (empty dict = single-image mode)

        Returns
        -------
        MICAResult with 300-dim stable shape coefficients.
        """
        frontal_b64 = base64.b64encode(frontal_bytes).decode()

        # Select best subset of side views (prefer lateral angles)
        selected = _select_views(side_views, _MAX_SIDE_VIEWS)
        side_b64  = {k: base64.b64encode(v).decode() for k, v in selected.items()}

        payload = {
            "job_type":       "mica_fit",
            "frontal_b64":    frontal_b64,
            "side_views_b64": side_b64,
        }

        logger.info(
            "MICA fit: frontal + %d side views → RunPod %s",
            len(side_b64), self._url,
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            job_id = await self._submit(client, payload)
            logger.info("MICA job submitted: %s", job_id)
            output = await self._poll(client, job_id, _MAX_WAIT)

        if "error" in output:
            raise RuntimeError(f"MICA worker returned error: {output['error']}")

        shape = output.get("shape")
        if not shape:
            raise RuntimeError(f"MICA worker returned no shape (keys: {list(output)})")
        if len(shape) < 300:
            shape = (list(shape) + [0.0] * 300)[:300]

        norm = sum(x * x for x in shape) ** 0.5
        if norm < 1e-6:
            # Worker's own fallback path: COMPLETED status but all-zero shape
            # (missing weights/imports on the GPU image). Surface it loudly —
            # a mean-face avatar otherwise looks like a mysterious quality bug.
            raise RuntimeError(
                "MICA worker returned an all-zero (neutral) shape — the GPU "
                "image is likely missing MICA weights or dependencies"
            )

        logger.info("MICA fit done — shape norm=%.4f", norm)
        return MICAResult(shape=shape)

    # ── RunPod polling ────────────────────────────────────────────────────────

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
            data   = resp.json()
            status = data.get("status", "")
            logger.debug("MICA %s status=%s elapsed=%.0fs", job_id, status, elapsed)

            if status == "COMPLETED":
                return data["output"]
            if status in _TERMINAL:
                raise RuntimeError(
                    f"MICA job {job_id} ended with {status}: "
                    f"{data.get('error', 'no details')}"
                )

        raise TimeoutError(f"MICA job {job_id} timed out after {timeout:.0f}s")


# ── helpers ───────────────────────────────────────────────────────────────────

def _select_views(
    views: dict[str, bytes],
    max_n: int,
) -> dict[str, bytes]:
    """Pick up to max_n views, preferring laterally-spread angles."""
    selected: dict[str, bytes] = {}
    # Preferred first
    for key in _PREFERRED_VIEWS:
        if key in views and len(selected) < max_n:
            selected[key] = views[key]
    # Fill remaining slots with whatever's left
    for key, val in views.items():
        if key not in selected and len(selected) < max_n:
            selected[key] = val
    return selected

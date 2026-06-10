from __future__ import annotations

"""
EMOCA detailed face reconstruction client — Phase 2.

Sends an aligned frontal image and MICA identity shape params to a RunPod
Serverless endpoint running EMOCA (https://github.com/radekd91/emoca).

EMOCA outputs:
  - Refined FLAME params (shape + per-image expression + pose + tex)
  - 1024×1024 albedo texture (separated skin, eye, lip regions)
  - Expression PCA basis (100, 5023×3) — used by Phase 4 ARKit blendshapes
  - Optional per-pixel detail displacement map

RunPod worker contract
──────────────────────
INPUT:
  {
    "job_type": "emoca_reconstruct",
    "image_b64": "<base64 JPEG>",          # aligned 512×512 frontal
    "shape": [<300 floats>]                # from MICA (or zeros for neutral)
  }

OUTPUT:
  {
    "shape":                 [<300 floats>],
    "expression":            [<100 floats>],
    "pose":                  [<6 floats>],
    "tex":                   [<50 floats>],
    "albedo_b64":            "<base64 JPEG>",        # 1024×1024 RGB
    "expression_basis_b64":  "<base64 NPZ>",         # (100, 5023×3) float32
    "displacement_b64":      "<base64 NPY>" | null   # 512×512 float32, optional
  }

Fallback behaviour (no endpoint / endpoint error):
  Returns EMOCAResult built from the input FlameParams + a blank albedo so
  Phase 3 builders still have something to work with.
"""

import asyncio
import base64
import io
import logging

import httpx
import numpy as np
from PIL import Image

from .schemas import EMOCAResult, FlameParams

logger = logging.getLogger(__name__)

_POLL_INTERVAL = 3
_MAX_WAIT      = 8 * 60   # 8 minutes (EMOCA is heavier than MICA)
_TERMINAL      = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class RunPodEMOCAReconstructor:
    """
    Detailed FLAME face reconstructor backed by EMOCA on RunPod.

    Does NOT implement the Reconstructor ABC directly — its output is richer
    (albedo + expression basis) and is consumed directly by pipeline_worker
    before the Gaussian reconstruction step.

    Usage in pipeline_worker::

        emoca = RunPodEMOCAReconstructor(endpoint_id, api_key)
        result: EMOCAResult = await emoca.reconstruct(aligned_bytes, mica_shape)
        flame_params  = result.flame_params
        albedo_bytes  = result.albedo_jpeg
        expr_basis    = result.expression_basis  # for Phase 4 blendshapes
    """

    def __init__(self, endpoint_id: str, api_key: str) -> None:
        self._url     = f"https://api.runpod.ai/v2/{endpoint_id}"
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }

    # ── public API ────────────────────────────────────────────────────────────

    async def reconstruct(
        self,
        image_bytes: bytes,
        shape_params: FlameParams,
    ) -> EMOCAResult:
        """
        Run EMOCA reconstruction.

        Parameters
        ----------
        image_bytes   : aligned 512×512 JPEG (preprocessed frontal)
        shape_params  : FLAME params — shape coefficients come from MICA;
                        expression/pose/tex are ignored (EMOCA re-estimates them)

        Returns
        -------
        EMOCAResult with refined params, albedo JPEG, and expression basis.
        """
        image_b64 = base64.b64encode(image_bytes).decode()

        payload = {
            "job_type":  "emoca_reconstruct",
            "image_b64": image_b64,
            "shape":     list(shape_params.shape),
        }

        logger.info("EMOCA reconstruct: sending to RunPod %s", self._url)

        async with httpx.AsyncClient(timeout=httpx.Timeout(30, read=30)) as client:
            job_id = await self._submit(client, payload)
            logger.info("EMOCA job submitted: %s", job_id)
            output = await self._poll(client, job_id, _MAX_WAIT)

        return self._parse_output(output, shape_params)

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
            logger.debug("EMOCA %s status=%s elapsed=%.0fs", job_id, status, elapsed)

            if status == "COMPLETED":
                return data["output"]
            if status in _TERMINAL:
                raise RuntimeError(
                    f"EMOCA job {job_id} ended with {status}: "
                    f"{data.get('error', 'no details')}"
                )

        raise TimeoutError(f"EMOCA job {job_id} timed out after {timeout:.0f}s")

    # ── output parsing ────────────────────────────────────────────────────────

    @staticmethod
    def _parse_output(output: dict, fallback_params: FlameParams) -> EMOCAResult:
        """Decode the RunPod JSON output into an EMOCAResult."""

        def _pad(key: str, n: int) -> list[float]:
            vals = output.get(key, [])
            return (list(vals) + [0.0] * n)[:n]

        flame_params = FlameParams(
            shape      = _pad("shape",      300),
            expression = _pad("expression", 100),
            pose       = _pad("pose",         6),
            tex        = _pad("tex",          50),
        )

        # Albedo: base64 JPEG → bytes
        albedo_jpeg: bytes
        if "albedo_b64" in output:
            albedo_jpeg = base64.b64decode(output["albedo_b64"])
        else:
            logger.warning("EMOCA: no albedo in output — using blank texture")
            albedo_jpeg = _blank_albedo_jpeg()

        # Expression basis: base64 NPZ → list[list[float]]  (100, 5023×3)
        expression_basis: list[list[float]] | None = None
        if "expression_basis_b64" in output:
            try:
                npz_bytes = base64.b64decode(output["expression_basis_b64"])
                arr = np.load(io.BytesIO(npz_bytes))
                # NPZ may store under key "expression_basis" or "arr_0"
                key = "expression_basis" if "expression_basis" in arr else list(arr.keys())[0]
                basis = arr[key].astype(np.float32)
                if basis.ndim == 2 and basis.shape[0] == 100:
                    expression_basis = basis.tolist()
                else:
                    logger.warning("EMOCA: expression_basis shape %s unexpected", basis.shape)
            except Exception as exc:
                logger.warning("EMOCA: could not decode expression_basis (%s)", exc)

        # Displacement map: optional
        displacement_npy: bytes | None = None
        if "displacement_b64" in output and output["displacement_b64"]:
            try:
                displacement_npy = base64.b64decode(output["displacement_b64"])
            except Exception as exc:
                logger.warning("EMOCA: could not decode displacement (%s)", exc)

        return EMOCAResult(
            flame_params      = flame_params,
            albedo_jpeg       = albedo_jpeg,
            displacement_npy  = displacement_npy,
            expression_basis  = expression_basis,
        )


# ── helpers ───────────────────────────────────────────────────────────────────

def _blank_albedo_jpeg(size: int = 512) -> bytes:
    """Return a neutral-skin-tone JPEG when EMOCA doesn't provide albedo."""
    img = Image.new("RGB", (size, size), color=(200, 160, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def emoca_fallback(image_bytes: bytes, flame_params: FlameParams) -> EMOCAResult:
    """
    Local CPU fallback used when no EMOCA endpoint is configured.
    Returns EMOCAResult with the original FlameParams and a skin-sampled albedo.
    Expression basis is None (Phase 4 will use the FLAME analytical mapping instead).
    """
    # Sample approximate skin colour from image for the albedo
    try:
        img   = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((512, 512))
        arr   = np.array(img, dtype=np.uint8)
        # Use the central face region as the albedo base colour
        patch = arr[150:350, 150:350]
        mean  = patch.mean(axis=(0, 1)).astype(np.uint8)
        albedo_img = Image.new("RGB", (512, 512), tuple(mean.tolist()))
        buf = io.BytesIO()
        albedo_img.save(buf, format="JPEG", quality=90)
        albedo_jpeg = buf.getvalue()
    except Exception:
        albedo_jpeg = _blank_albedo_jpeg()

    return EMOCAResult(
        flame_params     = flame_params,
        albedo_jpeg      = albedo_jpeg,
        displacement_npy = None,
        expression_basis = None,
    )

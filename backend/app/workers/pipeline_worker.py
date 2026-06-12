from __future__ import annotations

"""
Avatar pipeline worker — photo → FLAME-rigged avatar (MVP architecture).

Single GPU dependency: MICA on RunPod (identity shape from multi-view).
Everything else runs on CPU in this backend:

  multiview   Nano Banana synthetic views (cloud API, no GPU)
  mica_fit    RunPod MICA → 300-dim identity shape   [GPU, only RunPod stage]
  texture     bake frontal photo → FLAME UV texture  (replaces EMOCA albedo)
  reconstruct LocalReconstructor gaussian sampling   (replaces GPU reconstruct)
  rig/package/publish — unchanged CPU stages

Fallbacks: MICA unavailable → local mediapipe fitter (or mock when
MOCK_PIPELINE). See backend/MVP-production-pipeline.md for the decision log.
"""
import io
import logging

import httpx

from ..config import settings
from ..mocks.mock_face_detector import detect_faces_mock
from ..mocks.mock_flame_fitter import MockFlameFitter
from ..mocks.mock_reconstructor import MockReconstructor
from ..pipeline.flame_fit import flame_fit
from ..pipeline.ingest import IngestError, ingest
from ..pipeline.package import package
from ..pipeline.preprocess import preprocess
from ..pipeline.publish import publish
from ..pipeline.reconstruct import reconstruct
from ..pipeline.rig import rig
from ..pipeline.schemas import FlameParams
from ..services.queue import queue_service
from ..services.storage import storage_service

logger = logging.getLogger(__name__)


# ── backend factory helpers ───────────────────────────────────────────────────

def _make_mica_fitter():
    """RunPod MICA — the only GPU stage in the MVP pipeline."""
    if settings.RUNPOD_MICA_ENDPOINT_ID and not settings.MOCK_PIPELINE:
        from ..pipeline.runpod_mica import RunPodMICAFitter
        logger.info("Using RunPodMICAFitter (%s)", settings.RUNPOD_MICA_ENDPOINT_ID)
        return RunPodMICAFitter(settings.RUNPOD_MICA_ENDPOINT_ID, settings.RUNPOD_API_KEY)
    return None


def _make_fitter():
    """CPU fallback fitter used when MICA is not configured or fails."""
    if settings.MOCK_PIPELINE:
        logger.info("Using MockFlameFitter (sphere)")
        return MockFlameFitter()
    from ..pipeline.local_fitter import LocalFlameFitter
    logger.info("Using LocalFlameFitter (CPU mediapipe)")
    return LocalFlameFitter()


def _make_reconstructor():
    """Gaussian layer — CPU FLAME-mesh sampling by default (MVP decision).

    FlameMeshReconstructor needs no face detection (mesh comes from the
    identity fit) and binds gaussians to real FLAME triangles.
    """
    if settings.MOCK_PIPELINE:
        logger.info("Using MockReconstructor (sphere)")
        return MockReconstructor()
    from ..pipeline.flame_reconstructor import FlameMeshReconstructor
    logger.info("Using FlameMeshReconstructor (CPU, FLAME mesh + photo)")
    return FlameMeshReconstructor()


def _flat_albedo(aligned_bytes: bytes) -> bytes:
    """Last-resort albedo: flat mean skin tone sampled from the face centre."""
    import numpy as np
    from PIL import Image
    img = Image.open(io.BytesIO(aligned_bytes)).convert("RGB").resize((512, 512))
    arr = np.asarray(img, dtype=np.uint8)
    mean = arr[150:350, 150:350].mean(axis=(0, 1)).astype(np.uint8)
    out = Image.new("RGB", (512, 512), tuple(mean.tolist()))
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


# ── main pipeline ─────────────────────────────────────────────────────────────

async def run_avatar_pipeline(
    job_id: str,
    photo_url: str,
    _progress_offset: float = 0.0,
) -> None:
    """
    Full photo → FLAME-rigged avatar pipeline (MVP).

    Stage map (with progress %):
      05  downloading
      10  ingest
      20  preprocess
      25  multiview       (Nano Banana — requires GEMINI_API_KEY)
      35  mica_fit        (RunPod — requires RUNPOD_MICA_ENDPOINT_ID)
           OR flame_fit   (CPU fallback)
      50  texture         (CPU bake — replaces EMOCA)
      55  reconstruct     (CPU gaussian sampling)
      70  rig
      80  package
      90  publish
     100  done
    """
    mica_fitter = _make_mica_fitter()
    cpu_fitter = _make_fitter()
    reconstructor = _make_reconstructor()

    def _p(raw: float) -> float:
        return _progress_offset + raw * (1.0 - _progress_offset)

    try:
        # ── 1. Download ────────────────────────────────────────────────────────
        _stage(job_id, _p(0.05), "downloading")
        async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=60)) as client:
            resp = await client.get(photo_url)
            resp.raise_for_status()
            image_bytes = resp.content
        logger.info("job=%s downloaded %d bytes", job_id, len(image_bytes))

        # ── 2. Ingest ─────────────────────────────────────────────────────────
        _stage(job_id, _p(0.10), "ingest")
        result = ingest(image_bytes, detect_faces=detect_faces_mock)
        if isinstance(result, IngestError):
            queue_service.update_job_status(
                job_id, "failed", error=f"[{result.code}] {result.reason}"
            )
            logger.warning("job=%s ingest rejected: %s", job_id, result.reason)
            return

        # ── 2b. Gemini photo enhancement (optional) ────────────────────────────
        from ..services.gemini_image import enhance_photo
        image_bytes = await enhance_photo(image_bytes)

        # ── 3. Preprocess ─────────────────────────────────────────────────────
        _stage(job_id, _p(0.20), "preprocess")
        aligned_bytes = preprocess(image_bytes, result.face_bbox)

        # ── 3b. Multi-view synthesis (Nano Banana) ─────────────────────────────
        # Keeps bytes in memory (for MICA) and uploads URLs (for frontend orbit).
        multiview_bytes: dict[str, bytes] = {"front": aligned_bytes}

        if settings.GEMINI_API_KEY or settings.OPENAI_API_KEY:
            _stage(job_id, _p(0.25), "multiview")
            try:
                from ..pipeline.multiview_generator import MultiViewGenerator
                gen = MultiViewGenerator()
                views = await gen.generate(aligned_bytes, max_concurrent=4)

                multiview_urls: dict[str, str] = {}
                for angle_key, jpeg in views.items():
                    multiview_bytes[angle_key] = jpeg
                    key = f"avatars/{job_id}/multiview/{angle_key}.jpg"
                    url = storage_service.upload_fileobj(io.BytesIO(jpeg), key)
                    multiview_urls[angle_key] = url

                queue_service.update_job_status(
                    job_id, "processing", progress=_p(0.28),
                    result={"stage": "multiview", "multiview_images": multiview_urls},
                )
                logger.info("job=%s multiview: %d views", job_id, len(multiview_bytes))
            except Exception as mv_exc:
                logger.warning("job=%s multiview failed (non-fatal): %s", job_id, mv_exc)

        # ── 4. FLAME identity fit ──────────────────────────────────────────────
        if mica_fitter is not None:
            _stage(job_id, _p(0.35), "mica_fit")
            side_views = {k: v for k, v in multiview_bytes.items() if k != "front"}
            try:
                mica_result = await mica_fitter.fit_multiview(aligned_bytes, side_views)
                flame_params = FlameParams(
                    shape      = mica_result.shape,
                    expression = [0.0] * 100,
                    pose       = [0.0] * 6,
                    tex        = [0.0] * 50,
                )
                logger.info("job=%s MICA done, shape[0]=%.4f", job_id, mica_result.shape[0])
            except Exception as exc:
                logger.warning("job=%s MICA failed (%s) — CPU fitter fallback", job_id, exc)
                _stage(job_id, _p(0.35), "flame_fit")
                flame_params = await flame_fit(aligned_bytes, cpu_fitter)
        else:
            _stage(job_id, _p(0.35), "flame_fit")
            flame_params = await flame_fit(aligned_bytes, cpu_fitter)

        # ── 5. Texture bake (CPU — replaces EMOCA albedo) ─────────────────────
        _stage(job_id, _p(0.50), "texture")
        try:
            from ..pipeline.texture_bake import bake_texture
            albedo_bytes = bake_texture(aligned_bytes, flame_params)
        except Exception as exc:
            logger.warning("job=%s texture bake failed (%s) — flat albedo", job_id, exc)
            albedo_bytes = _flat_albedo(aligned_bytes)

        # ── 6. Gaussian reconstruction (CPU) ──────────────────────────────────
        _stage(job_id, _p(0.55), "reconstruct")
        gaussian_set = await reconstruct(aligned_bytes, flame_params, reconstructor)
        logger.info("job=%s reconstructed %d gaussians", job_id, len(gaussian_set.gaussians))

        # ── 7. Rig ────────────────────────────────────────────────────────────
        _stage(job_id, _p(0.70), "rig")
        binding_table = rig(gaussian_set)

        # ── 8. Package ────────────────────────────────────────────────────────
        _stage(job_id, _p(0.80), "package")
        artifacts = package(
            aligned_bytes,
            flame_params,
            gaussian_set,
            binding_table,
            albedo_bytes=albedo_bytes,
        )

        # ── 9. Publish ────────────────────────────────────────────────────────
        _stage(job_id, _p(0.90), "publish")
        bundle = publish(job_id, artifacts, storage_service.upload_fileobj)

        queue_service.update_job_status(
            job_id, "done", progress=1.0, result=bundle.model_dump(),
        )
        logger.info("job=%s done — preview: %s", job_id, bundle.preview)

    except Exception as exc:
        logger.exception("job=%s pipeline failed", job_id)
        queue_service.update_job_status(job_id, "failed", error=str(exc))


def _stage(job_id: str, progress: float, stage: str) -> None:
    logger.info("job=%s stage=%s progress=%.0f%%", job_id, stage, progress * 100)
    queue_service.update_job_status(
        job_id, "processing", progress=progress, result={"stage": stage}
    )

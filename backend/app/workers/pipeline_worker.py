from __future__ import annotations

"""
Avatar pipeline worker — photo → FLAME-rigged Gaussian head.

Backend selection order (checked at job start, not import time):

  Phase 2 path (highest quality):
    RUNPOD_MICA_ENDPOINT_ID set   → RunPodMICAFitter     (identity from multi-view)
    RUNPOD_EMOCA_ENDPOINT_ID set  → RunPodEMOCAReconstructor (detailed mesh + albedo)

  Phase 0 / fallback path:
    RUNPOD_FLAME_ENDPOINT_ID + RUNPOD_RECONSTRUCT_ENDPOINT_ID → DECA + GPU Gaussian
    ENABLE_LOCAL_WORKER                                         → mediapipe CPU
    default                                                     → mock sphere

All paths converge at rig → package → publish.
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
    """Return RunPodMICAFitter if endpoint is configured, else None."""
    if settings.RUNPOD_MICA_ENDPOINT_ID and not settings.MOCK_PIPELINE:
        from ..pipeline.runpod_mica import RunPodMICAFitter
        logger.info("Phase 2: using RunPodMICAFitter (%s)", settings.RUNPOD_MICA_ENDPOINT_ID)
        return RunPodMICAFitter(settings.RUNPOD_MICA_ENDPOINT_ID, settings.RUNPOD_API_KEY)
    return None


def _make_emoca_reconstructor():
    """Return RunPodEMOCAReconstructor if endpoint is configured, else None."""
    if settings.RUNPOD_EMOCA_ENDPOINT_ID and not settings.MOCK_PIPELINE:
        from ..pipeline.runpod_emoca import RunPodEMOCAReconstructor
        logger.info("Phase 2: using RunPodEMOCAReconstructor (%s)", settings.RUNPOD_EMOCA_ENDPOINT_ID)
        return RunPodEMOCAReconstructor(settings.RUNPOD_EMOCA_ENDPOINT_ID, settings.RUNPOD_API_KEY)
    return None


def _make_fitter():
    """Phase 0 DECA/local/mock fitter (used when MICA is not configured)."""
    if (
        settings.RUNPOD_FLAME_ENDPOINT_ID
        and settings.RUNPOD_RECONSTRUCT_ENDPOINT_ID
        and not settings.MOCK_PIPELINE
    ):
        from ..pipeline.runpod_fitter import RunPodFlameFitter
        logger.info("Using RunPodFlameFitter (endpoint %s)", settings.RUNPOD_FLAME_ENDPOINT_ID)
        return RunPodFlameFitter(settings.RUNPOD_FLAME_ENDPOINT_ID, settings.RUNPOD_API_KEY)

    if settings.ENABLE_LOCAL_WORKER and not settings.MOCK_PIPELINE:
        from ..pipeline.local_fitter import LocalFlameFitter
        logger.info("Using LocalFlameFitter (CPU mediapipe)")
        return LocalFlameFitter()

    logger.info("Using MockFlameFitter (sphere)")
    return MockFlameFitter()


def _make_reconstructor():
    """Phase 0 GPU/local/mock Gaussian reconstructor."""
    if (
        settings.RUNPOD_FLAME_ENDPOINT_ID
        and settings.RUNPOD_RECONSTRUCT_ENDPOINT_ID
        and not settings.MOCK_PIPELINE
    ):
        from ..pipeline.runpod_reconstructor import RunPodReconstructor
        logger.info("Using RunPodReconstructor (%s)", settings.RUNPOD_RECONSTRUCT_ENDPOINT_ID)
        return RunPodReconstructor(
            settings.RUNPOD_RECONSTRUCT_ENDPOINT_ID, settings.RUNPOD_API_KEY
        )

    if settings.ENABLE_LOCAL_WORKER and not settings.MOCK_PIPELINE:
        from ..pipeline.local_reconstructor import LocalReconstructor
        logger.info("Using LocalReconstructor (CPU mediapipe + photo texture)")
        return LocalReconstructor()

    logger.info("Using MockReconstructor (sphere)")
    return MockReconstructor()


# ── main pipeline ─────────────────────────────────────────────────────────────

async def run_avatar_pipeline(
    job_id: str,
    photo_url: str,
    _progress_offset: float = 0.0,
) -> None:
    """
    Full photo → FLAME-rigged avatar pipeline.

    Stage map (with progress %):
      05  downloading
      10  ingest
      20  preprocess
      25  multiview       (Sprint 1 — requires OPENAI_API_KEY)
      35  mica_fit        (Phase 2 — requires RUNPOD_MICA_ENDPOINT_ID)
           OR flame_fit   (Phase 0 fallback)
      50  emoca_reconstruct (Phase 2 — requires RUNPOD_EMOCA_ENDPOINT_ID)
           OR [skipped]   (Phase 0 fallback goes straight to reconstruct)
      55  reconstruct     (Gaussian splat generation)
      70  rig
      80  package         (eyes + teeth + body + PLY + flame params)
      90  publish
     100  done
    """
    mica_fitter     = _make_mica_fitter()
    emoca_recon     = _make_emoca_reconstructor()
    phase0_fitter   = _make_fitter()
    phase0_recon    = _make_reconstructor()

    def _p(raw: float) -> float:
        return _progress_offset + raw * (1.0 - _progress_offset)

    # Accumulated extras — passed into package() at the end
    albedo_bytes: bytes | None = None
    expression_basis: list | None = None

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

        # ── 3b. Multi-view synthesis ───────────────────────────────────────────
        # Generates side views for MICA and for the frontend orbit animation.
        # Keeps bytes in memory (for MICA) and uploads URLs (for frontend).
        multiview_bytes: dict[str, bytes] = {"front": aligned_bytes}

        if settings.OPENAI_API_KEY:
            _stage(job_id, _p(0.25), "multiview")
            try:
                from ..pipeline.multiview_generator import MultiViewGenerator
                gen   = MultiViewGenerator()
                views = await gen.generate(aligned_bytes, max_concurrent=3)

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
        # Phase 2 path: MICA (stable identity from multi-view)
        # Phase 0 path: DECA / local mediapipe / mock
        if mica_fitter is not None:
            _stage(job_id, _p(0.35), "mica_fit")
            side_views = {k: v for k, v in multiview_bytes.items() if k != "front"}
            try:
                mica_result  = await mica_fitter.fit_multiview(aligned_bytes, side_views)
                flame_params = FlameParams(
                    shape      = mica_result.shape,
                    expression = [0.0] * 100,
                    pose       = [0.0] * 6,
                    tex        = [0.0] * 50,
                )
                logger.info("job=%s MICA done, shape[0]=%.4f", job_id, mica_result.shape[0])
            except Exception as exc:
                logger.warning("job=%s MICA failed (%s) — falling back to DECA", job_id, exc)
                _stage(job_id, _p(0.35), "flame_fit")
                flame_params = await flame_fit(aligned_bytes, phase0_fitter)
        else:
            _stage(job_id, _p(0.35), "flame_fit")
            flame_params = await flame_fit(aligned_bytes, phase0_fitter)

        # ── 5. EMOCA detailed reconstruction ──────────────────────────────────
        # Phase 2: updates flame_params with EMOCA expression/pose/tex,
        #          produces high-quality albedo texture and expression PCA basis.
        # Phase 0: runs local CPU fallback that samples albedo from the photo.
        if emoca_recon is not None:
            _stage(job_id, _p(0.50), "emoca_reconstruct")
            try:
                emoca_result     = await emoca_recon.reconstruct(aligned_bytes, flame_params)
                flame_params     = emoca_result.flame_params
                albedo_bytes     = emoca_result.albedo_jpeg
                expression_basis = emoca_result.expression_basis
                logger.info(
                    "job=%s EMOCA done, albedo=%d bytes, expr_basis=%s",
                    job_id, len(albedo_bytes),
                    "yes" if expression_basis else "no",
                )
            except Exception as exc:
                logger.warning("job=%s EMOCA failed (%s) — using CPU fallback", job_id, exc)
                from ..pipeline.runpod_emoca import emoca_fallback
                er = emoca_fallback(aligned_bytes, flame_params)
                albedo_bytes = er.albedo_jpeg
        else:
            # Always run the CPU fallback so albedo_bytes is never None
            from ..pipeline.runpod_emoca import emoca_fallback
            er = emoca_fallback(aligned_bytes, flame_params)
            albedo_bytes = er.albedo_jpeg

        # ── 6. Gaussian reconstruction ─────────────────────────────────────────
        _stage(job_id, _p(0.55), "reconstruct")
        gaussian_set = await reconstruct(aligned_bytes, flame_params, phase0_recon)
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

        # Attach expression_basis URL to result if available (for Phase 4 blendshapes)
        result_dict = bundle.model_dump()
        if expression_basis is not None:
            result_dict["has_expression_basis"] = True

        queue_service.update_job_status(
            job_id, "done", progress=1.0, result=result_dict,
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

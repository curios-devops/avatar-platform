"""
LHM RunPod serverless handler — one photo → half/full-body gaussian avatar.

INPUT:
  { "job_type": "lhm_reconstruct", "image_b64": "<base64 JPEG/PNG>" }
  { "job_type": "warmup" }   → boots the worker ahead of a real job

OUTPUT:
  { "gaussians_ply_gz_b64": "<base64 gzip(standard 3DGS PLY)>",
    "lhm_commit": "<git sha>", "inference_s": <float>, "ply_bytes": <int> }
  or { "error": "<message>" } — NEVER a silent fallback (MICA lesson).

The LHM-500M-HF checkpoint handles BOTH half-body and full-body input photos
(no framing flag — the model infers it), so this one worker serves avatar
tiers 2 and 3. We run LHM's export_mesh path (`infer_mesh`): canonical-pose
gaussians saved via save_ply — already standard 3DGS (RGB2SH inside, unlike
LAM which needed a patch) and no motion sequence rendered.

PLY is gzipped: full-body splats can exceed LAM's ~6 MB; gzip keeps the
base64 response inside RunPod's payload limit. POC runs inference as a
subprocess per job (~model reload each time); resident-model mode like the
LAM worker's is the known next optimization once outputs are validated
(load lazily on first job — NEVER at import, see docs/lam-migration.md).
"""
from __future__ import annotations

import base64
import glob
import gzip
import logging
import os
import shutil
import subprocess
import tempfile
import time

import runpod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lhm_worker")

LHM_ROOT = "/opt/LHM"
LHM_MODEL = os.getenv("LHM_MODEL", "LHM-500M-HF")
# RunPod /run response ceiling is ~20 MB; leave margin for base64 + JSON.
_MAX_B64_BYTES = 18 * 1024 * 1024


def _run_lhm(image_path: str) -> str:
    """Run LHM mesh-export inference; return path to the produced 3DGS PLY."""
    shutil.rmtree(f"{LHM_ROOT}/exps", ignore_errors=True)  # no stale PLYs on warm workers
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0",
           "PYTHONPATH": f"{os.environ.get('PYTHONPATH','')}:{LHM_ROOT}"}
    # Mirrors inference_mesh.sh: export_mesh=True triggers infer_mesh(), which
    # saves canonical gaussians to exps/meshs/**/<image>.ply (no motion pass).
    cmd = [
        "python", "-m", "LHM.launch", "infer.human_lrm",
        f"model_name={LHM_MODEL}",
        f"image_input={image_path}",
        "export_mesh=True",
        "motion_seqs_dir=None", "motion_img_dir=None",
        "vis_motion=false", "motion_img_need_mask=true",
    ]
    logger.info("LHM inference: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=LHM_ROOT, env=env, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LHM inference failed (rc={proc.returncode}): {proc.stderr[-2000:]}"
        )

    candidates = sorted(
        glob.glob(f"{LHM_ROOT}/exps/**/*.ply", recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"LHM produced no .ply — stdout tail: {proc.stdout[-1000:]}"
        )
    return candidates[0]


def handler(event: dict) -> dict:
    inp = event.get("input", {})
    job_type = inp.get("job_type")

    if job_type == "warmup":
        # Container is booted; subprocess mode has nothing else to preload.
        return {"warmed": True, "model": LHM_MODEL}

    if job_type != "lhm_reconstruct":
        return {"error": f"unsupported job_type: {job_type}"}
    b64 = inp.get("image_b64")
    if not b64:
        return {"error": "image_b64 required for lhm_reconstruct"}

    try:
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "input.jpg")
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(b64))
            ply_path = _run_lhm(image_path)
            ply_bytes = open(ply_path, "rb").read()

        gz = gzip.compress(ply_bytes, compresslevel=6)
        out_b64 = base64.b64encode(gz).decode()
        if len(out_b64) > _MAX_B64_BYTES:
            return {"error": (
                f"PLY too large for RunPod response even gzipped "
                f"({len(ply_bytes)} raw / {len(gz)} gz) — wire R2 upload"
            )}

        commit = open("/opt/LHM_COMMIT").read().strip() if os.path.exists("/opt/LHM_COMMIT") else "?"
        logger.info("LHM done: %s (%d bytes raw, %d gz) in %.1fs",
                    ply_path, len(ply_bytes), len(gz), time.monotonic() - started)
        return {
            "gaussians_ply_gz_b64": out_b64,
            "lhm_commit": commit,
            "ply_bytes": len(ply_bytes),
            "inference_s": round(time.monotonic() - started, 1),
        }
    except Exception as exc:  # honest errors only — no silent fallbacks
        logger.exception("lhm_reconstruct failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})

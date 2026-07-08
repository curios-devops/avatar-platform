"""
LAM RunPod serverless handler — one photo → gaussian-head avatar.

INPUT:
  { "job_type": "lam_reconstruct", "image_b64": "<base64 JPEG/PNG>" }

OUTPUT:
  { "gaussians_ply_b64": "<base64 standard 3DGS PLY>",
    "lam_commit": "<git sha>", "inference_s": <float> }
  or { "error": "<message>" } — NEVER a silent fallback (MICA lesson).

Runs LAM's own inference script (scripts/inference.sh) and returns the
resulting gaussian PLY. LAM-20K ≈ 20k gaussians → PLY ~6 MB, ~8 MB base64,
within RunPod's response limit.
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import subprocess
import tempfile
import time

import runpod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lam_worker")

LAM_ROOT = "/opt/LAM"
# Default config shipped with the repo for LAM-20K inference
LAM_CONFIG = os.getenv("LAM_CONFIG", "configs/inference/lam-20k-8gpu.yaml")
LAM_MODEL = os.getenv(
    "LAM_MODEL", "model_zoo/lam_models/releases/lam/lam-20k/step_045500/"
)
# Neutral (no-motion) sequence: we only need the reconstructed avatar
LAM_MOTION = os.getenv("LAM_MOTION", "assets/sample_motion/export/Look_In_My_Eyes/")


def _lam_cmd(image_path: str) -> list[str]:
    """Mirror scripts/inference.sh but with save_ply=true (the script
    hardcodes SAVE_PLY=false). LAM asserts export_video OR export_mesh,
    so the video render stays on — it's the proven-working path."""
    return [
        "python", "-m", "lam.launch", "infer.lam", "--config", LAM_CONFIG,
        f"model_name={LAM_MODEL}", f"image_input={image_path}",
        "export_video=true",
        "export_mesh=false",
        f"motion_seqs_dir={LAM_MOTION}", "motion_img_dir=null",
        "vis_motion=false", "motion_img_need_mask=true",
        "render_fps=30", "motion_video_read_fps=30",
        # The canonical avatar PLY (exps/cano_gs/*_gs_offset.ply) is only
        # written inside LAM's `if save_img:` block — save_img must be true.
        "save_ply=true", "save_img=true",
        "gaga_track_type=", "cross_id=false", "test_sample=false",
        "rank=0", "nodes=0",
    ]


def _run_lam(image_path: str, out_dir: str) -> str:
    """Run LAM inference; return path to the produced gaussian PLY."""
    import shutil
    shutil.rmtree(f"{LAM_ROOT}/exps", ignore_errors=True)  # no stale PLYs on warm workers
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0",
           "PYTHONPATH": f"{os.environ.get('PYTHONPATH','')}:{LAM_ROOT}"}
    cmd = _lam_cmd(image_path)
    logger.info("LAM inference: %s", " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=LAM_ROOT, env=env, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LAM inference failed (rc={proc.returncode}): {proc.stderr[-2000:]}"
        )

    # LAM writes results under exps/ (layout depends on config) — find the
    # newest PLY produced anywhere under the repo after the run.
    candidates = sorted(
        glob.glob(f"{LAM_ROOT}/exps/**/*.ply", recursive=True)
        + glob.glob(f"{out_dir}/**/*.ply", recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(
            f"LAM produced no .ply — stdout tail: {proc.stdout[-1000:]}"
        )
    return candidates[0]


def handler(event: dict) -> dict:
    inp = event.get("input", {})
    if inp.get("job_type") != "lam_reconstruct":
        return {"error": f"unsupported job_type: {inp.get('job_type')}"}
    b64 = inp.get("image_b64")
    if not b64:
        return {"error": "image_b64 required for lam_reconstruct"}

    try:
        started = time.monotonic()
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "input.jpg")
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(b64))
            ply_path = _run_lam(image_path, tmp)
            ply_bytes = open(ply_path, "rb").read()

        commit = open("/opt/LAM_COMMIT").read().strip() if os.path.exists("/opt/LAM_COMMIT") else "?"
        logger.info("LAM done: %s (%d bytes) in %.1fs", ply_path, len(ply_bytes),
                    time.monotonic() - started)
        return {
            "gaussians_ply_b64": base64.b64encode(ply_bytes).decode(),
            "lam_commit": commit,
            "inference_s": round(time.monotonic() - started, 1),
        }
    except Exception as exc:  # honest errors only — no silent fallbacks
        logger.exception("lam_reconstruct failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})

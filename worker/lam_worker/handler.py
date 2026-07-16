"""
LAM RunPod serverless handler — one photo → gaussian-head avatar.

INPUT:
  { "job_type": "lam_reconstruct", "image_b64": "<base64 JPEG/PNG>" }
  { "job_type": "warmup" }   → fast no-op; boots the worker + resident model

OUTPUT:
  { "gaussians_ply_b64": "<base64 standard 3DGS PLY>",
    "lam_commit": "<git sha>", "inference_s": <float>, "mode": "resident|subprocess" }
  or { "error": "<message>" } — NEVER a silent fallback (MICA lesson).

Two execution modes:
  resident (default) — LAMInferrer is built ONCE per container, lazily on the
    FIRST job (loading at import delayed runpod.serverless.start and kept the
    worker stuck in "initializing" — observed live 2026-07-14). Warmup jobs
    trigger the load, so a warmed worker answers reconstructs immediately.
  subprocess (fallback) — the original scripts/inference.sh-style call, used
    automatically if the resident model fails to initialise.

The motion sequence is a 1-frame copy of Look_In_My_Eyes (built in the
Dockerfile): LAM renders every motion frame inside its forward pass, so the
frame count — not the reconstruction — dominated job time (116 s observed).
We only need the canonical PLY; the 1-frame video render is throwaway.
"""
from __future__ import annotations

import base64
import glob
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

import runpod

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("lam_worker")

LAM_ROOT = "/opt/LAM"
# Default config shipped with the repo for LAM-20K inference
LAM_CONFIG = os.getenv("LAM_CONFIG", "configs/inference/lam-20k-8gpu.yaml")
LAM_MODEL = os.getenv(
    "LAM_MODEL", "model_zoo/lam_models/releases/lam/lam-20k/step_045500/"
)
# 1-frame neutral sequence built by the Dockerfile — trailing slash required
# (LAM resolves transforms.json against dirname of this path).
LAM_MOTION = os.getenv("LAM_MOTION", "assets/sample_motion/export/neutral_1f/")

_CLI_OVERRIDES = [
    f"model_name={LAM_MODEL}",
    "export_video=true",
    "export_mesh=false",
    f"motion_seqs_dir={LAM_MOTION}",
    "motion_img_dir=null",
    "vis_motion=false",
    "motion_img_need_mask=true",
    "render_fps=30",
    "motion_video_read_fps=30",
    # The canonical avatar PLY (exps/cano_gs/*_gs_offset.ply) is only written
    # inside LAM's `if save_img:` block — save_img must be true.
    "save_ply=true",
    "save_img=true",
    "gaga_track_type=",
    "cross_id=false",
    "test_sample=false",
    "rank=0",
    "nodes=0",
]


def _find_cano_ply() -> str:
    """The canonical head PLY LAM just wrote (newest under exps/)."""
    candidates = sorted(
        glob.glob(f"{LAM_ROOT}/exps/cano_gs/**/*.ply", recursive=True)
        + glob.glob(f"{LAM_ROOT}/exps/**/*.ply", recursive=True),
        key=os.path.getmtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError("LAM produced no .ply under exps/")
    return candidates[0]


def _clean_outputs() -> None:
    shutil.rmtree(f"{LAM_ROOT}/exps", ignore_errors=True)
    shutil.rmtree(f"{LAM_ROOT}/tracking_output", ignore_errors=True)


# ── resident model (lazy: built on first job, kept for the container's life) ──

_INFERRER = None
_RESIDENT_ERROR: str | None = None
_LOAD_S: float | None = None


def _ensure_resident():
    """Instantiate LAMInferrer exactly as `python -m lam.launch infer.lam`
    would: parse_configs() reads sys.argv, so we impersonate the CLI.
    Runs inside the first job — never at import, so the worker registers
    with RunPod immediately. On failure, records the error and leaves
    _INFERRER as None (jobs then use the subprocess path)."""
    global _INFERRER, _RESIDENT_ERROR, _LOAD_S
    if _INFERRER is not None or _RESIDENT_ERROR is not None:
        return
    try:
        os.chdir(LAM_ROOT)
        sys.path.insert(0, LAM_ROOT)
        # parse_configs() asserts image_input is set even though we call
        # infer_single() with explicit paths — feed it a placeholder.
        sys.argv = ["rp_handler", "--config", LAM_CONFIG,
                    "image_input=/tmp/placeholder.jpg", *_CLI_OVERRIDES]
        t0 = time.monotonic()
        from lam.runners.infer.lam import LAMInferrer  # heavy: torch + weights

        _INFERRER = LAMInferrer()
        _LOAD_S = round(time.monotonic() - t0, 1)
        logger.info("resident LAM model ready in %.1fs", _LOAD_S)
    except Exception:
        _RESIDENT_ERROR = traceback.format_exc()
        logger.error("resident init failed — falling back to subprocess mode:\n%s",
                     _RESIDENT_ERROR)


def _run_resident(image_path: str) -> str:
    """Single-image flow mirroring LAMInferrer.infer(): tracking → forward.
    Returns path to the canonical PLY."""
    inf = _INFERRER
    assert (inf.flametracking.preprocess(image_path)) == 0, "flametracking preprocess failed"
    assert (inf.flametracking.optimize()) == 0, "flametracking optimize failed"
    rc, output_dir = inf.flametracking.export()
    assert rc == 0, "flametracking export failed"

    tracked = os.path.join(output_dir, "images/00000_00.png")
    uid = os.path.basename(os.path.dirname(os.path.dirname(tracked)))
    dump_image_dir = os.path.join(inf.cfg.image_dump, uid)
    dump_tmp_dir = os.path.join(inf.cfg.image_dump, "tmp_res")
    dump_video_path = os.path.join(inf.cfg.video_dump, f"{uid}.mp4")
    dump_mesh_path = os.path.join(inf.cfg.mesh_dump)
    for d in (dump_image_dir, dump_tmp_dir, dump_mesh_path):
        os.makedirs(d, exist_ok=True)

    inf.infer_single(
        tracked,
        motion_seqs_dir=inf.cfg.motion_seqs_dir,
        motion_img_dir=inf.cfg.motion_img_dir,
        motion_video_read_fps=inf.cfg.motion_video_read_fps,
        export_video=inf.cfg.export_video,
        export_mesh=inf.cfg.export_mesh,
        dump_tmp_dir=dump_tmp_dir,
        dump_image_dir=dump_image_dir,
        dump_video_path=dump_video_path,
        dump_mesh_path=None,  # export_mesh=false → skip per-frame PLYs
        gaga_track_type="",
    )
    return _find_cano_ply()


# ── subprocess fallback (original path) ───────────────────────────────────────

def _run_subprocess(image_path: str) -> str:
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": "0",
           "PYTHONPATH": f"{os.environ.get('PYTHONPATH', '')}:{LAM_ROOT}"}
    cmd = ["python", "-m", "lam.launch", "infer.lam", "--config", LAM_CONFIG,
           f"image_input={image_path}", *_CLI_OVERRIDES]
    logger.info("LAM inference (subprocess): %s", " ".join(cmd))
    proc = subprocess.run(
        cmd, cwd=LAM_ROOT, env=env, capture_output=True, text=True, timeout=600
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"LAM inference failed (rc={proc.returncode}): {proc.stderr[-2000:]}"
        )
    return _find_cano_ply()


# ── handler ───────────────────────────────────────────────────────────────────

def handler(event: dict) -> dict:
    inp = event.get("input", {})
    job_type = inp.get("job_type")

    if job_type == "warmup":
        _ensure_resident()  # first warmup pays the model load; rest are no-ops
        return {"warmed": True, "resident": _INFERRER is not None,
                "load_s": _LOAD_S, "resident_error": _RESIDENT_ERROR}

    if job_type != "lam_reconstruct":
        return {"error": f"unsupported job_type: {job_type}"}
    b64 = inp.get("image_b64")
    if not b64:
        return {"error": "image_b64 required for lam_reconstruct"}

    try:
        started = time.monotonic()
        _ensure_resident()
        _clean_outputs()  # no stale PLYs on warm workers
        with tempfile.TemporaryDirectory() as tmp:
            image_path = os.path.join(tmp, "input.jpg")
            with open(image_path, "wb") as f:
                f.write(base64.b64decode(b64))
            if _INFERRER is not None:
                mode, ply_path = "resident", _run_resident(image_path)
            else:
                mode, ply_path = "subprocess", _run_subprocess(image_path)
            ply_bytes = open(ply_path, "rb").read()

        commit = open("/opt/LAM_COMMIT").read().strip() if os.path.exists("/opt/LAM_COMMIT") else "?"
        logger.info("LAM done (%s): %s (%d bytes) in %.1fs", mode, ply_path,
                    len(ply_bytes), time.monotonic() - started)
        return {
            "gaussians_ply_b64": base64.b64encode(ply_bytes).decode(),
            "lam_commit": commit,
            "inference_s": round(time.monotonic() - started, 1),
            "mode": mode,
        }
    except Exception as exc:  # honest errors only — no silent fallbacks
        logger.exception("lam_reconstruct failed")
        return {"error": str(exc)}


runpod.serverless.start({"handler": handler})

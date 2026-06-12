# Avatar pipeline worker — MICA identity reconstruction ONLY (MVP architecture)
#
# MVP decision (see backend/MVP-production-pipeline.md):
#   - Single RunPod endpoint: avatar-mica (job_type: "mica_fit")
#   - DECA / EMOCA / GPU gaussian reconstruct removed — those stages now run
#     on CPU in the backend (texture bake + local gaussian sampling) or were
#     replaced (EMOCA → analytical FLAME expression basis + photo texture bake).
#
# Build (GitHub Actions does this automatically on push):
#   docker buildx build --platform linux/amd64 -f docker/avatar_worker.Dockerfile \
#     -t devopsavatar/avatar-worker:latest --push .
#
# Model weights — RunPod Network Volume mounted at /weights:
#   /weights/mica/mica.tar                      ← https://mica.is.tue.mpg.de (registration)
#   /weights/mica/FLAME2020/generic_model.pkl   ← https://flame.is.tue.mpg.de (registration)
#   /weights/mica/insightface/                  ← auto-downloads antelopev2 on first run

FROM runpod/pytorch:2.2.1-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# ── System deps (opencv/insightface runtime libs) ─────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────────────────
# numpy<2 for onnxruntime/insightface compatibility.
RUN pip install --no-cache-dir \
    "runpod>=1.6.0" \
    "numpy>=1.26.0,<2" \
    "Pillow>=10.0.0" \
    "scipy>=1.11.0" \
    "opencv-python-headless>=4.8.0" \
    "insightface>=0.7.3" \
    "onnxruntime-gpu>=1.16.0" \
    "yacs>=0.1.8" \
    "loguru>=0.7.0" \
    "scikit-image>=0.21.0"
# NOTE: chumpy is NOT installed — FLAME2020 pkl unpickling is handled by
# chumpy_stub.py in the worker code (chumpy doesn't build on modern numpy).

# ── pytorch3d — official prebuilt wheel for py3.10 + cu121 + torch 2.2.1 ─────
# (MICA's FLAME module imports it; wheel install takes seconds vs 40-min source build)
RUN pip install --no-cache-dir fvcore iopath && \
    pip install --no-cache-dir \
    "pytorch3d @ https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt221/pytorch3d-0.7.6-cp310-cp310-linux_x86_64.whl"

# ── MICA repo (https://github.com/Zielon/MICA) ────────────────────────────────
# Provides: configs.config.get_cfg_defaults, micalib.models.mica.MICA,
#           utils.* — all importable via PYTHONPATH (repo has no setup.py).
RUN git clone --depth 1 https://github.com/Zielon/MICA.git /opt/MICA

ENV PYTHONPATH="/opt/MICA"

# ── Worker code (last layer — handler changes rebuild only this, ~2 min) ─────
COPY worker/avatar_worker/ /app/

ENV MICA_WEIGHTS_PATH=/weights/mica

CMD ["python", "-u", "handler.py"]

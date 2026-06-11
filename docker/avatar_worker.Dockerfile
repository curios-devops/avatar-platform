# Avatar pipeline worker — DECA + MICA + EMOCA + Gaussian reconstruction
#
# Build:
#   docker build -f docker/avatar_worker.Dockerfile -t <your-hub>/avatar-worker:latest .
#   docker push <your-hub>/avatar-worker:latest
#
# RunPod setup — create FOUR serverless endpoints with this image:
#   1. flame_fit:          RUNPOD_FLAME_ENDPOINT_ID
#   2. reconstruct:        RUNPOD_RECONSTRUCT_ENDPOINT_ID
#   3. mica_fit:           RUNPOD_MICA_ENDPOINT_ID
#   4. emoca_reconstruct:  RUNPOD_EMOCA_ENDPOINT_ID
# All share the same image; job_type field routes to the right handler.
#
# Model weights:
#   Option A (recommended — RunPod Network Volume mounted at /weights):
#     Run once: python worker/avatar_worker/download_weights.py
#     DECA: auto-download from Google Drive
#     MICA: set MICA_DOWNLOAD_URL env var (requires mica.is.tue.mpg.de registration)
#     EMOCA: set EMOCA_DOWNLOAD_URL env var (requires emoca.is.tue.mpg.de registration)
#
#   Option B (bake into image — larger, easier cold start):
#     Uncomment the COPY blocks near the bottom.

FROM runpod/pytorch:2.2.1-py3.10-cuda12.1.1-devel-ubuntu22.04

WORKDIR /app

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget curl \
        libgl1-mesa-glx libglib2.0-0 libsm6 libxext6 libxrender-dev \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# ── Python core deps (fast layer — rarely changes) ───────────────────────────
RUN pip install --no-cache-dir \
    runpod>=1.6.0 \
    numpy>=1.26.0 \
    Pillow>=10.0.0 \
    scipy>=1.11.0 \
    torchvision>=0.16.0 \
    face-alignment>=1.3.5 \
    kornia>=0.6.12 \
    mediapipe>=0.10.0

# ── pytorch3d (build from source — compatible with CUDA 12.1 + torch 2.2) ────
RUN pip install --no-cache-dir fvcore iopath && \
    pip install --no-cache-dir "git+https://github.com/facebookresearch/pytorch3d.git@stable"

# ── DECA (Phase 0 FLAME fitter) ───────────────────────────────────────────────
RUN git clone --depth 1 https://github.com/YadiraF/DECA.git /opt/DECA

# ── MICA deps (Phase 2 multi-view identity reconstruction) ───────────────────
# insightface provides ArcFace feature extraction.
# onnxruntime-gpu accelerates ArcFace on CUDA.
RUN pip install --no-cache-dir \
    insightface>=0.7.3 \
    onnxruntime-gpu>=1.16.0

# ── MICA model (Phase 2) ──────────────────────────────────────────────────────
RUN git clone --depth 1 https://github.com/Zielon/MICA.git /opt/MICA

ENV PYTHONPATH="/opt/DECA:/opt/MICA:/opt/emoca:/opt/emoca/gdl"

# ── EMOCA deps (Phase 2 detailed reconstruction + albedo) ────────────────────
RUN pip install --no-cache-dir \
    omegaconf>=2.3.0 \
    hydra-core>=1.3.2 \
    scikit-image>=0.21.0

# ── EMOCA model (Phase 2) — clone only, install via PYTHONPATH ───────────────
# Avoids pip install failures if repo root lacks setup.py/pyproject.toml.
RUN git clone --depth 1 https://github.com/radekd91/emoca.git /opt/emoca && \
    pip install --no-cache-dir -e /opt/emoca 2>/dev/null || \
    echo "EMOCA pip install skipped — using PYTHONPATH fallback"

# ── Worker code ───────────────────────────────────────────────────────────────
COPY worker/avatar_worker/ /app/

# ── Weight paths (override with RunPod endpoint env vars if needed) ───────────
ENV DECA_WEIGHTS_PATH=/weights/deca_model.tar
ENV MICA_WEIGHTS_PATH=/weights/mica
ENV EMOCA_WEIGHTS_PATH=/weights/emoca

# ── Weights Option B: bake into image ────────────────────────────────────────
# Uncomment and supply pre-downloaded weight files at build time.
# DECA (~430 MB):
#   COPY weights/deca_model.tar /weights/deca_model.tar
# MICA (~200 MB):
#   COPY weights/mica/ /weights/mica/
# EMOCA (~1.5 GB):
#   COPY weights/emoca/ /weights/emoca/

CMD ["python", "-u", "handler.py"]

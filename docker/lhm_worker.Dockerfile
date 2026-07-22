# LHM (Large Animatable Human Model) RunPod serverless worker —
# one photo → half-body or full-body animatable gaussian avatar (3DGS PLY).
# POC decision 2026-07-17: LHM-500M-HF covers BOTH framings (half & full),
# giving avatar tiers 2 (half body w/ hands) and 3 (full body) with one
# worker. Tier 1 (talking head) stays on the LAM worker.
#
# Build (hours on Apple Silicon — pytorch3d etc. compile under qemu):
#   docker build --platform linux/amd64 -f docker/lhm_worker.Dockerfile \
#     [--build-arg HF_TOKEN=hf_xxx] -t devopsavatar/lhm-worker:v1 .
#   docker push devopsavatar/lhm-worker:v1
# HF_TOKEN is optional — pass it if HuggingFace 403s anonymous downloads
# (bitten on 2026-07-13 with LAM assets).
#
# RunPod endpoint: GPU 24 GB, allowedCudaVersions 12.1-12.6 (CUDA-13 driver
# hosts silently break cu121 images — see docs/lam-migration.md).

FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9"
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone https://github.com/aigc3d/LHM.git && cd LHM && \
    git rev-parse HEAD > /opt/LHM_COMMIT

# B2 needs the SMPL-X betas that infer_mesh() computes but discards — patch
# it to also dump a sidecar <name>_betas.npy next to the exported .ply.
COPY worker/lhm_worker/patch_export_betas.py /tmp/patch_export_betas.py
RUN python /tmp/patch_export_betas.py /opt/LHM/LHM/runners/infer/human_lrm.py

WORKDIR /opt/LHM
# LHM's own installer: torch 2.3 cu121 wheels + pytorch3d, sam2,
# diff-gaussian-rasterization, simple-knn from source.
RUN pip install rembg && sh ./install_cu121.sh

# Weights: LHM-500M-HF (half & full body, 24 GB VRAM, ~2 s inference).
# hub <1.0 pinned for the huggingface-cli entrypoint (same as LAM image).
ARG HF_TOKEN=""
RUN pip install "huggingface_hub[cli]>=0.23,<1.0" && \
    ( [ -n "$HF_TOKEN" ] && export HF_TOKEN="$HF_TOKEN"; \
      huggingface-cli download 3DAIGC/LHM-500M-HF --local-dir ./pretrained_models_tmp ) && \
    mkdir -p pretrained_models && \
    cp -r pretrained_models_tmp/* pretrained_models/ && rm -rf pretrained_models_tmp

# SMPL-X prior model assets — install_cu121.sh does NOT fetch these, but
# LHM/models/rendering/smpl_x_voxel_dense_sampling.py loads
# human_model_path/smplx/SMPL-X__FLAME_vertex_ids.npy at INFERENCE time (not
# just training). Missing this tar is a likely reason the original POC never
# produced a validated body.ply. Also the exact asset B2 (fuse.py) needs for
# the FLAME<->SMPL-X registration — no separate license fetch required.
RUN wget -q https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/for_lingteng/LHM/LHM_prior_model.tar \
      -O /tmp/LHM_prior_model.tar && \
    tar -xf /tmp/LHM_prior_model.tar -C /opt/LHM && rm /tmp/LHM_prior_model.tar

# Assets the runner lazily fetches at first inference — bake them so a cold
# worker doesn't depend on external hosts at job time.
RUN mkdir -p pretrained_models/dense_sample_points && \
    wget -q -O pretrained_models/dense_sample_points/1_20000.ply \
      https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/LHM/1_20000.ply

RUN pip install runpod

COPY worker/lhm_worker/handler.py /opt/LHM/rp_handler.py
CMD ["python", "-u", "/opt/LHM/rp_handler.py"]

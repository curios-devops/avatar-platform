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
# onnxruntime: human_lrm.py always falls back to rembg (SAM2Seg import fails
# since engine.SegmentAPI isn't installed here) — bare `pip install rembg`
# doesn't pull onnxruntime, confirmed missing by a real job failure.
RUN pip install rembg onnxruntime && sh ./install_cu121.sh

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
# just training). Missing this tree is a likely reason the original POC never
# produced a validated body.ply. Also the exact asset B2 (fuse.py) needs for
# the FLAME<->SMPL-X registration — no separate license fetch required.
# Source: LHM's own LHM_prior_model.tar (Aliyun OSS) 403s its entire bucket as
# of 2026-07-23 (upstream broke, not path-specific) — using the HuggingFace
# mirror instead (3DAIGC/LHMPP-Prior, public, same huggingface-cli already
# used above). See docker/lhm_worker.incremental.Dockerfile for the verified
# selective --include pattern (~6.5GB vs 7.67GB full repo). voxel_grid/,
# arcface_resnet18.pth and BiRefNet-general-epoch_244.pth are REQUIRED at
# model init (SMPLXVoxelMeshModel.register_constrain_prior, ResNetArcFace,
# matting) — each confirmed by a real job failure, not by reading the code.
# Don't drop any of them again; a failed job cycle costs more than the extra
# download size.
RUN huggingface-cli download 3DAIGC/LHMPP-Prior \
      --include "human_model_files/*" "gagatracker/vgghead/*" "voxel_grid/*" \
                "arcface_resnet18.pth" "BiRefNet-general-epoch_244.pth" \
      --exclude "human_model_files/smplx/smplx_npz.zip" \
      --local-dir pretrained_models && \
    test -f pretrained_models/gagatracker/vgghead/vgg_heads_l.trcd && \
    test -f pretrained_models/voxel_grid/human_prior_constrain.npz && \
    test -f pretrained_models/arcface_resnet18.pth && \
    test -f pretrained_models/BiRefNet-general-epoch_244.pth

# Sapiens-1B fine encoder checkpoint — LHMPP-Prior doesn't carry `sapiens/`
# at all; configs/inference/human-lrm-500M.yaml points fine_encoder_model_name
# at this exact file. Real source verified against the config (facebook/
# sapiens-pretrain-1b-torchscript), found only after a job crashed on it.
RUN mkdir -p pretrained_models/sapiens/pretrained/checkpoints/sapiens_1b && \
    huggingface-cli download facebook/sapiens-pretrain-1b-torchscript \
      sapiens_1b_epoch_173_torchscript.pt2 --local-dir /tmp/sapiens_dl && \
    mv /tmp/sapiens_dl/sapiens_1b_epoch_173_torchscript.pt2 \
       pretrained_models/sapiens/pretrained/checkpoints/sapiens_1b/ && \
    rm -rf /tmp/sapiens_dl && \
    test -f pretrained_models/sapiens/pretrained/checkpoints/sapiens_1b/sapiens_1b_epoch_173_torchscript.pt2

# RealESRGAN_x4plus.pth — ESRGANEasyModel (facesr: True in config) needs this
# at ./pretrained_models/RealESRGAN_x4plus.pth; confirmed missing by a real
# job traceback. Source verified against LHM's own ESRGANEasyModel.file_url
# (ESRGANer_utils.py): official xinntao/Real-ESRGAN v0.1.0 GitHub release.
RUN wget -q -O pretrained_models/RealESRGAN_x4plus.pth \
      https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth && \
    test -s pretrained_models/RealESRGAN_x4plus.pth

# Assets the runner lazily fetches at first inference — bake them so a cold
# worker doesn't depend on external hosts at job time.
# NOTE 2026-07-24: this URL is on the SAME Aliyun bucket that 403s everything
# else in this file (see the huggingface-cli fallback above) — it only still
# works here because it's cached in the v1 image layer from before the bucket
# broke. A genuine from-scratch rebuild of THIS file will need a new source
# for 1_20000.ply (LHMPP-Prior only has dense_sample_points/1_160000.ply, a
# different sample density — unverified as a drop-in substitute).
RUN mkdir -p pretrained_models/dense_sample_points && \
    wget -q -O pretrained_models/dense_sample_points/1_20000.ply \
      https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/LHM/1_20000.ply

RUN pip install runpod

COPY worker/lhm_worker/handler.py /opt/LHM/rp_handler.py
CMD ["python", "-u", "/opt/LHM/rp_handler.py"]

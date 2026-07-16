# LAM (Large Avatar Model) RunPod serverless worker — photo → animatable
# gaussian head. Replaces the MICA+multiview+texture-bake core (POC decision
# 2026-07-06, see docs/lam-migration.md).
#
# Build (needs ~40 GB disk, downloads ~10 GB of weights):
#   docker build -f docker/lam_worker.Dockerfile -t <hub>/lam-worker:latest .
#   docker push <hub>/lam-worker:latest

FROM pytorch/pytorch:2.3.0-cuda12.1-cudnn8-devel

ENV DEBIAN_FRONTEND=noninteractive TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9"
RUN apt-get update && apt-get install -y --no-install-recommends \
    git wget curl libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
# Pin LAM to a known commit for reproducible builds (update deliberately)
RUN git clone https://github.com/aigc3d/LAM.git && cd LAM && \
    git rev-parse HEAD > /opt/LAM_COMMIT

WORKDIR /opt/LAM
# LAM's own installer (CUDA 12.1): pytorch3d, diff-gaussian-rasterization, etc.
RUN sh ./scripts/install/install_cu121.sh

# Assets (FLAME templates, thirdparty models) + LAM-20K weights
# Pin <1.0: hub 1.x removed `huggingface-cli` and breaks transformers' pin
RUN pip install "huggingface_hub[cli]>=0.23,<1.0" && \
    huggingface-cli download 3DAIGC/LAM-assets --local-dir ./tmp && \
    tar -xf ./tmp/LAM_assets.tar && tar -xf ./tmp/thirdparty_models.tar && \
    rm -rf ./tmp && \
    huggingface-cli download 3DAIGC/LAM-20K \
      --local-dir ./model_zoo/lam_models/releases/lam/lam-20k/step_045500/

RUN pip install runpod

# LAM's runner saves the cano PLY with offset2xyz=True → x/y/z are per-gaussian
# OFFSETS, not positions (renders as a cloud). Switch to real positions + SH.
RUN sed -i "s/save_ply(cano_ply_pth, rgb2sh=False, offset2xyz=True)/save_ply(cano_ply_pth, rgb2sh=True, offset2xyz=False)/" \
    lam/runners/infer/lam.py && \
    grep -q "rgb2sh=True, offset2xyz=False" lam/runners/infer/lam.py

# 1-frame motion sequence: LAM renders EVERY motion frame inside its forward
# pass (+ a PNG each + video encode), so sequence length — not reconstruction —
# dominated job time. We only need the canonical PLY; keep a single frame.
# The wav is copied under the new base name because add_audio_to_video()
# crashes on a missing file (moviepy trims audio to the 1-frame video).
RUN python - <<'PYEOF'
import json, os, shutil
src = "assets/sample_motion/export/Look_In_My_Eyes"
dst = "assets/sample_motion/export/neutral_1f"
os.makedirs(dst, exist_ok=True)
d = json.load(open(f"{src}/transforms.json"))
d["frames"] = sorted(d["frames"], key=lambda x: x["flame_param_path"])[:1]
fp = d["frames"][0]["flame_param_path"]
os.makedirs(os.path.dirname(os.path.join(dst, fp)), exist_ok=True)
shutil.copy(os.path.join(src, fp), os.path.join(dst, fp))
for aux in ("canonical_flame_param.npz", "tracked_teeth_bs.npz"):
    if os.path.exists(f"{src}/{aux}"):
        shutil.copy(f"{src}/{aux}", f"{dst}/{aux}")
json.dump(d, open(f"{dst}/transforms.json", "w"))
shutil.copy(f"{src}/Look_In_My_Eyes.wav", f"{dst}/neutral_1f.wav")
print("neutral_1f:", os.listdir(dst))
PYEOF

COPY worker/lam_worker/handler.py /opt/LAM/rp_handler.py
CMD ["python", "-u", "/opt/LAM/rp_handler.py"]

#!/bin/bash
# The 80 GB pod of the arena: EchoMimicV3-Flash (half-body, arms) and LiveAvatar (Wan2.2-S2V-14B + LiveAvatar LoRA,
# single-GPU mode). Each in its own venv, weights from Hugging Face in parallel with the installs.
# Timings in /workspace/logs/setup_times.txt.  Run: setsid nohup bash setup_big.sh > logs/setup_big.txt 2>&1 &
set -uo pipefail
W=/workspace; mkdir -p $W/logs $W/out $W/in; cd $W
t(){ echo "$(date +%s) $1" >> $W/logs/setup_times.txt; echo "[$(date +%H:%M:%S)] $1"; }
t start
(apt-get update -qq && apt-get install -y -qq ffmpeg > /dev/null && t ffmpeg) &
pip install -q uv "huggingface_hub[cli]<1" hf_transfer > /dev/null 2>&1
export HF_HUB_ENABLE_HF_TRANSFER=1
FA_URL=https://github.com/Dao-AILab/flash-attention/releases/download
git clone -q --depth 1 https://github.com/Alibaba-Quark/LiveAvatar.git $W/la
git clone -q --depth 1 https://github.com/antgroup/echomimic_v3.git $W/em

# --- weights
( huggingface-cli download BadToBest/EchoMimicV3 --include "echomimicv3-flash-pro/*" --local-dir $W/models/em > $W/logs/dl_em.log 2>&1
  huggingface-cli download alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP --local-dir $W/models/em/Wan2.1-Fun-V1.1-1.3B-InP >> $W/logs/dl_em.log 2>&1
  huggingface-cli download TencentGameMate/chinese-wav2vec2-base --exclude "*fairseq*" --local-dir $W/models/em/chinese-wav2vec2-base >> $W/logs/dl_em.log 2>&1
  t weights_echomimic ) &
( huggingface-cli download Wan-AI/Wan2.2-S2V-14B --local-dir $W/la/ckpt/Wan2.2-S2V-14B > $W/logs/dl_la.log 2>&1
  huggingface-cli download Quark-Vision/Live-Avatar --local-dir $W/la/ckpt/LiveAvatar >> $W/logs/dl_la.log 2>&1
  t weights_liveavatar ) &

# --- EchoMimicV3 (same stack as the V1 benchmark)
( cd $W/em && uv venv -q -p 3.11 .venv && . .venv/bin/activate \
  && uv pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/${TORCH_CUDA:-cu126} \
  && uv pip install -q -r requirements.txt pyloudnorm "transformers==4.46.2" "diffusers==0.31.0" \
  && uv pip install -q "$FA_URL/v2.8.0.post2/flash_attn-2.8.0.post2+cu12torch2.7cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" \
  && python -c "import torch, diffusers, librosa; print('em ok', torch.__version__)" ) > $W/logs/pip_em.log 2>&1 &

# --- LiveAvatar (torch 2.8 cu128 as its README; flash-attn prebuilt wheel, else it falls back to SDPA)
( cd $W/la && uv venv -q -p 3.11 .venv && . .venv/bin/activate \
  && uv pip install -q torch==2.8.0 torchvision==0.23.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/${TORCH_CUDA:-cu126} \
  && uv pip install -q -r requirements.txt \
  && (uv pip install -q "$FA_URL/v2.8.3/flash_attn-2.8.3+cu12torch2.8cxx11abiTRUE-cp311-cp311-linux_x86_64.whl" \
      && python -c "import flash_attn" || (uv pip uninstall -q flash_attn; uv pip install -q "$FA_URL/v2.8.3/flash_attn-2.8.3+cu12torch2.8cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" && python -c "import flash_attn") || echo "no flash_attn") \
  && python -c "import torch, diffusers, peft; print('la ok', torch.__version__, torch.cuda.is_available())" ) > $W/logs/pip_la.log 2>&1 &
wait
tail -1 $W/logs/pip_em.log; tail -2 $W/logs/pip_la.log
t setup_end; df -h $W | tail -1

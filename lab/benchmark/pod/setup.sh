#!/bin/bash
# Lab GPU pod (runpod/pytorch 2.4 base, torch 2.7.1 cu126 in each venv, Python 3.11): SoulX-FlashHead (Lite + Pro) and EchoMimicV3-Flash, each in its
# own venv, weights from Hugging Face. Timings go to /workspace/logs/setup_times.txt.
set -uo pipefail
W=/workspace; mkdir -p $W/logs $W/out; cd $W
t(){ echo "$(date +%s) $1" >> $W/logs/setup_times.txt; echo "[$(date +%H:%M:%S)] $1"; }
t start
(apt-get update -qq && apt-get install -y -qq ffmpeg > /dev/null && t ffmpeg) &
pip install -q uv "huggingface_hub[cli]<1" hf_transfer > /dev/null 2>&1
export HF_HUB_ENABLE_HF_TRANSFER=1

# --- weights, in parallel with the installs
( huggingface-cli download Soul-AILab/SoulX-FlashHead-1_3B --local-dir $W/models/SoulX-FlashHead-1_3B > $W/logs/dl_fh.log 2>&1
  huggingface-cli download facebook/wav2vec2-base-960h --local-dir $W/models/wav2vec2-base-960h > /dev/null 2>&1
  t weights_flashhead
  huggingface-cli download BadToBest/EchoMimicV3 --include "echomimicv3-flash-pro/*" --local-dir $W/models/em > $W/logs/dl_em.log 2>&1
  huggingface-cli download alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP --local-dir $W/models/em/Wan2.1-Fun-V1.1-1.3B-InP >> $W/logs/dl_em.log 2>&1
  huggingface-cli download TencentGameMate/chinese-wav2vec2-base --exclude "*fairseq*" --local-dir $W/models/em/chinese-wav2vec2-base >> $W/logs/dl_em.log 2>&1
  t weights_echomimic ) &

# --- FlashHead
git clone -q --depth 1 https://github.com/Soul-AILab/SoulX-FlashHead.git $W/fh
( cd $W/fh && uv venv -q -p 3.11 .venv && . .venv/bin/activate \
  && uv pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128 \
  && uv pip install -q -r requirements.txt \
  && uv pip install -q "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.0.post2/flash_attn-2.8.0.post2+cu12torch2.7cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" \
  && python -c "import torch, flash_attn, xformers; print('fh ok', torch.__version__, torch.cuda.is_available())" ) > $W/logs/pip_fh.log 2>&1
tail -1 $W/logs/pip_fh.log; t deps_flashhead

# --- EchoMimicV3
git clone -q --depth 1 https://github.com/antgroup/echomimic_v3.git $W/em
( cd $W/em && uv venv -q -p 3.11 .venv && . .venv/bin/activate \
  && uv pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128 \
  && uv pip install -q -r requirements.txt \
  && uv pip install -q "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.0.post2/flash_attn-2.8.0.post2+cu12torch2.7cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" \
  && python -c "import torch, diffusers, librosa; print('em ok', torch.__version__)" ) > $W/logs/pip_em.log 2>&1
tail -1 $W/logs/pip_em.log; t deps_echomimic
wait
t setup_end; df -h $W | tail -1

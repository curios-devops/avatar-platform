#!/bin/bash
# EchoMimicV3 *preview* (the half-body model of their demos: 25 steps, 113-frame windows) on a 24 GB pod, own venv.
# Weights: Wan2.1-Fun-V1.1-1.3B-InP + the preview transformer + wav2vec2-base-960h.  TORCH_CUDA=cu128 for Blackwell.
set -uo pipefail
W=/workspace; mkdir -p $W/logs $W/models; cd $W
t(){ echo "$(date +%s) $1" >> $W/logs/setup_times.txt; echo "[$(date +%H:%M:%S)] $1"; }
pip install -q uv "huggingface_hub[cli]<1" hf_transfer > /dev/null 2>&1
export HF_HUB_ENABLE_HF_TRANSFER=1
git clone -q --depth 1 https://github.com/antgroup/echomimic_v3.git $W/em
( huggingface-cli download alibaba-pai/Wan2.1-Fun-V1.1-1.3B-InP --local-dir $W/models/em/Wan2.1-Fun-V1.1-1.3B-InP > $W/logs/dl_em.log 2>&1
  huggingface-cli download BadToBest/EchoMimicV3 --include "transformer/*" --local-dir $W/models/em/preview >> $W/logs/dl_em.log 2>&1
  [ -d $W/models/wav2vec2-base-960h ] || huggingface-cli download facebook/wav2vec2-base-960h --local-dir $W/models/wav2vec2-base-960h >> $W/logs/dl_em.log 2>&1
  t weights_echomimic_preview ) &
( cd $W/em && uv venv -q -p 3.11 .venv && . .venv/bin/activate \
  && uv pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/${TORCH_CUDA:-cu126} \
  && uv pip install -q -r requirements.txt pyloudnorm "transformers==4.46.2" "diffusers==0.31.0" \
  && uv pip install -q "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.0.post2/flash_attn-2.8.0.post2+cu12torch2.7cxx11abiFALSE-cp311-cp311-linux_x86_64.whl" \
  && python -c "import torch, diffusers, librosa; print('em ok', torch.__version__, torch.cuda.is_available())" ) > $W/logs/pip_em.log 2>&1
wait; tail -1 $W/logs/pip_em.log; t setup_em_end

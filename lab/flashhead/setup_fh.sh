#!/bin/bash
# Adds SoulX-FlashHead Lite (real time) next to MuseTalk on a meya-livetalking pod: own venv, Lite weights only.
# TORCH_CUDA=cu128 for drivers >= 570 (Blackwell needs it), cu126 otherwise.
set -uo pipefail
W=/workspace; mkdir -p $W/logs; cd $W
t(){ echo "[$(date +%H:%M:%S)] $1"; }
t start
pip install -q uv "huggingface_hub[cli]<1" hf_transfer > /dev/null 2>&1
export HF_HUB_ENABLE_HF_TRANSFER=1
( huggingface-cli download Soul-AILab/SoulX-FlashHead-1_3B --include "Model_Lite/*" "VAE_LTX/*" "*.json" --local-dir $W/models/SoulX-FlashHead-1_3B > /dev/null 2>&1
  huggingface-cli download facebook/wav2vec2-base-960h --local-dir $W/models/wav2vec2-base-960h > /dev/null 2>&1; t weights ) &
git clone -q --depth 1 https://github.com/Soul-AILab/SoulX-FlashHead.git $W/fh && cd $W/fh
CU=${TORCH_CUDA:-cu126}
uv venv -q -p 3.11 .venv && . .venv/bin/activate
uv pip install -q torch==2.7.1 torchvision==0.22.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/$CU
grep -vE "^(xformers|nvidia-nccl|gradio)" requirements.txt > /tmp/req.txt
uv pip install -q -r /tmp/req.txt xformers==0.0.31 aiortc aiohttp websockets \
  "https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.0.post2/flash_attn-2.8.0.post2+cu12torch2.7cxx11abiFALSE-cp311-cp311-linux_x86_64.whl"
python -c "import torch, flash_attn, aiortc; print('fh deps ok', torch.__version__, torch.cuda.get_device_name(0))"
t deps; wait; t setup_end

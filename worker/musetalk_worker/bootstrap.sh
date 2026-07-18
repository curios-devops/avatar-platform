#!/bin/bash
# A2 — bootstrap idempotente del pod MuseTalk (runpod/pytorch cu118).
# Instala repo + deps + pesos en /workspace y arranca el server (8600).
set -euo pipefail
cd /workspace
LOG=/workspace/bootstrap.log
exec > >(tee -a "$LOG") 2>&1
echo "=== bootstrap $(date) ==="

# 1. repo
if [ ! -d MuseTalk ]; then
  git clone https://github.com/TMElyralab/MuseTalk.git
fi
cd MuseTalk

# 2. deps python (mmlab con wheels precompiladas cu118/torch2.0.x via openmim)
if [ ! -f /workspace/.deps_ok ]; then
  pip install -q --no-cache-dir -r requirements.txt || true   # tolera pins rotos; abajo lo crítico
  pip install -q --no-cache-dir -U openmim
  mim install -q "mmengine" "mmcv==2.0.1" "mmdet==3.1.0" "mmpose==1.1.0"
  pip install -q --no-cache-dir fastapi uvicorn "pydantic>=2" transformers accelerate \
      librosa soundfile moviepy imageio[ffmpeg] "huggingface_hub[cli]<1.0"
  apt-get update -qq && apt-get install -y -qq ffmpeg
  touch /workspace/.deps_ok
fi

# 3. pesos (layout oficial ./models — el repo trae download_weights.sh)
if [ ! -f models/musetalkV15/unet.pth ]; then
  if [ -f download_weights.sh ]; then
    bash download_weights.sh
  else
    huggingface-cli download TMElyralab/MuseTalk --local-dir models
  fi
fi
ls -la models/ || true

# 4. server residente
mkdir -p /workspace/avatars
cp /workspace/server.py /workspace/MuseTalk/server_a2.py 2>/dev/null || true
pkill -f "uvicorn server_a2" 2>/dev/null || true
cd /workspace/MuseTalk
nohup python -m uvicorn server_a2:app --host 0.0.0.0 --port 8600 \
      > /workspace/server.log 2>&1 &
echo "=== bootstrap listo; server lanzado (log: /workspace/server.log) ==="

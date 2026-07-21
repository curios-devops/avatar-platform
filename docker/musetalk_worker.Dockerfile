# A2 — worker MuseTalk serverless. Deps EN LA IMAGEN (entorno limpio), pesos
# (~12 GB) en el NETWORK VOLUME. Esto elimina la clase de errores del enfoque
# anterior (pip --target al volumen → resolución imagen-vs-volumen
# indeterminista, hub 1.24.0 imponiéndose, etc.): aquí pip instala normal en el
# site-packages de la imagen, una sola vez, sin ambigüedad.
#
# El volumen guarda solo: /runpod-volume/models (pesos) y
# /runpod-volume/avatars (latentes preparados por avatar, persistentes).
#
# Build:  docker build --platform linux/amd64 \
#           -f docker/musetalk_worker.Dockerfile -t devopsavatar/musetalk-worker:w1 .
FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PYTHONUNBUFFERED=1
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    ffmpeg git wget && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 https://github.com/TMElyralab/MuseTalk.git

WORKDIR /opt/MuseTalk
# requirements.txt del repo pinea el stack HF consistente (transformers 4.39.2,
# diffusers 0.30.2, huggingface_hub 0.30.2, accelerate 0.28.0). Install normal:
# torch 2.0.1+cu118 de la base ya satisface las deps → pip no lo toca.
RUN pip install --no-cache-dir -r requirements.txt
# mmlab con wheels precompiladas cu118/torch2.0 vía openmim
RUN pip install --no-cache-dir -U openmim \
    && mim install "mmengine" "mmcv==2.0.1" "mmdet==3.1.0" "mmpose==1.1.0"
RUN pip install --no-cache-dir runpod
# Guarda de determinismo: si alguna dep pisó el torch cu118 de la base, restaurar
RUN python -c "import torch,sys; sys.exit(0 if torch.version.cuda else 1)" \
    || pip install --no-cache-dir torch==2.0.1 torchvision==0.15.2 \
       --index-url https://download.pytorch.org/whl/cu118
# ÚLTIMO paso: runpod (arriba) sube huggingface_hub a 1.24.0 (>=1.0, rompe
# transformers 4.39/diffusers 0.30 Y el huggingface-cli de descarga). Fijarlo
# al pin de MuseTalk como paso final, --no-deps para no tocar nada más.
RUN pip install --no-cache-dir --force-reinstall --no-deps "huggingface_hub==0.30.2" \
    && python -c "import huggingface_hub as h; print('hub', h.__version__); \
import transformers, diffusers; print('transformers', transformers.__version__, 'diffusers', diffusers.__version__)"

COPY worker/musetalk_worker/handler.py /opt/MuseTalk/rp_handler.py
CMD ["python", "-u", "/opt/MuseTalk/rp_handler.py"]

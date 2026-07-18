# A2 — imagen MÍNIMA del worker MuseTalk serverless.
#
# Todo lo pesado (repo MuseTalk, deps mmlab, pesos ~12 GB, latentes de
# avatares) vive en el NETWORK VOLUME (/runpod-volume), aprovisionado por el
# job {"job_type":"bootstrap"} del propio handler. La imagen solo aporta:
# base torch cu118 (capas ya en Docker Hub → push casi instantáneo por blob
# mounting) + runpod SDK + ffmpeg + handler.
#
# Build:  docker build --platform linux/amd64 \
#           -f docker/musetalk_worker.Dockerfile -t devopsavatar/musetalk-worker:v1 .
FROM runpod/pytorch:2.0.1-py3.10-cuda11.8.0-devel-ubuntu22.04

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir runpod

COPY worker/musetalk_worker/handler.py /handler.py
CMD ["python", "-u", "/handler.py"]

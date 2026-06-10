# RunPod Worker Dockerfile
# GPU-enabled container for reconstruction and animation

FROM nvidia/cuda:11.8.0-cudnn8-devel-ubuntu22.04

# Set environment
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3-pip \
    git \
    wget \
    ffmpeg \
    colmap \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install PyTorch with CUDA support
RUN pip3 install --no-cache-dir \
    torch==2.1.0 \
    torchvision==0.16.0 \
    torchaudio==2.1.0 \
    --index-url https://download.pytorch.org/whl/cu118

# Install core dependencies
RUN pip3 install --no-cache-dir \
    numpy \
    scipy \
    opencv-python \
    pillow \
    plyfile \
    tqdm \
    runpod \
    requests

# Install gsplat (nerfstudio gaussian splatting)
RUN pip3 install --no-cache-dir gsplat

# Clone SplattingAvatar (if public repo exists)
# RUN git clone https://github.com/SplattingAvatar/SplattingAvatar.git /app/splatting_avatar
# WORKDIR /app/splatting_avatar
# RUN pip3 install -e .

# Clone GaussianSpeech (if public repo exists)
# RUN git clone https://github.com/GaussianSpeech/GaussianSpeech.git /app/gaussian_speech
# WORKDIR /app/gaussian_speech
# RUN pip3 install -e .

# Copy worker code
WORKDIR /app
COPY worker/ /app/worker/

# Set Python path
ENV PYTHONPATH=/app

# Run worker
CMD ["python3", "-u", "worker/runpod_worker.py"]

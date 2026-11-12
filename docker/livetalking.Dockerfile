# MEYA live faces: LiveTalking (Apache-2.0) + MuseTalk 1.5, with the MEYA agent bridge. Everything a pod needs is baked
# in, so it boots in about a minute instead of seven; the avatars live in R2 (see docker/livetalking/entry.sh).
# Built by .github/workflows/build-livetalking.yml. The base is RunPod's own image, usually cached on their hosts.
FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive PIP_NO_CACHE_DIR=1 HF_HUB_ENABLE_HF_TRANSFER=1 EL_MODEL=eleven_v4_turbo
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*

# LiveTalking, pinned (the patches below assume this version).
ARG LT_COMMIT=c7269433a2b6ecebcd9342445d2ecc882c98b0da
RUN git clone https://github.com/lipku/LiveTalking.git /opt/lt && cd /opt/lt && git checkout $LT_COMMIT && rm -rf .git
WORKDIR /opt/lt

RUN pip install -q uv \
 && uv pip install --system -r requirements.txt "transformers==4.46.2" "diffusers==0.31.0" accelerate "numpy<2" \
      dlib-bin face_recognition_models hf_transfer "huggingface_hub[cli]<1" gdown \
 && uv pip install --system --no-deps face_recognition \
 && python -c "import aiortc, face_recognition, transformers, diffusers; print('deps ok')"

# Weights: MuseTalk 1.5, its VAE, Whisper tiny, the face parser and the face detector.
RUN M=models && mkdir -p $M/musetalkV15 $M/sd-vae $M/whisper $M/face-parse-bisent \
 && huggingface-cli download TMElyralab/MuseTalk --local-dir $M --include "musetalkV15/*" \
 && huggingface-cli download stabilityai/sd-vae-ft-mse --local-dir $M/sd-vae --include config.json diffusion_pytorch_model.bin \
 && huggingface-cli download openai/whisper-tiny --local-dir $M/whisper --include config.json pytorch_model.bin preprocessor_config.json \
 && (gdown 154JgKpzCPW82qINcVieuPH3fZ2e0P812 -O $M/face-parse-bisent/79999_iter.pth || (sleep 20 && gdown 154JgKpzCPW82qINcVieuPH3fZ2e0P812 -O $M/face-parse-bisent/79999_iter.pth)) \
 && curl -sfL https://download.pytorch.org/models/resnet18-5c106cde.pth -o $M/face-parse-bisent/resnet18-5c106cde.pth \
 && curl -sfL --retry 3 https://www.adrianbulat.com/downloads/python-fan/s3fd-619a316812.pth -o avatars/musetalk/utils/face_detection/detection/sfd/s3fd.pth \
 && rm -rf /root/.cache/huggingface && du -sh $M

# MEYA: the agent bridge, our ElevenLabs TTS plugin, the paste-back fix, the self-stop and the boot script.
COPY docker/livetalking/ /opt/meya/
RUN cp /opt/meya/elevenlabs.py tts/elevenlabs.py && cp /opt/meya/el_bridge.py el_bridge.py && python /opt/meya/patch_lt.py \
 && sed -i "s#'edgetts': 'tts.edge',#'edgetts': 'tts.edge', 'elevenlabs': 'tts.elevenlabs',#" avatars/base_avatar.py \
 && grep -q "'elevenlabs': 'tts.elevenlabs'" avatars/base_avatar.py && chmod +x /opt/meya/*.sh

EXPOSE 8010
CMD ["/opt/meya/entry.sh"]

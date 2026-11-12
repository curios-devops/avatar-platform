#!/bin/bash
# MEYA live faces (LiveTalking + MuseTalk 1.5, everything baked into the image). At boot:
#   1. the pod's own self-stop timer (MAX_SECONDS), which does not depend on anyone's laptop;
#   2. the avatars named in AVATARS, from R2 through short-lived presigned URLs (AVATAR_URL_<id>); one that is missing
#      is generated from its clip (CLIP_URL_<id>) and uploaded back (UPLOAD_URL_<id>), so the next boot downloads it;
#   3. the avatar server on :8010; then RunPod's own /start.sh (SSH), as in the base image.
# No long-lived secret reaches the pod: the agent comes in each call's signed URL.
set -u
LT=/opt/lt; K=/opt/meya; L=/workspace/logs; mkdir -p $L $LT/data/avatars
MAX_SECONDS=${MAX_SECONDS:-7200} nohup bash $K/selfstop.sh > $L/selfstop.log 2>&1 &
(
  ts(){ date +%H:%M:%S; }
  cd $LT; echo "[$(ts)] boot"
  for id in ${AVATARS:-}; do
    url=$(printenv "AVATAR_URL_$id"); clip=$(printenv "CLIP_URL_$id"); up=$(printenv "UPLOAD_URL_$id")
    if [ -n "$url" ] && curl -sfL --retry 3 "$url" | tar xzf - -C data/avatars 2>/dev/null && [ -f data/avatars/$id/latents.pt ]; then
      echo "[$(ts)] avatar $id downloaded"; continue
    fi
    rm -rf data/avatars/$id
    if [ -n "$clip" ] && curl -sfL --retry 3 "$clip" -o /tmp/$id.mp4; then
      python -m avatars.musetalk.genavatar --file /tmp/$id.mp4 --avatar_id $id --version v15 > $L/avatar_$id.log 2>&1 \
        && echo "[$(ts)] avatar $id generated" || echo "[$(ts)] avatar $id FAILED"
      if [ -n "$up" ] && [ -f data/avatars/$id/latents.pt ]; then
        tar czf /tmp/$id.tgz -C data/avatars $id && curl -sf --retry 3 -X PUT -T /tmp/$id.tgz "$up" && echo "[$(ts)] avatar $id saved to R2"
      fi
    fi
  done
  first=$(ls data/avatars | head -1)
  echo "[$(ts)] server start (default avatar ${first:-none})"
  python app.py --model musetalk --avatar_id "${first:-vale}" --tts elevenlabs --REF_FILE SDVJaMLoJa7wc3s2sn7d --transport webrtc \
    --stun stun:stun.l.google.com:19302 --batch_size "${BATCH:-4}" --listenport 8010 > $L/serve.log 2>&1
) > $L/boot.log 2>&1 &
exec /start.sh

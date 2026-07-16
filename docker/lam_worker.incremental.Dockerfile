# Incremental LAM worker build — layers the current handler + the 1-frame
# motion sequence on top of the last published image, so no HuggingFace
# downloads (403s without a token) and no dependency reinstall are needed.
#
# Source of truth for a from-scratch build stays lam_worker.Dockerfile.
#
#   docker build --platform linux/amd64 -f docker/lam_worker.incremental.Dockerfile \
#     --build-arg BASE=devopsavatar/lam-worker:v5 -t devopsavatar/lam-worker:v6 .

ARG BASE=devopsavatar/lam-worker:v5
FROM ${BASE}

WORKDIR /opt/LAM

# 1-frame motion sequence: LAM renders EVERY motion frame inside its forward
# pass (+ a PNG and a 20k-gaussian PLY each + two video encodes), so sequence
# length — not reconstruction — dominated job time. We only need the canonical
# PLY. The wav is copied under the new base name because add_audio_to_video()
# crashes on a missing file (moviepy trims audio to the 1-frame video).
RUN python - <<'PYEOF'
import json, os, shutil
src = "assets/sample_motion/export/Look_In_My_Eyes"
dst = "assets/sample_motion/export/neutral_1f"
os.makedirs(dst, exist_ok=True)
d = json.load(open(f"{src}/transforms.json"))
d["frames"] = sorted(d["frames"], key=lambda x: x["flame_param_path"])[:1]
fp = d["frames"][0]["flame_param_path"]
os.makedirs(os.path.dirname(os.path.join(dst, fp)) or dst, exist_ok=True)
shutil.copy(os.path.join(src, fp), os.path.join(dst, fp))
for aux in ("canonical_flame_param.npz", "tracked_teeth_bs.npz"):
    if os.path.exists(f"{src}/{aux}"):
        shutil.copy(f"{src}/{aux}", f"{dst}/{aux}")
json.dump(d, open(f"{dst}/transforms.json", "w"))
shutil.copy(f"{src}/Look_In_My_Eyes.wav", f"{dst}/neutral_1f.wav")
print("neutral_1f:", sorted(os.listdir(dst)))
PYEOF

COPY worker/lam_worker/handler.py /opt/LAM/rp_handler.py
CMD ["python", "-u", "/opt/LAM/rp_handler.py"]

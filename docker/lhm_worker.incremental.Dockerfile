# Incremental fixes on top of lhm-worker:v1.
#
# v2: pytorch3d was missing (LHM's install_cu121.sh compiles it from source,
#     which fails under qemu — "No CUDA runtime is found" — without aborting).
#     Install Facebook's prebuilt wheel for torch 2.3.0/cu121/py310 instead.
# v3: the LHM-500M-HF HF repo only carries the main checkpoint. Inference also
#     needs the prior-model tree (VGGHead face detector at
#     pretrained_models/gagatracker/vgghead/vgg_heads_l.trcd, SMPL-X human
#     model files, etc.) which LHM ships as a separate tarball. Bake it in.
#     (motion_video.tar is NOT needed — our export path is static, no video.)
#
# Build:  docker build --platform linux/amd64 \
#           -f docker/lhm_worker.incremental.Dockerfile \
#           -t devopsavatar/lhm-worker:v3 .
FROM devopsavatar/lhm-worker:v1

# ── v2: pytorch3d prebuilt wheel ──────────────────────────────────────────
RUN pip install --no-cache-dir fvcore iopath \
 && pip install --no-cache-dir --no-index --no-deps pytorch3d \
    -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/download.html \
 && python -c "import pytorch3d; print('pytorch3d', pytorch3d.__version__)"

# ── v3: LHM prior-model tree (face detector, SMPL-X, etc.) ────────────────
WORKDIR /opt/LHM
RUN wget -q -O /tmp/LHM_prior_model.tar \
      https://virutalbuy-public.oss-cn-hangzhou.aliyuncs.com/share/aigc3d/data/LHM/LHM_prior_model.tar \
 && tar -xf /tmp/LHM_prior_model.tar -C /opt/LHM \
 && rm /tmp/LHM_prior_model.tar \
 && test -f /opt/LHM/pretrained_models/gagatracker/vgghead/vgg_heads_l.trcd

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
# v4: B2 patch (export SMPL-X betas) — see patch_export_betas.py. SHIPPED
#     BROKEN: the v3 HF selective-include missed voxel_grid/, which
#     SMPLXVoxelMeshModel needs at model INIT (not just training) — every
#     real job failed. Found by running an actual job, not by reading code.
# v5: add voxel_grid/ to the HF include (fixes v4). ALSO SHIPPED BROKEN:
#     missed arcface_resnet18.pth (root-level file, ResNetArcFace init).
#     Two misses in a row from selective-include guessing what init touches
#     — real jobs keep finding files static analysis didn't.
# v6: add both remaining root-level model files (arcface_resnet18.pth,
#     BiRefNet-general-epoch_244.pth) so we stop guessing and playing
#     whack-a-mole with one missing asset per job. SHIPPED BROKEN TOO:
#     LHMPP-Prior (our HF substitute for the dead Aliyun tar) turned out to
#     be missing `sapiens/` entirely — config uses fine_encoder_type=sapiens
#     pointing at a 4.68GB torchscript checkpoint LHMPP-Prior never had.
# v7: fetch the Sapiens-1B checkpoint from its real source (facebook/
#     sapiens-pretrain-1b-torchscript on HF — verified exact filename match
#     against configs/inference/human-lrm-500M.yaml before building, not
#     after another failed job) + pin onnxruntime (rembg's fallback path —
#     SAM2Seg import always fails in our image since engine.SegmentAPI isn't
#     installed, and bare `pip install rembg` doesn't pull onnxruntime;
#     confirmed the exact same gap bit FaceLift's setup earlier this
#     session). sam2 itself is NOT needed — human_lrm.py wraps SAM2Seg() in
#     try/except and falls back to rembg on ImportError; verified in the
#     source, not assumed. Tags v4/v5/v6 stay on Docker Hub as known-broken
#     historical records.
#     Also bundled here: RealESRGANEasyModel needs ./pretrained_models/
#     RealESRGAN_x4plus.pth (facesr: True in the config) — confirmed missing
#     by a real job traceback (ESRGANer_utils.py FileNotFoundError). Source
#     verified against LHM's own ESRGANEasyModel.file_url: the official
#     xinntao/Real-ESRGAN v0.1.0 GitHub release, not guessed.
#     BUILD SUCCEEDED but PUSH FAILED 3/3 times, always on the single 4.68GB
#     Sapiens layer, always the exact same "broken pipe" writing to Docker
#     Desktop's internal proxy (192.168.65.1:3128) — every other layer
#     (dozens, incl. the 6.5GB LHMPP-Prior download) pushed fine. Consistent
#     failure on the same blob across 3 independent attempts (8-14 min each)
#     points at a structural size/duration limit in Docker Desktop's proxy,
#     not random network flakiness. Fix: split Sapiens into ~450MB COPY
#     layers (docker/assets/sapiens_chunks/, gitignored — regenerate via
#     `split -b 450m` from the .pt2, extracted from the local v7 image with
#     `docker cp` so it's not re-downloaded) instead of one RUN that fetches
#     the whole 4.68GB into a single layer. Reassembled once at container
#     cold-start by worker/lhm_worker/entrypoint.sh (cat the parts), not at
#     build time — reassembling in a RUN step would just recreate one big
#     layer and reintroduce the exact same push problem.
#
# v9: handler.py's "LHM produced no .ply" error path only ever included
#     stdout, never stderr — two real jobs failed with rc=0 (no exception, no
#     .ply) right after the identical "subdir_path and uid: input" log line,
#     and GFPGAN turned out to be a red herring (v8 baked those weights in,
#     failure persisted at the same spot with no GFPGAN download in the log
#     anymore). Whatever's actually going wrong is in stderr we've never
#     seen. Fix the error message only — not a guess at the real bug.
#
# v10: v9 finally showed stderr — clean tail, no traceback, a tqdm bar
#     hitting 100%, right up to the process exit. Doesn't look like a crash
#     at all. Widen the capture window and, on "no .ply", `find -newer` the
#     whole LHM_ROOT tree to see what infer_mesh() actually wrote (if
#     anything) instead of assuming the exps/**/*.ply glob is even the right
#     place to look.
#
# v11: v10's raw `find -newer` dump was mostly HF-cache/pycache noise and
#     got truncated by our own [-1500:] slice before it said anything useful
#     (never even reached whether exps/ existed). Ask targeted questions
#     instead: does exps/ exist, is there a .ply ANYWHERE under LHM_ROOT, and
#     scan the FULL stdout+stderr (not just the tail) for Error/Traceback/
#     Exception/Fail lines a tail-only slice could miss.
#
# v12: root cause finally found by reading human_lrm.py/SAM.py source, not by
#     another blind job. v11's targeted diagnostic showed exps/meshs/.../ was
#     created but empty with NO error anywhere — turned out to be a silent
#     `except: continue` on a body-ratio<0.4 assert BEFORE infer_mesh() is
#     even called, meaning our test image (a head/shoulders portrait) was
#     being silently skipped, not a code bug. Switching to a real full-body
#     test photo got past that and into a REAL traceback (rc=1, finally):
#     self.parsingnet is None because `self.parsingnet = SAM2Seg()` is
#     wrapped in a bare try/except that swallows SAM2Seg's ImportError (we
#     deliberately hadn't installed sam2, believing — correctly, but only for
#     a DIFFERENT code path — that human_lrm.py falls back to rembg; that
#     fallback isn't wired to this particular self.parsingnet used by
#     infer_mesh()'s parsing() call). Installs sam2 from the exact fork LHM's
#     own install_cu121.sh uses (not the unrelated generic PyPI "sam2"
#     package) + the sam2.1_hiera_large.pt checkpoint (898MB, single layer —
#     under the ~1GB range that pushed fine before without chunking).
#
# Build:  docker build --platform linux/amd64 \
#           -f docker/lhm_worker.incremental.Dockerfile \
#           -t devopsavatar/lhm-worker:v12 .
FROM devopsavatar/lhm-worker:v1

# ── v2: pytorch3d prebuilt wheel ──────────────────────────────────────────
RUN pip install --no-cache-dir fvcore iopath \
 && pip install --no-cache-dir --no-index --no-deps pytorch3d \
    -f https://dl.fbaipublicfiles.com/pytorch3d/packaging/wheels/py310_cu121_pyt230/download.html \
 && python -c "import pytorch3d; print('pytorch3d', pytorch3d.__version__)"

# ── v3: LHM prior-model tree (face detector, SMPL-X, etc.) ────────────────
# 2026-07-23: LHM_prior_model.tar's bucket (virutalbuy-public, Aliyun OSS) now
# 403s its ENTIRE tree with "AccessDenied ... bucket acl" — not a path bug,
# every object in the bucket is unreachable, including files our OWN v1 image
# already downloaded successfully in the past (1_20000.ply). Upstream broke,
# not us. Switched to the HuggingFace mirror of the same asset tree
# (3DAIGC/LHMPP-Prior, public, no gate) — same trusted download mechanism
# already used for the LHM-500M-HF weights above. Selective include (~6.5GB
# vs 7.67GB full repo): human_model_files/ (SMPL-X/SMPL/FLAME/MANO — LHM's
# renderer touches several of these paths, not just smplx/) + gagatracker/
# vgghead/ (face detector infer_mesh() needs) + voxel_grid/ (SMPLXVoxelMeshModel
# .register_constrain_prior() loads voxel_grid/human_prior_constrain.npz at
# MODEL INIT) + arcface_resnet18.pth (ResNetArcFace init, model_kwargs id_face_net)
# + BiRefNet-general-epoch_244.pth (matting — included defensively after TWO
# rounds of "unrelated pipeline, skip it" being wrong; a real job is the only
# reliable way to know what model init touches, and another failed cycle costs
# more than the extra ~900MB). Skips smplx_npz.zip (confirmed duplicate) and
# EMICA/mask2former (video/training-only, LHM's own README scopes these to
# the video-driven avatar path we don't use).
WORKDIR /opt/LHM
RUN huggingface-cli download 3DAIGC/LHMPP-Prior \
      --include "human_model_files/*" "gagatracker/vgghead/*" "voxel_grid/*" \
                "arcface_resnet18.pth" "BiRefNet-general-epoch_244.pth" \
      --exclude "human_model_files/smplx/smplx_npz.zip" \
      --local-dir pretrained_models \
 && test -f /opt/LHM/pretrained_models/gagatracker/vgghead/vgg_heads_l.trcd \
 && test -f /opt/LHM/pretrained_models/human_model_files/smplx/SMPL-X__FLAME_vertex_ids.npy \
 && test -f /opt/LHM/pretrained_models/voxel_grid/human_prior_constrain.npz \
 && test -f /opt/LHM/pretrained_models/arcface_resnet18.pth \
 && test -f /opt/LHM/pretrained_models/BiRefNet-general-epoch_244.pth

# ── v4: B2 patch — export SMPL-X betas that infer_mesh() discards ─────────
# (see worker/lhm_worker/patch_export_betas.py + docs/etapa-b/README.md)
COPY worker/lhm_worker/patch_export_betas.py /tmp/patch_export_betas.py
RUN python /tmp/patch_export_betas.py /opt/LHM/LHM/runners/infer/human_lrm.py

# ── v7: Sapiens-1B fine encoder checkpoint + rembg's onnxruntime backend ──
# Exact target path from configs/inference/human-lrm-500M.yaml
# (fine_encoder_model_name) — verified against the config, not guessed.
# Shipped as ~450MB chunks (see comment block above) — reassembled at
# container cold-start by entrypoint.sh, never combined into a build layer.
RUN mkdir -p pretrained_models/sapiens/pretrained/checkpoints/sapiens_1b /opt/LHM/sapiens_chunks
# One COPY per chunk on purpose — COPY'ing the whole directory in a single
# instruction would merge all 10 parts back into one ~4.68GB layer, the exact
# thing this split is meant to avoid. Each COPY below is its own pushable blob.
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_aa /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ab /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ac /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ad /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ae /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_af /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ag /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ah /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_ai /opt/LHM/sapiens_chunks/
COPY docker/assets/sapiens_chunks/sapiens_1b.pt2.part_aj /opt/LHM/sapiens_chunks/
RUN pip install --no-cache-dir onnxruntime

RUN wget -q -O pretrained_models/RealESRGAN_x4plus.pth \
      https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth && \
    test -s pretrained_models/RealESRGAN_x4plus.pth

# ── v8: GFPGAN/facexlib weights — infer_mesh() downloads these at INFERENCE
# time via torch.hub (not just facesr's RealESRGAN); a real job (rc=0, no
# .ply produced) died silently right after these "Downloading:" log lines,
# most likely the in-pod fetch stalling/failing without LHM surfacing an
# error. URLs and exact target paths read directly off that job's own log,
# not guessed.
RUN mkdir -p /opt/LHM/gfpgan/weights /opt/conda/lib/python3.10/site-packages/gfpgan/weights && \
    wget -q -O /opt/LHM/gfpgan/weights/detection_Resnet50_Final.pth \
      https://github.com/xinntao/facexlib/releases/download/v0.1.0/detection_Resnet50_Final.pth && \
    wget -q -O /opt/LHM/gfpgan/weights/parsing_parsenet.pth \
      https://github.com/xinntao/facexlib/releases/download/v0.2.2/parsing_parsenet.pth && \
    wget -q -O /opt/conda/lib/python3.10/site-packages/gfpgan/weights/GFPGANv1.3.pth \
      https://github.com/TencentARC/GFPGAN/releases/download/v1.3.0/GFPGANv1.3.pth && \
    test -s /opt/LHM/gfpgan/weights/detection_Resnet50_Final.pth && \
    test -s /opt/LHM/gfpgan/weights/parsing_parsenet.pth && \
    test -s /opt/conda/lib/python3.10/site-packages/gfpgan/weights/GFPGANv1.3.pth

# ── v12: SAM2 — infer_mesh()'s parsing() step needs self.parsingnet, which
# is SAM2Seg(); a bare try/except around its construction silently leaves it
# None if sam2 isn't installed, and there's no fallback on this path (rembg
# only covers a different code path). Exact fork LHM's own installer uses.
RUN pip install --no-cache-dir "git+https://github.com/hitsz-zuoqi/sam2/"
RUN mkdir -p pretrained_models/sam2 && \
    wget -q -O pretrained_models/sam2/sam2.1_hiera_large.pt \
      https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt && \
    test -s pretrained_models/sam2/sam2.1_hiera_large.pt

COPY worker/lhm_worker/handler.py /opt/LHM/rp_handler.py
COPY worker/lhm_worker/entrypoint.sh /opt/LHM/entrypoint.sh
RUN chmod +x /opt/LHM/entrypoint.sh
CMD ["/opt/LHM/entrypoint.sh"]

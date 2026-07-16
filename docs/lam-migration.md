# LAM migration — photo → gaussian-head avatar (POC decision 2026-07-06)

**Decision:** replace the multiview→MICA→texture-bake→FlameMeshReconstructor
core with [LAM](https://github.com/aigc3d/LAM) (SIGGRAPH 2025, Apache 2.0):
one photo → animatable gaussian head **with hair** in ~1.4 s GPU.

**Why:** MICA (2022) only yields 300 shape coefficients on a bald FLAME mesh
with a hand-made frontal texture bake — its quality ceiling is far below
2025/26 one-shot models. Anam-style realism is 2D diffusion video (different
architecture); LAM is the "vanilla" modern path for true-3D avatars.

## What changed in code
- `docker/lam_worker.Dockerfile` — CUDA 12.1 image: LAM repo + assets + LAM-20K weights + RunPod handler.
- `worker/lam_worker/handler.py` — `lam_reconstruct` job: image_b64 → 3DGS PLY (honest errors, no silent fallbacks).
- `backend/app/pipeline/runpod_lam.py` — async submit/poll client.
- `pipeline_worker.py` — when `RUNPOD_LAM_ENDPOINT_ID` is set, the LAM path
  runs INSTEAD of multiview/MICA/texture/reconstruct and publishes
  `gaussians.ply` + preview directly. Any LAM failure falls back to the
  legacy pipeline automatically.
- Frontend `splat_loader.ts` already parses standard 3DGS PLYs (property
  lookup by name) — no change needed to view a LAM avatar.

## Deploy steps (operator)
1. Start Docker, then:
   `docker build -f docker/lam_worker.Dockerfile -t <hub>/lam-worker:latest . && docker push <hub>/lam-worker:latest`
   (~40 GB disk during build; weights are baked into the image.)
2. RunPod → new Serverless endpoint with that image, GPU ≥ 24 GB (A10/L4/A100),
   **FlashBoot on / min workers 1 during dev** (cold starts killed MICA:
   observed 32 min queue vs the client's 6 min ceiling).
3. `backend/.env` → `RUNPOD_LAM_ENDPOINT_ID=<id>`, restart backend, run a job.

## Expected iteration points (first live test)
- `scripts/inference.sh` output layout: the handler globs `exps/**/*.ply`;
  adjust glob/OUTPUT_DIR once we see a real run's stdout.
- PLY size: LAM-20K ≈ 20k gaussians (~6 MB) fits RunPod's response limit;
  if a config yields bigger outputs, switch the worker to upload to R2.
- Animation (phase 2): keep neutral head first; then LAM's OpenAvatarChat
  export + `LAM_Audio2Expression` for talking, or adapt our ARKit rig to
  LAM's FLAME binding.

## Triage 2026-07-09 — "head backwards" + "black lines" root causes

First live LAM run (20 018 gaussians, 116 s inference) cross-checked against a
reference viewer (three.js + @mkkellogg/gaussian-splats-3d) and a synthetic
PLY with axis markers (blue nose +z / green +y / red +x). Verdict: **LAM output
is excellent and was never the problem** — both artifacts were ours:

1. **Orientation.** LAM heads face **+z, the canonical convention** (verified
   in the reference viewer). The `rotY = π` camera hack (added on the belief
   that "LAM avatars face -z in practice") was itself what showed the back of
   the head. Fixed: camera starts at +z again; the dead `_flip_y180_ply`
   helper was removed from `runpod_lam.py`. Rule going forward: assets are
   canonical (+z facing, Y-up); never compensate orientation in the camera.
2. **Black grid lines.** Two bugs in the WGSL EWA splatting shader
   (`webgpu_renderer.ts`), found by rendering the same PLY in both viewers:
   - the Jacobian `J` was filled column-major by WGSL while written in
     row-major reading order (the `R` matrix already had the `transpose()`
     fix; `J` was missing it) → covariance computed with Jᵀ;
   - the pixel→NDC conversion divided by `viewport` instead of
     `viewport/2` → every splat rendered at half size, leaving dark grid
     gaps between the UV-anchored gaussians of the LAM head.

Debug harness kept for future regressions: `frontend/triage.html?ply=<url>`
(mounts AvatarViewer standalone) and `.triage/ref_viewer.html` (reference
renderer, serve with any static server). Screenshots of the whole triage are
in `.triage/` (git-excluded).

## Multiview: closed decision (2026-07-09)

Multiview generation is **not** an input to LAM and must not be re-added to
the LAM path: LAM is one-shot single-image by design (its SIGGRAPH 2025
contribution). Multiview remains exactly where it is — the legacy
MICA/texture-bake fallback pipeline and the frontend orbit UI. Suggestions to
"restore multiview to fix orientation" conflate the two pipelines; the
orientation bug was the camera hack above.

Also evaluated (2026-07-09): Nanite-style meshlet renderers for three.js
(GLB→meshlet + PBR). Rendering tech for huge static triangle meshes — not
applicable to 3DGS avatars (no triangles) nor to the 10k-triangle FLAME mesh.
For full/half-body avatars later, the natural path is **LHM** (aigc3d, same
team as LAM): single image → animatable full-body gaussian human.

## Legacy path status
Multiview (Nano Banana via Vertex express), MICA client hardening, texture
bake and camera/shader fixes all remain functional as the fallback pipeline.
Nano Banana stays for the "Imagine" tab. The MICA worker image on RunPod is
still broken (returns neutral shapes) — not worth fixing if LAM lands.

## Inference optimization + CUDA-host incident (2026-07-14)

**Result: warm reconstruct 116 s → 28.4 s** (worker `mode=resident`), warmup
no-op 147 ms, one-time resident model load 20.2 s per container. PLY output
byte-class identical (1329 KB, 20k gaussians) and visually verified against
the reference viewer.

What changed (image `devopsavatar/lam-worker:v7`, built incrementally on v5
via `docker/lam_worker.incremental.Dockerfile` — no HF re-download, weights
copied from the known-good layers):
- **Resident model, lazy-loaded**: `LAMInferrer` is built once per container
  on the FIRST job (never at import — loading before
  `runpod.serverless.start()` keeps the worker stuck in "initializing"
  forever; observed live). Warmup jobs trigger/absorb the load.
- **1-frame motion sequence** (`assets/sample_motion/export/neutral_1f`):
  LAM renders every motion frame inside its forward pass; the sequence
  length, not reconstruction, dominated job time. We only need the canonical
  PLY.
- Subprocess mode kept as automatic fallback (`mode` field in the response
  tells which path ran).

**Incident (full evening lost to it): jobs stuck IN_QUEUE with "ready" workers.**
Root cause: RunPod hosts running **CUDA 13.x drivers** cannot run our
CUDA 12.1 image — container boots, torch CUDA init fails
(`Fitness check failed: _cuda_init_check … no kernel image is available`),
worker shows "ready" but never polls the queue. With every 24 GB pool at
stock "Low" the scheduler kept assigning exactly those hosts (FlashBoot makes
it sticky: it prefers hosts that already cached the image — including broken
ones). Discriminators that cracked it: fresh endpoint + public hello-world
image (no CUDA) → jobs flow; same endpoint + any of our images → silent.

**Fix: `allowedCudaVersions: ["12.1"…"12.6"]` on the endpoint** — first
warmup completed 3 minutes later.

Ops learnings (all bitten live):
- Changing a template's image does NOT recycle existing workers — bounce
  `workersMax` 0→N afterwards, with a verification read (the two PATCHes can
  race and leave the endpoint paused at max=0).
- Endpoint config drift: the backend now syncs `LAM_IDLE_TIMEOUT_S` from
  `.env` at startup (source of truth in repo, not the console).
- Worker quota is account-wide (10); creating endpoints fails with 500 until
  freed.
- Current endpoint: `avatar-lam-v4` (`x1hmke8mv6xouc`), template
  `9usabmb0fq` → `lam-worker:v7`, idleTimeout 300 s, FlashBoot on,
  min 0 / max 2, dataCenterIds global, CUDA 12.1–12.6.
- Region note (2026-07-14): users will be in the US, but with global stock
  "Low" restricting `dataCenterIds` would only shrink the pool; latency is
  irrelevant vs queue time for 30 s jobs. Revisit US pinning when stock
  normalizes.

Next optimization candidates: the remaining ~28 s is dominated by LAM's
per-image flame tracking/preprocessing, not the forward pass (~1.4 s per the
paper); and `docker login` is needed before the next image push (auth
expired — v8 with a newer runpod SDK was built locally but never needed).

## 2026-07-17 — cu126 rebuild deferred; LHM worker POC (avatar tiers 2-3)

**cu126 rebuild deferred, with reasoning:** cu121 images are the most widely
deployed on RunPod — if CUDA-13-driver hosts broke them all, the platform
would be on fire. Those hosts are simply misconfigured, and a cu126 image
doesn't make broken hosts work. `allowedCudaVersions 12.1-12.6` is therefore
the *correct standing defense*, not a workaround. Revisit only if the
12.x host pool visibly shrinks (symptom: rising queue delays).

**Avatar tiers decision:** three visualization levels —
1. talking head (LAM, in prod), 2. half body with hands, 3. full body.
**LHM (aigc3d, ICCV 2025, Apache 2.0) covers tiers 2 AND 3 with one worker:**
the `-HF` checkpoints (LHM-500M-HF / LHM-1B-HF) accept half-body or
full-body photos with no framing flag. ~2 s (500M) / ~6.6 s (1B) forward
pass, 24 GB VRAM, SMPL-X-anchored gaussians (body animation via skeleton;
Spark 2.0's experimental splat LBS is the natural web renderer for this).

POC scaffolding (mirrors the LAM worker pattern):
- `docker/lhm_worker.Dockerfile` — same cu121 base/stack; LHM-500M-HF weights
  baked; optional `HF_TOKEN` build-arg (HF 403s anonymous pulls some days).
- `worker/lhm_worker/handler.py` — `lhm_reconstruct` job runs LHM's
  export_mesh path (`infer_mesh`: canonical gaussians, **no motion pass**,
  save_ply is already standard 3DGS — no LAM-style patch needed). Output is
  gzipped (full-body PLYs outgrow LAM's ~6 MB). Subprocess mode for the POC;
  resident-lazy mode is the known follow-up.
- `backend/app/pipeline/runpod_lhm.py` + `RUNPOD_LHM_ENDPOINT_ID` in config.

Deploy: build+push `devopsavatar/lhm-worker:v1`, create endpoint (24 GB pool,
FlashBoot, idleTimeout 300, **allowedCudaVersions 12.1-12.6**), set
`RUNPOD_LHM_ENDPOINT_ID`, test with a half-body and a full-body photo, view
PLYs in the triage viewer (`frontend/triage.html?ply=...`).

**Deployed 2026-07-17:** `devopsavatar/lhm-worker:v1` pushed (first push died
mid-blob on a broken pipe — plain `docker push` retry resumed the mounted
layers). Endpoint `avatar-lhm-v1` = `vd52f2vtq86buv` (template `w10p5l00xu`,
4090/A5000/3090/L4 pool, CUDA 12.1-12.6, 0-2 workers, FlashBoot, idle 300 s).
Worker quota was 10/10 — freed it by `workersMax 2→0` on the dead legacy
`avatar-mica` endpoint (`nwzu1fx25zkin9`); restore with the same PATCH if MICA
is ever revived.

## Viewer animation (2026-07-17)

Static-PLY procedural animation shipped in the WebGPU viewer (commits
9b98936 / da6ce7f / 93ac5de):
- **Idle**: rigid model matrix (incommensurate-sine yaw/pitch/roll about a
  neck pivot + breathing bob), folded into the view matrix on the CPU —
  covariance math untouched, depth sort keeps the camera-only view.
- **Mouth**: soft radial mask at (0, -0.06, 0.045) canonical, chin-weighted;
  FFT amplitude ×2.4 gain, fast-attack/0.25-release smoothing.
- **Blink**: one tight mask PER eye (1.0-2.6 cm falloff, lid line y=0.032).
  Lesson: masks wider than half the eye separation (6.6 cm) merge across the
  nose bridge and read as a stretched band — same failure mode as the
  original "everything below y=0" jaw placeholder.
- Debug hooks: `?amp=`, `?blink=`, `?noidle=1`, live `amp N.NN` in the fps
  badge. Verification method: pixel-diff of forced-state screenshots
  (`.triage/ab_*.png`) — bbox of changed pixels must stay inside the
  intended feature.

True lipsync (tier B) still requires LAM's rigged export +
LAM_Audio2Expression + splat LBS (Spark 2.0 spike).

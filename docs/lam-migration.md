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

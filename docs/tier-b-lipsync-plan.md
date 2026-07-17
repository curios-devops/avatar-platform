# Tier B — Real phonetic lipsync (LAM rig + Audio2Expression + WebGL LBS)

Status: **planning** (approved 2026-07-17). Supersedes the procedural mouth
animation (idle/blink/amplitude-jaw) as the talking-head animation path.
The procedural work stays as the fallback for the static (unrigged) viewer.

## Why the procedural mouth can't get to "real"
The shipped PLY is a static gaussian snapshot: no rig, no skinning weights, no
mouth interior. Amplitude→jaw-drop is a volume proxy — it opens on loud
sibilants, never closes cleanly between words, and an open mouth stretches
skin instead of revealing a cavity. Phoneme-accurate lipsync needs an
articulated model. LAM already provides exactly that; we just haven't been
exporting or driving it.

## The three real pieces LAM ships (verified 2026-07-17)
1. **Rigged asset** — LAM's canonical gaussians are FLAME-anchored and animate
   with standard **linear blend skinning + corrective blendshapes** (as FLAME
   does). LAM exports this as a **ZIP** (cf. `asset/arkit/p2-1.zip`) via
   `python app_lam.py --blender_path <blender>` (see LAM `tools/AVATAR_EXPORT_GUIDE.md`).
   ⚠️ Export needs **Blender** — a new dependency in the worker image.
2. **Audio → expression** — `LAM_Audio2Expression`: Wav2Vec-based, audio →
   **ARKit blendshape coefficients** (FLAME-topology adapted), with a
   **streaming/real-time** mode (`inference_streaming_audio.py`) and a batch
   mode (`inference.py`). PyTorch, CUDA 12.1/11.8. No ONNX export advertised →
   run it **server-side / on GPU**, not in the browser.
3. **WebGL renderer** — `LAM_WebRender`, published on npm as
   **`gaussian-splat-renderer-for-lam`** (TypeScript/Vite, WebGL). Loads the
   ZIP asset and plays a per-frame ARKit coefficient stream. Minimal API:
   ```js
   import * as G from 'gaussian-splat-renderer-for-lam';
   const r = await G.GaussianSplatRenderer.getInstance(div, assetZipUrl);
   ```
   It already implements LBS + correctives internally. This **replaces our
   hand-written WebGPU renderer for the talking-head tier** (the WebGPU one
   stays for the static/LHM-body path until Spark 2.0).

## Open technical risks (confirm during Milestone 0)
- **Per-frame drive API**: docs show loading a static `expression_1s.json`.
  Must confirm `gaussian-splat-renderer-for-lam` exposes a *live* per-frame
  setter (feed ARKit coeffs synced to `<audio>.currentTime`) and not only a
  pre-baked clip. If clip-only: pre-bake the coeff JSON per utterance from the
  TTS wav and hand renderer+audio together (still fine, just not open-mic).
- **ARKit set**: expected 52 standard names; confirm exact list/order the
  renderer wants and that Audio2Expression emits the same order.
- **Blender in the worker**: image size + headless Blender export time per
  reconstruction. Measure; may push export to a separate job so the fast
  reconstruct path isn't blocked.
- **Coordinate/scale parity**: the ZIP asset viewer vs our current camera
  framing (portrait lens, +z). LAM_WebRender brings its own camera — re-tune.

## Milestones

### M0 — Spike (de-risk, ~0.5 day)
- Clone `LAM_WebRender`; run its demo with the bundled `arkit/p2-1.zip` +
  `test_expression_1s.json` locally. Confirm it renders + animates.
- Inspect the npm package API for a **per-frame** coefficient setter.
- Unzip a sample asset; document the real ZIP contents (gaussians, LBS
  weights, correctives, arkit mapping).
- **Exit criterion**: a LAM sample avatar lip-syncs a sample clip in our dev
  page, and we know whether live per-frame drive is possible.

### M1 — Asset export in the worker (~1 day)
- Add Blender (headless) to `lam_worker` image; wire `app_lam.py` export path.
- New handler output: alongside `gaussians.ply`, produce `avatar_arkit.zip`;
  upload to R2; return `asset_zip_url` in the bundle.
- Keep the current PLY output for backward compat / static fallback.

### M2 — Audio2Expression service (~1 day)
- Stand up `LAM_Audio2Expression` on GPU. Options (pick in M2):
  (a) extend the LAM worker with an `audio2expr` job_type (reuses torch/GPU),
  (b) a small dedicated RunPod endpoint.
- Backend `speak` flow: TTS wav → Audio2Expression → ARKit coeff sequence
  (JSON, ~30/60 fps). Return `{audio_url, expression_url}` from `/speak`.

### M3 — Frontend swap (~1 day)
- Add a rigged-avatar viewer using `gaussian-splat-renderer-for-lam`, loading
  `asset_zip_url`. Feed the coeff stream synced to audio playback
  (per-frame if M0 allows; else pre-baked clip + play together).
- Re-tune camera/framing. Keep procedural WebGPU viewer behind a flag as
  fallback and for the LHM body tier.

### M4 — Integrate + verify
- End-to-end: photo → LAM reconstruct (+ZIP) → Speak → phoneme lipsync in the
  rigged viewer. Verify closure between words, no sibilant false-opens, mouth
  interior reads as a cavity. Screenshot/again pixel-diff key phonemes.

## Sequencing note
M0 is pure de-risk and blocks nothing else — do it first. M1 (worker/Blender)
and M2 (Audio2Expression) are independent and can build in parallel (both are
long GPU image builds, run unattended). M3 depends on M0's API finding and a
sample asset from M1. Total ~3-4 focused days, dominated by image builds.

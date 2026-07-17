# Renderer / architecture comparison for a realistic talking avatar (2026-07-17)

Question: would Spark 2.0 (or another modern architecture) give a *more
realistic* avatar than the current plan (LAM + LAM_WebRender + Audio2Expression)?

## What actually sets the realism ceiling
Realism is decided by three things, in this order — and the renderer is last:
1. **Reconstruction** (how good the 3D head is): LAM's job.
2. **Animation model** (how the face articulates): the FLAME rig — LBS +
   corrective blendshapes — driven by Audio2Expression.
3. **Rendering** (AA, sorting, shadows, LoD): the renderer's job.

A renderer swap changes (3), not (1) or (2). So Spark can't make the
reconstruction or the lipsync more *accurate*; it can make the picture nicer
(shadows/LoD/scale) and unify head+body.

## The decisive finding: Spark 2.0 has NO blendshapes
LAM's animation = **LBS (4 FLAME joints: jaw/neck/eyes) + 51 corrective ARKit
blendshapes** (the fine mouth/eye/brow shapes that make lipsync read as real).

- **Spark 2.0** supports *experimental* **LBS only** (per-splat bone
  indices/weights). Its docs describe **no morph-target / blendshape** support.
  FLAME expressions are corrective *blendshapes*, not bones — so Spark cannot
  drive the ARKit lipsync natively. You'd have to hand-build a 51-target
  blendshape blender in its (programmable) shader graph. Real work, zero
  realism gain over a renderer that already does it.
- **LAM_WebRender** (`gaussian-splat-renderer-for-lam`) does **both** LBS and
  the 51 blendshapes out of the box — it is purpose-built for exactly this
  asset. Downsides: head-only (no SMPL-X body), alpha (0.0.9), WebGL.

## The 2025-26 research landscape (not turnkey)
HeadGaS, RGBAvatar, 3D Gaussian Blendshapes (Ma 2024), Splatshot, etc. are all
**reconstruction** techniques, not deployable web renderers. Notably, "3D
Gaussian Blendshapes" (neutral gaussians + per-expression offsets blended with
FACS/ARKit coefficients) **is exactly the representation LAM already uses** —
i.e. LAM is on the SOTA representation. There is no turnkey web renderer that
beats LAM_WebRender for our case; alternatives are either research code or
general renderers (Spark) that lack blendshapes.

## A realism win that comes from the rig, not the renderer
The procedural jaw on the static PLY stretched skin (no mouth interior). The
LAM **rigged** asset's `jawOpen` blendshape opens a real FLAME mouth with
interior geometry — so tier B lipsync looks materially more real, and that gain
comes from the rig + Audio2Expression, available in LAM_WebRender today.

## Recommendation
| Need | Best choice now |
|---|---|
| Talking-head lipsync (tier B) | **LAM_WebRender** — only web renderer that drives LBS + 51 ARKit blendshapes |
| Reconstruction realism | Keep **LAM** (already SOTA gaussian-blendshape); improve *input* (reframe/enhance), not the model |
| Body tier | Keep our WebGPU / LHM path |
| Head+body in one scene, LoD, VR/mobile, shadows/scale | **Spark 2.0 later** — port the blendshape driver into its shader graph then |

**Bottom line:** Spark 2.0 is a *scale/unification* play, not a *realism*
upgrade for the head — and adopting it now would mean re-building the
blendshape lipsync Spark lacks. Ship tier B on LAM_WebRender; hold Spark 2.0
for the future head+body unification milestone (where its LoD/scene strengths
actually pay off), accepting we'd port the ARKit blendshape blend into its
programmable pipeline at that point.

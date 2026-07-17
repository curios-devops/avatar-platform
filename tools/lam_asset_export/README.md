# LAM ARKit asset export — Blender-free (tier B, M1)

Produces the `{name}.zip` asset that `LAM_WebRender`
(`gaussian-splat-renderer-for-lam`) loads to render + ARKit-animate a LAM head,
**without Blender**.

## ZIP layout (verified against the official `p2-1.zip`)
```
{name}/
  skin.glb          # FLAME mesh: POSITION(20018 verts) + JOINTS_0/WEIGHTS_0
                    # skin + 51 ARKit morph targets (targetNames in extras)
  offset.ply        # neural gaussian splats (per-avatar, from LAM)
  animation.glb     # idle/animation rig channels  — TEMPLATE, constant
  vertex_order.json # ply↔mesh vertex mapping       — TEMPLATE, constant
```

## What is per-avatar vs constant
- `offset.ply` — LAM neural output (per-avatar).
- `skin.glb` — **only its POSITION block is per-avatar** (the FLAME shaped
  vertices). Skeleton, skin weights and all 51 ARKit morph-target deltas are
  the fixed FLAME template, identical for every avatar.
- `animation.glb`, `vertex_order.json` — fixed templates, ship once.

## Why no Blender
LAM's official export (`tools/generateARKITGLBWithBlender.py`) only uses
Blender to (a) convert a template FBX→GLB and (b) emit `vertex_order.json` —
both one-time, format-only steps. The rig/weights/blendshapes come from a fixed
template; the gaussians are neural. So the per-avatar step is just swapping the
POSITION block of a template `skin.glb`, which `inject_flame_vertices.py` does
in pure Python. **Realism is unaffected** — Blender contributed no shape data.

## Validation (2026-07-17)
- `inject_flame_vertices.py` round-trips the official `skin.glb` losslessly
  (max abs vertex diff 0.0; 51 morph targets, skin, 264 nodes preserved).
- Repackaged that regenerated `skin.glb` into a ZIP and loaded it in
  `LAM_WebRender` → renders + animates identically to the original. The
  Blender-free path is proven end-to-end.

## Remaining M1 work
- Extract the avatar's FLAME shaped vertices from the LAM worker
  (`flame_model.save_shaped_mesh()` / the inferrer's FLAME output), in the
  template's 20018-vertex order.
- Confirm our LAM `offset.ply` matches the expected gaussian format/scale
  (note: template `skin.glb` is in a standing-figure frame, head y≈1.5–1.8 m —
  check offset.ply shares it).
- Bake the template `skin.glb`/`animation.glb`/`vertex_order.json` into the
  worker image; wire the injector; upload the ZIP to R2; return `asset_zip_url`.

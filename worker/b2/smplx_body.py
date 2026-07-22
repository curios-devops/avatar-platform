"""B2 helper — SMPL-X canonical body mesh + head/neck segmentation +
FLAME<->SMPL-X vertex correspondence.

Deliberately does NOT reimplement SMPL-X forward kinematics (300-dim shape
blendshapes + corrective pose blendshapes + LBS) — that math is exactly what
the `smplx` pip package already does, and it's already a dependency inside
the LHM worker environment (LHM imports it directly:
`LHM.models.rendering.smplx.smplx`). Re-deriving it here would risk a subtly
wrong body mesh. This module is a thin, auditable wrapper around it.

Two assets this module needs, both of which LHM's own inference already
requires at `human_model_path/smplx/` (see LHM/models/rendering/
smpl_x_voxel_dense_sampling.py) — no separate license fetch beyond what
already made the LHM worker run:
  - the SMPL-X model files themselves (for `smplx.create(...)`)
  - `SMPL-X__FLAME_vertex_ids.npy` — official per-FLAME-vertex correspondence
    into the SMPL-X mesh (5023,) int array. If it's missing for some reason,
    falls back to a self-contained nearest-vertex KDTree match against
    `smplx_vert_segmentation.json`'s head region (worker/b2/assets/) — less
    precise, but license-free and inspectable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).parent / "assets"


@dataclass
class SmplxBody:
    vertices: np.ndarray      # (10475, 3) canonical (neutral pose) mesh, meters
    faces: np.ndarray         # (F, 3) int
    head_mask: np.ndarray     # (10475,) bool — SMPL-X 'head' segment
    neck_mask: np.ndarray     # (10475,) bool — SMPL-X 'neck' segment
    flame_correspondence: np.ndarray  # (5023,) int — SMPL-X vertex idx per FLAME vertex


def _load_segmentation() -> dict:
    return json.loads((ASSETS / "smplx_vert_segmentation.json").read_text())


def _flame_correspondence(human_model_path: Path, smplx_verts: np.ndarray,
                          flame_v_template: np.ndarray) -> np.ndarray:
    official = human_model_path / "smplx" / "SMPL-X__FLAME_vertex_ids.npy"
    if official.exists():
        print(f"[smplx_body] usando correspondencia oficial: {official}")
        return np.load(official).astype(np.int64)

    print("[smplx_body] ⚠️ SMPL-X__FLAME_vertex_ids.npy no encontrado — "
         "fallback: nearest-vertex KDTree (menos preciso, sin dependencia de licencia)")
    from scipy.spatial import cKDTree
    seg = _load_segmentation()
    head_idx = np.array(seg["head"] + seg["neck"])
    tree = cKDTree(smplx_verts[head_idx])
    # FLAME neutral mesh is roughly centered on the head; nearest SMPL-X head
    # vertex to each FLAME vertex, in the SAME neutral/canonical frame.
    _, nn = tree.query(flame_v_template)
    return head_idx[nn]


def build(betas: list[float] | np.ndarray, human_model_path: str | Path,
         flame_v_template: np.ndarray) -> SmplxBody:
    """betas: SMPL-X shape params from LHM (worker/lhm_worker patch_export_betas).
    human_model_path: dir containing `smplx/` model files (same LHM uses)."""
    import torch
    import smplx

    human_model_path = Path(human_model_path)
    betas_t = torch.as_tensor(np.asarray(betas, dtype=np.float32)).unsqueeze(0)
    model = smplx.create(str(human_model_path), "smplx", gender="neutral",
                         num_betas=betas_t.shape[-1], use_pca=False)
    out = model(betas=betas_t, return_verts=True)
    verts = out.vertices[0].detach().cpu().numpy().astype(np.float32)
    faces = model.faces.astype(np.int64)

    seg = _load_segmentation()
    n = verts.shape[0]
    head_mask = np.zeros(n, dtype=bool); head_mask[seg["head"]] = True
    neck_mask = np.zeros(n, dtype=bool); neck_mask[seg["neck"]] = True

    corr = _flame_correspondence(human_model_path, verts, flame_v_template)
    return SmplxBody(vertices=verts, faces=faces, head_mask=head_mask,
                     neck_mask=neck_mask, flame_correspondence=corr)

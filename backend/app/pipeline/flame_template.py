"""
FLAME 2023 mesh template loader.

Loads the pre-extracted NPZ file (backend/data/flame2023_template.npz) and
exposes the canonical mesh geometry used throughout the pipeline:

    v_template  (5023, 3)       canonical neutral-pose vertex positions  (m)
    f           (9976, 3)       triangles (uint32)
    shapedirs   (5023, 3, 400)  shape + expression blendshape directions
                                first 300 cols = identity, last 100 = expression
    posedirs    (5023, 3, 36)   pose-corrective blendshapes
    J_regressor (5, 5023)       joint positions from vertex weights
    weights     (5023, 5)       LBS skinning weights
    kintree     (2, 5)          kinematic tree (parent table)

All arrays are float32 (cast on load) to keep them GPU-friendly.
UV coords are not stored in the FLAME pkl; the build_uv_map() function
generates a simple cylindrical UV unwrap as a placeholder until a proper
UV atlas is available.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import numpy as np

_NPZ = Path(__file__).parent.parent.parent / "data" / "flame2023_template.npz"

N_VERTS      = 5_023
N_FACES      = 9_976
N_SHAPE_DIMS = 300   # identity blendshapes in shapedirs[:, :, :300]
N_EXPR_DIMS  = 100   # expression blendshapes in shapedirs[:, :, 300:]


class FlameTemplate(NamedTuple):
    v_template:  np.ndarray   # (5023, 3)  float32
    faces:       np.ndarray   # (9976, 3)  int32
    shapedirs:   np.ndarray   # (5023, 3, 400)  float32
    posedirs:    np.ndarray   # (5023, 3, 36)   float32
    J_regressor: np.ndarray   # (5, 5023)  float32
    weights:     np.ndarray   # (5023, 5)  float32
    kintree:     np.ndarray   # (2, 5)     int32
    uv_coords:   np.ndarray   # (5023, 2)  float32  (cylindrical placeholder)
    uv_faces:    np.ndarray   # (9976, 3)  int32  (same as faces)


@lru_cache(maxsize=1)
def load() -> FlameTemplate:
    """Load and cache the FLAME 2023 template arrays."""
    if not _NPZ.exists():
        raise FileNotFoundError(
            f"FLAME 2023 template not found at {_NPZ}.\n"
            "Run:  python backend/scripts/extract_flame.py"
        )

    d = np.load(str(_NPZ))
    v   = d["v_template"].astype(np.float32)
    f   = d["f"].astype(np.int32)
    sd  = d["shapedirs"].astype(np.float32)
    pd  = d["posedirs"].astype(np.float32)
    jr  = d["J_regressor"].astype(np.float32)
    w   = d["weights"].astype(np.float32)
    kt  = d["kintree_table"].astype(np.int32)

    uv, uvf = _build_cylindrical_uv(v, f)
    return FlameTemplate(v, f, sd, pd, jr, w, kt, uv, uvf)


def apply_shape(template: FlameTemplate, shape_params: np.ndarray) -> np.ndarray:
    """
    Return vertex positions with identity shape applied.

    shape_params : (N_SHAPE_DIMS,)  up to 300 coefficients.
    Returns      : (5023, 3)  float32 vertex positions in metres.
    """
    n = len(shape_params)
    if n > N_SHAPE_DIMS:
        shape_params = shape_params[:N_SHAPE_DIMS]
    elif n < N_SHAPE_DIMS:
        shape_params = np.pad(shape_params, (0, N_SHAPE_DIMS - n))

    sd = template.shapedirs[:, :, :N_SHAPE_DIMS]   # (5023, 3, 300)
    # einsum "vci,i->vc" = sum over shape dims
    delta = np.einsum("vci,i->vc", sd, shape_params.astype(np.float32))
    return template.v_template + delta


def apply_expression(template: FlameTemplate,
                     verts: np.ndarray,
                     expr_params: np.ndarray) -> np.ndarray:
    """
    Apply expression blendshapes on top of already-shaped vertices.

    expr_params : (N_EXPR_DIMS,)  up to 100 expression coefficients.
    Returns     : (5023, 3)  float32.
    """
    n = len(expr_params)
    if n > N_EXPR_DIMS:
        expr_params = expr_params[:N_EXPR_DIMS]
    elif n < N_EXPR_DIMS:
        expr_params = np.pad(expr_params, (0, N_EXPR_DIMS - n))

    sd = template.shapedirs[:, :, N_SHAPE_DIMS:N_SHAPE_DIMS + N_EXPR_DIMS]
    delta = np.einsum("vci,i->vc", sd, expr_params.astype(np.float32))
    return verts + delta


# ── UV helpers ───────────────────────────────────────────────────────────────

def _build_cylindrical_uv(v: np.ndarray, f: np.ndarray):
    """
    Simple cylindrical UV unwrap around the Y-axis.
    Good enough for texture sampling; replace with a proper atlas later.
    """
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    theta = np.arctan2(x, z) / (2 * np.pi) + 0.5   # [0, 1]
    y_min, y_max = y.min(), y.max()
    v_coord = (y - y_min) / (y_max - y_min + 1e-8)  # [0, 1]
    uv = np.stack([theta, v_coord], axis=1).astype(np.float32)
    return uv, f.copy()

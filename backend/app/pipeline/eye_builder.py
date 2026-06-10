"""
Eyeball geometry builder — Phase 3 CPU avatar completion.

Produces a GLB containing two eyeball meshes (left + right):
  - Sclera: white sphere, radius 12 mm
  - Iris:   coloured disc overlaid on the front hemisphere
  - Pupil:  dark disc at iris centre

Eye centres are derived from the FLAME 2023 neutral template, then adjusted
by the identity shape parameters so they track the actual face geometry.

Coordinate system: Y-up, Z-forward (same as FLAME).
"""

from __future__ import annotations

import numpy as np

from .glb_utils import GLBBuilder, PBRMaterial, compute_normals
from .flame_template import load as load_flame, apply_shape
from .schemas import FlameParams

# ── anatomical constants (from FLAME neutral template analysis) ───────────────
# Left eye centre in neutral template (x>0 = avatar's left = viewer's right)
_EYE_L_NEUTRAL = np.array([ 0.0304,  0.0377,  0.041], dtype=np.float32)
_EYE_R_NEUTRAL = np.array([-0.0286,  0.0437,  0.0418], dtype=np.float32)

EYE_RADIUS   = 0.012   # metres  (12 mm — typical human eyeball)
IRIS_RADIUS  = 0.006   # metres  (6 mm radius → 12 mm diameter iris)
PUPIL_RADIUS = 0.0025  # metres  (2.5 mm)
IRIS_Z_OFFSET = EYE_RADIUS * 0.82   # how far forward from centre the iris sits

# Default iris colour (hazel-brown); tinted from albedo when available
_IRIS_COLOR  = (0.30, 0.18, 0.08, 1.0)
_PUPIL_COLOR = (0.04, 0.04, 0.04, 1.0)
_SCLERA_COLOR = (0.95, 0.935, 0.91, 1.0)


# ── mesh generators ──────────────────────────────────────────────────────────

def _uv_sphere(
    center: np.ndarray,
    radius: float,
    lat: int = 20,
    lon: int = 24,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (positions, indices) for a UV sphere."""
    verts = []
    for i in range(lat + 1):
        phi = np.pi * i / lat          # 0 → π  (top → bottom)
        for j in range(lon + 1):
            theta = 2 * np.pi * j / lon
            x = radius * np.sin(phi) * np.cos(theta)
            y = radius * np.cos(phi)
            z = radius * np.sin(phi) * np.sin(theta)
            verts.append(center + [x, y, z])

    idx = []
    for i in range(lat):
        for j in range(lon):
            a = i * (lon + 1) + j
            b = a + lon + 1
            idx += [a, b, a + 1,
                    b, b + 1, a + 1]

    return (np.array(verts, dtype=np.float32),
            np.array(idx,   dtype=np.uint32))


def _disc(
    center: np.ndarray,
    radius: float,
    normal_dir: np.ndarray,
    segments: int = 24,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (positions, indices) for a flat disc perpendicular to normal_dir.
    Uses fan triangulation: centre vertex + ring of edge vertices.
    """
    # Build a local frame perpendicular to normal_dir
    ndir = normal_dir / (np.linalg.norm(normal_dir) + 1e-8)
    up   = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    if abs(np.dot(ndir, up)) > 0.99:
        up = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    right = np.cross(ndir, up).astype(np.float32)
    right /= np.linalg.norm(right)
    up    = np.cross(right, ndir).astype(np.float32)

    verts = [center.copy()]                                    # index 0 = centre
    for k in range(segments):
        angle = 2 * np.pi * k / segments
        v = center + radius * (np.cos(angle) * right + np.sin(angle) * up)
        verts.append(v)

    idx = []
    for k in range(segments):
        nxt = (k + 1) % segments
        idx += [0, k + 1, nxt + 1]

    return (np.array(verts, dtype=np.float32),
            np.array(idx,   dtype=np.uint32))


# ── eye centre derivation ─────────────────────────────────────────────────────

def _eye_centers(flame_params: FlameParams) -> tuple[np.ndarray, np.ndarray]:
    """
    Derive actual eye centre positions by applying identity shape params to
    the FLAME template and finding the offset from neutral template centres.

    We compute the mean displacement of the forehead region under shape params
    and apply it as a rigid offset to the hardcoded neutral centres.
    This avoids needing per-vertex FLAME landmark indices while still tracking
    face-specific geometry.
    """
    template = load_flame()
    shaped   = apply_shape(template, np.array(flame_params.shape, dtype=np.float32))

    # Compute mean displacement in the upper-front face region
    v0 = template.v_template
    dv = shaped - v0

    # Mask: front (z > 0), upper (y > 0), centre (|x| < 0.06)
    mask = (v0[:, 2] > 0) & (v0[:, 1] > 0) & (np.abs(v0[:, 0]) < 0.06)
    mean_disp = dv[mask].mean(axis=0) if mask.sum() > 0 else np.zeros(3, np.float32)

    left_center  = (_EYE_L_NEUTRAL + mean_disp).astype(np.float32)
    right_center = (_EYE_R_NEUTRAL + mean_disp).astype(np.float32)
    return left_center, right_center


# ── public API ────────────────────────────────────────────────────────────────

def build_eyes(
    flame_params: FlameParams,
    iris_color: tuple[float, float, float, float] | None = None,
) -> bytes:
    """
    Build a GLB containing left + right eyeballs.

    Returns GLB bytes ready to embed in the avatar bundle.
    Meshes included: sclera_L, iris_L, pupil_L, sclera_R, iris_R, pupil_R.
    """
    ic = iris_color or _IRIS_COLOR
    left_c, right_c = _eye_centers(flame_params)

    b = GLBBuilder()

    mat_sclera = b.add_material(PBRMaterial(
        name="sclera", base_color=_SCLERA_COLOR,
        roughness=0.3, metallic=0.0,
    ))
    mat_iris = b.add_material(PBRMaterial(
        name="iris", base_color=ic,
        roughness=0.5, metallic=0.0,
    ))
    mat_pupil = b.add_material(PBRMaterial(
        name="pupil", base_color=_PUPIL_COLOR,
        roughness=0.1, metallic=0.0,
    ))

    for side, center in (("L", left_c), ("R", right_c)):
        # Sclera sphere
        pos, idx = _uv_sphere(center, EYE_RADIUS)
        b.add_mesh(f"sclera_{side}", pos, idx, mat_sclera)

        # Iris disc — at front hemisphere of sphere, facing +Z
        iris_center = center + np.array([0.0, 0.0, IRIS_Z_OFFSET], dtype=np.float32)
        pos, idx = _disc(iris_center, IRIS_RADIUS, np.array([0, 0, 1]))
        nrm = np.tile([0.0, 0.0, 1.0], (len(pos), 1)).astype(np.float32)
        b.add_mesh(f"iris_{side}", pos, idx, mat_iris, normals=nrm)

        # Pupil disc — slightly in front of iris
        pupil_center = iris_center + np.array([0.0, 0.0, 0.0002], dtype=np.float32)
        pos, idx = _disc(pupil_center, PUPIL_RADIUS, np.array([0, 0, 1]))
        nrm = np.tile([0.0, 0.0, 1.0], (len(pos), 1)).astype(np.float32)
        b.add_mesh(f"pupil_{side}", pos, idx, mat_pupil, normals=nrm)

    return b.build()

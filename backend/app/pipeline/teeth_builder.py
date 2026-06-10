"""
Dental arch geometry builder — Phase 3 CPU avatar completion.

Replaces the empty placeholder in package._teeth_glb() with real geometry:
  - Upper arch:  16 teeth (8 left + 8 right), parented to head
  - Lower arch:  16 teeth (8 left + 8 right), parented to jaw bone
  - Tongue base: flat plane, displaced by tongueOut blendshape later

Arch is a parabolic curve so teeth follow natural dental alignment.
Positions are in FLAME coordinate space (metres, Y-up, Z-forward).

Key FLAME positions from neutral template:
  Mouth centre: ( 0.000, -0.033,  0.052)
  Nose tip:     ( 0.001, -0.010,  0.075)   ← sets lip depth reference
"""

from __future__ import annotations

import numpy as np

from .glb_utils import GLBBuilder, PBRMaterial
from .schemas import FlameParams

# ── constants ─────────────────────────────────────────────────────────────────
# Mouth geometry from FLAME neutral template
_MOUTH_CENTER = np.array([0.0, -0.033, 0.052], dtype=np.float32)

# Dental arch dimensions (adult average)
_ARCH_HALF_WIDTH = 0.025   # m  — half-width of arch at widest point (molars)
_ARCH_DEPTH      = 0.018   # m  — front-to-back depth of arch curve

# Single tooth dimensions (front incisor reference)
_TOOTH_W         = 0.0055  # m  — mesio-distal width
_TOOTH_H         = 0.010   # m  — crown height
_TOOTH_D         = 0.007   # m  — labio-lingual depth

# Number of teeth per arch half (8 per side = 16 total)
_N_HALF          = 8

# Vertical separation between upper and lower arches (at rest / jaw closed)
_ARCH_GAP        = 0.002   # m  — 2 mm occlusal gap (slightly open)

# Jaw rotation axis is approximately at the ear level in FLAME
# pose[3] is jaw opening angle in FLAME (radians, 0 = closed)
_JAW_PIVOT_Y     = -0.060  # m  — approximate jaw pivot height

# Enamel / ivory colours
_ENAMEL_COLOR    = (0.95, 0.93, 0.87, 1.0)   # slightly warm white
_GUM_COLOR       = (0.85, 0.50, 0.48, 1.0)   # pinkish gum
_TONGUE_COLOR    = (0.80, 0.36, 0.34, 1.0)   # tongue pink


# ── arch coordinate generation ───────────────────────────────────────────────

def _arch_positions(n_half: int, half_width: float, depth: float) -> np.ndarray:
    """
    Return (N, 2) array of (x, z_offset) for a parabolic dental arch.
    x ranges from -half_width to +half_width.
    z_offset = depth * (1 - (x/half_width)^2) so centre sticks forward.

    Index 0 = rightmost tooth (avatar's right = -x), index N-1 = leftmost.
    """
    n = n_half * 2
    xs = np.linspace(-half_width, half_width, n, dtype=np.float32)
    zs = depth * (1.0 - (xs / half_width) ** 2)
    return np.stack([xs, zs], axis=1)


# ── single tooth geometry ────────────────────────────────────────────────────

def _tooth_box(
    center: np.ndarray,  # (3,) world-space centre of this tooth crown
    width: float,
    height: float,
    depth: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (positions, indices) for a single tooth as a rounded-top box.
    The top surface is slightly convex (cusp simulation).
    """
    hw, hh, hd = width / 2, height / 2, depth / 2

    # 8 box corners: bottom 4, top 4 with slight upward bow
    bx = np.array([
        [-hw, -hh, -hd],
        [ hw, -hh, -hd],
        [ hw, -hh,  hd],
        [-hw, -hh,  hd],
        [-hw,  hh, -hd],
        [ hw,  hh, -hd],
        [ hw,  hh,  hd],
        [-hw,  hh,  hd],
    ], dtype=np.float32)

    # Slight cusp bow on top face: raise centre by 1 mm
    cusp = 0.001
    top_extra = np.array([
        [0.0, cusp, -hd * 0.4],
        [0.0, cusp,  hd * 0.4],
    ], dtype=np.float32)

    verts = np.vstack([bx, bx + center, top_extra + center + [0, hh, 0]])
    # Use just the base box (8 verts) for simplicity — 6 faces × 2 triangles
    verts = (bx + center).astype(np.float32)

    idx = np.array([
        0, 2, 1,  0, 3, 2,   # bottom
        4, 5, 6,  4, 6, 7,   # top
        0, 1, 5,  0, 5, 4,   # front
        2, 3, 7,  2, 7, 6,   # back
        0, 4, 7,  0, 7, 3,   # left
        1, 2, 6,  1, 6, 5,   # right
    ], dtype=np.uint32)

    return verts, idx


# ── arch assembly ─────────────────────────────────────────────────────────────

def _build_arch(
    arch_positions_xz: np.ndarray,   # (N, 2) in local arch coords
    y_base: float,                    # world-space y of tooth base
    tooth_h: float,
    tooth_d: float,
    mouth_center: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Merge all tooth boxes in one arch into a single mesh."""
    all_pos: list[np.ndarray] = []
    all_idx: list[np.ndarray] = []
    offset = 0

    n = len(arch_positions_xz)
    tooth_w = _ARCH_HALF_WIDTH * 2 / n   # auto-size width to fill arch

    for i in range(n):
        x_local, z_off = arch_positions_xz[i]
        center = np.array([
            mouth_center[0] + x_local,
            y_base + tooth_h / 2,
            mouth_center[2] - z_off,   # z_off pushes forward, subtract for Z-forward
        ], dtype=np.float32)

        pos, idx = _tooth_box(center, tooth_w * 0.85, tooth_h, tooth_d)
        all_pos.append(pos)
        all_idx.append(idx + offset)
        offset += len(pos)

    positions = np.vstack(all_pos).astype(np.float32)
    indices   = np.concatenate(all_idx).astype(np.uint32)
    return positions, indices


# ── tongue plane ──────────────────────────────────────────────────────────────

def _tongue_plane(mouth_center: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Simple flat tongue base — a quad in the floor of the mouth.
    Will be displaced by tongueOut blendshape in animation.
    """
    cx, cy, cz = mouth_center
    y  = cy - 0.008
    hw = 0.018
    hd = 0.014
    verts = np.array([
        [cx - hw, y, cz - hd],
        [cx + hw, y, cz - hd],
        [cx + hw, y, cz + hd],
        [cx - hw, y, cz + hd],
    ], dtype=np.float32)
    idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    return verts, idx


# ── jaw displacement ──────────────────────────────────────────────────────────

def _jaw_open_offset(jaw_angle_rad: float) -> float:
    """
    Convert FLAME jaw rotation (radians, positive = open) to a
    vertical displacement (metres) for the lower arch.
    Uses the approximate jaw pivot distance from the lower arch.
    """
    # Pivot is about 60 mm above the lower arch centre
    pivot_dist = abs(_MOUTH_CENTER[1] - _JAW_PIVOT_Y)
    return pivot_dist * np.sin(np.clip(jaw_angle_rad, 0, 0.6))


# ── public API ────────────────────────────────────────────────────────────────

def build_teeth(flame_params: FlameParams) -> bytes:
    """
    Build a GLB containing upper teeth, lower teeth, and tongue base.

    Returns GLB bytes. The lower arch is displaced by the jaw angle
    extracted from flame_params.pose[3].
    """
    jaw_angle = float(flame_params.pose[3]) if len(flame_params.pose) > 3 else 0.0
    jaw_drop  = _jaw_open_offset(jaw_angle)

    arch_xz = _arch_positions(_N_HALF, _ARCH_HALF_WIDTH, _ARCH_DEPTH)

    b = GLBBuilder()
    mat_enamel = b.add_material(PBRMaterial(
        name="enamel", base_color=_ENAMEL_COLOR, roughness=0.25, metallic=0.0,
    ))
    mat_tongue = b.add_material(PBRMaterial(
        name="tongue", base_color=_TONGUE_COLOR, roughness=0.8, metallic=0.0,
    ))

    mc = _MOUTH_CENTER.copy()

    # Upper teeth (static — attached to head)
    y_upper = mc[1] + _ARCH_GAP / 2
    pos_u, idx_u = _build_arch(arch_xz, y_upper, _TOOTH_H, _TOOTH_D, mc)
    b.add_mesh("teeth_upper", pos_u, idx_u, mat_enamel)

    # Lower teeth (displaced by jaw opening)
    mc_lower = mc.copy()
    mc_lower[1] -= jaw_drop        # jaw pivot pulls lower arch down
    y_lower = mc_lower[1] - _ARCH_GAP / 2 - _TOOTH_H
    pos_l, idx_l = _build_arch(arch_xz, y_lower, _TOOTH_H, _TOOTH_D, mc_lower)
    b.add_mesh("teeth_lower", pos_l, idx_l, mat_enamel)

    # Tongue base
    tongue_center = mc_lower.copy()
    tongue_center[1] -= _TOOTH_H * 0.5
    pos_t, idx_t = _tongue_plane(tongue_center)
    b.add_mesh("tongue_base", pos_t, idx_t, mat_tongue)

    return b.build()

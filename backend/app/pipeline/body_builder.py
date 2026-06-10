"""
Neck + upper torso geometry builder — Phase 3 CPU avatar completion.

Generates neck and shoulder geometry so the avatar is not a floating head.
Runs entirely on CPU. Does NOT require the SMPL-X model download — uses a
procedural approach derived from FLAME head proportions.

(When SMPL-X is available, this module can be replaced by smplx_body.py
 that reads the official parametric model. Interface stays the same.)

Coordinate system: Y-up, Z-forward (FLAME).

Generated geometry:
  neck   — tapered cylinder from chin (y ≈ -0.10) down to collarbone
  clavicle_L / clavicle_R — shoulder slope segments
  chest  — flat quad capping the chest

Texture sampling:
  The original photo is sampled in the lower-face / neck region to extract
  skin colour, which is applied as the base colour for all body geometry.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image

from .glb_utils import GLBBuilder, PBRMaterial, compute_normals
from .schemas import FlameParams

logger = logging.getLogger(__name__)

# ── anatomical constants ──────────────────────────────────────────────────────
# All in metres.  Derived from average adult proportions and FLAME template.

# FLAME chin position (from template analysis): y ≈ -0.187
# We start the neck slightly above the chin so it blends with the FLAME mesh.
_NECK_TOP_Y     = -0.100   # m  — neck mesh starts here (just below jaw)
_NECK_BOT_Y     = -0.230   # m  — collarbone level
_NECK_TOP_R     = 0.038    # m  — neck radius at top (matches FLAME jaw width)
_NECK_BOT_R     = 0.050    # m  — neck radius at collarbone (slightly wider)

# Shoulder geometry
_SHOULDER_Y     = -0.230   # m  — shoulder tip height (same as neck bottom)
_SHOULDER_W     = 0.180    # m  — half-width (total shoulder span ≈ 36 cm)
_SHOULDER_DROP  = 0.030    # m  — shoulder tip is this far below collarbone

# Chest cap
_CHEST_TOP_Y    = -0.230   # m
_CHEST_BOT_Y    = -0.340   # m  — bottom of visible chest in portrait crop
_CHEST_HW       = 0.160    # m  — half-width

_NECK_SEGMENTS  = 12       # radial subdivisions on neck cylinder
_NECK_RINGS     = 4        # vertical rings along neck

# Skin colour fallback (when photo texture fails)
_SKIN_FALLBACK  = (0.78, 0.61, 0.48, 1.0)


# ── texture sampling ──────────────────────────────────────────────────────────

def _sample_neck_color(image_bytes: bytes) -> tuple[float, float, float, float]:
    """
    Sample the average skin colour from the lower-face / neck area of the photo.
    The preprocessed crop is 512×512 with the face centred; the neck region is
    roughly rows 380-480, cols 180-340.
    Returns (r, g, b, a) in [0, 1].
    """
    try:
        img  = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((512, 512))
        arr  = np.array(img, dtype=np.float32) / 255.0
        patch = arr[370:480, 170:340]            # lower face / neck strip
        mean  = patch.mean(axis=(0, 1))
        # Slightly lighten the sampled colour (shadows make neck look darker)
        mean  = np.clip(mean * 1.1, 0, 1)
        return (float(mean[0]), float(mean[1]), float(mean[2]), 1.0)
    except Exception as exc:
        logger.warning("body_builder: texture sample failed (%s) — using fallback", exc)
        return _SKIN_FALLBACK


# ── mesh generators ───────────────────────────────────────────────────────────

def _tapered_cylinder(
    top_y: float, bot_y: float,
    top_r: float, bot_r: float,
    segments: int, rings: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Tapered cylinder (frustum) centred on X=0, Z=0."""
    verts = []
    for ring in range(rings + 1):
        t  = ring / rings
        y  = top_y + t * (bot_y - top_y)
        r  = top_r + t * (bot_r - top_r)
        for s in range(segments):
            angle = 2 * np.pi * s / segments
            x = r * np.cos(angle)
            z = r * np.sin(angle)
            verts.append([x, y, z])

    idx = []
    for ring in range(rings):
        for s in range(segments):
            a = ring * segments + s
            b = ring * segments + (s + 1) % segments
            c = (ring + 1) * segments + s
            d = (ring + 1) * segments + (s + 1) % segments
            idx += [a, c, b, b, c, d]

    return (np.array(verts, dtype=np.float32),
            np.array(idx,   dtype=np.uint32))


def _shoulder_mesh(
    neck_bot_y: float,
    shoulder_y: float,
    shoulder_drop: float,
    half_width: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Two trapezoidal shoulder slabs connecting neck bottom to shoulder tips.
    Left and right are mirrored.

    Generated as two quads (4 triangles total per side).
    """
    ny = neck_bot_y
    sy = shoulder_y - shoulder_drop

    # Each shoulder: 4-vertex quad
    left_verts = np.array([
        [ _NECK_BOT_R,  ny, -_NECK_BOT_R],     # inner top
        [ half_width,   sy,  0.0],              # outer top
        [ half_width,   sy - 0.025, 0.0],       # outer bottom
        [ _NECK_BOT_R,  ny - 0.025, -_NECK_BOT_R], # inner bottom
    ], dtype=np.float32)

    right_verts = left_verts.copy()
    right_verts[:, 0] *= -1   # mirror on x-axis

    verts = np.vstack([left_verts, right_verts])
    idx   = np.array([
        0, 1, 2,  0, 2, 3,    # left shoulder
        4, 6, 5,  4, 7, 6,    # right shoulder (flipped winding)
    ], dtype=np.uint32)
    return verts, idx


def _chest_quad(
    top_y: float, bot_y: float, half_width: float, z: float = 0.02,
) -> tuple[np.ndarray, np.ndarray]:
    """Flat quad representing the upper chest / décolletage area."""
    verts = np.array([
        [-half_width, top_y, z],
        [ half_width, top_y, z],
        [ half_width, bot_y, z],
        [-half_width, bot_y, z],
    ], dtype=np.float32)
    idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)
    return verts, idx


# ── public API ────────────────────────────────────────────────────────────────

def build_upper_body(
    flame_params: FlameParams,
    aligned_image_bytes: bytes,
) -> bytes:
    """
    Build a GLB containing neck + shoulders + upper chest.

    Parameters
    ----------
    flame_params       : used to scale neck width from identity shape
    aligned_image_bytes: 512×512 preprocessed face crop (for skin colour sampling)

    Returns
    -------
    GLB bytes — three meshes: neck, shoulders, chest
    """
    skin_color = _sample_neck_color(aligned_image_bytes)

    # Scale neck radius proportionally to face width from shape params
    # shape[0] is usually the dominant identity dimension (head size)
    shape0 = float(flame_params.shape[0]) if flame_params.shape else 0.0
    # Keep scaling subtle — ±1 std dev shifts neck by ±5%
    neck_scale = 1.0 + np.clip(shape0 * 0.05, -0.15, 0.15)
    top_r = _NECK_TOP_R * neck_scale
    bot_r = _NECK_BOT_R * neck_scale

    b = GLBBuilder()
    mat_skin = b.add_material(PBRMaterial(
        name="skin",
        base_color=skin_color,
        roughness=0.7,
        metallic=0.0,
        double_sided=True,
    ))

    # Neck cylinder
    pos, idx = _tapered_cylinder(
        _NECK_TOP_Y, _NECK_BOT_Y,
        top_r, bot_r,
        _NECK_SEGMENTS, _NECK_RINGS,
    )
    b.add_mesh("neck", pos, idx, mat_skin)

    # Shoulders
    pos, idx = _shoulder_mesh(
        _NECK_BOT_Y, _SHOULDER_Y, _SHOULDER_DROP, _SHOULDER_W,
    )
    b.add_mesh("shoulders", pos, idx, mat_skin)

    # Chest cap
    pos, idx = _chest_quad(_CHEST_TOP_Y, _CHEST_BOT_Y, _CHEST_HW)
    b.add_mesh("chest", pos, idx, mat_skin)

    return b.build()

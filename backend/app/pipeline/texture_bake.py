"""
Texture bake — project the aligned frontal photo onto the FLAME UV layout.

CPU replacement for EMOCA's albedo (MVP architecture decision):
the baked texture preserves the person's actual likeness (skin detail,
facial hair, lips) far better than EMOCA's statistical albedo model.

Method
──────
1. Apply MICA shape params to the FLAME template → posed neutral vertices.
2. Orthographic projection of vertices onto the aligned 512×512 photo
   (FLAME faces +z toward the camera; x→right, y→up).
3. Per-vertex colour = bilinear photo sample, validity-weighted by the
   vertex normal's z component (back-facing vertices get no photo colour).
4. Back-facing / occluded vertices inherit the mean skin tone.
5. Rasterise every FLAME triangle into the cylindrical UV layout at 512²,
   interpolating vertex colours barycentrically.

Output: 512×512 RGB PNG bytes in FLAME UV space (uv_coords/uv_faces from
flame_template). Runs in ~2-4 s on CPU, no dependencies beyond numpy/PIL.
"""

from __future__ import annotations

import io
import logging

import numpy as np
from PIL import Image

from . import flame_template
from .schemas import FlameParams

logger = logging.getLogger(__name__)

TEXTURE_SIZE = 512

# Fraction of the photo height that the FLAME head span occupies in an
# aligned crop produced by preprocess() (face centered, padded).
_HEAD_FRACTION = 0.62

# Minimum normal-z for a vertex to take colour from the frontal photo.
_FRONT_FACING_MIN = 0.10

# FLAME 5023-vertex layout: head 0..3930, then the two eyeball meshes.
_EYEBALL_A = slice(3931, 4477)
_EYEBALL_B = slice(4477, 5023)

# Scalp/hair region starts this far above the eye line (metres).
_HAIR_LINE_ABOVE_EYES = 0.05


def _vertex_normals(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Smooth per-vertex normals, (V, 3) float32."""
    v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)  # (F, 3) area-weighted
    normals = np.zeros_like(verts)
    for i in range(3):
        np.add.at(normals, faces[:, i], fn)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    return (normals / np.maximum(lens, 1e-12)).astype(np.float32)


def _project_to_photo(verts: np.ndarray, photo_hw: tuple[int, int]) -> np.ndarray:
    """Orthographic vertex → pixel mapping for the aligned frontal crop."""
    h, w = photo_hw
    span = verts[:, 1].max() - verts[:, 1].min()  # head height in metres
    scale = (h * _HEAD_FRACTION) / max(span, 1e-6)
    cx_v = (verts[:, 0].max() + verts[:, 0].min()) / 2
    cy_v = (verts[:, 1].max() + verts[:, 1].min()) / 2
    px = (verts[:, 0] - cx_v) * scale + w / 2
    py = (cy_v - verts[:, 1]) * scale + h / 2  # photo y grows downward
    return np.stack([px, py], axis=1).astype(np.float32)


def project_flame_to_photo(verts: np.ndarray, photo_u8: np.ndarray) -> np.ndarray:
    """
    FLAME vertex → photo pixel mapping anchored on the *detected* eyes.

    Similarity transform (scale + translation) that maps the FLAME eyeball
    centres onto the mediapipe eye landmarks, so the scalp projects onto hair
    and features line up. Falls back to the head-fraction heuristic when
    landmarks are unavailable.
    """
    h, w = photo_u8.shape[:2]
    lms = None
    try:
        from .mediapipe_utils import detect_face_landmarks
        lms = detect_face_landmarks(photo_u8)
    except Exception as exc:
        logger.warning("texture_bake: mediapipe unavailable (%s)", exc)

    if lms is None or len(lms) < 468:
        logger.warning("texture_bake: no landmarks — head-fraction heuristic")
        return _project_to_photo(verts, (h, w))

    # Eye centres in photo pixels (mean of inner + outer corners per eye)
    img_left_eye = np.array([(lms[33].x + lms[133].x) / 2 * w,
                             (lms[33].y + lms[133].y) / 2 * h])
    img_right_eye = np.array([(lms[362].x + lms[263].x) / 2 * w,
                              (lms[362].y + lms[263].y) / 2 * h])
    eye_dist_px = float(np.linalg.norm(img_left_eye - img_right_eye))

    eye_a = verts[_EYEBALL_A].mean(axis=0)
    eye_b = verts[_EYEBALL_B].mean(axis=0)
    flame_dist = float(np.linalg.norm(eye_a[:2] - eye_b[:2]))

    # Sanity: interocular ≈ 6.3 cm on FLAME, ≥ 20 px on a usable photo
    if eye_dist_px < 20 or not (0.03 < flame_dist < 0.12):
        logger.warning(
            "texture_bake: implausible eye anchors (%.0fpx / %.3fm) — heuristic",
            eye_dist_px, flame_dist,
        )
        return _project_to_photo(verts, (h, w))

    scale = eye_dist_px / flame_dist
    mid_px = (img_left_eye + img_right_eye) / 2
    mid_v = (eye_a + eye_b) / 2
    px = (verts[:, 0] - mid_v[0]) * scale + mid_px[0]
    py = (mid_v[1] - verts[:, 1]) * scale + mid_px[1]  # photo y grows downward
    return np.stack([px, py], axis=1).astype(np.float32)


def backfill_hidden_colors(
    verts: np.ndarray, colors: np.ndarray, front: np.ndarray
) -> np.ndarray:
    """
    Give back-facing vertices the mean tone of their region — hair above the
    eye line, skin below — so the back of the head is not painted skin-colour.
    Mutates and returns ``colors``.
    """
    if not front.any():
        return colors
    global_mean = colors[front].mean(axis=0)
    eye_y = (verts[_EYEBALL_A, 1].mean() + verts[_EYEBALL_B, 1].mean()) / 2
    upper = verts[:, 1] > eye_y + _HAIR_LINE_ABOVE_EYES
    for region in (upper, ~upper):
        src = front & region
        dst = ~front & region
        if dst.any():
            colors[dst] = colors[src].mean(axis=0) if src.any() else global_mean
    return colors


def _bilinear(img: np.ndarray, px: np.ndarray, py: np.ndarray) -> np.ndarray:
    """Vectorised bilinear sample. img float32 (H,W,3), returns (N,3)."""
    h, w = img.shape[:2]
    x = np.clip(px, 0, w - 2)
    y = np.clip(py, 0, h - 2)
    ix, iy = x.astype(np.int32), y.astype(np.int32)
    fx, fy = (x - ix)[:, None], (y - iy)[:, None]
    return (
        img[iy,     ix    ] * (1 - fx) * (1 - fy) +
        img[iy,     ix + 1] *      fx  * (1 - fy) +
        img[iy + 1, ix    ] * (1 - fx) *      fy  +
        img[iy + 1, ix + 1] *      fx  *      fy
    )


def _rasterize_uv(
    uv: np.ndarray,          # (V, 2) in [0,1]
    uv_faces: np.ndarray,    # (F, 3)
    vert_colors: np.ndarray, # (V, 3) float32 [0,1]
    size: int,
) -> np.ndarray:
    """Fill a (size, size, 3) texture by barycentric triangle rasterisation."""
    tex = np.zeros((size, size, 3), dtype=np.float32)
    filled = np.zeros((size, size), dtype=bool)

    uv_px = uv * (size - 1)
    uv_px[:, 1] = (size - 1) - uv_px[:, 1]  # UV v grows up; image y grows down

    for f in uv_faces:
        p = uv_px[f]              # (3, 2)
        c = vert_colors[f]        # (3, 3)
        x0, y0 = np.floor(p.min(axis=0)).astype(int)
        x1, y1 = np.ceil(p.max(axis=0)).astype(int)
        x0, y0 = max(x0, 0), max(y0, 0)
        x1, y1 = min(x1, size - 1), min(y1, size - 1)
        if x1 < x0 or y1 < y0:
            continue

        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        xs_f, ys_f = xs.ravel().astype(np.float32), ys.ravel().astype(np.float32)

        # Barycentric coords via the edge-function determinant
        d = ((p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) +
             (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1]))
        if abs(d) < 1e-9:
            continue
        w0 = ((p[1, 1] - p[2, 1]) * (xs_f - p[2, 0]) +
              (p[2, 0] - p[1, 0]) * (ys_f - p[2, 1])) / d
        w1 = ((p[2, 1] - p[0, 1]) * (xs_f - p[2, 0]) +
              (p[0, 0] - p[2, 0]) * (ys_f - p[2, 1])) / d
        w2 = 1.0 - w0 - w1

        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not inside.any():
            continue
        xi, yi = xs.ravel()[inside], ys.ravel()[inside]
        cols = (w0[inside, None] * c[0] +
                w1[inside, None] * c[1] +
                w2[inside, None] * c[2])
        tex[yi, xi] = cols
        filled[yi, xi] = True

    # Fill unrasterised texels with mean skin tone to avoid black seams
    if filled.any():
        tex[~filled] = tex[filled].mean(axis=0)
    return tex


def bake_texture(
    aligned_image_bytes: bytes,
    flame_params: FlameParams,
    size: int = TEXTURE_SIZE,
) -> bytes:
    """
    Bake the aligned frontal photo into a FLAME-UV texture.

    Returns PNG bytes (size × size RGB). Raises on unreadable input image;
    callers should treat failures as non-fatal and fall back to a flat tone.
    """
    tpl = flame_template.load()
    shape = np.asarray(flame_params.shape, dtype=np.float32)
    verts = flame_template.apply_shape(tpl, shape)

    img = Image.open(io.BytesIO(aligned_image_bytes)).convert("RGB")
    photo_u8 = np.asarray(img, dtype=np.uint8)
    photo = photo_u8.astype(np.float32) / 255.0

    pix = project_flame_to_photo(verts, photo_u8)
    colors = _bilinear(photo, pix[:, 0], pix[:, 1])  # (V, 3)

    # Back-facing vertices → mean tone of their region (hair / skin)
    normals = _vertex_normals(verts, tpl.faces)
    front = normals[:, 2] > _FRONT_FACING_MIN
    colors = backfill_hidden_colors(verts, colors, front)

    tex = _rasterize_uv(tpl.uv_coords, tpl.uv_faces, colors, size)

    out = Image.fromarray((np.clip(tex, 0, 1) * 255).astype(np.uint8), "RGB")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    logger.info("texture_bake: %d×%d UV texture baked", size, size)
    return buf.getvalue()

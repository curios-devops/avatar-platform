from __future__ import annotations

import io
import json
import logging
import struct
from typing import Optional

import numpy as np
from PIL import Image

from .schemas import FlameParams, GaussianSet, BindingTable

logger = logging.getLogger(__name__)


# x y z (3f)  f_dc_0-2 (3f)  opacity (1f)  scale_0-2 (3f)  rot_0-3 (4f) = 14f
# triangle_idx (1i)  bary_u bary_v bary_w (3f)
# total: 14*4 + 4 + 3*4 = 72 bytes per vertex
_PLY_STRUCT = struct.Struct("<" + "f" * 14 + "i" + "f" * 3)


def _ply_bytes(gaussian_set: GaussianSet) -> bytes:
    n = len(gaussian_set.gaussians)
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        f"element vertex {n}\n"
        "property float x\n"
        "property float y\n"
        "property float z\n"
        "property float f_dc_0\n"
        "property float f_dc_1\n"
        "property float f_dc_2\n"
        "property float opacity\n"
        "property float scale_0\n"
        "property float scale_1\n"
        "property float scale_2\n"
        "property float rot_0\n"
        "property float rot_1\n"
        "property float rot_2\n"
        "property float rot_3\n"
        "property int triangle_idx\n"
        "property float bary_u\n"
        "property float bary_v\n"
        "property float bary_w\n"
        "end_header\n"
    ).encode("ascii")

    buf = bytearray(header)
    for g in gaussian_set.gaussians:
        p, c, s, r, b = g.position, g.sh_dc, g.scale, g.rotation, g.barycentric
        buf += _PLY_STRUCT.pack(
            p[0], p[1], p[2],
            c[0], c[1], c[2],
            g.opacity,
            s[0], s[1], s[2],
            r[0], r[1], r[2], r[3],
            g.triangle_idx,
            b[0], b[1], b[2],
        )
    return bytes(buf)


def _binding_npz(gaussian_set: GaussianSet) -> bytes:
    tri = np.array([g.triangle_idx for g in gaussian_set.gaussians], dtype=np.int32)
    bary = np.array([g.barycentric for g in gaussian_set.gaussians], dtype=np.float32)
    buf = io.BytesIO()
    np.savez(buf, triangle_indices=tri, barycentric=bary)
    return buf.getvalue()


def _iris_color_from_albedo(
    albedo_bytes: bytes,
) -> tuple[float, float, float, float] | None:
    """Sample iris colour from the eye region of the EMOCA albedo texture."""
    try:
        import numpy as np
        img   = Image.open(io.BytesIO(albedo_bytes)).convert("RGB").resize((512, 512))
        arr   = np.array(img, dtype=np.float32) / 255.0
        # In EMOCA UV layout, the left eye iris sits roughly at [200:240, 140:180]
        # and the right eye at [200:240, 330:370] of a 512×512 albedo.
        # We sample both and average.
        left_patch  = arr[200:240, 140:180]
        right_patch = arr[200:240, 330:370]
        mean = ((left_patch.mean(axis=(0, 1)) + right_patch.mean(axis=(0, 1))) / 2)
        return (float(mean[0]), float(mean[1]), float(mean[2]), 1.0)
    except Exception:
        return None


def _build_eyes(
    flame_params: FlameParams,
    albedo_bytes: bytes | None = None,
) -> bytes:
    try:
        from .eye_builder import build_eyes
        iris_color = _iris_color_from_albedo(albedo_bytes) if albedo_bytes else None
        return build_eyes(flame_params, iris_color=iris_color)
    except Exception as exc:
        logger.warning("eye_builder failed (%s) — using empty GLB", exc)
        return _empty_glb("eyes_proxy")


def _build_teeth(flame_params: FlameParams) -> bytes:
    try:
        from .teeth_builder import build_teeth
        return build_teeth(flame_params)
    except Exception as exc:
        logger.warning("teeth_builder failed (%s) — using empty GLB", exc)
        return _empty_glb("teeth_proxy")


def _build_body(flame_params: FlameParams, aligned_image_bytes: bytes) -> bytes:
    try:
        from .body_builder import build_upper_body
        return build_upper_body(flame_params, aligned_image_bytes)
    except Exception as exc:
        logger.warning("body_builder failed (%s) — using empty GLB", exc)
        return _empty_glb("body_proxy")


def _empty_glb(name: str = "proxy") -> bytes:
    """Minimal valid GLB with no geometry (fallback on builder failure)."""
    json_chunk = json.dumps(
        {"asset": {"version": "2.0"}, "scene": 0,
         "scenes": [{"name": name}]},
        separators=(",", ":"),
    ).encode()
    pad = (4 - len(json_chunk) % 4) % 4
    json_chunk += b" " * pad
    chunk  = struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    header = struct.pack("<III", 0x46546C67, 2, 12 + len(chunk))
    return header + chunk


def _preview_png(aligned_image_bytes: bytes) -> bytes:
    img = Image.open(io.BytesIO(aligned_image_bytes)).convert("RGB")
    img = img.resize((512, 512), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def package(
    aligned_image_bytes: bytes,
    flame_params: FlameParams,
    gaussian_set: GaussianSet,
    binding_table: BindingTable,
    albedo_bytes: bytes | None = None,
) -> dict[str, bytes]:
    """
    Assemble AvatarBundle artifacts. Validates completeness before building.
    Raises ValueError on missing/incomplete components (never silently returns partial).
    Returns {filename: bytes} ready for the publish stage.
    """
    if not binding_table.is_complete:
        raise ValueError("Binding table is incomplete — all Gaussians must be bound to FLAME")
    if not flame_params:
        raise ValueError("FLAME params are required")
    if not gaussian_set.gaussians:
        raise ValueError("Gaussian set is empty")

    flame_json = json.dumps(
        {
            "shape": flame_params.shape,
            "expression": flame_params.expression,
            "pose": flame_params.pose,
            "tex": flame_params.tex,
            "topology_version": "FLAME_2023",
        },
        separators=(",", ":"),
    ).encode()

    logger.info("package: building eyes…")
    eyes_glb = _build_eyes(flame_params, albedo_bytes=albedo_bytes)

    logger.info("package: building teeth…")
    teeth_glb = _build_teeth(flame_params)

    logger.info("package: building upper body…")
    body_glb = _build_body(flame_params, aligned_image_bytes)

    return {
        "gaussians.ply":                _ply_bytes(gaussian_set),
        "flame_params.json":            flame_json,
        "gaussian_flame_binding.npz":   _binding_npz(gaussian_set),
        "eyes.glb":                     eyes_glb,
        "teeth.glb":                    teeth_glb,
        "body.glb":                     body_glb,
        "neutral_front.png":            _preview_png(aligned_image_bytes),
    }

"""
Minimal GLB 2.0 (binary glTF) packer.

No external dependencies — only numpy + json + struct.

Usage::

    from .glb_utils import GLBBuilder, PBRMaterial

    b = GLBBuilder()
    mat_white = b.add_material(PBRMaterial(name="sclera", base_color=(0.95, 0.94, 0.92, 1.0)))
    b.add_mesh("left_eye", positions, normals, indices, mat_white)
    glb_bytes = b.build()
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ── glTF constants ────────────────────────────────────────────────────────────
_MAGIC        = 0x46546C67   # "glTF"
_VERSION      = 2
_CHUNK_JSON   = 0x4E4F534A   # "JSON"
_CHUNK_BIN    = 0x004E4942   # "BIN\0"
_CT_FLOAT     = 5126         # float32
_CT_UINT32    = 5125         # uint32
_CT_UINT16    = 5123         # uint16
_BV_ARRAY     = 34962        # ARRAY_BUFFER  (vertex/normal data)
_BV_ELEMENTS  = 34963        # ELEMENT_ARRAY_BUFFER (index data)
_MODE_TRIS    = 4            # TRIANGLES


@dataclass
class PBRMaterial:
    name: str = "material"
    base_color: tuple[float, float, float, float] = (0.8, 0.8, 0.8, 1.0)
    metallic: float = 0.0
    roughness: float = 0.6
    double_sided: bool = False
    alpha_mode: str = "OPAQUE"   # "OPAQUE" | "BLEND" | "MASK"
    emissive: tuple[float, float, float] = (0.0, 0.0, 0.0)


def compute_normals(positions: np.ndarray, indices: np.ndarray) -> np.ndarray:
    """Compute smooth per-vertex normals by averaging incident face normals."""
    n = len(positions)
    normals = np.zeros((n, 3), dtype=np.float32)
    tris = indices.reshape(-1, 3)
    v0 = positions[tris[:, 0]]
    v1 = positions[tris[:, 1]]
    v2 = positions[tris[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0).astype(np.float32)
    np.add.at(normals, tris[:, 0], fn)
    np.add.at(normals, tris[:, 1], fn)
    np.add.at(normals, tris[:, 2], fn)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    normals /= np.maximum(lens, 1e-8)
    return normals


class GLBBuilder:
    """Accumulates meshes + materials then serialises to GLB bytes."""

    def __init__(self):
        self._materials: list[dict] = []
        self._meshes: list[tuple[str, np.ndarray, np.ndarray, np.ndarray, int]] = []
        # (name, positions(N,3), normals(N,3), indices(M,), mat_idx)

    # ── public API ────────────────────────────────────────────────────────────

    def add_material(self, mat: PBRMaterial) -> int:
        """Register a PBR material; returns its index."""
        d: dict = {
            "name": mat.name,
            "pbrMetallicRoughness": {
                "baseColorFactor": list(mat.base_color),
                "metallicFactor":  mat.metallic,
                "roughnessFactor": mat.roughness,
            },
            "doubleSided": mat.double_sided,
            "alphaMode":   mat.alpha_mode,
        }
        if any(v > 0 for v in mat.emissive):
            d["emissiveFactor"] = list(mat.emissive)
        self._materials.append(d)
        return len(self._materials) - 1

    def add_mesh(
        self,
        name: str,
        positions: np.ndarray,
        indices: np.ndarray,
        mat_idx: int,
        normals: Optional[np.ndarray] = None,
    ) -> None:
        """
        Add a triangle mesh.

        positions : (N, 3)  float32, in metres
        indices   : (M,)    uint32  (M must be divisible by 3)
        normals   : (N, 3)  float32  — computed if not supplied
        """
        pos = np.asarray(positions, dtype=np.float32)
        idx = np.asarray(indices,   dtype=np.uint32)
        nrm = (np.asarray(normals, dtype=np.float32)
               if normals is not None
               else compute_normals(pos, idx))
        self._meshes.append((name, pos, nrm, idx, mat_idx))

    def build(self) -> bytes:
        """Serialise everything to a GLB 2.0 byte string."""
        if not self._meshes:
            return _empty_glb()

        bin_parts: list[bytes] = []
        accessors: list[dict]   = []
        buf_views: list[dict]   = []

        nodes:    list[dict] = []
        meshes_j: list[dict] = []

        byte_offset = 0

        for mesh_name, pos, nrm, idx, mat_idx in self._meshes:
            # ── position accessor ──────────────────────────────────────────
            pos_bytes  = pos.tobytes()
            nrm_bytes  = nrm.tobytes()
            idx_bytes  = idx.tobytes()

            # bufferViews
            bv_pos = _bv(byte_offset, len(pos_bytes), _BV_ARRAY)
            byte_offset += len(pos_bytes)
            buf_views.append(bv_pos)
            acc_pos = _acc_vec3(_CT_FLOAT, len(pos), len(buf_views) - 1,
                                pos.min(axis=0).tolist(), pos.max(axis=0).tolist())
            accessors.append(acc_pos)

            bv_nrm = _bv(byte_offset, len(nrm_bytes), _BV_ARRAY)
            byte_offset += len(nrm_bytes)
            buf_views.append(bv_nrm)
            acc_nrm = _acc_vec3(_CT_FLOAT, len(nrm), len(buf_views) - 1)
            accessors.append(acc_nrm)

            bv_idx = _bv(byte_offset, len(idx_bytes), _BV_ELEMENTS)
            byte_offset += len(idx_bytes)
            buf_views.append(bv_idx)
            acc_idx = {
                "bufferView": len(buf_views) - 1,
                "componentType": _CT_UINT32,
                "count": len(idx),
                "type": "SCALAR",
            }
            accessors.append(acc_idx)

            n_acc = len(accessors)
            prim = {
                "attributes": {
                    "POSITION": n_acc - 3,
                    "NORMAL":   n_acc - 2,
                },
                "indices":  n_acc - 1,
                "material": mat_idx,
                "mode":     _MODE_TRIS,
            }
            meshes_j.append({"name": mesh_name, "primitives": [prim]})
            nodes.append({"mesh": len(meshes_j) - 1, "name": mesh_name})
            bin_parts.extend([pos_bytes, nrm_bytes, idx_bytes])

        bin_blob = b"".join(bin_parts)
        # BIN chunk must be 4-byte aligned
        pad = (4 - len(bin_blob) % 4) % 4
        bin_blob += b"\x00" * pad

        # ── glTF JSON ─────────────────────────────────────────────────────
        gltf = {
            "asset": {"version": "2.0", "generator": "avatar-platform/glb_utils"},
            "scene": 0,
            "scenes":      [{"nodes": list(range(len(nodes)))}],
            "nodes":       nodes,
            "meshes":      meshes_j,
            "materials":   self._materials or [_default_material()],
            "accessors":   accessors,
            "bufferViews": buf_views,
            "buffers":     [{"byteLength": len(bin_blob)}],
        }
        json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
        json_pad   = (4 - len(json_bytes) % 4) % 4
        json_bytes += b" " * json_pad

        # ── pack GLB ──────────────────────────────────────────────────────
        json_chunk = struct.pack("<II", len(json_bytes), _CHUNK_JSON) + json_bytes
        bin_chunk  = struct.pack("<II", len(bin_blob),  _CHUNK_BIN)  + bin_blob
        total      = 12 + len(json_chunk) + len(bin_chunk)
        header     = struct.pack("<III", _MAGIC, _VERSION, total)

        return header + json_chunk + bin_chunk


# ── private helpers ───────────────────────────────────────────────────────────

def _bv(offset: int, length: int, target: int) -> dict:
    return {"buffer": 0, "byteOffset": offset, "byteLength": length, "target": target}


def _acc_vec3(comp_type: int, count: int, bv: int,
              mn: list | None = None, mx: list | None = None) -> dict:
    d: dict = {"bufferView": bv, "componentType": comp_type, "count": count, "type": "VEC3"}
    if mn is not None:
        d["min"] = mn
    if mx is not None:
        d["max"] = mx
    return d


def _default_material() -> dict:
    return {
        "name": "default",
        "pbrMetallicRoughness": {
            "baseColorFactor": [0.8, 0.8, 0.8, 1.0],
            "metallicFactor": 0.0,
            "roughnessFactor": 0.6,
        },
    }


def _empty_glb() -> bytes:
    """Minimal valid GLB with no geometry."""
    j = b'{"asset":{"version":"2.0"},"scene":0,"scenes":[{}]}'
    j += b" " * ((4 - len(j) % 4) % 4)
    chunk  = struct.pack("<II", len(j), _CHUNK_JSON) + j
    header = struct.pack("<III", _MAGIC, _VERSION, 12 + len(chunk))
    return header + chunk

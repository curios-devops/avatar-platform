"""Lector de PLY de Gaussian Splatting (formato INRIA/LAM) en numpy puro.

Lee los MISMOS campos que el visor WebGPU (webgpu_renderer.ts): posición,
color DC (f_dc → RGB), opacidad (sigmoid), escala (exp) y rotación (quaternion
normalizado). Sin torch, sin GPU.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

# SH banda-0: RGB = 0.5 + C0 * f_dc  (constante estándar de 3DGS)
_SH_C0 = 0.28209479177387814


@dataclass
class Gaussians:
    xyz: np.ndarray      # (N,3) float32  posición mundo
    rgb: np.ndarray      # (N,3) float32  color en [0,1]
    opacity: np.ndarray  # (N,)  float32  en [0,1]
    scale: np.ndarray    # (N,3) float32  desvío estándar (lineal, ya exp)
    rot: np.ndarray      # (N,4) float32  quaternion normalizado (w,x,y,z)

    def __len__(self) -> int:
        return int(self.xyz.shape[0])


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


# PLY → numpy dtype (solo los tipos que aparecen en los splats que leemos:
# LAM/LHM son 100% float, FaceLift mezcla uchar de color con floats de SH).
_PLY_DTYPE = {
    "float": "<f4", "float32": "<f4",
    "double": "<f8", "float64": "<f8",
    "uchar": "u1", "uint8": "u1",
    "char": "i1", "int8": "i1",
    "int": "<i4", "int32": "<i4",
    "uint": "<u4", "uint32": "<u4",
    "short": "<i2", "int16": "<i2",
    "ushort": "<u2", "uint16": "<u2",
}


def load_ply(path: str | Path) -> Gaussians:
    """Lee cualquier PLY 3DGS binario con propiedades por-vértice de tipo
    escalar (no listas) — tolera layouts mixtos (p.ej. FaceLift intercala
    red/green/blue en uchar entre floats de posición y SH). Extra fields
    (f_rest_*, red/green/blue) se ignoran: usamos f_dc para color, como el
    resto del harness."""
    path = Path(path)
    raw = path.read_bytes()
    hdr_end = raw.index(b"end_header\n") + len(b"end_header\n")
    header = raw[:hdr_end].decode("ascii", "replace").splitlines()

    n = 0
    props: list[tuple[str, str]] = []  # (name, ply_type)
    fmt = "binary_little_endian"
    for line in header:
        if line.startswith("element vertex"):
            n = int(line.split()[-1])
        elif line.startswith("property"):
            parts = line.split()
            if parts[1] == "list":
                raise ValueError(f"propiedades tipo 'list' no soportadas: {line!r}")
            props.append((parts[2], parts[1]))
        elif line.startswith("format"):
            fmt = line.split()[1]
    if "binary_little_endian" not in fmt:
        raise ValueError(f"solo binary_little_endian soportado, no {fmt!r}")

    dtype = np.dtype([(name, _PLY_DTYPE[t]) for name, t in props])
    data = np.frombuffer(raw[hdr_end:], dtype=dtype, count=n)

    def field(name: str) -> np.ndarray:
        return data[name].astype(np.float32)

    xyz = np.stack([field("x"), field("y"), field("z")], axis=1)
    f_dc = np.stack([field("f_dc_0"), field("f_dc_1"), field("f_dc_2")], axis=1)
    rgb = np.clip(0.5 + _SH_C0 * f_dc, 0.0, 1.0).astype(np.float32)
    opacity = _sigmoid(field("opacity"))
    scale = np.exp(np.stack([field("scale_0"), field("scale_1"), field("scale_2")], axis=1))
    rot = np.stack([field("rot_0"), field("rot_1"), field("rot_2"), field("rot_3")], axis=1)
    rot /= (np.linalg.norm(rot, axis=1, keepdims=True) + 1e-9)

    return Gaussians(xyz=xyz, rgb=rgb, opacity=opacity, scale=scale, rot=rot)


def quat_to_rotmat(q: np.ndarray) -> np.ndarray:
    """(N,4) quaternion (w,x,y,z) → (N,3,3) matriz de rotación."""
    w, x, y, z = q[:, 0], q[:, 1], q[:, 2], q[:, 3]
    R = np.empty((q.shape[0], 3, 3), dtype=np.float32)
    R[:, 0, 0] = 1 - 2 * (y * y + z * z)
    R[:, 0, 1] = 2 * (x * y - w * z)
    R[:, 0, 2] = 2 * (x * z + w * y)
    R[:, 1, 0] = 2 * (x * y + w * z)
    R[:, 1, 1] = 1 - 2 * (x * x + z * z)
    R[:, 1, 2] = 2 * (y * z - w * x)
    R[:, 2, 0] = 2 * (x * z - w * y)
    R[:, 2, 1] = 2 * (y * z + w * x)
    R[:, 2, 2] = 1 - 2 * (x * x + y * y)
    return R


def save_ply(g: Gaussians, path: str | Path) -> None:
    """Escribe un PLY 3DGS binario (mismas propiedades que load_ply lee) —
    inversas exactas de las transformaciones de carga: RGB→f_dc, opacidad→
    logit, escala lineal→log. rot se re-normaliza por seguridad."""
    path = Path(path)
    n = len(g)
    f_dc = (g.rgb - 0.5) / _SH_C0
    opacity_logit = np.log(np.clip(g.opacity, 1e-6, 1 - 1e-6) /
                           (1 - np.clip(g.opacity, 1e-6, 1 - 1e-6)))
    log_scale = np.log(np.maximum(g.scale, 1e-9))
    rot = g.rot / (np.linalg.norm(g.rot, axis=1, keepdims=True) + 1e-9)
    nx_nz = np.zeros((n, 3), dtype=np.float32)  # normals: LAM/LHM no las usan

    props = ["x", "y", "z", "nx", "ny", "nz",
             "f_dc_0", "f_dc_1", "f_dc_2", "opacity",
             "scale_0", "scale_1", "scale_2", "rot_0", "rot_1", "rot_2", "rot_3"]
    data = np.concatenate([g.xyz, nx_nz, f_dc, opacity_logit[:, None],
                           log_scale, rot], axis=1).astype("<f4")

    header = "ply\nformat binary_little_endian 1.0\n" \
             f"element vertex {n}\n" + \
             "".join(f"property float {p}\n" for p in props) + "end_header\n"
    with path.open("wb") as f:
        f.write(header.encode("ascii"))
        f.write(data.tobytes())


def covariance3d(g: Gaussians) -> np.ndarray:
    """Σ3d = R S S^T R^T por gaussiano → (N,3,3)."""
    R = quat_to_rotmat(g.rot)
    S = g.scale  # (N,3) desvíos
    # M = R * diag(S);  Σ = M M^T
    M = R * S[:, None, :]                    # escala columnas de R
    return np.matmul(M, np.transpose(M, (0, 2, 1)))

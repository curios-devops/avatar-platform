"""Put a splat in a common frame for side-by-side renders: feet at y=0, +Y up, front view on +Z, 1.65 m tall.

COLMAP's world frame is arbitrary. For a turntable reconstruction the camera centres lie on a ring:
its normal is "up" (signed so it matches the cameras' up vector) and the camera of the first frame,
which is the seed image, looks at the front. A TripoSplat output only needs the height rescale and
an optional fixed rotation.

    python splat/normalize.py in.ply out.ply --colmap recon_dir
    python splat/normalize.py in.ply out.ply --rot-x 180
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
from plyfile import PlyData, PlyElement

HEIGHT = 1.65


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:  # (w, x, y, z)
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b.T
    return np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], axis=1)


def mat_to_quat(R: np.ndarray) -> np.ndarray:
    """Rotation matrix to (w, x, y, z), Shepperd's method: stays exact for half turns, where w = 0."""
    t = np.trace(R)
    if t > 0:
        s = 2 * np.sqrt(1 + t)
        return np.array([s / 4, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s])
    i = int(np.argmax(np.diag(R)))
    j, k = (i + 1) % 3, (i + 2) % 3
    s = 2 * np.sqrt(1 + R[i, i] - R[j, j] - R[k, k])
    q = np.zeros(4)
    q[0], q[1 + i] = (R[k, j] - R[j, k]) / s, s / 4
    q[1 + j], q[1 + k] = (R[j, i] + R[i, j]) / s, (R[k, i] + R[i, k]) / s
    return q


def colmap_frame(recon_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Rotation (rows = new x, y, z axes) and the ring centre, from the registered cameras."""
    import pycolmap
    rec = pycolmap.Reconstruction(str(recon_dir / "sparse" / "0"))
    imgs = sorted(rec.images.values(), key=lambda im: im.name)
    centres, ups = [], []
    for im in imgs:
        w2c = im.cam_from_world() if callable(im.cam_from_world) else im.cam_from_world
        R = w2c.rotation.matrix()
        centres.append(-R.T @ w2c.translation)
        ups.append(-R[1])  # the image y axis points down
    c = np.array(centres)
    ring = c.mean(axis=0)
    up = np.linalg.svd(c - ring)[2][2]
    up *= np.sign(up @ np.mean(ups, axis=0))
    front = c[0] - ring  # the first frame is the seed, seen from the front
    front -= (front @ up) * up
    z = front / np.linalg.norm(front)
    x = np.cross(up, z)
    return np.stack([x, up, z]), ring


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--colmap", type=Path)
    ap.add_argument("--rot-x", type=float, default=0.0, help="extra rotation about x, degrees")
    ap.add_argument("--rot-y", type=float, default=0.0, help="extra rotation about y, degrees")
    a = ap.parse_args()
    ply = PlyData.read(str(a.src))
    v = ply["vertex"].data
    xyz = np.stack([v["x"], v["y"], v["z"]], axis=1).astype(np.float64)
    if a.colmap:
        R, origin = colmap_frame(a.colmap)
    else:
        R, origin = np.eye(3), np.median(xyz, axis=0)
    for ang, axis in ((a.rot_x, 0), (a.rot_y, 1)):
        if ang:
            t = np.radians(ang)
            c, s = np.cos(t), np.sin(t)
            E = {0: np.array([[1, 0, 0], [0, c, -s], [0, s, c]]), 1: np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])}[axis]
            R = E @ R
    p = (xyz - origin) @ R.T
    op = 1 / (1 + np.exp(-v["opacity"]))
    solid = p[op > 0.3]  # floaters with low opacity must not set the height
    lo, hi = np.percentile(solid[:, 1], 0.5), np.percentile(solid[:, 1], 99.5)
    k = HEIGHT / (hi - lo)
    p = (p - [np.median(solid[:, 0]), lo, np.median(solid[:, 2])]) * k
    out = v.copy()
    out["x"], out["y"], out["z"] = p[:, 0], p[:, 1], p[:, 2]
    for s in ("scale_0", "scale_1", "scale_2"):
        out[s] = v[s] + np.log(k)
    q = np.stack([v["rot_0"], v["rot_1"], v["rot_2"], v["rot_3"]], axis=1)
    q = quat_mul(mat_to_quat(R), q / np.linalg.norm(q, axis=1, keepdims=True))
    for i in range(4):
        out[f"rot_{i}"] = q[:, i]
    PlyData([PlyElement.describe(out, "vertex")], text=False).write(str(a.dst))
    print(f"{a.dst}: {len(out)} splats, scale x{k:.3f}, {a.dst.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()

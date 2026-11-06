"""Fuse a full-body TripoSplat with a bust TripoSplat of the same image: body everywhere, bust face.

A whole-body splat spends its 262k gaussians on the whole person, so the face loses its identity.
A splat of the cropped bust has a photoreal face but a weak back of the head (translucent, the
ponytail a grid). The fusion keeps each where it is good:

1. Both clouds go to one frame: +Y up, the face looking at -Z.
2. The bust is registered onto the body's head: try the four quarter turns, match the
   crown-to-neck height, then refine with scaled ICP on the head points.
3. Above the neck, the front and sides come from the bust and the back from the body. Each side
   fades out over a band, so the seams cross-fade instead of cutting.
4. The bust's skin is shifted towards the body's colour around the neck.

    backend/.venv/bin/python splat/fuse_bust.py body.splat bust.ply fused.splat
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

SH_C0 = 0.28209479177387814


class G:
    """Gaussians as plain arrays: xyz, linear scale, quaternion (w, x, y, z), rgb 0..1, opacity 0..1."""

    def __init__(self, xyz, scale, quat, rgb, alpha):
        self.xyz, self.scale, self.quat, self.rgb, self.alpha = xyz, scale, quat, rgb, alpha

    def take(self, m):
        return G(self.xyz[m], self.scale[m], self.quat[m], self.rgb[m], self.alpha[m])

    def __len__(self):
        return len(self.xyz)


def load_splat(p: Path) -> G:  # antimatter15 .splat: 32 bytes per gaussian
    b = np.fromfile(p, np.uint8).reshape(-1, 32)
    f = b[:, :24].copy().view(np.float32)
    rgba = b[:, 24:28].astype(np.float32) / 255
    q = (b[:, 28:32].astype(np.float32) - 128) / 128
    return G(f[:, :3].astype(np.float64), f[:, 3:6], q / np.linalg.norm(q, axis=1, keepdims=True), rgba[:, :3], rgba[:, 3])


def load_ply(p: Path) -> G:
    raw = p.read_bytes()
    end = raw.index(b"end_header\n") + len(b"end_header\n")
    names = [l.split()[-1] for l in raw[:end].decode().splitlines() if l.startswith("property")]
    a = np.frombuffer(raw[end:], np.float32).reshape(-1, len(names))
    c = {n: a[:, i] for i, n in enumerate(names)}
    q = np.stack([c["rot_0"], c["rot_1"], c["rot_2"], c["rot_3"]], 1)
    rgb = np.clip(0.5 + SH_C0 * np.stack([c["f_dc_0"], c["f_dc_1"], c["f_dc_2"]], 1), 0, 1)
    return G(np.stack([c["x"], c["y"], c["z"]], 1).astype(np.float64),
             np.exp(np.stack([c["scale_0"], c["scale_1"], c["scale_2"]], 1)),
             q / np.linalg.norm(q, axis=1, keepdims=True), rgb, 1 / (1 + np.exp(-c["opacity"])))


def save_splat(g: G, p: Path) -> None:
    order = np.argsort(-(g.alpha * g.scale.prod(1)))  # big, opaque first, as .splat viewers expect
    out = np.zeros((len(g), 32), np.uint8)
    out[:, :24] = np.concatenate([g.xyz.astype(np.float32), g.scale.astype(np.float32)], 1).view(np.uint8)
    out[:, 24:27] = np.clip(g.rgb * 255, 0, 255)
    out[:, 27] = np.clip(g.alpha * 255, 0, 255)
    out[:, 28:32] = np.clip(g.quat * 128 + 128, 0, 255)
    out[order].tofile(p)


def quat_of(R: np.ndarray) -> np.ndarray:
    """Rotation matrix to (w, x, y, z), Shepperd's method: stays exact for half turns, where w = 0."""
    t = np.trace(R)
    if t > 0:
        s = 2 * np.sqrt(1 + t)
        q = [s / 4, (R[2, 1] - R[1, 2]) / s, (R[0, 2] - R[2, 0]) / s, (R[1, 0] - R[0, 1]) / s]
    else:
        i = int(np.argmax(np.diag(R)))
        j, k = (i + 1) % 3, (i + 2) % 3
        s = 2 * np.sqrt(1 + R[i, i] - R[j, j] - R[k, k])
        q = [0.0] * 4
        q[0], q[1 + i] = (R[k, j] - R[j, k]) / s, s / 4
        q[1 + j], q[1 + k] = (R[j, i] + R[i, j]) / s, (R[k, i] + R[i, k]) / s
    q = np.array(q)
    return q / np.linalg.norm(q)


def qmul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b.T
    return np.stack([w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
                     w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2], 1)


def transform(g: G, R: np.ndarray, s: float = 1.0, t=np.zeros(3)) -> G:
    return G(g.xyz @ R.T * s + t, g.scale * s, qmul(quat_of(R), g.quat), g.rgb, g.alpha)


def rot_y(deg: float) -> np.ndarray:
    a = np.radians(deg)
    return np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])


FLIP_X = np.diag([1.0, -1.0, -1.0])  # TripoSplat files are y-down: a half turn about x stands them up


def neck_and_top(g: G, head_frac: float = 0.45) -> tuple[float, float]:
    """Crown height and neck height (narrowest slice between head and shoulders) of the solid points."""
    p = g.xyz[g.alpha > 0.5]
    top, bot = np.percentile(p[:, 1], 99.7), np.percentile(p[:, 1], 0.3)
    ys = np.linspace(top - (top - bot) * head_frac, top - (top - bot) * 0.05, 60)
    widths = []
    for y in ys:
        sl = p[np.abs(p[:, 1] - y) < (top - bot) / 120]
        widths.append(np.ptp(np.percentile(sl[:, 0], [3, 97])) if len(sl) > 30 else np.inf)
    return top, float(ys[int(np.argmin(widths))])


def icp_scaled(src: np.ndarray, dst: np.ndarray, iters: int = 30) -> tuple[np.ndarray, float, np.ndarray, float]:
    """Umeyama-ICP: find R, s, t with s*R@src+t ~ dst. Returns the transform and the mean residual."""
    tree = cKDTree(dst)
    R, s, t = np.eye(3), 1.0, np.zeros(3)
    for _ in range(iters):
        cur = src @ R.T * s + t
        d, idx = tree.query(cur)
        keep = d < np.percentile(d, 80)  # trim the worst matches: hair and shoulders differ
        a, b = src[keep], dst[idx[keep]]
        ma, mb = a.mean(0), b.mean(0)
        A, B = a - ma, b - mb
        U, S, Vt = np.linalg.svd(B.T @ A / len(a))
        D = np.diag([1, 1, np.sign(np.linalg.det(U @ Vt))])
        R = U @ D @ Vt
        s = float(np.trace(np.diag(S) @ D) / (A ** 2).sum(1).mean())
        t = mb - s * R @ ma
    d, _ = tree.query(src @ R.T * s + t)
    return R, s, t, float(np.median(d))


def ramp(x: np.ndarray, x0: float, width: float) -> np.ndarray:
    """0 below x0 - width/2, 1 above x0 + width/2, smooth in between."""
    u = np.clip((x - x0) / width + 0.5, 0, 1)
    return u * u * (3 - 2 * u)


def main() -> None:
    body_p, bust_p, out_p = map(Path, sys.argv[1:4])
    body = transform(load_splat(body_p) if body_p.suffix == ".splat" else load_ply(body_p), FLIP_X)
    bust0 = transform(load_ply(bust_p) if bust_p.suffix == ".ply" else load_splat(bust_p), FLIP_X)
    report = {"body": len(body), "bust": len(bust0)}

    b_top, b_neck = neck_and_top(body, 0.25)
    head_b = body.xyz[(body.xyz[:, 1] > b_neck) & (body.alpha > 0.5)]
    best = None
    for yaw in (0, 90, 180, 270):  # the bust may face any axis: keep the turn ICP fits best
        bust = transform(bust0, rot_y(yaw))
        h_top, h_neck = neck_and_top(bust, 0.7)
        s0 = (b_top - b_neck) / (h_top - h_neck)
        hp = bust.xyz[(bust.xyz[:, 1] > h_neck) & (bust.alpha > 0.5)]
        t0 = np.array([head_b[:, 0].mean(), b_neck, head_b[:, 2].mean()]) - s0 * np.array([hp[:, 0].mean(), h_neck, hp[:, 2].mean()])
        sub = hp[np.random.default_rng(0).choice(len(hp), min(len(hp), 20000), replace=False)]
        R, s, t, res = icp_scaled(sub * s0 + t0, head_b)
        # the face side matters: a turned head fits a round skull almost as well, so also require
        # the bust's dense, detailed side (its face) to end up on the body's front (-z)
        moved = (hp * s0 + t0) @ R.T * s + t
        front = float(np.mean(moved[:, 2] < head_b[:, 2].mean()))
        score = res * (1.5 - front)
        report[f"yaw{yaw}"] = {"residual": round(res, 5), "front_share": round(front, 3), "scale": round(s0 * s, 4)}
        if best is None or score < best[0]:
            best = (score, yaw, R, s * s0, R @ t0 * s + t, h_neck)
    _, yaw, R, s, t, h_neck = best
    bust = transform(transform(bust0, rot_y(yaw)), R, s, t)
    report["chosen_yaw"] = yaw

    # head frame on the body: centre and radius of the skull above the neck
    centre = np.median(head_b, axis=0)
    radius = float(np.percentile(np.linalg.norm(head_b[:, [0, 2]] - centre[[0, 2]], axis=1), 90))
    # the face looks at -z: the bust gives the front half of the head, the body the back half, and
    # both overlap and cross-fade across the plane through the head centre
    neck_band, band = 0.2 * radius, 0.3 * radius

    # bust: keep the head (above the neck) but not the back of the skull or the ponytail
    up = ramp(bust.xyz[:, 1], b_neck + neck_band * 0.5, neck_band)
    w_bust = up * (1 - ramp(bust.xyz[:, 2], centre[2] + 0.15 * radius, band))
    # body: drop the face half of the head, keep the neck, the back of the skull and the ponytail
    up_b = ramp(body.xyz[:, 1], b_neck + neck_band * 0.5, neck_band)
    w_body = 1 - up_b * (1 - ramp(body.xyz[:, 2], centre[2] - 0.15 * radius, band))

    # colour: shift the bust's skin towards the body's neck so the cross-fade does not show
    ring_b = (np.abs(body.xyz[:, 1] - b_neck) < neck_band) & (body.alpha > 0.5)
    ring_h = (np.abs(bust.xyz[:, 1] - b_neck) < neck_band) & (bust.alpha > 0.5)
    if ring_b.sum() > 50 and ring_h.sum() > 50:
        shift = np.median(body.rgb[ring_b], 0) - np.median(bust.rgb[ring_h], 0)
        bust.rgb = np.clip(bust.rgb + 0.7 * shift, 0, 1)
        report["colour_shift"] = np.round(shift, 3).tolist()

    bust.alpha = bust.alpha * w_bust
    body.alpha = body.alpha * w_body
    keep_h, keep_b = bust.alpha > 0.01, body.alpha > 0.01
    fused = G(*(np.concatenate([getattr(body.take(keep_b), k), getattr(bust.take(keep_h), k)])
                for k in ("xyz", "scale", "quat", "rgb", "alpha")))
    fused = transform(fused, FLIP_X)  # back to the y-down convention of the inputs, so viewers treat both alike
    save_splat(fused, out_p)
    for name, part in (("body", body.take(keep_b)), ("bust", bust.take(keep_h))):  # parts, to inspect seams
        save_splat(transform(part, FLIP_X), out_p.with_name(f"{out_p.stem}_{name}.splat"))
    report.update(kept_body=int(keep_b.sum()), kept_bust=int(keep_h.sum()), fused=len(fused),
                  mb=round(out_p.stat().st_size / 1e6, 2))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

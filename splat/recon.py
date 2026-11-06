"""Turntable video -> Gaussian splat on this Mac: frames, subject masks, COLMAP poses, msplat training.

The camera in a generated turntable clip stays still while the person spins, so the background is
blacked out before feature matching: COLMAP then sees only the subject and solves it as a camera
orbiting a static person. Training runs on the Apple GPU through msplat (Metal).

    python splat/recon.py orbit.mp4 out_dir --frames 96 --iters 7000
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np


def extract(video: Path, out: Path, n: int) -> list[Path]:
    raw = out / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    total = int(subprocess.check_output(["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0",
                                         "-show_entries", "stream=nb_read_frames", "-of", "csv=p=0", str(video)]))
    step = max(1, total // n)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf", f"select='not(mod(n\\,{step}))'",
                    "-vsync", "vfr", str(raw / "f%04d.png")], check=True)
    return sorted(raw.glob("*.png"))[:n]


def mask(img: np.ndarray) -> np.ndarray:
    """Subject mask against a plain studio backdrop: distance from the local backdrop, then GrabCut.

    The backdrop has a vignette, so it is estimated per pixel: a first rough mask is inpainted away
    on a small copy, and the second pass measures each pixel against that smooth backdrop."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    border = np.concatenate([lab[:8].reshape(-1, 3), lab[:, :8].reshape(-1, 3), lab[:, -8:].reshape(-1, 3)])
    d = np.linalg.norm((lab - np.median(border, axis=0)) * [0.6, 1.4, 1.4], axis=2)
    small = cv2.resize(img, (w // 8, h // 8), interpolation=cv2.INTER_AREA)
    rough = cv2.dilate(cv2.resize((d > 14).astype(np.uint8), (w // 8, h // 8)), np.ones((5, 5), np.uint8))
    backdrop = cv2.resize(cv2.inpaint(small, rough * 255, 6, cv2.INPAINT_TELEA), (w, h), interpolation=cv2.INTER_CUBIC)
    bg = cv2.cvtColor(cv2.GaussianBlur(backdrop, (0, 0), 6), cv2.COLOR_BGR2LAB).astype(np.float32)
    d = np.linalg.norm((lab - bg) * [0.6, 1.4, 1.4], axis=2)  # chroma counts more than shading
    fg = (d > 12).astype(np.uint8)
    # floor shadow: grey (no chroma) and darker than the backdrop, only below the knees, where the
    # subject is blue jeans and white shoes (hair, also dark and grey, sits far above)
    chroma = np.linalg.norm(lab[..., 1:] - bg[..., 1:], axis=2)
    shadow = (chroma < 6) & (lab[..., 0] < bg[..., 0] - 4)
    shadow[: int(h * 0.7)] = False
    fg[shadow] = 0
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(fg)
    if n > 1:  # keep the largest blob: the person
        fg = (lbl == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))).astype(np.uint8)
    gc = np.where(fg > 0, cv2.GC_PR_FGD, cv2.GC_PR_BGD).astype(np.uint8)
    gc[cv2.erode(fg, np.ones((15, 15), np.uint8)) > 0] = cv2.GC_FGD
    gc[cv2.dilate(fg, np.ones((31, 31), np.uint8)) == 0] = cv2.GC_BGD
    bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(img, gc, None, bgm, fgm, 3, cv2.GC_INIT_WITH_MASK)
    m = np.isin(gc, (cv2.GC_FGD, cv2.GC_PR_FGD)).astype(np.uint8) * 255
    return cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))


def prepare(frames: list[Path], out: Path) -> Path:
    img_dir = out / "images"
    shutil.rmtree(img_dir, ignore_errors=True)
    img_dir.mkdir(parents=True)
    for i, f in enumerate(frames):
        img = cv2.imread(str(f))
        m = mask(img)
        img[m == 0] = 0  # black background: no features, and msplat trains against bg_color 0
        cv2.imwrite(str(img_dir / f"{i:04d}.png"), img)
        cv2.imwrite(str(out / "raw" / f"mask_{i:04d}.png"), m)
    return img_dir


def poses(out: Path) -> dict:
    import pycolmap
    db, sparse = out / "database.db", out / "sparse"
    db.unlink(missing_ok=True)
    shutil.rmtree(sparse, ignore_errors=True)
    sparse.mkdir()
    reader = pycolmap.ImageReaderOptions()
    reader.camera_model = "SIMPLE_PINHOLE"  # one focal: msplat assumes square pixels, and fx != fy broke training
    pycolmap.extract_features(db, out / "images", camera_mode=pycolmap.CameraMode.SINGLE, reader_options=reader)
    pycolmap.match_exhaustive(db)
    maps = pycolmap.incremental_mapping(db, out / "images", sparse)
    if not maps:
        raise RuntimeError("COLMAP could not register the frames")
    best = max(maps.values(), key=lambda r: r.num_reg_images())
    shutil.rmtree(sparse, ignore_errors=True)
    (sparse / "0").mkdir(parents=True)
    best.write(sparse / "0")
    return {"registered": best.num_reg_images(), "frames": len(list((out / "images").glob("*.png"))),
            "points": best.num_points3D(), "reproj_error": round(best.compute_mean_reprojection_error(), 3)}


def hull(out: Path, res: int = 200, agree: float = 0.9) -> dict:
    """Replace COLMAP's few thousand sparse points with the surface of the visual hull.

    A voxel stays when it falls inside the subject mask in at least `agree` of the views that see
    it; its colour comes from the nearest camera, which is usually the one facing that side. This
    gives msplat ~10^5 starting points on the body instead of a sparse cloud it fails to densify."""
    import pycolmap
    rec = pycolmap.Reconstruction(str(out / "sparse" / "0"))
    prm = next(iter(rec.cameras.values())).params
    fx, fy, cx, cy = (prm[0], prm[0], prm[1], prm[2]) if len(prm) == 3 else prm
    ims = sorted(rec.images.values(), key=lambda im: im.name)
    pts = np.array([p.xyz for p in rec.points3D.values()])
    lo, hi = np.percentile(pts, 0.5, axis=0), np.percentile(pts, 99.5, axis=0)
    pad = (hi - lo) * 0.2
    lo, hi = lo - pad, hi + pad
    step = (hi - lo).max() / res
    axes = [np.arange(lo[i], hi[i], step) for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1)
    P = grid.reshape(-1, 3)
    seen, inside = np.zeros(len(P), np.int16), np.zeros(len(P), np.int16)
    views = []
    for im in ims:
        w2c = im.cam_from_world() if callable(im.cam_from_world) else im.cam_from_world
        R, t = w2c.rotation.matrix(), w2c.translation
        m = cv2.imread(str(out / "raw" / f"mask_{im.name[:4]}.png"), cv2.IMREAD_GRAYSCALE)
        h, w = m.shape
        pc = P @ R.T + t
        z = np.maximum(pc[:, 2], 1e-6)
        u, v = (fx * pc[:, 0] / z + cx).astype(np.int32), (fy * pc[:, 1] / z + cy).astype(np.int32)
        ok = (pc[:, 2] > 0) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
        hit = np.zeros(len(P), bool)
        hit[ok] = m[v[ok], u[ok]] > 0
        seen += ok
        inside += hit
        views.append((R, t, im.name))
    occ = (inside >= agree * seen) & (seen >= 0.5 * len(ims))
    occ3 = occ.reshape(grid.shape[:3])
    core = occ3.copy()
    for ax in range(3):  # a voxel is on the surface when a face neighbour is empty
        for d in (1, -1):
            core &= np.roll(occ3, d, axis=ax)
    surf = P[(occ3 & ~core).reshape(-1)]
    best_z, colour = np.full(len(surf), np.inf), np.zeros((len(surf), 3), np.uint8)
    for R, t, name in views:
        img = cv2.imread(str(out / "images" / name))
        m = cv2.imread(str(out / "raw" / f"mask_{name[:4]}.png"), cv2.IMREAD_GRAYSCALE)
        h, w = m.shape
        pc = surf @ R.T + t
        z = np.maximum(pc[:, 2], 1e-6)
        u, v = (fx * pc[:, 0] / z + cx).astype(np.int32), (fy * pc[:, 1] / z + cy).astype(np.int32)
        ok = (pc[:, 2] > 0) & (u >= 0) & (u < w) & (v >= 0) & (v < h)
        ok[ok] &= m[v[ok], u[ok]] > 0
        near = ok & (pc[:, 2] < best_z)
        best_z[near] = pc[near, 2]
        colour[near] = img[v[near], u[near]][:, ::-1]
    shutil.copytree(out / "sparse" / "0", out / "sparse_colmap", dirs_exist_ok=True)
    rec.delete_all_points2D_and_points3D()
    for p, c in zip(surf, colour):
        rec.add_point3D(p, pycolmap.Track(), c)
    rec.write(str(out / "sparse" / "0"))
    return {"voxels": int(occ.sum()), "surface_points": len(surf), "voxel_m": round(float(step), 4)}


def train(out: Path, iters: int, grad: float = 2e-4) -> dict:
    import msplat
    ds = msplat.load_dataset(str(out))
    cfg = msplat.TrainingConfig()
    cfg.iterations, cfg.bg_color, cfg.sh_degree = iters, [0.0, 0.0, 0.0], 0  # SH 0: colour only, like Splat Human
    cfg.densify_grad_thresh = grad  # a small subject on black needs a lower bar than a full scene
    cfg.output = str(out / "msplat")
    t = msplat.GaussianTrainer(ds, cfg)
    t.train(lambda s: print(f"iter {t.iteration} · {t.splat_count} splats", flush=True), 1000)
    t.export_ply(str(out / "splat.ply"))
    m = t.evaluate() if ds.num_test else {}
    return {"splats": t.splat_count, "eval": str(m)[:200], "ply_mb": round((out / "splat.ply").stat().st_size / 1e6, 2)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--frames", type=int, default=96)
    ap.add_argument("--iters", type=int, default=7000)
    ap.add_argument("--grad", type=float, default=2e-4)
    ap.add_argument("--skip-to", choices=["poses", "train"])
    a = ap.parse_args()
    report, t0 = {}, time.time()
    if not a.skip_to:
        prepare(extract(a.video, a.out, a.frames), a.out)
        report["prep_s"] = round(time.time() - t0, 1)
    if a.skip_to != "train":
        t1 = time.time()
        report["colmap"] = poses(a.out)
        report["colmap_s"] = round(time.time() - t1, 1)
        print(report)
    t2 = time.time()
    report["train"] = train(a.out, a.iters, a.grad)
    report["train_s"] = round(time.time() - t2, 1)
    (a.out / "report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

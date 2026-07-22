#!/usr/bin/env python3
"""QA1 — render_sweep.py: renderiza el head.ply LAM en el barrido FIJO de
cameras.json y guarda un PNG por cámara en qa/out/sweep/<tag>/.

    python qa/render_sweep.py --ply .triage/lam_head_v7.ply --tag lam_v7

Determinista (rasterizador CPU): mismas cámaras → mismos píxeles.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raster import build_camera, load_cameras, render, scene_frame  # noqa: E402
from splat_io import load_ply  # noqa: E402


def render_sweep(ply: Path, tag: str, out_root: Path = None) -> Path:
    out_root = out_root or (Path(__file__).resolve().parent / "out" / "sweep" / tag)
    out_root.mkdir(parents=True, exist_ok=True)
    cams = load_cameras()
    g = load_ply(ply)
    center, radius = scene_frame(g)
    print(f"[sweep] {ply.name}: {len(g)} gaussianos · centro={center.round(3)} r90={radius:.3f}")

    for spec in cams["sweep"]:
        t0 = time.time()
        cam = build_camera(spec, cams, center, radius)
        rgb, cover = render(g, cam)
        Image.fromarray(rgb).save(out_root / f"{spec['name']}.png")
        np.save(out_root / f"{spec['name']}.cover.npy", cover.astype(np.float16))
        print(f"[sweep]   {spec['name']:14} cover={cover.mean():.3f} ({time.time()-t0:.1f}s)")
    print(f"[sweep] → {out_root}")
    return out_root


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ply", required=True, type=Path)
    ap.add_argument("--tag", required=True, help="etiqueta de salida (p.ej. lam_v7)")
    args = ap.parse_args()
    if not args.ply.exists():
        print(f"no existe: {args.ply}"); return 1
    render_sweep(args.ply, args.tag)
    return 0


if __name__ == "__main__":
    sys.exit(main())

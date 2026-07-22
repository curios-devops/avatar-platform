#!/usr/bin/env python3
"""QA1 — metrics.py: métricas deterministas sobre un sweep ya renderizado.

    python qa/metrics.py --tag lam_v7 --ref .triage/test_portrait.jpg

Emite qa/out/sweep/<tag>/metrics.json:
  - identidad: coseno ArcFace vs foto original, por ángulo (insightface/buffalo_l)
  - huecos:    % de píxeles de fondo visibles DENTRO de la silueta esperada
               (proxy de agujeros del splat), por ángulo, desde el cover buffer
  - costura:   ratio de gradiente en la banda del cuello vs el resto (solo B2;
               N/A mientras sea cabeza suelta sin cuerpo)

Sin GPU (onnxruntime CPU). El score de visión NO se calcula aquí: lo emite el
agente mirando la hoja (Principio 1 del harness).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raster import load_cameras  # noqa: E402

# ── identidad (ArcFace) ──────────────────────────────────────────────────────
_FACE_APP = None


def _face_app():
    global _FACE_APP
    if _FACE_APP is None:
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1, det_size=(512, 512))
        _FACE_APP = app
    return _FACE_APP


def _embed(img_rgb: np.ndarray):
    """Embedding ArcFace normalizado de la cara más grande, o None si no hay."""
    import cv2
    bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
    faces = _face_app().get(bgr)
    if not faces:
        return None
    f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
    return f.normed_embedding


def arcface_cos(render_rgb: np.ndarray, ref_emb) -> float | None:
    if ref_emb is None:
        return None
    e = _embed(render_rgb)
    if e is None:
        return None
    return float(np.dot(e, ref_emb))


# ── huecos (oclusión) ────────────────────────────────────────────────────────

def holes_pct(cover: np.ndarray, fg_thresh: float = 0.5) -> float:
    """% de huecos interiores: píxeles de baja cobertura DENTRO de la silueta
    esperada (relleno morfológico de la máscara de primer plano)."""
    from scipy import ndimage
    fg = cover >= fg_thresh
    if fg.sum() < 50:
        return 0.0
    filled = ndimage.binary_fill_holes(fg)
    interior_gap = filled & ~fg
    return 100.0 * float(interior_gap.sum()) / float(filled.sum())


# ── costura (solo B2) ────────────────────────────────────────────────────────

def seam_ratio(rgb: np.ndarray, neck_band: tuple | None) -> float | None:
    """Ratio gradiente(banda cuello) / gradiente(busto). >1.5 = costura visible.
    N/A (None) mientras no haya fusión cabeza-cuerpo (B2)."""
    if neck_band is None:
        return None
    import cv2
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0); gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1)
    grad = np.sqrt(gx * gx + gy * gy)
    y0, y1 = neck_band
    band = grad[y0:y1].mean()
    rest = grad[:y0].mean() + 1e-6
    return float(band / rest)


# ── driver ───────────────────────────────────────────────────────────────────

def compute(tag: str, ref: Path | None, out_root: Path | None = None) -> dict:
    out_root = out_root or (Path(__file__).resolve().parent / "out" / "sweep" / tag)
    cams = load_cameras()
    ref_emb = None
    if ref and ref.exists():
        ref_emb = _embed(np.asarray(Image.open(ref).convert("RGB")))
        if ref_emb is None:
            print(f"[metrics] ⚠️ no se detectó cara en la referencia {ref}")

    per_angle = []
    for spec in cams["sweep"]:
        name = spec["name"]
        png = out_root / f"{name}.png"
        cov = out_root / f"{name}.cover.npy"
        if not png.exists():
            continue
        rgb = np.asarray(Image.open(png).convert("RGB"))
        cover = np.load(cov).astype(np.float32) if cov.exists() else None
        per_angle.append({
            "name": name, "yaw": spec["yaw"], "pitch": spec["pitch"], "dist": spec["dist"],
            "arcface_cos": arcface_cos(rgb, ref_emb),
            "holes_pct": None if cover is None else round(holes_pct(cover), 3),
            "seam_ratio": None,  # B2
        })

    def _vals(key, filt=lambda a: True):
        return [a[key] for a in per_angle if a[key] is not None and filt(a)]

    front = next((a for a in per_angle if a["name"] == "front"), None)
    yaw45 = lambda a: abs(a["yaw"]) >= 45 and a["dist"] == "medio_cuerpo"
    within45 = lambda a: abs(a["yaw"]) <= 45 and a["dist"] == "medio_cuerpo"
    af = _vals("arcface_cos")
    summary = {
        "arcface_front": front["arcface_cos"] if front else None,
        "arcface_mean": round(float(np.mean(af)), 4) if af else None,
        "arcface_min": round(float(np.min(af)), 4) if af else None,
        "holes_max_within45": round(max(_vals("holes_pct", within45), default=0.0), 3),
        "holes_at_yaw45": round(max(_vals("holes_pct", yaw45), default=0.0), 3),
        "faces_detected": sum(1 for a in per_angle if a["arcface_cos"] is not None),
        "n_angles": len(per_angle),
    }
    result = {"tag": tag, "ref": str(ref) if ref else None,
              "summary": summary, "per_angle": per_angle}
    (out_root / "metrics.json").write_text(json.dumps(result, indent=2))
    print(f"[metrics] → {out_root/'metrics.json'}")
    print(f"[metrics] identidad front={summary['arcface_front']} "
          f"mean={summary['arcface_mean']} min={summary['arcface_min']} "
          f"| huecos≤45°={summary['holes_max_within45']}% "
          f"| caras={summary['faces_detected']}/{summary['n_angles']}")
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--ref", type=Path, default=Path(".triage/test_portrait.jpg"))
    args = ap.parse_args()
    compute(args.tag, args.ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())

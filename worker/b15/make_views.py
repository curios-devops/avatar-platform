#!/usr/bin/env python3
"""B1.5 Paso 1 — make_views.py: vistas sintéticas laterales + QC de identidad.

Genera vistas nuevas de la cabeza (yaw ±15/30/45/60, pitch ±10) ANTES de
reconstruir, para eliminar el estiramiento lateral del splat LAM de vista única.
Reutiliza el MultiViewGenerator del backend (Nano Banana 2 Lite vía Vertex
express) y añade el filtro de identidad ArcFace del harness.

    backend/.venv/bin/python worker/b15/make_views.py \
        --photo .triage/test_portrait.jpg --out qa/out/b15/views

Salida: <out>/<key>.jpg + <out>/views_meta.json (pose nominal por vista +
coseno ArcFace + válida sí/no). Criterio: ≥6 vistas válidas (coseno > 0.35).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "qa"))

# Ángulos B1.5 (yaw a pitch 0) + inclinaciones (pitch a yaw 0). Convención LAM:
# +yaw mira a su izquierda, +pitch mira arriba. Cubre ±45° real con margen ±60/±15.
VIEWS_B15 = [
    ("yaw-60", -60, 0), ("yaw-45", -45, 0), ("yaw-30", -30, 0), ("yaw-15", -15, 0),
    ("yaw+15", 15, 0), ("yaw+30", 30, 0), ("yaw+45", 45, 0), ("yaw+60", 60, 0),
    ("pitch-10", 0, -10), ("pitch+10", 0, 10),
]
IDENTITY_MIN = 0.35   # coseno ArcFace mínimo vs foto original (umbral del doc)
MIN_VALID = 6


def _extend_prompts():
    """El generador solo describe yaw ±30/60/90 y pitch ±15; añadir ±45/±15/±10."""
    from app.pipeline import multiview_generator as mv
    mv._YAW_DESCRIPTIONS.update({
        -45: "45 degree turn to the left, nose and one cheek visible",
         45: "45 degree turn to the right, nose and one cheek visible",
        -15: "slight 15 degree turn to the left",
         15: "slight 15 degree turn to the right",
    })
    mv._PITCH_DESCRIPTIONS.update({
        -10: "head tilted slightly downward, looking down",
         10: "head tilted slightly upward, looking up",
    })


async def _generate(photo: bytes) -> dict[str, bytes]:
    from app.pipeline.multiview_generator import MultiViewGenerator
    _extend_prompts()
    gen = MultiViewGenerator()

    def _on(key, jpeg, done, total):
        print(f"[views] {done}/{total} {key} {'ok' if jpeg else 'FAILED'}")

    return await gen.generate(photo, angles=VIEWS_B15, on_view=_on)


def _qc(views: dict[str, bytes], photo_path: Path, out: Path) -> dict:
    from metrics import _embed  # qa/metrics.py
    ref = _embed(np.asarray(Image.open(photo_path).convert("RGB")))
    if ref is None:
        raise SystemExit("no se detectó cara en la foto original — QC imposible")

    meta = {"identity_min": IDENTITY_MIN, "views": []}
    pose = {k: (y, p) for k, y, p in VIEWS_B15}
    n_valid = 0
    for key, jpeg in views.items():
        if key == "front":
            continue
        img = np.asarray(Image.open(_bio(jpeg)).convert("RGB"))
        emb = _embed(img)
        cos = float(np.dot(emb, ref)) if emb is not None else None
        valid = cos is not None and cos >= IDENTITY_MIN
        n_valid += int(valid)
        (out / f"{key}.jpg").write_bytes(jpeg)
        yaw, pitch = pose.get(key, (None, None))
        meta["views"].append({"key": key, "yaw": yaw, "pitch": pitch,
                              "arcface_cos": None if cos is None else round(cos, 4),
                              "valid": valid})
        print(f"[qc]   {key:9} cos={cos if cos is None else round(cos,3)} "
              f"{'VÁLIDA' if valid else 'descartada'}")

    # incluir la frontal original como vista de referencia (pose 0,0)
    (out / "front.jpg").write_bytes(views["front"])
    meta["n_valid"] = n_valid
    meta["ok"] = n_valid >= MIN_VALID
    (out / "views_meta.json").write_text(json.dumps(meta, indent=2))
    return meta


def _bio(b: bytes):
    import io
    return io.BytesIO(b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", type=Path, default=Path(".triage/test_portrait.jpg"))
    ap.add_argument("--out", type=Path, default=Path("qa/out/b15/views"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    photo = args.photo.read_bytes()
    views = asyncio.run(_generate(photo))
    print(f"[views] generadas {len(views)-1}/{len(VIEWS_B15)}")
    meta = _qc(views, args.photo, args.out)
    print(f"[qc] válidas {meta['n_valid']}/{len(VIEWS_B15)} → "
          f"{'✅ OK' if meta['ok'] else '❌ <6, insuficientes'}  ({args.out}/views_meta.json)")
    return 0 if meta["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())

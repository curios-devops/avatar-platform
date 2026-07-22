#!/usr/bin/env python3
"""QA1 — make_sheet.py: empaqueta UNA hoja PNG por ciclo de revisión.

    python qa/make_sheet.py --tag lam_v7 --ref .triage/test_portrait.jpg

Fila superior: referencia (foto original) + los 3 primeros planos de cara.
Rejilla inferior: barrido medio-cuerpo (yaw -45..+45, pitch ±10) con etiquetas.
Pie: métricas de metrics.json. Es la ÚNICA imagen que el agente mira para juzgar.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from raster import load_cameras  # noqa: E402

TILE = 220
PAD = 8
LABEL_H = 22
FOOTER_H = 96
BG = (18, 18, 20)
FG = (235, 235, 235)


def _font(sz=14):
    for p in ("/System/Library/Fonts/Helvetica.ttc",
              "/System/Library/Fonts/Supplemental/Arial.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default()


def _tile(img: Image.Image, label: str, sub: str = "") -> Image.Image:
    t = Image.new("RGB", (TILE, TILE + LABEL_H), BG)
    im = img.convert("RGB").copy()
    im.thumbnail((TILE, TILE))
    t.paste(im, ((TILE - im.width) // 2, (TILE - im.height) // 2))
    d = ImageDraw.Draw(t)
    d.text((4, TILE + 3), label, fill=FG, font=_font(13))
    if sub:
        w = d.textlength(sub, font=_font(12))
        d.text((TILE - w - 4, TILE + 4), sub, fill=(150, 200, 150), font=_font(12))
    return t


def build_sheet(tag: str, ref: Path | None, out: Path | None = None) -> Path:
    root = Path(__file__).resolve().parent / "out" / "sweep" / tag
    out = out or (root / "sheet.png")
    cams = load_cameras()
    metrics = {}
    mp = root / "metrics.json"
    if mp.exists():
        metrics = json.loads(mp.read_text())
    per = {a["name"]: a for a in metrics.get("per_angle", [])}

    def af_sub(name):
        a = per.get(name, {})
        v = a.get("arcface_cos")
        return f"id {v:.2f}" if v is not None else ""

    # fila superior: referencia + primeros planos
    top_names = ["cara-yaw-30", "cara-front", "cara-yaw+30"]
    top = []
    if ref and ref.exists():
        top.append(_tile(Image.open(ref), "FOTO ORIGINAL"))
    for n in top_names:
        p = root / f"{n}.png"
        if p.exists():
            top.append(_tile(Image.open(p), n, af_sub(n)))

    # rejilla inferior: medio cuerpo en orden de yaw, luego pitch
    order = ["yaw-45", "yaw-30", "yaw-15", "front", "yaw+15", "yaw+30", "yaw+45",
             "pitch-10", "pitch+10"]
    bottom = []
    for n in order:
        p = root / f"{n}.png"
        if p.exists():
            a = per.get(n, {})
            sub = af_sub(n)
            h = a.get("holes_pct")
            if h is not None:
                sub = (sub + f"  h{h:.1f}%").strip()
            bottom.append(_tile(Image.open(p), n, sub))

    cols = max(len(top), 7)
    tw = TILE + LABEL_H
    W = cols * TILE + (cols + 1) * PAD
    rows_bottom = (len(bottom) + cols - 1) // cols
    H = PAD + tw + PAD + rows_bottom * (tw + PAD) + FOOTER_H

    sheet = Image.new("RGB", (W, H), BG)
    for i, t in enumerate(top):
        sheet.paste(t, (PAD + i * (TILE + PAD), PAD))
    y0 = PAD + tw + PAD
    for i, t in enumerate(bottom):
        r, c = divmod(i, cols)
        sheet.paste(t, (PAD + c * (TILE + PAD), y0 + r * (tw + PAD)))

    # pie con métricas
    d = ImageDraw.Draw(sheet)
    s = metrics.get("summary", {})
    lines = [
        f"tag={tag}   gaussianos: head.ply LAM   ref={ref.name if ref else '—'}",
        f"IDENTIDAD ArcFace  front={s.get('arcface_front')}  mean={s.get('arcface_mean')}  "
        f"min={s.get('arcface_min')}  caras={s.get('faces_detected')}/{s.get('n_angles')}",
        f"HUECOS  max(|yaw|<=45)={s.get('holes_max_within45')}%   @yaw45={s.get('holes_at_yaw45')}%"
        f"   COSTURA=N/A (sin cuerpo, B2 pendiente)",
    ]
    for i, ln in enumerate(lines):
        d.text((PAD, H - FOOTER_H + 6 + i * 22), ln, fill=FG, font=_font(15))
    sheet.save(out)
    print(f"[sheet] → {out}  ({W}x{H})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--ref", type=Path, default=Path(".triage/test_portrait.jpg"))
    args = ap.parse_args()
    build_sheet(args.tag, args.ref)
    return 0


if __name__ == "__main__":
    sys.exit(main())

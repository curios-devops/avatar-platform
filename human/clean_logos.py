"""Plain copies of the MakeHuman tees that print the MakeHuman mark (a third-party brand) on the chest.

The CC0 assets stay untouched; this writes assets_src/nologo/<garment>_diffuse.png, which the renderer
(frontend/src/human/engine.ts, NOLOGO) loads instead of the original diffuse texture.

For each logo: inside a box around it, pixels that differ from the fabric's median colour are the print;
they are dilated, feathered and replaced by plain fabric from the same panel (a shifted copy, tone-matched).
Deterministic, CPU only, ~2 s.

    .venv/bin/python clean_logos.py           # writes assets_src/nologo/
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).parent
CLOTHES = HERE / "assets_src" / "makehuman_system_assets_cc0" / "clothes"
OUT = HERE / "assets_src" / "nologo"

# garment -> [(box x0, y0, x1, y1 in the 2048 px texture, source shift dx, dy, colour threshold)]
LOGOS: dict[str, list[tuple[int, int, int, int, int, int, int]]] = {
    "female_casualsuit01": [(1455, 315, 1790, 630, -330, 0, 40)],
    "female_casualsuit02": [(1455, 315, 1790, 630, -330, 0, 40)],
    "male_casualsuit02": [(1012, 210, 1278, 484, 0, 290, 40)],
    "male_casualsuit04": [(1012, 208, 1276, 474, 0, 270, 40)],
    # white tee: the "MAKE(H)UMAN" wordmark on the front, a small one on the back and a sliver on a sleeve
    "male_casualsuit06": [(905, 245, 1280, 420, 0, 210, 26), (400, 235, 600, 335, 0, 160, 26), (1505, 315, 1545, 360, 0, 70, 26)],
}


def clean(src: Path, logos: list[tuple[int, int, int, int, int, int, int]]) -> Image.Image:
    img = np.asarray(Image.open(src).convert("RGB")).astype(np.float32)
    out = img.copy()
    for x0, y0, x1, y1, dx, dy, thr in logos:
        box = img[y0:y1, x0:x1]
        border = np.concatenate([box[0], box[-1], box[:, 0], box[:, -1]])
        ref = np.median(border, 0)
        print_px = (np.linalg.norm(box - ref, axis=-1) > thr).astype(np.uint8) * 255
        m = Image.fromarray(print_px).filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(3))
        m = np.asarray(m).astype(np.float32)[..., None] / 255
        patch = img[y0 + dy:y1 + dy, x0 + dx:x1 + dx]
        pborder = np.concatenate([patch[0], patch[-1], patch[:, 0], patch[:, -1]])
        patch = np.clip(patch + (ref - np.median(pborder, 0)), 0, 255)
        out[y0:y1, x0:x1] = box * (1 - m) + patch * m
    return Image.fromarray(out.round().astype(np.uint8))


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for garment, logos in LOGOS.items():
        src = CLOTHES / garment / f"{garment}_diffuse.png"
        clean(src, logos).save(OUT / src.name, optimize=False)
        print("plain", OUT / src.name)


if __name__ == "__main__":
    main()

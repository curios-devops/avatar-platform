"""MEYA backgrounds, step 2: the generated scenes (gen.sh) become the web's assets, plus one made in code.

    backend/.venv/bin/python lab/backgrounds/publish.py <png_dir> <web_public_backgrounds_dir> <presets.json>

Each scene: <id>.webp at 1280x960 (q 82) for compositing, and <id>-thumb.webp at 144x108 for the picker.
"meya-warm" and "studio-grey" are drawn here (a warm gradient; a photo studio's grey backdrop with a soft light
behind the head), no model needed. presets.json lists what is published, by category and in picker order, for the
web to read: [{"id": "new", "scenes": [...]}, ...]; a category with nothing published is left out.
Light work, seconds.
"""
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageFilter

W, H = 1280, 960
THUMB = (144, 108)


def meya_warm() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    # a warm light from the upper left fading to cream: MEYA's orange, never loud behind a face
    d = np.clip(np.hypot((x - W * 0.18) / W, (y - H * 0.1) / H) / 1.15, 0, 1)[..., None]
    a, b = np.array([235, 122, 84], np.float32), np.array([246, 236, 222], np.float32)
    img = a * (1 - d) ** 1.4 + b * (1 - (1 - d) ** 1.4)
    img += np.random.default_rng(7).normal(0, 2.2, img.shape)  # grain, so it never bands
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))


def studio_grey() -> Image.Image:
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    # a seamless paper backdrop: lighter behind the head, falling off to the edges, like a lit portrait studio
    d = np.clip(np.hypot((x - W / 2) / (W * 0.62), (y - H * 0.38) / (H * 0.75)), 0, 1.4)[..., None]
    light, dark = np.array([196, 196, 192], np.float32), np.array([92, 93, 92], np.float32)
    t = np.clip(d / 1.2, 0, 1) ** 1.5
    img = light * (1 - t) + dark * t
    img += np.random.default_rng(11).normal(0, 1.8, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.6))


# The picker's categories, Meet-style, in order; a scene shows up once its image is published.
CATEGORIES = [
    ("new", ["snow-chalet", "snowy-living", "christmas-hearth"]),
    ("pro", ["shelves-plants", "tech-desk", "study-library"]),
    ("home", ["home-sofa", "home-desk", "pool-terrace"]),
    ("places", ["camping", "sunset"]),
    ("fantasy", ["space-station", "mars", "moon"]),
    ("plain", ["studio-grey", "meya-warm"]),
]


def publish(img: Image.Image, out: pathlib.Path, name: str):
    img = img.convert("RGB")
    if img.size != (W, H):
        s = max(W / img.width, H / img.height)
        img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)
        l, t = (img.width - W) // 2, (img.height - H) // 2
        img = img.crop((l, t, l + W, t + H))
    img.save(out / f"{name}.webp", "WEBP", quality=82, method=6)
    img.resize(THUMB, Image.LANCZOS).save(out / f"{name}-thumb.webp", "WEBP", quality=80, method=6)
    print(name, (out / f"{name}.webp").stat().st_size // 1024, "KB")


def main():
    src, out, manifest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    for png in sorted(src.glob("*.png")):
        publish(Image.open(png), out, png.stem)
    publish(meya_warm(), out, "meya-warm")
    publish(studio_grey(), out, "studio-grey")
    done = {p.stem for p in out.glob("*.webp") if not p.stem.endswith("-thumb")}
    groups = [{"id": cat, "scenes": [i for i in ids if i in done]} for cat, ids in CATEGORIES]
    groups = [g for g in groups if g["scenes"]]
    manifest.write_text(json.dumps(groups, indent=2) + "\n")
    known = {i for _, ids in CATEGORIES for i in ids}
    print("presets:", {g["id"]: g["scenes"] for g in groups}, "| not in a category:", sorted(done - known) or "none")


if __name__ == "__main__":
    main()

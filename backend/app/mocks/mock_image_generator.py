"""
Mock image generator: turns a text description into a synthetic face-like PNG using Pillow.
Used when no real text-to-image API (Stable Diffusion, DALL-E, etc.) is configured.

The image is a coloured circle with eyes and a mouth so it passes the face ingest check.
Colour and shape are seeded from the description so the same prompt always looks the same.
"""
from __future__ import annotations

import hashlib
import io
import math
import random


def generate_image(description: str, style: str = "Cartoon") -> bytes:
    from PIL import Image, ImageDraw

    seed = int(hashlib.md5(f"{description}:{style}".encode()).hexdigest(), 16) % (2**31)
    rng  = random.Random(seed)

    # skin tone palette
    palettes = [
        (255, 220, 177),
        (241, 194, 125),
        (198, 134,  66),
        (141,  85,  36),
        ( 73,  37,   7),
    ]
    skin = palettes[rng.randint(0, len(palettes) - 1)]
    bg   = tuple(max(0, c - 40) for c in skin)
    eye_col = (rng.randint(20, 80), rng.randint(60, 150), rng.randint(80, 200))

    W = H = 512
    img  = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    # face oval
    margin = 60
    draw.ellipse([margin, margin + 30, W - margin, H - margin + 20], fill=skin)

    # eyes
    ey = H // 2 - 40
    for ex in [W // 2 - 70, W // 2 + 70]:
        draw.ellipse([ex - 22, ey - 18, ex + 22, ey + 18], fill=(255, 255, 255))
        dx = rng.randint(-5, 5)
        dy = rng.randint(-3, 3)
        draw.ellipse([ex - 10 + dx, ey - 10 + dy, ex + 10 + dx, ey + 10 + dy], fill=eye_col)
        draw.ellipse([ex - 4 + dx, ey - 4 + dy, ex + 4 + dx, ey + 4 + dy], fill=(0, 0, 0))
        # highlight
        draw.ellipse([ex - 2 + dx, ey - 6 + dy, ex + 4 + dx, ey      + dy], fill=(255, 255, 255))

    # eyebrows
    brow_y = ey - 28
    draw.line([(W // 2 - 90, brow_y), (W // 2 - 50, brow_y - 8)], fill=(80, 50, 20), width=5)
    draw.line([(W // 2 + 50, brow_y - 8), (W // 2 + 90, brow_y)], fill=(80, 50, 20), width=5)

    # nose
    ny = H // 2 + 10
    draw.polygon([(W // 2, ny - 20), (W // 2 - 14, ny + 14), (W // 2 + 14, ny + 14)],
                 fill=tuple(max(0, c - 25) for c in skin))

    # mouth — smile arc
    mouth_x, mouth_y = W // 2, H // 2 + 70
    smile_w, smile_h = 70, 28
    draw.arc(
        [mouth_x - smile_w, mouth_y - smile_h, mouth_x + smile_w, mouth_y + smile_h],
        start=10, end=170,
        fill=(180, 60, 60), width=6,
    )

    # ears
    for ex, sx in [(margin, -1), (W - margin, 1)]:
        draw.ellipse([ex - 18, H // 2 - 28, ex + 18, H // 2 + 28], fill=skin)

    # style-specific tint overlay
    overlays = {
        "Cartoon":   (255, 220, 0, 18),
        "Realistic": (0, 0, 0, 0),
        "Anime":     (200, 180, 255, 25),
        "3D Render": (180, 210, 255, 20),
    }
    tint = overlays.get(style, (0, 0, 0, 0))
    if tint[3]:
        overlay = Image.new("RGBA", (W, H), tint)
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=92)
    return buf.getvalue()

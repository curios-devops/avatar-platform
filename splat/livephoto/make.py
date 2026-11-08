"""Live photo: one image -> a camera-facing Gaussian splat with ±20° of parallax (MEYA landing, character cards).

    .venv/bin/python make.py <image> <out_stem> [--height 1.75] [--relief 0.3] [--max-side 768]

Our own take on the single-image idea (SHARP-like), not a copy, built only from permissive parts:
  - depth: Depth Anything V2 Small (Apache-2.0), relative disparity;
  - subject matte: Otsu split of that same disparity, gated by DETR panoptic's person mask (Apache-2.0);
  - one Gaussian per subject pixel, back-projected with a pinhole camera.

There is no inpainting: what the photo does not show stays empty, so past ~±30° the sides open up.
Writes <out_stem>.splat (32 B per Gaussian) and <out_stem>.spz (SPZ v2, gzip) plus <out_stem>.json.
Subject centred on the origin, y up, facing +Z, scaled so the image height at the subject is --height metres.
"""
import argparse, gzip, json, pathlib, struct, time

import numpy as np
import torch
from PIL import Image
from transformers import AutoImageProcessor, AutoModelForDepthEstimation

DEV = "mps" if torch.backends.mps.is_available() else "cpu"
SH_C0 = 0.28209479177387814


def depth_map(img: Image.Image) -> np.ndarray:
    proc = AutoImageProcessor.from_pretrained("depth-anything/Depth-Anything-V2-Small-hf")
    model = AutoModelForDepthEstimation.from_pretrained("depth-anything/Depth-Anything-V2-Small-hf").to(DEV).eval()
    with torch.no_grad():
        out = model(**proc(images=img, return_tensors="pt").to(DEV)).predicted_depth
    out = torch.nn.functional.interpolate(out[:, None], size=img.size[::-1], mode="bicubic", align_corners=False)
    return out[0, 0].float().cpu().numpy()  # relative disparity: larger = nearer


def person_mask(img: Image.Image) -> np.ndarray:
    """Coarse 'person' region from DETR panoptic (Apache-2.0, native transformers): keeps the floor and props
    that sit as near as the subject out of the matte. Its edges are blocky, so it only gates the depth matte."""
    from transformers import DetrForSegmentation, DetrImageProcessor
    proc = DetrImageProcessor.from_pretrained("facebook/detr-resnet-50-panoptic")
    model = DetrForSegmentation.from_pretrained("facebook/detr-resnet-50-panoptic").eval()
    with torch.no_grad():
        out = model(**proc(images=img, return_tensors="pt"))
    seg = proc.post_process_panoptic_segmentation(out, target_sizes=[img.size[::-1]], label_ids_to_fuse=set())[0]
    person = [s["id"] for s in seg["segments_info"] if model.config.id2label[s["label_id"]] == "person"]
    m = np.isin(seg["segmentation"].numpy(), person).astype(np.float32)
    if not person:
        return np.ones_like(m)
    # grow by ~2 % of the height so hair and fingertips the blocky mask misses stay in
    k = max(3, int(0.02 * m.shape[0]))
    t = torch.from_numpy(m)[None, None]
    return torch.nn.functional.max_pool2d(t, 2 * k + 1, 1, k)[0, 0].numpy()


def matte(disp: np.ndarray, gate: np.ndarray, soft=0.04) -> np.ndarray:
    """Subject = the near mode of the disparity histogram (Otsu split, inside the person gate), feathered
    over ±soft of the range."""
    d = (disp - disp.min()) / (disp.max() - disp.min())
    hist, edges = np.histogram(d, 256, (0, 1))
    p = hist / hist.sum(); w0 = np.cumsum(p); mu = np.cumsum(p * edges[:-1]); mt = mu[-1]
    between = (mt * w0 - mu) ** 2 / np.maximum(w0 * (1 - w0), 1e-9)
    t = edges[np.argmax(between)]
    return np.clip((d - t) / (2 * soft) + 0.5, 0, 1) * gate


def gaussians(img, disp, alpha, height, relief):
    h, w = alpha.shape
    # half-matted rim pixels carry backdrop depth and colour: from the side they float behind the subject as streaks
    keep = alpha > 0.6
    d = disp[keep]
    lo, hi = np.percentile(d, 2), np.percentile(d, 98)
    dn = np.clip((disp - lo) / max(hi - lo, 1e-6), 0, 1)
    s = height / h                                   # metres per pixel at the subject
    depth = relief * (dn - 0.5)                      # metres toward the camera (+Z), subject centred on 0
    # a pixel whose neighbour sits much nearer or farther (cheek, shoulder, hair outline) gets a deeper Gaussian,
    # so the side views see a wall instead of a crack
    gy, gx = np.gradient(depth)
    grad = np.hypot(gx, gy)
    v, u = np.nonzero(keep)
    rgb = np.asarray(img.convert("RGB"), np.float32)[v, u] / 255.0
    ys = v[keep[v, u]]
    cy = (ys.min() + ys.max()) / 2
    pos = np.stack([(u - w / 2) * s, -(v - cy) * s, depth[v, u]], 1).astype(np.float32)
    sig = 0.65 * s
    scale = np.stack([np.full(len(u), sig), np.full(len(u), sig), np.clip(0.5 * grad[v, u], sig, 2.5 * sig)], 1).astype(np.float32)
    a = np.clip((alpha[v, u] - 0.6) / 0.3, 0, 0.99).astype(np.float32)
    return pos, scale, rgb.astype(np.float32), a


def write_splat(path, pos, scale, rgb, a):
    n = len(pos)
    buf = np.zeros(n, dtype=[("p", "<f4", 3), ("s", "<f4", 3), ("c", "u1", 4), ("r", "u1", 4)])
    buf["p"], buf["s"] = pos, scale
    buf["c"] = np.clip(np.concatenate([rgb, a[:, None]], 1) * 255, 0, 255).round()
    buf["r"] = [255, 128, 128, 128]                  # identity quaternion (w, x, y, z) -> (q*128+128)
    path.write_bytes(buf.tobytes())


def write_spz(path, pos, scale, rgb, a, frac_bits=12):
    """SPZ v2: gzip(header, positions 24-bit fixed point, alphas, colours, log-scales, rotations), SH degree 0."""
    n = len(pos)
    fx = np.round(pos.astype(np.float64) * (1 << frac_bits)).astype(np.int32)
    p24 = np.stack([fx & 0xFF, (fx >> 8) & 0xFF, (fx >> 16) & 0xFF], -1).astype(np.uint8).reshape(n, 9)
    alphas = np.clip(a * 255, 0, 255).round().astype(np.uint8)
    dc = (rgb - 0.5) / SH_C0
    colors = np.clip((dc * 0.15 + 0.5) * 255, 0, 255).round().astype(np.uint8)
    scales = np.clip((np.log(scale) + 10) * 16, 0, 255).round().astype(np.uint8)
    rots = np.full((n, 3), 128, np.uint8)            # xyz of the identity quaternion, (x * 127.5 + 127.5)
    header = struct.pack("<IIIBBBB", 0x5053474E, 2, n, 0, frac_bits, 0, 0)
    body = header + p24.tobytes() + alphas.tobytes() + colors.tobytes() + scales.tobytes() + rots.tobytes()
    path.write_bytes(gzip.compress(body, 9))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image"); ap.add_argument("out")
    ap.add_argument("--height", type=float, default=1.75, help="image height at the subject, metres")
    ap.add_argument("--relief", type=float, default=0.3, help="front-to-back depth of the subject, metres")
    ap.add_argument("--max-side", type=int, default=768)
    args = ap.parse_args()
    t0 = time.time()
    img = Image.open(args.image).convert("RGB")
    img.thumbnail((args.max_side, args.max_side), Image.LANCZOS)
    disp = depth_map(img); t_depth = time.time() - t0
    alpha = matte(disp, person_mask(img)); t_matte = time.time() - t0 - t_depth
    pos, scale, rgb, a = gaussians(img, disp, alpha, args.height, args.relief)
    out = pathlib.Path(args.out); out.parent.mkdir(parents=True, exist_ok=True)
    write_splat(out.with_suffix(".splat"), pos, scale, rgb, a)
    write_spz(out.with_suffix(".spz"), pos, scale, rgb, a)
    Image.fromarray((alpha * 255).astype(np.uint8)).save(out.with_name(out.name + "_matte.png"))
    dn = (disp - disp.min()) / (disp.max() - disp.min())
    Image.fromarray((dn * 255).astype(np.uint8)).save(out.with_name(out.name + "_depth.png"))
    info = {"image": args.image, "size": img.size, "gaussians": len(pos), "device": DEV,
            "depth_s": round(t_depth, 1), "matte_s": round(t_matte, 1), "total_s": round(time.time() - t0, 1),
            "splat_mb": round(out.with_suffix(".splat").stat().st_size / 1e6, 2),
            "spz_mb": round(out.with_suffix(".spz").stat().st_size / 1e6, 2)}
    out.with_suffix(".json").write_text(json.dumps(info, indent=1))
    print(json.dumps(info))


if __name__ == "__main__":
    main()

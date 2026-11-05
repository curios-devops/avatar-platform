"""Twin mode: fit the Anny face to one photo and project the photo onto the skin texture.

1. Correspondence (once, cached): render the neutral Anny head, run MediaPipe on the render and keep, for each
   of the 468 face landmarks, the mesh triangle and barycentric coordinates under it.
2. Fit: optimize Anny's facial local changes + a few phenotypes + a weak-perspective camera so those surface
   points land on the photo's landmarks (Anny is differentiable, so this is plain Adam on CPU).
3. Texture: rasterize the fitted mesh in UV space, project every texel into the photo, keep the visible,
   camera-facing ones inside the face oval, and blend them over a base skin recoloured to the photo's tone.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw, ImageFilter

import baker
from baker import ASSETS, R, Shape, models

HERE = Path(__file__).parent
OUT = HERE / "out" / "twin"
OUT.mkdir(parents=True, exist_ok=True)
BACKEND_PY = HERE.parent / "backend" / ".venv" / "bin" / "python"
FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176,
             149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
BASE_SKIN = "makehuman_system_assets_cc0/skins/young_caucasian_female/young_lightskinned_female_diffuse.png"


def landmarks(*paths: Path) -> dict[str, np.ndarray | None]:
    out = subprocess.run([str(BACKEND_PY), str(HERE / "landmarks.py"), *map(str, paths)], capture_output=True, text=True, check=True)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    return {k: (np.array(v) if v else None) for k, v in data.items()}


# --------------------------------------------------------------------------------------------- raster


def raster(xy: np.ndarray, z: np.ndarray, w: int, h: int):
    """Z-buffer rasterizer. xy (n,3,2) pixel coords, z (n,3) depth (bigger = closer).
    Returns face id (h,w) with -1 where empty, and barycentric coordinates (h,w,3)."""
    fid = np.full((h, w), -1, np.int32)
    bary = np.zeros((h, w, 3), np.float32)
    zbuf = np.full((h, w), -np.inf, np.float32)
    lo = np.floor(xy.min(1)).astype(int)
    hi = np.ceil(xy.max(1)).astype(int)
    for i in range(len(xy)):
        x0, y0 = max(lo[i, 0], 0), max(lo[i, 1], 0)
        x1, y1 = min(hi[i, 0], w - 1), min(hi[i, 1], h - 1)
        if x0 > x1 or y0 > y1:
            continue
        (ax, ay), (bx, by), (cx, cy) = xy[i]
        den = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
        if abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        l0 = ((by - cy) * (gx - cx) + (cx - bx) * (gy - cy)) / den
        l1 = ((cy - ay) * (gx - cx) + (ax - cx) * (gy - cy)) / den
        l2 = 1 - l0 - l1
        inside = (l0 >= -1e-4) & (l1 >= -1e-4) & (l2 >= -1e-4)
        if not inside.any():
            continue
        depth = l0 * z[i, 0] + l1 * z[i, 1] + l2 * z[i, 2]
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (depth > sub)
        sub[win] = depth[win]
        fid[y0:y1 + 1, x0:x1 + 1][win] = i
        bary[y0:y1 + 1, x0:x1 + 1][win] = np.stack([l0, l1, l2], -1)[win]
    return fid, bary


def _body():
    full, body = models()
    faces = body.faces.numpy().astype(np.int64)
    bmvi = body.base_mesh_vertex_indices.numpy()
    labels = list(full.bone_labels)
    vbi, vbw = full.vertex_bone_indices.numpy(), full.vertex_bone_weights.numpy()
    eye_w = np.where(np.isin(vbi, [labels.index("eye.L"), labels.index("eye.R")]), vbw, 0).sum(1)
    keep = (bmvi[faces] < 13380).all(1) & ~(eye_w[bmvi[faces]] > 0.5).all(1)
    return full, body, faces, bmvi, keep


def _shape_verts(full, phenotype: dict, local: dict, grad=False):
    ph = {k: (v if torch.is_tensor(v) else torch.tensor(float(v))).reshape(1) for k, v in phenotype.items()}
    lc = {k: (v if torch.is_tensor(v) else torch.tensor(float(v))).reshape(1) for k, v in local.items()}
    ctx = torch.enable_grad() if grad else torch.no_grad()
    with ctx:
        out = full(phenotype_kwargs=ph or None, local_changes_kwargs=lc or None)
    v = out["rest_vertices"][0]
    return v @ torch.tensor(R.T, dtype=v.dtype)  # glTF axes: y up, z front


def _texture(path: str, size: int) -> np.ndarray:
    img = Image.open(ASSETS / path).convert("RGB").resize((size, size), Image.LANCZOS)
    return np.asarray(img).astype(np.float32) / 255


# --------------------------------------------------------------------------------------------- correspondence


def correspondence() -> dict:
    cache = OUT / "correspondence.npz"
    if cache.exists():
        d = np.load(cache)
        return {"lm": d["lm"], "face": d["face"], "bary": d["bary"]}
    full, body, faces, bmvi, keep = _body()
    v = _shape_verts(full, {}, {}).numpy()[bmvi]
    head = v[faces[keep]].reshape(-1, 3)
    top = head[:, 1].max()
    center = np.array([0.0, top - 0.13, 0.0])
    size, scale = 768, 768 / 0.30
    to_px = lambda p: np.stack([(p[..., 0] - center[0]) * scale + size / 2, size / 2 - (p[..., 1] - center[1]) * scale], -1)  # noqa: E731
    tri = faces[keep]
    xy, z = to_px(v[tri]), v[tri][..., 2]
    fid, bary = raster(xy, z, size, size)
    # shade with the base skin so MediaPipe sees a face
    uv = body.texture_coordinates.numpy()
    tuv = body.face_texture_coordinate_indices.numpy()[keep]
    tex = _texture(BASE_SKIN, 1024)
    img = np.full((size, size, 3), 0.55, np.float32)
    m = fid >= 0
    f = fid[m]
    uvp = (bary[m][:, :, None] * uv[tuv[f]]).sum(1)
    col = tex[np.clip(((1 - uvp[:, 1]) * 1023).astype(int), 0, 1023), np.clip((uvp[:, 0] * 1023).astype(int), 0, 1023)]
    n = np.cross(v[tri[:, 1]] - v[tri[:, 0]], v[tri[:, 2]] - v[tri[:, 0]])
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-12
    light = np.clip(n[f] @ (np.array([0.3, 0.4, 1.0]) / np.linalg.norm([0.3, 0.4, 1.0])), 0, 1)
    img[m] = col * (0.35 + 0.65 * light[:, None])
    path = OUT / "anny_front.png"
    Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).save(path)
    lms = landmarks(path)[str(path)]
    if lms is None:
        raise RuntimeError("MediaPipe found no face on the Anny render")
    ids, face_ids, barys = [], [], []
    for i, (x, y, _) in enumerate(lms[:468]):
        xi, yi = int(x), int(y)
        if 0 <= xi < size and 0 <= yi < size and fid[yi, xi] >= 0:
            ids.append(i)
            face_ids.append(np.nonzero(keep)[0][fid[yi, xi]])
            barys.append(bary[yi, xi])
    np.savez(cache, lm=np.array(ids), face=np.array(face_ids), bary=np.array(barys))
    return {"lm": np.array(ids), "face": np.array(face_ids), "bary": np.array(barys)}


# --------------------------------------------------------------------------------------------- fit


def fit(photo: Path, face_changes: list[str], steps: int = 120) -> dict:
    import roma

    t0 = time.time()
    corr = correspondence()
    target = landmarks(photo)[str(photo)]
    if target is None:
        raise ValueError("no face found in the photo")
    full, body, faces, bmvi, keep = _body()
    lm_ids = corr["lm"]
    tgt = torch.tensor(target[lm_ids, :2], dtype=torch.float32)
    weight = torch.tensor([0.4 if i in FACE_OVAL else 1.0 for i in lm_ids])
    iod = float(np.linalg.norm(target[33, :2] - target[263, :2]))
    tri = torch.tensor(faces[corr["face"]])
    bary = torch.tensor(corr["bary"], dtype=torch.float32)
    bm = torch.tensor(bmvi)

    pheno_keys = ["gender", "age", "weight", "african", "asian", "caucasian"]
    p_raw = torch.zeros(len(pheno_keys), requires_grad=True)
    l_raw = torch.zeros(len(face_changes), requires_grad=True)
    rot = torch.zeros(3, requires_grad=True)
    log_s = torch.tensor(float(np.log(iod / 0.062)), requires_grad=True)  # ~62 mm between the outer eye corners
    trans = torch.tensor(target[lm_ids, :2].mean(0), dtype=torch.float32, requires_grad=True)

    def project(v):
        pts = (v[bm][tri] * bary[..., None]).sum(1)
        pts = pts - pts.mean(0, keepdim=True).detach()
        rp = pts @ roma.rotvec_to_rotmat(rot).T
        s = torch.exp(log_s)
        return torch.stack([rp[:, 0] * s, -rp[:, 1] * s], 1) + trans, rp

    def shape():
        ph = {k: torch.sigmoid(p_raw[i]) for i, k in enumerate(pheno_keys)}
        lc = {k: torch.tanh(l_raw[i]) for i, k in enumerate(face_changes)}
        return ph, lc

    history = []
    # stage 0 only moves the camera, so the neutral body is evaluated once; stage 1 converges by ~80-100 steps
    # (2026-11-05: 1.121 % at step 80 vs 1.122 % at 220), and each step is a full Anny forward pass
    neutral = _shape_verts(full, {}, {})
    for stage, (params, n, lr) in enumerate((([rot, log_s, trans], 80, 0.03), ([rot, log_s, trans, p_raw, l_raw], steps, 0.04))):
        opt = torch.optim.Adam(params, lr=lr)
        for it in range(n):
            ph, lc = shape()
            v = _shape_verts(full, ph, lc, grad=True) if stage else neutral
            proj, _ = project(v)
            err = ((proj - tgt) ** 2).sum(1) / iod**2
            loss = (err * weight).mean() + (2e-5 * (torch.tanh(l_raw) ** 2).sum() + 1e-5 * (p_raw**2).sum() if stage else 0)
            opt.zero_grad()
            loss.backward()
            opt.step()
            if it % 20 == 0 or it == n - 1:
                history.append(round(float(err.sqrt().mean()) * 100, 3))
    ph, lc = shape()
    phenotype = {k: round(float(v), 4) for k, v in ph.items()}
    local = {k: round(float(v), 4) for k, v in lc.items() if abs(float(v)) > 0.02}
    with torch.no_grad():
        v = _shape_verts(full, phenotype, local)
        proj, _ = project(v)
    err_iod = float((((proj - tgt) ** 2).sum(1).sqrt() / iod).mean())
    cam = {"rot": rot.detach().numpy().tolist(), "scale": float(torch.exp(log_s)), "trans": trans.detach().numpy().tolist()}
    return {"phenotype": phenotype, "local": local, "camera": cam, "error_iod": round(err_iod, 4),
            "history_err_pct_iod": history, "fit_s": round(time.time() - t0, 1)}


# --------------------------------------------------------------------------------------------- texture


def project_texture(photo: Path, result: dict, size: int = 2048, base: str = BASE_SKIN) -> Path:
    import roma

    full, body, faces, bmvi, keep = _body()
    img = np.asarray(Image.open(photo).convert("RGB")).astype(np.float32) / 255
    H, W = img.shape[:2]
    v = _shape_verts(full, result["phenotype"], result["local"]).numpy()[bmvi]
    corr = correspondence()
    pts = (v[faces[corr["face"]]] * corr["bary"][..., None]).sum(1)
    rotm = roma.rotvec_to_rotmat(torch.tensor(result["camera"]["rot"])).numpy()
    s, t = result["camera"]["scale"], np.array(result["camera"]["trans"])
    rp = (v - pts.mean(0)) @ rotm.T
    px = np.stack([rp[:, 0] * s + t[0], -rp[:, 1] * s + t[1]], 1)
    depth = rp[:, 2]

    # visibility: depth buffer of the fitted mesh in photo space (only faces near the head)
    tri = faces[keep]
    near = (px[tri][:, :, 0].max(1) > 0) & (px[tri][:, :, 0].min(1) < W) & (px[tri][:, :, 1].max(1) > 0) & (px[tri][:, :, 1].min(1) < H)
    head_y = px[tri][:, :, 1].mean(1) < t[1] + 2.2 * s * 0.1
    sel = tri[near & head_y]
    fid, bary = raster(px[sel], depth[sel], W, H)
    zbuf = np.full((H, W), -np.inf, np.float32)
    m = fid >= 0
    zbuf[m] = (bary[m] * depth[sel[fid[m]]]).sum(1)

    # face-oval mask in the photo, feathered
    lms = landmarks(photo)[str(photo)]
    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).polygon([tuple(lms[i, :2]) for i in FACE_OVAL], fill=255)
    mask = np.asarray(mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(int(0.06 * s * 0.1 + 6)))).astype(np.float32) / 255

    # UV raster of the body
    uv = body.texture_coordinates.numpy()
    tuv = body.face_texture_coordinate_indices.numpy()
    cand = np.nonzero(keep)[0]
    cand = cand[(px[faces[cand]][:, :, 1].mean(1) < t[1] + 2.2 * s * 0.1)]
    uv_px = np.stack([uv[tuv[cand]][..., 0] * size, (1 - uv[tuv[cand]][..., 1]) * size], -1)
    ufid, ubary = raster(uv_px, np.zeros((len(cand), 3)), size, size)
    um = ufid >= 0
    fsel = cand[ufid[um]]
    b = ubary[um]
    p_img = (b[..., None] * px[faces[fsel]]).sum(1)
    p_depth = (b * depth[faces[fsel]]).sum(1)
    vn = baker._normals(v, np.concatenate([faces[keep]]))
    n_cam = (b[..., None] * (vn[faces[fsel]] @ rotm.T)).sum(1)
    n_cam /= np.linalg.norm(n_cam, axis=1, keepdims=True) + 1e-9
    xi = np.clip(p_img[:, 0], 0, W - 1.001)
    yi = np.clip(p_img[:, 1], 0, H - 1.001)
    x0, y0 = xi.astype(int), yi.astype(int)
    fx, fy = (xi - x0)[:, None], (yi - y0)[:, None]
    col = (img[y0, x0] * (1 - fx) * (1 - fy) + img[y0, x0 + 1] * fx * (1 - fy) + img[y0 + 1, x0] * (1 - fx) * fy + img[y0 + 1, x0 + 1] * fx * fy)
    visible = p_depth >= zbuf[y0, x0] - 0.004
    facing = np.clip((n_cam[:, 2] - 0.25) / 0.35, 0, 1)
    w = facing * visible * mask[y0, x0]

    photo_uv = np.zeros((size, size, 3), np.float32)
    wmap = np.zeros((size, size), np.float32)
    photo_uv[um] = col
    wmap[um] = w
    wmap = np.asarray(Image.fromarray((wmap * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(4))).astype(np.float32) / 255
    wmap = np.minimum(wmap, (np.asarray(Image.fromarray((photo_uv.sum(-1) > 0).astype(np.uint8) * 255)) > 0))

    # recolour the base skin to the photo's tone, then composite
    tex = _texture(base, size)
    sel_px = wmap > 0.6
    mu_p, sd_p = photo_uv[sel_px].mean(0), photo_uv[sel_px].std(0) + 1e-4
    mu_b, sd_b = tex[sel_px].mean(0), tex[sel_px].std(0) + 1e-4
    matched = np.clip((tex - mu_b) / sd_b * (0.6 * sd_p + 0.4 * sd_b) + mu_p, 0, 1)
    out = matched * (1 - wmap[..., None]) + photo_uv * wmap[..., None]
    name = f"{photo.stem}_{int(time.time())}.png"
    Image.fromarray((out * 255).astype(np.uint8)).save(OUT / name)
    return OUT / name


if __name__ == "__main__":
    import sys

    photo = Path(sys.argv[1])
    labels = [c for c in models()[0].local_change_labels if c.startswith(("head", "nose", "mouth", "chin", "l-cheek", "r-cheek", "l-eye", "r-eye", "eyebrows", "forehead"))]
    res = fit(photo, labels)
    tex = project_texture(photo, res)
    res["texture"] = str(tex)
    print(json.dumps({k: v for k, v in res.items() if k != "local"}, indent=1), "\nlocal changes:", len(res["local"]))
    (OUT / f"{photo.stem}_fit.json").write_text(json.dumps(res))

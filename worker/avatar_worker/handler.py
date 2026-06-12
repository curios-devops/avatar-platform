"""
RunPod Serverless worker — FLAME fitting + Gaussian reconstruction + MICA + EMOCA.

Four endpoints (same Docker image, routed by job_type):
  RUNPOD_FLAME_ENDPOINT_ID        → job_type: "flame_fit"
  RUNPOD_RECONSTRUCT_ENDPOINT_ID  → job_type: "reconstruct"
  RUNPOD_MICA_ENDPOINT_ID         → job_type: "mica_fit"
  RUNPOD_EMOCA_ENDPOINT_ID        → job_type: "emoca_reconstruct"

Inference stack:
  DECA  — FLAME fitting + vertex decoding    (requires /weights/deca_model.tar)
  MICA  — Multi-view identity reconstruction (requires /weights/mica/)
  EMOCA — Detailed face reconstruction       (requires /weights/emoca/)
  Mediapipe — fallback face mesh (auto-installed)

flame_fit output:      { shape[300], expression[100], pose[6], tex[50] }
reconstruct output:    { gaussians_npz_b64: "<base64 NPZ>" }
mica_fit output:       { shape[300] }
emoca_reconstruct out: { shape[300], expression[100], pose[6], tex[50],
                         albedo_b64: "<base64 JPEG>",
                         expression_basis_b64: "<base64 NPZ>" | absent,
                         displacement_b64: null }
"""

from __future__ import annotations

import base64
import io
import logging
import math
import os
import random

import numpy as np
import runpod  # type: ignore[import]
from PIL import Image

# Register fake chumpy modules BEFORE MICA's flame.py unpickles FLAME2020 pkl
# (real chumpy doesn't build on modern numpy). No-op if real chumpy exists.
try:
    import chumpy_stub  # noqa: F401
except ImportError:
    pass

logger = logging.getLogger(__name__)

# ── weight paths (override via env vars) ─────────────────────────────────────
DECA_WEIGHTS  = os.getenv("DECA_WEIGHTS_PATH",  "/weights/deca_model.tar")
MICA_WEIGHTS  = os.getenv("MICA_WEIGHTS_PATH",  "/weights/mica")
EMOCA_WEIGHTS = os.getenv("EMOCA_WEIGHTS_PATH", "/weights/emoca")

# ── reconstruction constants ─────────────────────────────────────────────────
N_GAUSSIANS   = 50_000
FLAME_TRIS    = 9_976
HEAD_DIAMETER = 0.18
SH_C0         = 0.28209479177387814

# ── lazy model cache ──────────────────────────────────────────────────────────
_deca  = None
_mica  = None
_arc   = None   # insightface ArcFace app (shared with MICA)
_emoca = None


# ═══════════════════════════════════════════════════════════════════════════════
# DECA — FLAME fitting + Gaussian reconstruction (Phase 0)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_deca():
    global _deca
    if _deca is not None:
        return _deca
    if not os.path.exists(DECA_WEIGHTS):
        raise FileNotFoundError(
            f"DECA weights not found at {DECA_WEIGHTS}. "
            "Run download_weights.py or mount a RunPod Network Volume."
        )
    from deca.decalib.deca import DECA  # type: ignore[import]
    from deca.decalib.utils.config import cfg as deca_cfg  # type: ignore[import]
    deca_cfg.pretrained_modelpath = DECA_WEIGHTS
    deca_cfg.rasterizer_type = "standard"
    _deca = DECA(config=deca_cfg, device="cuda")
    logger.info("DECA loaded from %s", DECA_WEIGHTS)
    return _deca


def _pil_to_tensor(img_pil: Image.Image, size: int = 224):
    import torch
    img = img_pil.convert("RGB").resize((size, size))
    arr = np.array(img, dtype=np.float32) / 255.0
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
    return t.cuda() if torch.cuda.is_available() else t


def _pad_to(vals: list, n: int) -> list:
    return (list(vals) + [0.0] * n)[:n]


def _tensor_to_list(t, n: int) -> list:
    return _pad_to(t.squeeze().detach().cpu().numpy().flatten().tolist(), n)


def _deca_faces(deca) -> np.ndarray:
    flame = deca.flame
    if hasattr(flame, "faces_tensor"):
        return flame.faces_tensor.long().cpu().numpy()
    if hasattr(flame, "faces"):
        return np.asarray(flame.faces, dtype=np.int64)
    raise AttributeError("Cannot find face connectivity on DECA flame model")


def _fit_deca(image_bytes: bytes) -> dict:
    import torch
    deca = _load_deca()
    tensor = _pil_to_tensor(Image.open(io.BytesIO(image_bytes)), size=224)
    with torch.no_grad():
        codedict = deca.encode(tensor)
    return {
        "shape":      _tensor_to_list(codedict["shape"], 300),
        "expression": _tensor_to_list(codedict["exp"],   100),
        "pose":       _tensor_to_list(codedict["pose"],    6),
        "tex":        _tensor_to_list(codedict["tex"],    50),
    }


def _fit_neutral(_image_bytes: bytes) -> dict:
    logger.warning("Returning neutral FLAME params (DECA unavailable)")
    return {"shape": [0.0]*300, "expression": [0.0]*100, "pose": [0.0]*6, "tex": [0.0]*50}


def _handle_flame_fit(inp: dict) -> dict:
    image_bytes = base64.b64decode(inp["image_b64"])
    try:
        return _fit_deca(image_bytes)
    except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
        logger.warning("DECA unavailable (%s), falling back to neutral params", exc)
        return _fit_neutral(image_bytes)


def _decode_deca(flame_params: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import torch
    deca = _load_deca()

    def _t(key, n):
        vals = _pad_to(flame_params.get(key, []), n)
        return torch.tensor([vals], dtype=torch.float32).cuda()

    codedict = {
        "shape": _t("shape",      100),
        "exp":   _t("expression",  50),
        "pose":  _t("pose",         6),
        "tex":   _t("tex",         50),
        "light": torch.zeros(1, 9, 3, device="cuda"),
        "cam":   torch.tensor([[8.0, 0.0, 0.0]], device="cuda"),
    }
    with torch.no_grad():
        opdict, _ = deca.decode(codedict, rendering=False, vis_lmk=False, return_vis=False)

    verts_raw = opdict["verts"].squeeze(0).cpu().numpy()
    trans     = opdict["trans_verts"].squeeze(0).cpu().numpy()

    centre  = verts_raw.mean(axis=0)
    span    = verts_raw.max(axis=0) - verts_raw.min(axis=0)
    scale_f = HEAD_DIAMETER / (span.max() + 1e-8)
    verts_m = (verts_raw - centre) * scale_f
    verts_m[:, 1] += 0.05

    pix2d = np.stack([
        (trans[:, 0] + 1.0) * 0.5 * 512.0,
        (1.0 - trans[:, 1]) * 0.5 * 512.0,
    ], axis=1)

    return verts_m, pix2d, _deca_faces(deca)


def _decode_mediapipe(image_bytes: bytes) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    import mediapipe as mp  # type: ignore[import]
    from scipy.spatial import Delaunay  # type: ignore[import]

    img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    img_np  = np.array(img_pil)
    h, w    = img_np.shape[:2]

    with mp.solutions.face_mesh.FaceMesh(
        static_image_mode=True, max_num_faces=1, refine_landmarks=True
    ) as fm:
        results = fm.process(img_np)

    if not results.multi_face_landmarks:
        raise ValueError("mediapipe: no face detected")

    lms = results.multi_face_landmarks[0].landmark
    verts_raw = np.array(
        [[lm.x - 0.5, -(lm.y - 0.5), -lm.z] for lm in lms], dtype=np.float32
    )

    centre  = verts_raw.mean(axis=0)
    span    = verts_raw.max(axis=0) - verts_raw.min(axis=0)
    scale_f = HEAD_DIAMETER / (span.max() + 1e-8)
    verts_m = (verts_raw - centre) * scale_f
    verts_m[:, 1] += 0.05

    pix2d = np.array([[lm.x * w, lm.y * h] for lm in lms], dtype=np.float32)
    tri   = Delaunay(pix2d)
    faces = tri.simplices.astype(np.int64)

    valid = []
    for f in faces:
        e1 = verts_m[f[1]] - verts_m[f[0]]
        e2 = verts_m[f[2]] - verts_m[f[0]]
        if np.linalg.norm(np.cross(e1, e2)) > 1e-9:
            valid.append(f)
    if valid:
        faces = np.array(valid, dtype=np.int64)

    return verts_m, pix2d, faces


def _sample_color(img_np: np.ndarray, px: float, py: float) -> np.ndarray:
    H, W = img_np.shape[:2]
    x0 = max(0, min(W - 2, int(px)))
    y0 = max(0, min(H - 2, int(py)))
    fx, fy = px - x0, py - y0
    return (
        img_np[y0,     x0]   * (1 - fx) * (1 - fy) +
        img_np[y0,     x0+1] *      fx  * (1 - fy) +
        img_np[y0 + 1, x0]   * (1 - fx) *      fy  +
        img_np[y0 + 1, x0+1] *      fx  *      fy
    )


def _build_gaussians(
    image_bytes: bytes,
    verts_m: np.ndarray,
    pix2d:   np.ndarray,
    faces:   np.ndarray,
) -> dict:
    img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((512, 512))
    img_np  = np.array(img_pil, dtype=np.float32) / 255.0

    n_faces  = len(faces)
    samp_per = max(1, N_GAUSSIANS // n_faces)
    rng      = random.Random(42)

    pos_list  = []
    opa_list  = []
    scl_list  = []
    rot_list  = []
    sh_list   = []
    tri_list  = []
    bary_list = []

    for fi in range(n_faces):
        i, j, k     = faces[fi]
        v0, v1, v2  = verts_m[i], verts_m[j], verts_m[k]
        p0, p1, p2  = pix2d[i],   pix2d[j],   pix2d[k]
        flame_tri   = fi % FLAME_TRIS

        for _ in range(samp_per):
            r1, r2 = rng.random(), rng.random()
            if r1 + r2 > 1.0:
                r1, r2 = 1.0 - r1, 1.0 - r2
            r3 = 1.0 - r1 - r2

            pos = r1 * v0 + r2 * v1 + r3 * v2
            pix = r1 * p0 + r2 * p1 + r3 * p2

            rgb = _sample_color(img_np, pix[0], pix[1])
            sh  = [(float(c) - 0.5) / SH_C0 for c in rgb]
            log_s = math.log(rng.uniform(5e-4, 3e-3))

            pos_list.append(pos.tolist())
            opa_list.append(rng.uniform(0.78, 0.97))
            scl_list.append([log_s, log_s, log_s])
            rot_list.append([1.0, 0.0, 0.0, 0.0])
            sh_list.append(sh)
            tri_list.append(flame_tri)
            bary_list.append([r1, r2, r3])

    total  = len(pos_list)
    np_rng = np.random.default_rng(42)
    if total > N_GAUSSIANS:
        idx = np_rng.choice(total, N_GAUSSIANS, replace=False)
    else:
        idx = np.concatenate([
            np.arange(total),
            np_rng.choice(total, N_GAUSSIANS - total, replace=True),
        ])

    def _sel(lst): return [lst[i] for i in idx]

    buf = io.BytesIO()
    np.savez(buf,
        position    = np.array(_sel(pos_list),  dtype=np.float32),
        opacity     = np.array(_sel(opa_list),  dtype=np.float32),
        scale       = np.array(_sel(scl_list),  dtype=np.float32),
        rotation    = np.array(_sel(rot_list),  dtype=np.float32),
        sh_dc       = np.array(_sel(sh_list),   dtype=np.float32),
        triangle_idx= np.array(_sel(tri_list),  dtype=np.int32),
        barycentric = np.array(_sel(bary_list), dtype=np.float32),
    )
    return {"gaussians_npz_b64": base64.b64encode(buf.getvalue()).decode()}


def _handle_reconstruct(inp: dict) -> dict:
    image_bytes  = base64.b64decode(inp["image_b64"])
    flame_params = inp.get("flame_params")
    if not flame_params:
        return {"error": "flame_params is required for reconstruct job"}

    try:
        verts_m, pix2d, faces = _decode_deca(flame_params)
        logger.info("Reconstruction via DECA (%d faces)", len(faces))
    except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
        logger.warning("DECA unavailable (%s), trying mediapipe", exc)
        try:
            verts_m, pix2d, faces = _decode_mediapipe(image_bytes)
            logger.info("Reconstruction via mediapipe (%d faces)", len(faces))
        except Exception as mp_exc:
            raise RuntimeError(
                f"Both DECA and mediapipe failed. DECA: {exc}  Mediapipe: {mp_exc}"
            ) from mp_exc

    return _build_gaussians(image_bytes, verts_m, pix2d, faces)


# ═══════════════════════════════════════════════════════════════════════════════
# MICA — multi-view identity reconstruction (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════════

# Preferred view angles for MICA (laterally spread, no tilt)
_MICA_PREFERRED = ["left_60", "right_60", "left_30", "right_30", "left_90"]
_MICA_MAX_VIEWS = 5


def _mica_data_path(p: str) -> str:
    """Resolve MICA's relative data paths (e.g. 'data/FLAME2020/generic_model.pkl')
    against the weights volume first, then the cloned repo."""
    mica_repo = os.getenv("MICA_REPO_PATH", "/opt/MICA")
    if os.path.isabs(p) and os.path.exists(p):
        return p
    rel = p[len("data/"):] if p.startswith("data/") else p
    for base in (MICA_WEIGHTS, os.path.join(mica_repo, "data")):
        cand = os.path.join(base, rel)
        if os.path.exists(cand):
            return cand
    return p


def _load_mica():
    """Load MICA model + insightface ArcFace app. Raises on missing weights."""
    global _mica, _arc
    if _mica is not None:
        return _mica, _arc

    if not os.path.isdir(MICA_WEIGHTS):
        raise FileNotFoundError(f"MICA weights not found at {MICA_WEIGHTS}")

    import torch
    from insightface.app import FaceAnalysis  # type: ignore[import]

    # Face detector for ArcFace crops — auto-downloads on first run.
    # antelopev2 (MICA's choice) has a known packaging bug where the zip
    # extracts nested and FaceAnalysis asserts 'detection' missing; buffalo_l
    # provides equivalent SCRFD detection + 5-point kps for norm_crop.
    insightface_root = os.path.join(MICA_WEIGHTS, "insightface")
    os.makedirs(insightface_root, exist_ok=True)

    # Repair nested antelopev2 extraction if present (models/antelopev2/antelopev2)
    nested = os.path.join(insightface_root, "models", "antelopev2", "antelopev2")
    if os.path.isdir(nested):
        import shutil
        parent = os.path.dirname(nested)
        for f in os.listdir(nested):
            shutil.move(os.path.join(nested, f), os.path.join(parent, f))
        os.rmdir(nested)
        logger.info("Repaired nested antelopev2 extraction")

    _arc = None
    arc_error: Exception | None = None
    for pack in ("antelopev2", "buffalo_l"):
        try:
            _arc = FaceAnalysis(
                name=pack,
                root=insightface_root,
                providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
            )
            _arc.prepare(
                ctx_id=0 if torch.cuda.is_available() else -1,
                det_size=(224, 224),
            )
            logger.info("insightface pack: %s", pack)
            break
        except Exception as exc:
            logger.warning("insightface %s failed (%s) — trying next pack", pack, exc)
            arc_error = exc
            _arc = None
    if _arc is None:
        raise RuntimeError(f"No insightface detection pack available: {arc_error}")

    # MICA model — repo layout (PYTHONPATH=/opt/MICA):
    #   configs/config.py        → get_cfg_defaults()
    #   micalib/models/mica.py   → class MICA(cfg, device)
    from configs.config import get_cfg_defaults  # type: ignore[import]
    from utils import util as mica_util          # type: ignore[import]

    cfg = get_cfg_defaults()
    cfg.model.testing = True

    # Resolve relative data paths (FLAME pkl, head template, lmk embeddings)
    for attr in ("topology_path", "flame_model_path", "flame_lmk_embedding_path"):
        if hasattr(cfg.model, attr):
            setattr(cfg.model, attr, _mica_data_path(getattr(cfg.model, attr)))

    device = "cuda" if torch.cuda.is_available() else "cpu"
    _mica = mica_util.find_model_using_name(
        model_dir="micalib.models", model_name=cfg.model.name
    )(cfg, device)

    # Checkpoint keys per Zielon/MICA demo.py: 'arcface' + 'flameModel'
    ckpt_path = os.path.join(MICA_WEIGHTS, "mica.tar")
    ckpt = torch.load(ckpt_path, map_location=device)
    if "arcface" in ckpt:
        _mica.arcface.load_state_dict(ckpt["arcface"])
    if "flameModel" in ckpt:
        _mica.flameModel.load_state_dict(ckpt["flameModel"])
    if "arcface" not in ckpt and "flameModel" not in ckpt:
        _mica.load_state_dict(ckpt.get("state_dict", ckpt), strict=False)

    _mica = _mica.to(device).eval()
    logger.info("MICA loaded from %s", MICA_WEIGHTS)
    return _mica, _arc


def _arcface_crop(img_rgb: np.ndarray, arc_app) -> np.ndarray | None:
    """Detect face, return 112×112 ArcFace input (3,112,112) float32 or None.

    Matches MICA's get_arcface_input: BGR detection, norm_crop, then
    (RGB - 127.5) / 127.5 normalisation, channels-first.
    """
    from insightface.utils import face_align  # type: ignore[import]
    img_bgr = img_rgb[:, :, ::-1]
    faces = arc_app.get(img_bgr)
    if not faces:
        return None
    crop_bgr = face_align.norm_crop(img_bgr, faces[0].kps, image_size=112)
    crop_rgb = crop_bgr[:, :, ::-1].astype(np.float32)
    blob = (crop_rgb - 127.5) / 127.5
    return blob.transpose(2, 0, 1)  # (3, 112, 112)


def _handle_mica_fit(inp: dict) -> dict:
    """
    mica_fit handler.
    Input: { frontal_b64: str, side_views_b64: {angle: str} }
    Output: { shape: [300 floats] }
    """
    side_views_b64 = inp.get("side_views_b64", {})

    try:
        mica_model, arc_app = _load_mica()
        import torch

        device = next(mica_model.parameters()).device

        # Build list of (key, base64_str) for all images, frontal first
        all_views = [("frontal", inp["frontal_b64"])]
        # Select up to _MICA_MAX_VIEWS side views, preferred angles first
        selected: dict[str, str] = {}
        for k in _MICA_PREFERRED:
            if k in side_views_b64 and len(selected) < _MICA_MAX_VIEWS:
                selected[k] = side_views_b64[k]
        for k, v in side_views_b64.items():
            if k not in selected and len(selected) < _MICA_MAX_VIEWS:
                selected[k] = v
        all_views.extend(selected.items())

        # Extract ArcFace-normalised inputs (3,112,112) per view
        crops: list[np.ndarray] = []
        for key, b64 in all_views:
            try:
                img_np = np.array(
                    Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
                )
                crop = _arcface_crop(img_np, arc_app)
                if crop is not None:
                    crops.append(crop)
            except Exception as e:
                logger.debug("MICA: skipping view %s: %s", key, e)

        if not crops:
            raise ValueError("No valid face crops from any view")

        arcface_batch = torch.from_numpy(
            np.stack(crops).astype(np.float32)
        ).to(device)
        # MICA stores `images` in the codedict but identity comes from arcface;
        # a zero batch keeps decode() happy without the 224px crops.
        images_dummy = torch.zeros(
            len(crops), 3, 224, 224, dtype=torch.float32, device=device
        )

        with torch.no_grad():
            codedict = mica_model.encode(images_dummy, arcface_batch)
            opdict   = mica_model.decode(codedict, 0)

        shape_t = opdict.get("pred_shape_code")
        if shape_t is None:
            raise ValueError("MICA decode() returned no pred_shape_code")

        # Average across views, flatten to list
        shape_np = shape_t.mean(0).squeeze().cpu().numpy()
        shape    = _pad_to(shape_np.tolist(), 300)

        logger.info("MICA fit done — shape[0]=%.4f from %d crops", shape[0], len(crops))
        return {"shape": shape}

    except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
        logger.warning("MICA unavailable (%s) — returning neutral shape", exc)
        return {"shape": [0.0] * 300}


# ═══════════════════════════════════════════════════════════════════════════════
# EMOCA — detailed face reconstruction + albedo (Phase 2)
# ═══════════════════════════════════════════════════════════════════════════════

def _load_emoca():
    """Load EMOCA model. Raises on missing weights or missing package."""
    global _emoca
    if _emoca is not None:
        return _emoca

    if not os.path.isdir(EMOCA_WEIGHTS):
        raise FileNotFoundError(f"EMOCA weights not found at {EMOCA_WEIGHTS}")

    import torch
    from omegaconf import OmegaConf  # type: ignore[import]

    cfg_path  = os.path.join(EMOCA_WEIGHTS, "cfg.yaml")
    ckpt_path = os.path.join(EMOCA_WEIGHTS, "emoca.tar")

    cfg = OmegaConf.load(cfg_path)

    # EMOCA ships as the 'gdl' package (geometry deep learning)
    from gdl.models.EMOCA import EMOCA as EMOCAModel  # type: ignore[import]

    _emoca = EMOCAModel(cfg.model)
    ckpt   = torch.load(ckpt_path, map_location="cpu")
    state  = ckpt.get("state_dict", ckpt.get("model", ckpt))
    _emoca.load_state_dict(state, strict=False)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    _emoca = _emoca.to(device).eval()

    logger.info("EMOCA loaded from %s", EMOCA_WEIGHTS)
    return _emoca


def _blank_albedo_jpeg(size: int = 512) -> bytes:
    img = Image.new("RGB", (size, size), color=(200, 160, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _albedo_tensor_to_jpeg(t) -> bytes:
    """Convert (1, 3, H, W) float32 [0,1] albedo tensor to JPEG bytes."""
    arr = t.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()
    arr = (arr * 255).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").resize((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _expr_basis_to_npz(t) -> bytes:
    """Convert expression basis tensor to compressed NPZ bytes.

    Expected shape: (100, V, 3) or (100, V*3). Stored as (100, V*3) float32.
    """
    arr = t.detach().cpu().numpy().astype(np.float32)
    if arr.ndim == 3:
        arr = arr.reshape(arr.shape[0], -1)
    buf = io.BytesIO()
    np.savez_compressed(buf, expression_basis=arr)
    return buf.getvalue()


def _emoca_photo_albedo(image_bytes: bytes) -> bytes:
    """Sample central face patch from photo as a flat-colour albedo."""
    try:
        img   = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((512, 512))
        arr   = np.array(img, dtype=np.uint8)
        patch = arr[150:350, 150:350]
        mean  = patch.mean(axis=(0, 1)).astype(np.uint8)
        albedo = Image.new("RGB", (512, 512), tuple(int(c) for c in mean))
        buf = io.BytesIO()
        albedo.save(buf, format="JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return _blank_albedo_jpeg()


def _handle_emoca_reconstruct(inp: dict) -> dict:
    """
    emoca_reconstruct handler.
    Input:  { image_b64: str, shape: [300 floats] }
    Output: { shape, expression, pose, tex, albedo_b64,
              expression_basis_b64? (absent when unavailable) }
    """
    image_bytes  = base64.b64decode(inp["image_b64"])
    shape_prior  = inp.get("shape", [0.0] * 300)

    try:
        emoca_model = _load_emoca()
        import torch

        device = next(emoca_model.parameters()).device

        # Prepare 224×224 input tensor
        img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB").resize((224, 224))
        arr     = np.array(img_pil, dtype=np.float32) / 255.0
        img_t   = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).to(device)

        with torch.no_grad():
            codedict = emoca_model.encode(img_t)
            opdict   = emoca_model.decode(codedict, rendering=True)

        def _tlist(key_candidates, n):
            for k in key_candidates:
                t = codedict.get(k)
                if t is None:
                    t = opdict.get(k)
                if t is not None:
                    return _pad_to(t.squeeze().detach().cpu().numpy().flatten().tolist(), n)
            return [0.0] * n

        shape = _tlist(["shapecode", "shape"],              300)
        expr  = _tlist(["expcode",   "exp",    "expression"], 100)
        pose  = _tlist(["posecode",  "pose"],                 6)
        tex   = _tlist(["texcode",   "tex"],                 50)

        # Albedo
        albedo_t = None
        for k in ("albedo", "texture", "uv_texture_gt", "uv_detail_normals"):
            albedo_t = opdict.get(k)
            if albedo_t is not None:
                break
        albedo_jpeg = _albedo_tensor_to_jpeg(albedo_t) if albedo_t is not None \
                      else _emoca_photo_albedo(image_bytes)

        result: dict = {
            "shape":      shape,
            "expression": expr,
            "pose":       pose,
            "tex":        tex,
            "albedo_b64": base64.b64encode(albedo_jpeg).decode(),
        }

        # Expression basis (per-subject PCA from decoder, if available)
        expr_basis_t = opdict.get("expression_basis")
        if expr_basis_t is not None:
            result["expression_basis_b64"] = base64.b64encode(
                _expr_basis_to_npz(expr_basis_t)
            ).decode()

        logger.info(
            "EMOCA done — shape[0]=%.4f albedo=%d bytes expr_basis=%s",
            shape[0], len(albedo_jpeg),
            "yes" if "expression_basis_b64" in result else "no",
        )
        return result

    except (FileNotFoundError, ImportError, ModuleNotFoundError) as exc:
        logger.warning("EMOCA unavailable (%s) — using photo-albedo fallback", exc)
        return {
            "shape":      _pad_to(list(shape_prior), 300),
            "expression": [0.0] * 100,
            "pose":       [0.0] * 6,
            "tex":        [0.0] * 50,
            "albedo_b64": base64.b64encode(_emoca_photo_albedo(image_bytes)).decode(),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# RunPod entrypoint
# ═══════════════════════════════════════════════════════════════════════════════

def handler(job: dict) -> dict:
    """
    RunPod job handler — routes by job_type.

    Input shape:  { "input": { "job_type": "<type>", ... } }
    Output shape: type-specific dict (see module docstring).
    """
    inp      = job.get("input", {})
    job_type = inp.get("job_type", "")

    try:
        if job_type == "flame_fit":
            if "image_b64" not in inp:
                return {"error": "image_b64 required for flame_fit"}
            return _handle_flame_fit(inp)

        elif job_type == "reconstruct":
            if "image_b64" not in inp:
                return {"error": "image_b64 required for reconstruct"}
            return _handle_reconstruct(inp)

        elif job_type == "mica_fit":
            if "frontal_b64" not in inp:
                return {"error": "frontal_b64 required for mica_fit"}
            return _handle_mica_fit(inp)

        elif job_type == "emoca_reconstruct":
            if "image_b64" not in inp:
                return {"error": "image_b64 required for emoca_reconstruct"}
            return _handle_emoca_reconstruct(inp)

        else:
            return {
                "error": (
                    f"Unknown job_type '{job_type}'. "
                    "Expected one of: flame_fit, reconstruct, mica_fit, emoca_reconstruct."
                )
            }

    except KeyError as exc:
        return {"error": f"Missing required field: {exc}"}
    except Exception as exc:
        logger.exception("Handler error for job_type=%s", job_type)
        return {"error": str(exc)}


if __name__ == "__main__":
    # Populate the network volume from presigned URLs on first boot
    try:
        from bootstrap_weights import ensure_weights
        ensure_weights()
    except Exception as _exc:  # never block worker start on bootstrap issues
        logger.warning("weights bootstrap skipped: %s", _exc)

    runpod.serverless.start({"handler": handler})

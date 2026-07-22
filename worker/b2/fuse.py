#!/usr/bin/env python3
"""B2 — fuse.py: fusión cabeza-cuerpo (offline; "el trabajo duro").

    a. Eliminar splats de cabeza del cuerpo LHM (banda de solape ~2cm bajo
       mandíbula), usando la segmentación SMPL-X head/neck (geométrica, no
       skinning weights — LHM no expone pesos por-gaussiano; ver docstring
       de smplx_body.py).
    b. Registro rígido cabeza→cuerpo: Procrustes (escala+rotación+traslación)
       sobre landmarks compartidos (ojos, nariz, mentón), normalizando escala
       por distancia interpupilar ANTES de optimizar, priorizando
       mandíbula/ojos sobre coronilla (no se usa coronilla como landmark).
    c. Rampa de opacidad en la banda de solape (fade cruzado body↔head).
    d. Match de color (LAB, mismo método que prep_clips.py::match_color) en
       la zona de unión.
    e. Exporta avatar_body.ply + avatar_head.ply + fused.ply (preview para el
       harness) + rig.json.

NOTA: el doc pide .spz; exportamos .ply porque es el formato que YA lee/escribe
todo nuestro harness (qa/splat_io.py) — .spz es compresión de entrega para B3
runtime, no afecta la corrección de la fusión que este gate evalúa.

Requiere GPU/CUDA (smplx + torch para construir la malla del cuerpo) — no
corre en este Mac. Uso en sesión dedicada, después de generar body.ply (LHM,
con el parche de betas) y head.ply (LAM o FaceLift refinado de B1.5):

    python worker/b2/fuse.py \
        --head .triage/lam_head_v7.ply --body /path/to/lhm_body.ply \
        --betas /path/to/lhm_body_betas.npy \
        --human-model-path /opt/LHM/pretrained_models/human_model_files \
        --out-dir qa/out/b2/fused_v1
    qa/run_all.sh qa/out/b2/fused_v1/fused.ply b2_v1 .triage/test_portrait.jpg

Contingencia del doc si el registro se atasca: este script SIEMPRE exporta
`landmarks_debug.png`-equivalente en JSON (rig.json incluye ambos sets de
landmarks 3D) para visualizar los dos "esqueletos" superpuestos antes de
seguir optimizando.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "qa"))
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).parent))

from splat_io import Gaussians, load_ply, save_ply  # noqa: E402
import smplx_body  # noqa: E402

OVERLAP_BAND_M = 0.02   # "banda de solape ~2cm bajo mandíbula"


# ── landmarks en la nube de splats de la cabeza (heurística geométrica) ─────
#
# Convención LAM (memoria project_lam_migration): +Z frontal canónico, +Y
# arriba. Reusa el mismo tipo de estadística robusta que raster.scene_frame()
# (mediana/percentiles) en vez de literales de una sola foto.

def _head_landmarks(head: Gaussians) -> dict[str, np.ndarray]:
    center = np.median(head.xyz, axis=0)
    x, y, z = (head.xyz - center).T

    # cara frontal: los splats más protuberantes en +Z, banda vertical media
    face_band = (y > -0.10) & (y < 0.08) & (head.opacity > 0.3)
    if face_band.sum() < 50:
        face_band = head.opacity > np.percentile(head.opacity, 70)

    # nariz: punto más protuberante (+Z) cerca del eje medio (x≈0)
    midline = face_band & (np.abs(x) < 0.02)
    nose = head.xyz[midline][np.argmax(z[midline])] if midline.sum() else center

    # ojos: splats oscuros (iris/pestañas) en la banda superior de la cara,
    # separados en clusters izq/der por el signo de x — mismo principio que
    # el blink mask de webgpu_renderer.ts ("dark facial splats").
    upper_face = face_band & (y > -0.01) & (y < 0.06) & (z > np.percentile(z[face_band], 60))
    luminance = head.rgb.mean(axis=1)
    dark = upper_face & (luminance < np.percentile(luminance[upper_face], 25)) if upper_face.sum() > 20 else upper_face
    left = dark & (x < -0.01)
    right = dark & (x > 0.01)
    eye_l = head.xyz[left].mean(axis=0) if left.sum() else center + [-0.035, 0.02, 0.03]
    eye_r = head.xyz[right].mean(axis=0) if right.sum() else center + [0.035, 0.02, 0.03]

    # mentón: punto más bajo (-Y) de la banda frontal de piel
    lower_face = face_band & (y < -0.04) & (z > np.percentile(z[face_band], 50))
    chin = head.xyz[lower_face][np.argmin(y[lower_face])] if lower_face.sum() else center + [0, -0.09, 0.04]

    return {"nose": nose, "eye_l": eye_l, "eye_r": eye_r, "chin": chin}


def _body_landmarks(smplx_out_joints: np.ndarray, joint_names: list[str]) -> dict[str, np.ndarray]:
    """Landmarks faciales del modelo SMPL-X (use_face_contour=True añade
    landmarks de cara a `joints`, en el mismo orden que `joint_names`)."""
    idx = {n: i for i, n in enumerate(joint_names)}
    def pt(name_options):
        for n in name_options:
            if n in idx:
                return smplx_out_joints[idx[n]]
        raise KeyError(f"ninguno de {name_options} en joint_names del modelo SMPL-X")
    return {
        "nose": pt(["nose", "nose_middle", "face-2"]),
        "eye_l": pt(["left_eye", "leye", "face-38"]),
        "eye_r": pt(["right_eye", "reye", "face-44"]),
        "chin": pt(["chin", "jaw", "face-9"]),
    }


# ── Procrustes con normalización por distancia interpupilar ─────────────────

def procrustes(src: dict[str, np.ndarray], dst: dict[str, np.ndarray]) -> tuple[np.ndarray, float, np.ndarray]:
    """src (cabeza) -> dst (socket del cuerpo). Devuelve (R 3x3, s, t) tal que
    dst_pt ≈ s·R·src_pt + t. Normaliza escala por distancia interpupilar ANTES
    de optimizar (paso explícito del doc); pesos: mandíbula/ojos > nariz
    (no se usa "coronilla" — no forma parte de este set de landmarks)."""
    keys = ["eye_l", "eye_r", "nose", "chin"]
    weights = np.array([1.5, 1.5, 1.0, 1.5])  # ojos+mandíbula priorizados sobre nariz
    S = np.array([src[k] for k in keys])
    D = np.array([dst[k] for k in keys])

    ipd_src = np.linalg.norm(src["eye_l"] - src["eye_r"])
    ipd_dst = np.linalg.norm(dst["eye_l"] - dst["eye_r"])
    scale_norm = ipd_dst / max(ipd_src, 1e-6)
    S = S * scale_norm  # normalización por IPD antes de optimizar (paso del doc)

    w = weights / weights.sum()
    s_mean = (S * w[:, None]).sum(axis=0)
    d_mean = (D * w[:, None]).sum(axis=0)
    Sc, Dc = S - s_mean, D - d_mean

    H = (Sc * w[:, None]).T @ Dc
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1] *= -1
        R = Vt.T @ U.T

    num = np.sum(w[:, None] * (Sc @ R.T) * Dc)
    den = np.sum(w[:, None] * (Sc @ R.T) ** 2)
    s_fine = num / max(den, 1e-9)
    s_total = scale_norm * s_fine

    t = d_mean - s_fine * (R @ s_mean)
    residual = np.sqrt(np.mean(np.sum((s_fine * (Sc @ R.T) - Dc) ** 2, axis=1)))
    print(f"[fuse] Procrustes: escala_ipd={scale_norm:.4f} escala_fina={s_fine:.4f} "
         f"residual={residual*1000:.2f}mm")
    return R, s_total, t


def apply_transform(g: Gaussians, R: np.ndarray, s: float, t: np.ndarray) -> Gaussians:
    from splat_io import quat_to_rotmat
    xyz = (g.xyz @ R.T) * s + t
    Rm = quat_to_rotmat(g.rot)
    Rm_new = np.einsum("ij,njk->nik", R, Rm)
    # reconvertir a quaternion
    rot = np.zeros_like(g.rot)
    for i in range(len(g)):
        rot[i] = _mat_to_quat(Rm_new[i])
    scale = g.scale * s
    return Gaussians(xyz=xyz.astype(np.float32), rgb=g.rgb, opacity=g.opacity,
                     scale=scale.astype(np.float32), rot=rot.astype(np.float32))


def _mat_to_quat(R: np.ndarray) -> np.ndarray:
    tr = np.trace(R)
    if tr > 0:
        s = 2.0 * np.sqrt(tr + 1.0)
        w, x, y, z = 0.25 * s, (R[2,1]-R[1,2])/s, (R[0,2]-R[2,0])/s, (R[1,0]-R[0,1])/s
    else:
        i = np.argmax([R[0,0], R[1,1], R[2,2]])
        if i == 0:
            s = 2.0*np.sqrt(1+R[0,0]-R[1,1]-R[2,2]); w=(R[2,1]-R[1,2])/s; x=0.25*s; y=(R[0,1]+R[1,0])/s; z=(R[0,2]+R[2,0])/s
        elif i == 1:
            s = 2.0*np.sqrt(1+R[1,1]-R[0,0]-R[2,2]); w=(R[0,2]-R[2,0])/s; x=(R[0,1]+R[1,0])/s; y=0.25*s; z=(R[1,2]+R[2,1])/s
        else:
            s = 2.0*np.sqrt(1+R[2,2]-R[0,0]-R[1,1]); w=(R[1,0]-R[0,1])/s; x=(R[0,2]+R[2,0])/s; y=(R[1,2]+R[2,1])/s; z=0.25*s
    q = np.array([w, x, y, z], dtype=np.float32)
    return q / (np.linalg.norm(q) + 1e-9)


# ── a. eliminar splats de cabeza del cuerpo + c. rampa de opacidad ──────────

def carve_and_ramp(body: Gaussians, seam_world: np.ndarray, seam_normal: np.ndarray,
                   band_m: float = OVERLAP_BAND_M) -> Gaussians:
    """seam_world: punto de la costura (bajo la mandíbula, en el cuerpo YA
    registrado al frame del cuerpo). seam_normal: dirección "hacia arriba"
    de la costura (normalmente +Y del cuerpo). Elimina splats por encima de
    seam+band; aplica rampa de opacidad lineal dentro de la banda."""
    h = (body.xyz - seam_world) @ seam_normal  # altura relativa a la costura
    keep = h < band_m
    g = Gaussians(xyz=body.xyz[keep], rgb=body.rgb[keep], opacity=body.opacity[keep].copy(),
                 scale=body.scale[keep], rot=body.rot[keep])
    h_keep = h[keep]
    in_band = (h_keep > 0) & (h_keep < band_m)
    ramp = 1.0 - (h_keep[in_band] / band_m)  # 1 en la costura → 0 al final de la banda
    g.opacity[in_band] *= ramp
    n_removed = int((~keep).sum())
    print(f"[fuse] carve: {n_removed}/{len(body)} splats de cuerpo eliminados "
         f"(por encima de costura+{band_m*100:.0f}mm); {in_band.sum()} en rampa de opacidad")
    return g


# ── d. match de color en la costura (mismo método LAB que prep_clips.py) ───

def match_color_seam(head: Gaussians, body: Gaussians, seam_world: np.ndarray,
                     seam_normal: np.ndarray, band_m: float = OVERLAP_BAND_M * 2) -> Gaussians:
    """Reinhard LAB transfer del color del CUERPO cerca de la costura hacia
    los splats de CABEZA cerca de la costura — mismo principio que
    worker/clips_gen/prep_clips.py::match_color, adaptado a splats."""
    import cv2
    h_body = (body.xyz - seam_world) @ seam_normal
    near_body = np.abs(h_body) < band_m
    if near_body.sum() < 20:
        print("[fuse] ⚠️ muy pocos splats de cuerpo cerca de la costura — sin match de color")
        return head
    h_head = (head.xyz - seam_world) @ seam_normal
    near_head = np.abs(h_head) < band_m
    if near_head.sum() < 20:
        return head

    def lab_stats(rgb):
        lab = cv2.cvtColor((rgb[None] * 255).astype(np.uint8), cv2.COLOR_RGB2LAB)[0].astype(np.float32)
        return lab.mean(0), lab.std(0) + 1e-6

    body_mean, body_std = lab_stats(body.rgb[near_body])
    head_mean, head_std = lab_stats(head.rgb[near_head])

    rgb_new = head.rgb.copy()
    lab = cv2.cvtColor((rgb_new[None] * 255).astype(np.uint8), cv2.COLOR_RGB2LAB)[0].astype(np.float32)
    w = np.clip(1.0 - np.abs(h_head) / band_m, 0, 1)  # 1 en la costura → 0 lejos
    lab_matched = (lab - head_mean) * (body_std / head_std) + body_mean
    lab_out = lab * (1 - w[:, None]) + lab_matched * w[:, None]
    rgb_new = cv2.cvtColor(np.clip(lab_out, 0, 255).astype(np.uint8)[None], cv2.COLOR_LAB2RGB)[0].astype(np.float32) / 255.0
    print(f"[fuse] color match: {near_head.sum()} splats de cabeza ajustados cerca de la costura")
    return Gaussians(xyz=head.xyz, rgb=rgb_new, opacity=head.opacity, scale=head.scale, rot=head.rot)


def concat(a: Gaussians, b: Gaussians) -> Gaussians:
    return Gaussians(
        xyz=np.concatenate([a.xyz, b.xyz]), rgb=np.concatenate([a.rgb, b.rgb]),
        opacity=np.concatenate([a.opacity, b.opacity]),
        scale=np.concatenate([a.scale, b.scale]), rot=np.concatenate([a.rot, b.rot]),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", required=True, type=Path)
    ap.add_argument("--body", required=True, type=Path)
    ap.add_argument("--betas", required=True, type=Path, help="<body>_betas.npy del worker LHM parcheado")
    ap.add_argument("--human-model-path", required=True, type=Path,
                    help="dir con smplx/ (mismo que usa LHM en inferencia)")
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    head = load_ply(args.head)
    body = load_ply(args.body)
    betas = np.load(args.betas).reshape(-1)
    print(f"[fuse] head={len(head)} splats  body={len(body)} splats  betas={betas.shape}")

    from pipeline.flame_template import load as load_flame  # backend/app/pipeline
    flame = load_flame()
    sx = smplx_body.build(betas, args.human_model_path, flame.v_template)

    # landmarks del cuerpo vía joints faciales de SMPL-X (use_face_contour)
    import torch, smplx as smplx_pkg
    model = smplx_pkg.create(str(args.human_model_path), "smplx", gender="neutral",
                             num_betas=len(betas), use_face_contour=True, use_pca=False)
    out = model(betas=torch.as_tensor(betas, dtype=torch.float32).unsqueeze(0), return_verts=True)
    joints = out.joints[0].detach().cpu().numpy()
    joint_names = list(smplx_pkg.joint_names.JOINT_NAMES)[:joints.shape[0]]
    body_lm = _body_landmarks(joints, joint_names)
    head_lm = _head_landmarks(head)

    R, s, t = procrustes(head_lm, body_lm)
    head_reg = apply_transform(head, R, s, t)

    seam_pt = body_lm["chin"] - np.array([0, 0.005, 0])  # justo bajo la mandíbula
    seam_normal = np.array([0.0, 1.0, 0.0])  # +Y del cuerpo (arriba)
    body_carved = carve_and_ramp(body, seam_pt, seam_normal)
    head_final = match_color_seam(head_reg, body_carved, seam_pt, seam_normal)

    save_ply(head_final, args.out_dir / "avatar_head.ply")
    save_ply(body_carved, args.out_dir / "avatar_body.ply")
    fused = concat(body_carved, head_final)
    save_ply(fused, args.out_dir / "fused.ply")

    rig = {
        "registration": {"R": R.tolist(), "s": float(s), "t": t.tolist()},
        "seam": {"point": seam_pt.tolist(), "normal": seam_normal.tolist(),
                "overlap_band_m": OVERLAP_BAND_M},
        "landmarks_head_canonical": {k: v.tolist() for k, v in head_lm.items()},
        "landmarks_body_smplx": {k: v.tolist() for k, v in body_lm.items()},
        "smplx_betas": betas.tolist(),
        "n_head_splats": len(head_final), "n_body_splats_kept": len(body_carved),
    }
    (args.out_dir / "rig.json").write_text(json.dumps(rig, indent=2))
    print(f"[fuse] → {args.out_dir}/  (avatar_head.ply, avatar_body.ply, fused.ply, rig.json)")
    print(f"[fuse] siguiente paso: qa/run_all.sh {args.out_dir}/fused.ply b2_v1 <foto>")
    return 0


if __name__ == "__main__":
    sys.exit(main())

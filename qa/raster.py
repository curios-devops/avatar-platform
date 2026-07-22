"""Rasterizador 3DGS offline en CPU (EWA splatting) en numpy puro.

Proyecta cada gaussiano 3D a una gaussiana 2D (Jacobiano de la proyección
perspectiva), compone back-to-front con alpha "over", y devuelve el RGB y un
buffer de cobertura (alpha acumulado) para medir huecos.

Determinista: mismas cámaras → mismos píxeles. Sin GPU, sin browser.
Es una aproximación del rasterizador de Spark/INRIA suficiente para juzgar
identidad, huecos y costura en un barrido fijo — no un render de producción.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from splat_io import Gaussians, covariance3d


@dataclass
class Camera:
    R: np.ndarray        # (3,3) world→cam (filas = right, up, forward)
    pos: np.ndarray      # (3,)  posición cámara en mundo
    focal: float         # píxeles
    width: int
    height: int
    bg: tuple


def _look_at(cam_pos: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    forward = target - cam_pos
    forward /= np.linalg.norm(forward) + 1e-9
    right = np.cross(forward, up)
    right /= np.linalg.norm(right) + 1e-9
    true_up = np.cross(right, forward)
    return np.stack([right, true_up, forward]).astype(np.float32)  # z_cam>0 en frente


def scene_frame(g: Gaussians) -> tuple[np.ndarray, float]:
    """Centro (mediana robusta) y radio (percentil 90) para auto-encuadre."""
    center = np.median(g.xyz, axis=0)
    r = float(np.percentile(np.linalg.norm(g.xyz - center, axis=1), 90))
    return center.astype(np.float32), max(r, 1e-3)


def build_camera(spec: dict, cams: dict, center: np.ndarray, radius: float) -> Camera:
    """spec = una entrada de cameras.json['sweep']; distancias = múltiplos de r90."""
    yaw = np.radians(spec["yaw"])
    pitch = np.radians(spec["pitch"])
    mult = cams["distances"][spec["dist"]]
    dist = mult * radius
    # LAM: +Z frontal. yaw=0,pitch=0 → cámara en +Z mirando al centro.
    offset = dist * np.array([
        np.sin(yaw) * np.cos(pitch),
        np.sin(pitch),
        np.cos(yaw) * np.cos(pitch),
    ], dtype=np.float32)
    cam_pos = center + offset
    up = np.array(cams["up"], dtype=np.float32)
    R = _look_at(cam_pos, center, up)
    W = cams["image"]["width"]
    H = cams["image"]["height"]
    focal = (H / 2.0) / np.tan(np.radians(cams["fov_deg"]) / 2.0)
    return Camera(R=R, pos=cam_pos, focal=float(focal), width=W, height=H,
                  bg=tuple(cams.get("background", [0, 0, 0])))


def render(g: Gaussians, cam: Camera) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (rgb uint8 HxWx3, coverage float HxW en [0,1])."""
    W, H, f = cam.width, cam.height, cam.focal
    cx, cy = W / 2.0, H / 2.0

    # 1. a espacio cámara
    cam_xyz = (g.xyz - cam.pos) @ cam.R.T           # (N,3), z>0 en frente
    z = cam_xyz[:, 2]
    front = z > 1e-4
    if not np.any(front):
        bg = np.array(cam.bg, np.uint8)
        return np.tile(bg, (H, W, 1)), np.zeros((H, W), np.float32)

    # 2. covarianza 2D vía Jacobiano  Σ2d = J (R Σ3d R^T) J^T
    cov3d = covariance3d(g)                          # (N,3,3) mundo
    Rw = cam.R
    cov_cam = Rw @ cov3d @ Rw.T                       # (N,3,3)
    x, y = cam_xyz[:, 0], cam_xyz[:, 1]
    inv_z = 1.0 / z
    J = np.zeros((len(g), 2, 3), np.float32)
    J[:, 0, 0] = f * inv_z
    J[:, 0, 2] = -f * x * inv_z * inv_z
    J[:, 1, 1] = f * inv_z
    J[:, 1, 2] = -f * y * inv_z * inv_z
    cov2d = J @ cov_cam @ np.transpose(J, (0, 2, 1))  # (N,2,2)
    cov2d[:, 0, 0] += 0.3                             # blur anti-alias
    cov2d[:, 1, 1] += 0.3

    det = cov2d[:, 0, 0] * cov2d[:, 1, 1] - cov2d[:, 0, 1] * cov2d[:, 1, 0]
    valid = front & (det > 1e-9)
    # centro en pantalla (flip Y a coords de imagen)
    u = cx + f * x * inv_z
    v = cy - f * y * inv_z

    inv_det = np.where(det != 0, 1.0 / det, 0.0)
    # cónica = inv(cov2d)
    con_a = cov2d[:, 1, 1] * inv_det
    con_b = -cov2d[:, 0, 1] * inv_det
    con_c = cov2d[:, 0, 0] * inv_det
    # radio de bbox: √(2·λ_max) ≈ 1.41σ — MISMA truncación del visor WebGPU
    # (webgpu_renderer.ts: quad = sqrt(2·l1)); 3σ integraba demasiada cola y
    # lavaba la cara al solapar miles de splats de baja opacidad.
    mid = 0.5 * (cov2d[:, 0, 0] + cov2d[:, 1, 1])
    lam = mid + np.sqrt(np.maximum(mid * mid - det, 0.0))
    radius = np.ceil(np.sqrt(2.0 * np.maximum(lam, 1e-6))).astype(np.int32)

    on = valid & (u + radius >= 0) & (u - radius < W) & (v + radius >= 0) & (v - radius < H) \
        & (radius < 256)
    idx = np.nonzero(on)[0]
    # front-to-back: NEAR primero + transmitancia (1-cover). Con la fórmula
    # front-to-back hay que iterar cercano→lejano; ordenarlo al revés hacía que
    # los splats del fondo dominaran y borraba los rasgos de la cara.
    idx = idx[np.argsort(z[idx])]

    color = np.zeros((H, W, 3), np.float32)
    cover = np.zeros((H, W), np.float32)             # alpha acumulado "over"

    for i in idx:
        r = int(radius[i])
        ui, vi = u[i], v[i]
        x0, x1 = max(0, int(ui - r)), min(W, int(ui + r) + 1)
        y0, y1 = max(0, int(vi - r)), min(H, int(vi + r) + 1)
        if x0 >= x1 or y0 >= y1:
            continue
        gx = np.arange(x0, x1) - ui
        gy = np.arange(y0, y1) - vi
        dx, dy = np.meshgrid(gx, gy)
        power = -0.5 * (con_a[i] * dx * dx + con_c[i] * dy * dy) - con_b[i] * dx * dy
        alpha = g.opacity[i] * np.exp(np.minimum(power, 0.0))
        alpha = np.clip(alpha, 0.0, 0.99)
        t = 1.0 - cover[y0:y1, x0:x1]                # transmitancia restante
        contrib = alpha * t
        color[y0:y1, x0:x1] += contrib[..., None] * g.rgb[i]
        cover[y0:y1, x0:x1] += contrib

    bg = np.array(cam.bg, np.float32) / 255.0
    rgb = color + (1.0 - cover)[..., None] * bg
    return (np.clip(rgb, 0, 1) * 255).astype(np.uint8), cover


def load_cameras(path: str | Path = None) -> dict:
    path = Path(path) if path else Path(__file__).with_name("cameras.json")
    return json.loads(path.read_text())

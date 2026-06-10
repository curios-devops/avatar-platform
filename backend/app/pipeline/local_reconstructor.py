"""
Local Gaussian reconstructor — no GPU required.

Uses mediapipe face mesh (478 landmarks) + Delaunay triangulation to build
real face geometry, then projects the photo texture onto the surface to colour
every Gaussian.  Runs entirely on CPU in a thread pool.

Three quality improvements vs the naive flat projection:
  1. Sphere-inflated Z depth — nose/cheeks protrude naturally instead of flat mask.
  2. Convex-hull extension — mesh grows 40 % outward to capture hair and neck.
  3. Larger Gaussian scales — 2–6 mm fills the surface without gaps or washed-out dots.
"""

from __future__ import annotations

import asyncio
import io
import logging

import numpy as np
from PIL import Image

from .interfaces import Reconstructor
from .schemas import FlameParams, GaussianSet, GaussianSplat

logger = logging.getLogger(__name__)

N_GAUSSIANS    = 50_000
FLAME_TRIS     = 9_976
SH_C0          = 0.28209479177387814   # DC SH coefficient (matches frontend loader)
HEAD_M         = 0.18                  # target head diameter in metres
SPHERE_DEPTH_M = 0.050                 # max z-protrusion at face centre (50 mm)


class LocalReconstructor(Reconstructor):
    """CPU face reconstruction: mediapipe landmarks + sphere depth + photo texture."""

    async def reconstruct(self, image_bytes: bytes, flame_params: FlameParams) -> GaussianSet:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._reconstruct_sync, image_bytes)

    # ── sync core ─────────────────────────────────────────────────────────────

    def _reconstruct_sync(self, image_bytes: bytes) -> GaussianSet:
        try:
            from scipy.spatial import ConvexHull, Delaunay  # type: ignore[import]
        except ImportError as exc:
            raise RuntimeError(
                "LocalReconstructor requires scipy.  Run:  pip install scipy"
            ) from exc

        from .mediapipe_utils import detect_face_landmarks

        img_pil = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        img_np  = np.array(img_pil, dtype=np.uint8)
        h, w    = img_np.shape[:2]

        # ── face mesh landmarks ───────────────────────────────────────────────
        lms = detect_face_landmarks(img_np, min_detection_confidence=0.4)
        if lms is None:
            raise ValueError("no_face: mediapipe could not detect a face")

        # ── 3-D face vertices (XY only for now; Z added below) ───────────────
        # Normalise XY to head metric scale.
        xy_raw  = np.array([[lm.x - 0.5, -(lm.y - 0.5)] for lm in lms],
                           dtype=np.float32)
        centre2 = xy_raw.mean(axis=0)
        span_xy = xy_raw.max(axis=0) - xy_raw.min(axis=0)
        scale_f = HEAD_M / (span_xy.max() + 1e-8)
        xy_m    = (xy_raw - centre2) * scale_f           # (V, 2), metres

        # ── sphere-inflation depth ────────────────────────────────────────────
        # Model the head as a shallow hemisphere facing the camera.
        # z(r) = SPHERE_DEPTH * sqrt(1 - (r / face_R)²)
        # → nose/forehead centre protrudes SPHERE_DEPTH_M = 25 mm forward,
        #   edges (jaw/temples) sit at z = 0.
        cx, cy    = xy_m[:, 0].mean(), xy_m[:, 1].mean()
        dx        = xy_m[:, 0] - cx
        dy        = xy_m[:, 1] - cy
        r2        = dx**2 + dy**2
        face_R    = np.sqrt(r2).max()
        z_sphere  = SPHERE_DEPTH_M * np.sqrt(np.maximum(0.0, 1.0 - r2 / (face_R**2 + 1e-12)))

        z_m       = z_sphere.astype(np.float32)

        verts_m   = np.column_stack([xy_m[:, 0],
                                     xy_m[:, 1] + 0.05,   # FLAME: origin at neck
                                     z_m]).astype(np.float32)

        # ── 2-D pixel coords for texture ──────────────────────────────────────
        pix_face  = np.array([[lm.x * w, lm.y * h] for lm in lms], dtype=np.float32)

        # ── hair/neck extension ───────────────────────────────────────────────
        # Scale the convex hull of face landmarks outward by 40 % to cover
        # the hair, ears, and neck captured in the padded crop image.
        hull          = ConvexHull(pix_face)
        hull_pix      = pix_face[hull.vertices]           # boundary pixels
        hull_3d       = verts_m[hull.vertices]
        centroid_pix  = pix_face.mean(axis=0)

        ext_pix   = centroid_pix + (hull_pix - centroid_pix) * 1.40
        ext_pix   = np.clip(ext_pix, [2.0, 2.0], [w - 3.0, h - 3.0]).astype(np.float32)

        # 3-D positions of extension ring: same XY mapping, z slightly behind face edge
        ext_xy_raw = np.column_stack(
            [ext_pix[:, 0] / w - 0.5,
             -(ext_pix[:, 1] / h - 0.5)]
        )
        ext_xy_m   = (ext_xy_raw - centre2) * scale_f
        avg_edge_z = hull_3d[:, 2].mean()
        ext_z      = np.full(len(ext_pix), avg_edge_z - 0.008, dtype=np.float32)
        ext_3d     = np.column_stack([ext_xy_m[:, 0],
                                      ext_xy_m[:, 1] + 0.05,
                                      ext_z]).astype(np.float32)

        # Combine face + extension
        pix_all   = np.vstack([pix_face, ext_pix])
        verts_all = np.vstack([verts_m,  ext_3d])

        # ── Delaunay triangulation ─────────────────────────────────────────────
        tri   = Delaunay(pix_all)
        faces = tri.simplices.astype(np.int64)

        # Drop near-degenerate triangles (area < threshold in 3-D)
        v0, v1, v2 = verts_all[faces[:, 0]], verts_all[faces[:, 1]], verts_all[faces[:, 2]]
        areas = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
        keep  = areas > 1e-8
        faces = faces[keep]
        areas = areas[keep]
        logger.info(
            "LocalReconstructor: %d valid triangles (%d landmarks + %d extension pts)",
            len(faces), len(lms), len(ext_pix),
        )

        return self._build_gaussians(img_np, verts_all, pix_all, faces, areas)

    # ── vectorised Gaussian sampler ───────────────────────────────────────────

    def _build_gaussians(
        self,
        img_np:   np.ndarray,   # (H, W, 3) uint8
        verts_m:  np.ndarray,   # (V, 3)   float32, metres
        pix2d:    np.ndarray,   # (V, 2)   float32, pixel coords
        faces:    np.ndarray,   # (F, 3)   int64
        areas:    np.ndarray,   # (F,)     float32, triangle areas
    ) -> GaussianSet:
        img_f32 = img_np.astype(np.float32) / 255.0
        h, w    = img_f32.shape[:2]
        n_faces = len(faces)

        rng = np.random.default_rng(42)

        # Area-weighted face sampling
        probs    = areas / areas.sum()
        face_idx = rng.choice(n_faces, size=N_GAUSSIANS, p=probs)

        # Uniform barycentric coordinates
        r        = rng.random((N_GAUSSIANS, 2)).astype(np.float32)
        swap     = (r[:, 0] + r[:, 1]) > 1.0
        r[swap]  = 1.0 - r[swap]
        r1, r2, r3 = r[:, 0], r[:, 1], 1.0 - r[:, 0] - r[:, 1]

        # 3-D positions
        v0s       = verts_m[faces[face_idx, 0]]
        v1s       = verts_m[faces[face_idx, 1]]
        v2s       = verts_m[faces[face_idx, 2]]
        positions = r1[:, None] * v0s + r2[:, None] * v1s + r3[:, None] * v2s

        # 2-D texture interpolation
        p0s  = pix2d[faces[face_idx, 0]]
        p1s  = pix2d[faces[face_idx, 1]]
        p2s  = pix2d[faces[face_idx, 2]]
        px_f = r1[:, None] * p0s + r2[:, None] * p1s + r3[:, None] * p2s  # (N, 2)

        # Bilinear texture sampling
        ix   = np.clip(px_f[:, 0].astype(np.int32), 0, w - 2)
        iy   = np.clip(px_f[:, 1].astype(np.int32), 0, h - 2)
        fx   = (px_f[:, 0] - ix).astype(np.float32)
        fy   = (px_f[:, 1] - iy).astype(np.float32)
        colors = (
            img_f32[iy,     ix    ] * ((1 - fx) * (1 - fy))[:, None] +
            img_f32[iy,     ix + 1] * (     fx  * (1 - fy))[:, None] +
            img_f32[iy + 1, ix    ] * ((1 - fx) *      fy )[:, None] +
            img_f32[iy + 1, ix + 1] * (     fx  *      fy )[:, None]
        )   # (N, 3) ∈ [0, 1]

        # SH-DC encoding
        sh_dc = (colors - 0.5) / SH_C0

        # Gaussian scales: 2–6 mm (log-uniform), stored as log(metres).
        # Larger than the old 0.5–3 mm → smoother surface, no visible dot gaps.
        log_scales = np.log(rng.uniform(2e-3, 6e-3, N_GAUSSIANS)).astype(np.float32)
        scales     = np.stack([log_scales, log_scales, log_scales], axis=1)

        # Opacity: loader applies sigmoid(raw), so store logit(desired_opacity).
        # logit(p) = log(p / (1-p)).  Targeting true opacity 0.80–0.95 gives
        # logit range ≈ 1.39–2.94, keeping the surface solid without blowout.
        target_op  = rng.uniform(0.80, 0.95, N_GAUSSIANS).astype(np.float32)
        opacities  = np.log(target_op / (1.0 - target_op))              # logit

        # FLAME triangle IDs
        flame_tris = (face_idx % FLAME_TRIS).astype(np.int32)

        # Barycentric coords
        barycs     = np.stack([r1, r2, r3], axis=1)

        splats = [
            GaussianSplat(
                position     = positions[i].tolist(),
                opacity      = float(opacities[i]),
                scale        = scales[i].tolist(),
                rotation     = [1.0, 0.0, 0.0, 0.0],
                sh_dc        = sh_dc[i].tolist(),
                triangle_idx = int(flame_tris[i]),
                barycentric  = barycs[i].tolist(),
            )
            for i in range(N_GAUSSIANS)
        ]
        return GaussianSet(gaussians=splats)

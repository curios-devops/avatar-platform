"""
FLAME-mesh Gaussian reconstructor — CPU, no face detection required.

MVP default: samples N_GAUSSIANS on the FLAME mesh produced by the identity
fit (MICA shape params), colouring each gaussian by orthographic projection
of the aligned frontal photo — the same mapping texture_bake uses.

Advantages over the mediapipe LocalReconstructor:
  - Cannot fail on unusual photos (no face detection — the mesh comes from
    flame_params, which always exist at this stage).
  - triangle_idx is the REAL FLAME triangle the gaussian sits on, with exact
    barycentric coords → animation binding is correct by construction
    (LocalReconstructor approximated with `face_idx % 9976` over a Delaunay
    triangulation that doesn't match FLAME topology).
"""

from __future__ import annotations

import asyncio
import io
import logging

import numpy as np
from PIL import Image

from . import flame_template
from .interfaces import Reconstructor
from .schemas import FlameParams, GaussianSet, GaussianSplat
from .texture_bake import _bilinear, _project_to_photo, _vertex_normals

logger = logging.getLogger(__name__)

N_GAUSSIANS = 50_000
SH_C0 = 0.28209479177387814  # DC SH coefficient (matches frontend loader)

# Back-facing gaussians take the mean front skin tone (same rule as the bake)
_FRONT_FACING_MIN = 0.10


class FlameMeshReconstructor(Reconstructor):
    """Sample photo-coloured gaussians directly on the fitted FLAME mesh."""

    async def reconstruct(
        self, image_bytes: bytes, flame_params: FlameParams
    ) -> GaussianSet:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._reconstruct_sync, image_bytes, flame_params
        )

    def _reconstruct_sync(
        self, image_bytes: bytes, flame_params: FlameParams
    ) -> GaussianSet:
        tpl = flame_template.load()
        shape = np.asarray(flame_params.shape, dtype=np.float32)
        verts = flame_template.apply_shape(tpl, shape)          # (5023, 3)
        faces = tpl.faces.astype(np.int64)                      # (9976, 3)

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        photo = np.asarray(img, dtype=np.float32) / 255.0
        h, w = photo.shape[:2]

        # Per-vertex photo colour (orthographic projection, like texture_bake)
        pix = _project_to_photo(verts, (h, w))
        vert_colors = _bilinear(photo, pix[:, 0], pix[:, 1])    # (V, 3)
        normals = _vertex_normals(verts, faces)
        front = normals[:, 2] > _FRONT_FACING_MIN
        if front.any():
            vert_colors[~front] = vert_colors[front].mean(axis=0)

        # Area-weighted triangle sampling
        v0, v1, v2 = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
        areas = np.linalg.norm(np.cross(v1 - v0, v2 - v0), axis=1)
        probs = areas / areas.sum()

        rng = np.random.default_rng(42)
        face_idx = rng.choice(len(faces), size=N_GAUSSIANS, p=probs)

        r = rng.random((N_GAUSSIANS, 2)).astype(np.float32)
        swap = (r[:, 0] + r[:, 1]) > 1.0
        r[swap] = 1.0 - r[swap]
        r1, r2 = r[:, 0], r[:, 1]
        r3 = 1.0 - r1 - r2

        tri = faces[face_idx]
        positions = (r1[:, None] * verts[tri[:, 0]] +
                     r2[:, None] * verts[tri[:, 1]] +
                     r3[:, None] * verts[tri[:, 2]])
        colors = (r1[:, None] * vert_colors[tri[:, 0]] +
                  r2[:, None] * vert_colors[tri[:, 1]] +
                  r3[:, None] * vert_colors[tri[:, 2]])
        sh_dc = (colors - 0.5) / SH_C0

        # Scales 2–6 mm log-uniform; opacity stored as logit (loader sigmoids)
        log_scales = np.log(rng.uniform(2e-3, 6e-3, N_GAUSSIANS)).astype(np.float32)
        target_op = rng.uniform(0.80, 0.95, N_GAUSSIANS).astype(np.float32)
        opacities = np.log(target_op / (1.0 - target_op))

        barycs = np.stack([r1, r2, r3], axis=1)

        splats = [
            GaussianSplat(
                position     = positions[i].tolist(),
                opacity      = float(opacities[i]),
                scale        = [float(log_scales[i])] * 3,
                rotation     = [1.0, 0.0, 0.0, 0.0],
                sh_dc        = sh_dc[i].tolist(),
                triangle_idx = int(face_idx[i]),
                barycentric  = barycs[i].tolist(),
            )
            for i in range(N_GAUSSIANS)
        ]
        logger.info(
            "FlameMeshReconstructor: %d gaussians on FLAME mesh (exact binding)",
            N_GAUSSIANS,
        )
        return GaussianSet(gaussians=splats)

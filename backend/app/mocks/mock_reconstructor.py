import math
import random

# Gaussian Splatting convention: scale is stored as log(metres).
# The frontend loader applies Math.exp() to recover the actual scale.
# A head splat of 1–3 mm → log(0.001) ≈ -6.9,  log(0.003) ≈ -5.8

from ..pipeline.interfaces import Reconstructor
from ..pipeline.schemas import FlameParams, GaussianSet, GaussianSplat

FLAME_TRIANGLE_COUNT = 9976  # FLAME 2023 topology
NUM_GAUSSIANS = 50_000


class MockReconstructor(Reconstructor):
    """
    Mock Gaussian reconstructor. Emits a synthetic but schema-valid Gaussian set:
    - All Gaussians are positioned on a rough ellipsoidal head surface.
    - Every Gaussian is bound to a valid FLAME triangle (triangle_idx in range).
    - Barycentric coordinates sum exactly to 1.0 for each Gaussian.
    - Output is deterministic (seeded RNG).

    TODO(integration): Replace with LamReconstructor for real GPU-based reconstruction:
      1. pip install <LAM package> (see LAM repo README for exact install steps).
      2. In __init__, load LAM model weights from disk:
             self.model = LAM.load(weights_path)
      3. In reconstruct(), run inference:
             raw = self.model.infer(image_bytes, flame_params)
      4. Convert raw LAM output (positions, opacities, SH coefficients, binding)
         into GaussianSet / GaussianSplat schema objects and return.
      The real reconstructor must honour the same Reconstructor ABC interface —
      no other pipeline stages need to change.
    """

    async def reconstruct(self, image_bytes: bytes, flame_params: FlameParams) -> GaussianSet:
        rng = random.Random(42)
        splats: list[GaussianSplat] = []

        for _ in range(NUM_GAUSSIANS):
            # Rough spherical shell approximating a human head
            theta = rng.uniform(0, math.pi)
            phi = rng.uniform(0, 2 * math.pi)
            r = rng.uniform(0.08, 0.12)
            x = r * math.sin(theta) * math.cos(phi)
            y = r * math.cos(theta) + 0.05   # shift up from neck origin
            z = r * math.sin(theta) * math.sin(phi)

            # Valid barycentric triple summing to 1
            a = rng.random()
            b = rng.random() * (1.0 - a)
            c = 1.0 - a - b

            # store log(scale) so the loader's Math.exp() gives metres
            log_s = math.log(rng.uniform(5e-4, 3e-3))

            splats.append(
                GaussianSplat(
                    position=[x, y, z],
                    opacity=rng.uniform(0.7, 1.0),
                    scale=[log_s, log_s, log_s],
                    rotation=[1.0, 0.0, 0.0, 0.0],  # identity quaternion
                    sh_dc=[rng.uniform(0.5, 0.9)] * 3,
                    triangle_idx=rng.randint(0, FLAME_TRIANGLE_COUNT - 1),
                    barycentric=[a, b, c],
                )
            )

        return GaussianSet(gaussians=splats)

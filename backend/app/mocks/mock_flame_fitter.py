import random
from ..pipeline.interfaces import FlameFitter
from ..pipeline.schemas import FlameParams


class MockFlameFitter(FlameFitter):
    """
    Deterministic mock FLAME fitter.
    Returns a fixed neutral-expression parameter set seeded from a constant RNG.
    The neutral expression (all-zero expression coefficients) is intentional.

    TODO(integration): Replace with a real FLAME fitter, e.g. DECA or EMOCA:
      pip install git+https://github.com/YadiraF/DECA.git
      Implement fit() by running DECA inference on the 512×512 aligned image.
      Output must map to FlameParams(shape, expression, pose, tex).
    """

    async def fit(self, image_bytes: bytes) -> FlameParams:
        rng = random.Random(42)  # deterministic — same image always yields same params
        return FlameParams(
            shape=[rng.gauss(0, 0.3) for _ in range(300)],
            expression=[0.0] * 100,   # neutral
            pose=[0.0] * 6,           # neutral jaw + neck + global
            tex=[rng.gauss(0, 0.1) for _ in range(50)],
        )

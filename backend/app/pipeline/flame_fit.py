from .interfaces import FlameFitter
from .schemas import FlameParams


async def flame_fit(image_bytes: bytes, fitter: FlameFitter) -> FlameParams:
    """
    Estimate FLAME parameters from a preprocessed (512×512) face image.
    Delegates entirely to the injected FlameFitter; no model details leak here.
    """
    return await fitter.fit(image_bytes)

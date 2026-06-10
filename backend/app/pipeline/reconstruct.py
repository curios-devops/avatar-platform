from .interfaces import Reconstructor
from .schemas import FlameParams, GaussianSet


async def reconstruct(
    image_bytes: bytes,
    flame_params: FlameParams,
    reconstructor: Reconstructor,
) -> GaussianSet:
    """
    Reconstruct Gaussian splats from the face image guided by FLAME parameters.
    Delegates to the injected Reconstructor; swap MockReconstructor for
    LamReconstructor when GPU + LAM weights are available.
    """
    return await reconstructor.reconstruct(image_bytes, flame_params)

from abc import ABC, abstractmethod
from .schemas import FlameParams, GaussianSet


class FlameFitter(ABC):
    @abstractmethod
    async def fit(self, image_bytes: bytes) -> FlameParams:
        """
        Fit FLAME model to an aligned 512×512 face image.
        Returns FlameParams (shape 300, expression 100, pose 6, tex 50).
        """
        ...


class Reconstructor(ABC):
    @abstractmethod
    async def reconstruct(self, image_bytes: bytes, flame_params: FlameParams) -> GaussianSet:
        """
        Reconstruct Gaussian splats from a face image guided by FLAME params.
        Every returned GaussianSplat must carry a valid triangle_idx and barycentric
        coords summing to 1.0 so the rig stage can validate without extra I/O.

        TODO(integration): Replace MockReconstructor with RunPodReconstructor.
          RunPod endpoint must have LAM weights installed.
          See worker/avatar_worker/handler.py for the GPU worker contract.
        """
        ...

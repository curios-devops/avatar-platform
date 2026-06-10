"""
Local FLAME fitter — no GPU required.

Uses mediapipe face mesh to estimate approximate FLAME pose parameters
(head rotation) from the aligned 512×512 face image.
Shape, expression, and tex coefficients are returned as neutral (zeros),
which is correct for a frontal aligned image and is sufficient for the
rig/animation stages.
"""

from __future__ import annotations

import asyncio
import io
import logging
import math

from PIL import Image

from .interfaces import FlameFitter
from .schemas import FlameParams

logger = logging.getLogger(__name__)


class LocalFlameFitter(FlameFitter):
    """CPU FLAME fitter using mediapipe face geometry."""

    async def fit(self, image_bytes: bytes) -> FlameParams:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fit_sync, image_bytes)

    def _fit_sync(self, image_bytes: bytes) -> FlameParams:
        try:
            import numpy as np
            from .mediapipe_utils import detect_face_landmarks

            img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            img_np = np.array(img)

            lms = detect_face_landmarks(img_np)

            pose = [0.0] * 6
            if lms is not None:
                # Rough head pitch from nose tip vs forehead vertical offset
                nose_tip = lms[1]
                forehead = lms[10]
                pitch = math.atan2(nose_tip.z - forehead.z,
                                   abs(nose_tip.y - forehead.y))
                pose[3] = float(pitch)   # global x-rotation ≈ head nod

        except Exception as exc:
            logger.warning("LocalFlameFitter mediapipe failed (%s), returning neutral pose", exc)
            pose = [0.0] * 6

        return FlameParams(
            shape=[0.0] * 300,       # neutral mean face
            expression=[0.0] * 100,  # neutral expression
            pose=pose,
            tex=[0.0] * 50,
        )

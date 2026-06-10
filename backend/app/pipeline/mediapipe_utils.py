"""
Mediapipe 0.10+ face landmark helpers.

The 0.10+ Tasks API requires a model .task file. This module downloads it
once to ~/.cache/mediapipe and reuses it on every subsequent call.
"""
from __future__ import annotations

import logging
import os
import urllib.request

import numpy as np

logger = logging.getLogger(__name__)

_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/"
    "face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "mediapipe")
_MODEL_PATH = os.path.join(_CACHE_DIR, "face_landmarker.task")


def ensure_model() -> str:
    """Return path to face_landmarker.task, downloading if needed."""
    if not os.path.exists(_MODEL_PATH):
        os.makedirs(_CACHE_DIR, exist_ok=True)
        logger.info("Downloading mediapipe face_landmarker model → %s", _MODEL_PATH)
        urllib.request.urlretrieve(_MODEL_URL, _MODEL_PATH)
        logger.info("face_landmarker model downloaded (%d bytes)", os.path.getsize(_MODEL_PATH))
    return _MODEL_PATH


def detect_face_landmarks(img_np: np.ndarray, min_detection_confidence: float = 0.4):
    """
    Run FaceLandmarker on a uint8 RGB numpy array.

    Returns list of NormalizedLandmark (478 items, same .x/.y/.z attributes
    as the old mp.solutions.face_mesh API), or None if no face detected.
    """
    import mediapipe as mp
    from mediapipe.tasks import python
    from mediapipe.tasks.python import vision

    model_path = ensure_model()
    base_options = python.BaseOptions(model_asset_path=model_path)
    options = vision.FaceLandmarkerOptions(
        base_options=base_options,
        running_mode=vision.RunningMode.IMAGE,
        num_faces=1,
        min_face_detection_confidence=min_detection_confidence,
    )

    with vision.FaceLandmarker.create_from_options(options) as landmarker:
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(img_np))
        result = landmarker.detect(mp_image)

    if not result.face_landmarks:
        return None
    return result.face_landmarks[0]  # list of NormalizedLandmark (.x, .y, .z)

import io
from PIL import Image


def detect_faces_mock(image_bytes: bytes) -> list[dict]:
    """
    Mock face detector. Returns a single synthetic frontal face bbox for any
    valid image, or an empty list if the image cannot be decoded.
    bbox format: [x0, y0, x1, y1] normalized 0–1.

    TODO(integration): Replace with a real CPU face detector, e.g.:
      - MediaPipe FaceDetector (pip install mediapipe)
      - InsightFace RetinaFace (pip install insightface)
      - OpenCV DNN + res10_300x300_ssd_iter_140000.caffemodel
    The replacement must return the same list[{"bbox": [...], "confidence": float}] shape.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
    except Exception:
        return []

    # Synthetic centred frontal bbox: covers ~60 % of the frame horizontally
    return [{"bbox": [0.20, 0.10, 0.80, 0.90], "confidence": 0.99}]

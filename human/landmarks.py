"""MediaPipe face landmarks for one or more images, as JSON on stdout.

Runs with the backend venv (Python 3.9 has mediapipe; the human venv on 3.14 does not):
    ../backend/.venv/bin/python landmarks.py a.png b.jpg
Output: {"a.png": [[x_px, y_px, z], ...478] | null, ...}
"""
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from app.pipeline.mediapipe_utils import detect_face_landmarks  # noqa: E402

out = {}
for path in sys.argv[1:]:
    img = np.asarray(Image.open(path).convert("RGB"))
    lms = detect_face_landmarks(img, min_detection_confidence=0.3)
    h, w = img.shape[:2]
    out[path] = None if lms is None else [[p.x * w, p.y * h, p.z * w] for p in lms]
print(json.dumps(out))

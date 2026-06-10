from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Callable, Union

from PIL import Image

MIN_DIM = 256
MAX_SIZE_MB = 20
SUPPORTED_FORMATS = {"JPEG", "PNG", "WEBP"}


@dataclass
class IngestError:
    code: str
    reason: str


@dataclass
class IngestSuccess:
    width: int
    height: int
    face_count: int
    face_bbox: list  # [x0, y0, x1, y1] normalized 0–1


def ingest(
    image_bytes: bytes,
    detect_faces: Callable[[bytes], list[dict]],
) -> IngestSuccess | IngestError:
    """
    Validate a photo for the avatar pipeline.
    Rejects: wrong format, oversized, too small, zero faces, multiple faces, off-angle.
    Returns IngestSuccess or IngestError with a structured code + reason.
    """
    if len(image_bytes) > MAX_SIZE_MB * 1024 * 1024:
        return IngestError(code="too_large", reason=f"Image exceeds {MAX_SIZE_MB} MB limit")

    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
        img = Image.open(io.BytesIO(image_bytes))  # reopen after verify (verify closes)
    except Exception as exc:
        return IngestError(code="invalid_image", reason=f"Cannot decode image: {exc}")

    if img.format not in SUPPORTED_FORMATS:
        return IngestError(
            code="invalid_format",
            reason=f"Format '{img.format}' not supported; use JPEG, PNG, or WEBP",
        )

    w, h = img.size
    if w < MIN_DIM or h < MIN_DIM:
        return IngestError(
            code="too_small",
            reason=f"Image {w}×{h} is below the {MIN_DIM}px minimum in both dimensions",
        )

    faces = detect_faces(image_bytes)

    if len(faces) == 0:
        return IngestError(code="no_face", reason="No face detected in the image")

    if len(faces) > 1:
        return IngestError(
            code="multiple_faces",
            reason=f"Found {len(faces)} faces; exactly one face is required",
        )

    bbox = faces[0]["bbox"]  # [x0, y0, x1, y1] normalized
    face_cx = (bbox[0] + bbox[2]) / 2
    if face_cx < 0.15 or face_cx > 0.85:
        return IngestError(
            code="off_angle",
            reason="Face center is too far off-axis; use a near-frontal photo",
        )

    return IngestSuccess(width=w, height=h, face_count=1, face_bbox=bbox)

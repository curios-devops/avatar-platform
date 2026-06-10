import io
from PIL import Image

TARGET_SIZE = 512


def preprocess(image_bytes: bytes, face_bbox: list[float]) -> bytes:
    """
    Align, crop, and normalize the face image to TARGET_SIZE × TARGET_SIZE JPEG.
    face_bbox: [x0, y0, x1, y1] normalized 0–1 (from ingest stage).
    Returns JPEG bytes of the aligned face crop.
    """
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size

    x0 = int(face_bbox[0] * w)
    y0 = int(face_bbox[1] * h)
    x1 = int(face_bbox[2] * w)
    y1 = int(face_bbox[3] * h)

    # Add 20 % padding so ears and chin are included
    pad_x = int((x1 - x0) * 0.20)
    pad_y = int((y1 - y0) * 0.20)
    x0 = max(0, x0 - pad_x)
    y0 = max(0, y0 - pad_y)
    x1 = min(w, x1 + pad_x)
    y1 = min(h, y1 + pad_y)

    # Force square crop centred on the face
    cx = (x0 + x1) // 2
    cy = (y0 + y1) // 2
    half = max(x1 - x0, y1 - y0) // 2
    x0 = max(0, cx - half)
    y0 = max(0, cy - half)
    x1 = min(w, cx + half)
    y1 = min(h, cy + half)

    cropped = img.crop((x0, y0, x1, y1))
    resized = cropped.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)

    buf = io.BytesIO()
    resized.save(buf, format="JPEG", quality=95)
    return buf.getvalue()

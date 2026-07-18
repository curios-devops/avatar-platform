"""Backend Veo 2 (Vertex AI, proyecto curios-vertex) para make_clips.py.

Image-to-video: la foto reencuadrada (medio cuerpo) es el primer frame y el
prompt manda la actitud/gesto. Corre desde el portátil — sin pod GPU.

Auth: ADC (gcloud auth application-default login) o service account
(GOOGLE_APPLICATION_CREDENTIALS). Región us-central1 (donde vive Veo 2).
Flujo: :predictLongRunning → poll :fetchPredictOperation → MP4 en base64.
"""
from __future__ import annotations

import base64
import time
from pathlib import Path

import httpx

_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_creds = None


def _token() -> str:
    global _creds
    if _creds is None:
        import google.auth
        _creds, _ = google.auth.default(scopes=[_SCOPE])
    if not _creds.valid:
        import google.auth.transport.requests
        _creds.refresh(google.auth.transport.requests.Request())
    return _creds.token


def generate_clip(
    photo: Path,
    prompt: str,
    out: Path,
    seconds: int = 8,
    project: str = "curios-vertex",
    location: str = "us-central1",
    model: str = "veo-2.0-generate-001",
    timeout_s: int = 600,
) -> Path:
    base = (f"https://{location}-aiplatform.googleapis.com/v1/projects/{project}"
            f"/locations/{location}/publishers/google/models/{model}")
    headers = {"Authorization": f"Bearer {_token()}"}
    body = {
        "instances": [{
            "prompt": prompt,
            "image": {
                "bytesBase64Encoded": base64.b64encode(photo.read_bytes()).decode(),
                "mimeType": "image/jpeg",
            },
        }],
        "parameters": {
            "durationSeconds": max(5, min(8, seconds)),  # Veo 2: 5-8 s
            "aspectRatio": "9:16",                        # Feed vertical (A4)
            "sampleCount": 1,
            "personGeneration": "allow_adult",
        },
    }
    r = httpx.post(f"{base}:predictLongRunning", json=body, headers=headers, timeout=60)
    r.raise_for_status()
    op_name = r.json()["name"]
    print(f"    veo op: …{op_name[-28:]}")

    t0 = time.time()
    while time.time() - t0 < timeout_s:
        time.sleep(15)
        pr = httpx.post(f"{base}:fetchPredictOperation",
                        json={"operationName": op_name},
                        headers={"Authorization": f"Bearer {_token()}"}, timeout=60)
        pr.raise_for_status()
        op = pr.json()
        if op.get("done"):
            if "error" in op:
                raise RuntimeError(f"Veo error: {op['error']}")
            videos = op.get("response", {}).get("videos", [])
            if not videos:
                raise RuntimeError(f"Veo sin videos en la respuesta: {str(op)[:400]}")
            v = videos[0]
            if "bytesBase64Encoded" in v:
                out.write_bytes(base64.b64decode(v["bytesBase64Encoded"]))
            elif "gcsUri" in v:
                raise RuntimeError(f"Veo devolvió gcsUri (configura storageUri o descarga): {v['gcsUri']}")
            else:
                raise RuntimeError(f"formato de video desconocido: {list(v)}")
            return out
        print(f"    …generando ({int(time.time()-t0)}s)")
    raise TimeoutError(f"Veo no completó en {timeout_s}s")

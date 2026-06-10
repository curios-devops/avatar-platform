# Photo → FLAME-rigged Gaussian Head Pipeline

Refactor of the production avatar pipeline.  
Input: one uploaded portrait photo.  
Output: `AvatarBundle` — FLAME-rigged Gaussian head asset ready for animation.

---

## Table of contents

1. [Architecture](#architecture)
2. [Module layout](#module-layout)
3. [Pipeline stages](#pipeline-stages)
4. [AvatarBundle contract](#avatarbundle-contract)
5. [Running locally (mocks, no GPU)](#running-locally-mocks-no-gpu)
6. [Cloudflare R2 storage setup](#cloudflare-r2-storage-setup)
7. [RunPod GPU endpoints setup](#runpod-gpu-endpoints-setup)
8. [Wiring real LAM + DECA](#wiring-real-lam--deca)
9. [API reference](#api-reference)
10. [Testing together — checklist](#testing-together--checklist)

---

## Architecture

```
Browser / client
      │
      │  POST /api/v1/avatar/upload   (existing — untouched)
      │  ← { video_url: "https://..." }          (R2 presigned URL)
      │
      │  POST /api/v1/avatar/process
      │    { photo_url }
      │  ← { id: job_id, status: "processing", progress: 0 }
      │
      │  GET  /api/v1/avatar/job/{job_id}/status  (poll every 2 s)
      │  ← { status, progress, result: AvatarBundle | { stage } }
      │
      │  GET  /api/v1/avatar/job/{job_id}/preview
      │  ← { preview_url, job_id }               (UI shortcut)
      │
      ▼
  FastAPI BackgroundTask
      │
      ▼
  Pipeline stages (sequential, status written to Redis after each)
  ┌──────────┬───────────────────────────────────────────────────────┐
  │ Stage    │ What it does                                          │
  ├──────────┼───────────────────────────────────────────────────────┤
  │ download │ Fetch photo bytes from the uploaded R2 URL            │
  │ ingest   │ Validate format/size, face count, off-angle rejection │
  │ preprocess│ Align, crop with 20 % padding, resize to 512 × 512  │
  │ flame_fit│ Estimate FLAME params (shape 300, expr 100, pose 6)   │
  │reconstruct│ Reconstruct 50 k Gaussian splats, each FLAME-bound  │
  │ rig      │ Validate binding table completeness                   │
  │ package  │ Assemble .ply / .json / .npz / .glb / .png artifacts │
  │ publish  │ Upload all artifacts to R2, return AvatarBundle URLs  │
  └──────────┴───────────────────────────────────────────────────────┘
      │
      ▼
  Cloudflare R2
  avatars/{job_id}/
    gaussians.ply
    flame_params.json
    gaussian_flame_binding.npz
    teeth.glb
    neutral_front.png          ← UI preview
```

### Backend selection (flame_fit + reconstruct)

| `RUNPOD_FLAME_ENDPOINT_ID` | `RUNPOD_RECONSTRUCT_ENDPOINT_ID` | `MOCK_PIPELINE` | Backend used |
|---|---|---|---|
| set | set | false | **RunPod** (real GPU — DECA + LAM) |
| missing or blank | — | — | **Mock** (deterministic, no GPU) |
| set | set | true | **Mock** (forced, useful for local dev) |

---

## Module layout

```
backend/app/
├── api/
│   └── avatar.py                 # POST /avatar/upload (untouched)
│                                 # POST /avatar/process  ← NEW
│                                 # GET  /avatar/job/{id}/status
│                                 # GET  /avatar/job/{id}/preview  ← NEW
│
├── pipeline/
│   ├── interfaces.py             # FlameFitter ABC, Reconstructor ABC
│   ├── schemas.py                # All stage I/O models + AvatarBundle
│   ├── ingest.py                 # Format / size / face validation
│   ├── preprocess.py             # Align, crop, normalize
│   ├── flame_fit.py              # Delegates to FlameFitter
│   ├── reconstruct.py            # Delegates to Reconstructor
│   ├── rig.py                    # Validate FLAME binding table
│   ├── package.py                # Build artifact bytes
│   ├── publish.py                # Upload to R2, return AvatarBundle
│   ├── runpod_fitter.py          # RunPodFlameFitter (real GPU)
│   └── runpod_reconstructor.py   # RunPodReconstructor (real GPU)
│
├── mocks/
│   ├── mock_face_detector.py     # Returns one synthetic bbox
│   ├── mock_flame_fitter.py      # Seeded-RNG FLAME params
│   └── mock_reconstructor.py     # 50 k spherical Gaussians, all bound
│
├── workers/
│   └── pipeline_worker.py        # Orchestrates stages; selects mock vs RunPod
│
└── services/
    ├── storage.py                # R2-backed S3-compat upload / URL generation
    └── queue.py                  # Redis job status tracking

worker/avatar_worker/
├── handler.py                    # RunPod GPU worker (DECA + LAM)
├── requirements.txt
└── (model weights via Network Volume at /weights/)

docker/
└── avatar_worker.Dockerfile      # GPU worker Docker image
```

---

## Pipeline stages

### 1. ingest — `pipeline/ingest.py`

Rejects early with a structured `IngestError(code, reason)`.  
Rejection codes:

| Code | Condition |
|---|---|
| `too_large` | File > `MAX_PHOTO_SIZE_MB` (default 20 MB) |
| `invalid_format` | Not JPEG / PNG / WEBP |
| `invalid_image` | Corrupt / undecodable |
| `too_small` | Width or height < 256 px |
| `no_face` | Zero faces detected |
| `multiple_faces` | More than one face detected |
| `off_angle` | Face centre x < 15 % or > 85 % of frame width |

Any rejection stops the pipeline immediately; the job is marked `failed` with the structured reason. The reconstruct stage is never reached.

---

### 2. preprocess — `pipeline/preprocess.py`

1. Converts to RGB.
2. Expands face bbox by 20 % on each side (includes chin, ears).
3. Forces a square crop centred on the face.
4. Resizes to **512 × 512** with Lanczos.
5. Returns JPEG bytes (quality 95).

---

### 3. flame_fit — `pipeline/flame_fit.py` + `pipeline/interfaces.py`

Calls `await fitter.fit(aligned_bytes) → FlameParams`.

`FlameParams` schema:

```python
class FlameParams(BaseModel):
    shape:      list[float]  # 300 coefficients
    expression: list[float]  # 100 coefficients (neutral = all zeros)
    pose:       list[float]  # 6  coefficients (jaw, neck, global rotation)
    tex:        list[float]  # 50 coefficients
```

Real implementation: **DECA** or **EMOCA** running on RunPod GPU worker.  
Swap point: `RunPodFlameFitter` in `pipeline/runpod_fitter.py`.

---

### 4. reconstruct — `pipeline/reconstruct.py` + `pipeline/interfaces.py`

Calls `await reconstructor.reconstruct(aligned_bytes, flame_params) → GaussianSet`.

Every `GaussianSplat` in the set must carry:
- `triangle_idx` in `[0, 9975]` (FLAME 2023 topology: 9 976 triangles)
- `barycentric` summing to **1.0** within 1 × 10⁻⁴

The binding is validated by the next stage; an invalid binding is a **hard failure**.

Real implementation: **LAM** running on RunPod GPU worker.  
Swap point: `RunPodReconstructor` in `pipeline/runpod_reconstructor.py`.

---

### 5. rig — `pipeline/rig.py`

Validates the full binding table (every Gaussian checked).  
Emits `BindingTable`:

```python
class BindingTable(BaseModel):
    gaussian_count:       int
    flame_triangle_count: int        # pinned to 9976
    unmodeled:            list[str]  # ["tongue", "mouth_interior_detail"]
    is_complete:          bool
```

`unmodeled` surfaces intentional gaps — tongue and mouth interior are not reconstructed. Downstream animation code must handle these explicitly; they are not hidden.

---

### 6. package — `pipeline/package.py`

Raises `ValueError` (hard failure) if binding is incomplete, params missing, or Gaussian set empty. Builds:

| File | Format | Contents |
|---|---|---|
| `gaussians.ply` | ASCII PLY | Position, opacity, scale, rotation, SH-DC, triangle_idx, barycentric |
| `flame_params.json` | JSON | shape, expression, pose, tex, topology_version |
| `gaussian_flame_binding.npz` | NumPy NPZ | `triangle_indices` int32 (N,), `barycentric` float32 (N, 3) |
| `teeth.glb` | Binary glTF | Minimal proxy mesh (placeholder) |
| `neutral_front.png` | PNG 512 × 512 | Aligned face crop — UI preview |

---

### 7. publish — `pipeline/publish.py`

Uploads all artifact bytes to R2 under `avatars/{job_id}/`.  
Returns `AvatarBundle` with final URLs.

---

## AvatarBundle contract

```json
{
  "version": "1.0",
  "coordinate_system": "y_up_right_handed",
  "scale_units": "meters",
  "gaussians":   "https://.../avatars/{job_id}/gaussians.ply",
  "flame": {
    "params":           "https://.../avatars/{job_id}/flame_params.json",
    "topology_version": "FLAME_2023"
  },
  "binding":       "https://.../avatars/{job_id}/gaussian_flame_binding.npz",
  "teeth_proxy":   "https://.../avatars/{job_id}/teeth.glb",
  "expression_basis": "ARKit_52",
  "unmodeled":     ["tongue", "mouth_interior_detail"],
  "preview":       "https://.../avatars/{job_id}/neutral_front.png"
}
```

`topology_version` is pinned. If FLAME topology ever drifts, the binding indices become invalid and animation silently breaks — changing this field is a breaking change.

`expression_basis: "ARKit_52"` means the animation layer expects 52 ARKit blend-shape targets as the expression driving signal.

---

## Running locally (mocks, no GPU)

```bash
# 1. Copy env template
cp .env.example .env

# 2. Edit .env — set MOCK_PIPELINE=true and leave RunPod endpoint IDs blank.
#    R2 credentials are still required (or use a local MinIO for storage).

# 3. Start Redis
docker run -d -p 6379:6379 redis:7-alpine

# 4. Start backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The server starts with `MockFlameFitter` + `MockReconstructor`.  
Logs will show: `Using MockFlameFitter (no GPU)` and `Using MockReconstructor (no GPU)`.

### Quick smoke test (curl)

```bash
# Upload a portrait photo (existing endpoint — untouched)
curl -s -X POST http://localhost:8000/api/v1/avatar/upload \
  -F "file=@/path/to/portrait.jpg" | jq .
# → { "video_url": "https://..." }

# Start the pipeline
curl -s -X POST http://localhost:8000/api/v1/avatar/process \
  -H "Content-Type: application/json" \
  -d '{"photo_url": "THE_URL_FROM_ABOVE"}' | jq .
# → { "id": "avatar_pipeline_XXXXX", "status": "processing", "progress": 0 }

# Poll status
JOB_ID="avatar_pipeline_XXXXX"
curl -s http://localhost:8000/api/v1/avatar/job/$JOB_ID/status | jq .
# → { "status": "processing", "progress": 0.55, "result": {"stage": "reconstruct"} }
# → { "status": "done", "progress": 1.0, "result": { ...AvatarBundle... } }

# Get just the preview URL
curl -s http://localhost:8000/api/v1/avatar/job/$JOB_ID/preview | jq .
# → { "preview_url": "https://.../neutral_front.png", "job_id": "..." }
```

---

## Cloudflare R2 storage setup

### 1. Create bucket

Cloudflare Dashboard → **R2** → **Create bucket** → name: `avatar-platform`.

### 2. Create API token

Dashboard → R2 → **Manage R2 API Tokens** → **Create API token**

- Permissions: **Object Read & Write**
- Scope: **Specific bucket** → `avatar-platform`

Copy **Access Key ID** and **Secret Access Key**.

### 3. Get account ID

Dashboard → right sidebar → **Account ID** (32-char hex string).

### 4. Set env vars

```bash
S3_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
S3_ACCESS_KEY=<ACCESS_KEY_ID>
S3_SECRET_KEY=<SECRET_ACCESS_KEY>
S3_BUCKET_NAME=avatar-platform
S3_REGION=auto
```

### 5. Optional: public URLs (no presigning)

For a stable, non-expiring preview URL (recommended for production):

1. In R2 bucket settings → **Allow Public Access** → enable.
2. Either use the managed `pub-HASH.r2.dev` domain, or connect a custom domain.
3. Set in `.env`:

```bash
STORAGE_PUBLIC_BASE_URL=https://pub-YOURHASH.r2.dev
# or
STORAGE_PUBLIC_BASE_URL=https://assets.yourdomain.com
```

When set, `get_url()` returns `{base}/{object_key}` — no presigning, no expiry.  
When blank, all URLs are presigned with 1-hour expiry.

---

## RunPod GPU endpoints setup

### Overview

Two separate RunPod Serverless endpoints share one Docker image (`docker/avatar_worker.Dockerfile`). The handler routes by `job_type` field.

```
RUNPOD_FLAME_ENDPOINT_ID       → job_type: "flame_fit"   (DECA)
RUNPOD_RECONSTRUCT_ENDPOINT_ID → job_type: "reconstruct" (LAM)
```

### 1. Build and push the worker image

```bash
# Build
docker build -f docker/avatar_worker.Dockerfile -t avatar-worker:latest .

# Tag for your registry (Docker Hub or RunPod's registry)
docker tag avatar-worker:latest YOUR_DOCKERHUB/avatar-worker:latest
docker push YOUR_DOCKERHUB/avatar-worker:latest
```

### 2. Create RunPod Network Volume for model weights

Dashboard → **Storage** → **+ Network Volume**

- Name: `avatar-weights`
- Size: 30 GB (DECA ~2 GB, LAM ~10 GB, buffer for updates)
- Mount path in container: `/weights`

Upload weights:
```
/weights/
  deca/
    deca_model.tar          # from DECA repo releases
  lam/
    lam_model.pt            # from LAM repo releases
```

### 3. Create the FLAME fitting endpoint

Dashboard → **Serverless** → **+ New Endpoint**

| Setting | Value |
|---|---|
| Name | `avatar-flame-fit` |
| Docker image | `YOUR_DOCKERHUB/avatar-worker:latest` |
| GPU type | RTX 3090 or A4000 (DECA is light) |
| Min workers | 0 (scale to zero) |
| Max workers | 3 |
| Network Volume | `avatar-weights` mounted at `/weights` |
| Container disk | 10 GB |

Copy the endpoint ID → set `RUNPOD_FLAME_ENDPOINT_ID` in `.env`.

### 4. Create the reconstruction endpoint

Same settings, but:

| Setting | Value |
|---|---|
| Name | `avatar-reconstruct` |
| GPU type | RTX 4090 or A100 (LAM is heavier) |
| Max workers | 2 |

Copy the endpoint ID → set `RUNPOD_RECONSTRUCT_ENDPOINT_ID` in `.env`.

### 5. Verify endpoints are live

```bash
# Test FLAME endpoint (replace with your values)
curl -s -X POST https://api.runpod.ai/v2/$RUNPOD_FLAME_ENDPOINT_ID/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input": {"job_type": "flame_fit", "image_b64": "'"$(base64 -i portrait.jpg)"'"}}' \
  | jq .output
# → { "shape": [...], "expression": [...], "pose": [...], "tex": [...] }
```

### RunPod job protocol

**FLAME fitting input:**
```json
{
  "input": {
    "job_type": "flame_fit",
    "image_b64": "<base64 encoded 512×512 aligned JPEG>"
  }
}
```

**FLAME fitting output:**
```json
{
  "shape":      [/* 300 floats */],
  "expression": [/* 100 floats */],
  "pose":       [/* 6 floats */],
  "tex":        [/* 50 floats */]
}
```

**Reconstruction input:**
```json
{
  "input": {
    "job_type": "reconstruct",
    "image_b64": "<base64 encoded 512×512 aligned JPEG>",
    "flame_params": {
      "shape": [/* 300 */], "expression": [/* 100 */],
      "pose": [/* 6 */],    "tex": [/* 50 */]
    }
  }
}
```

**Reconstruction output:**
```json
{
  "gaussians_npz_b64": "<base64 encoded NPZ>"
}
```

The NPZ must contain arrays:

| Key | dtype | Shape | Notes |
|---|---|---|---|
| `position` | float32 | (N, 3) | Metres, y-up right-handed |
| `opacity` | float32 | (N,) | [0, 1] |
| `scale` | float32 | (N, 3) | |
| `rotation` | float32 | (N, 4) | Quaternion [w, x, y, z] |
| `sh_dc` | float32 | (N, 3) | DC spherical harmonics (RGB) |
| `triangle_idx` | int32 | (N,) | [0, 9975] — FLAME 2023 |
| `barycentric` | float32 | (N, 3) | Each row sums to 1.0 ± 1e-4 |

---

## Wiring real LAM + DECA

All GPU-specific code is isolated behind the `FlameFitter` and `Reconstructor` ABCs in `pipeline/interfaces.py`. Replacing the mocks is a one-file change per model.

### Replace DECA (FLAME fitter)

Edit `worker/avatar_worker/handler.py`, function `_handle_flame_fit`:

```python
# 1. Install DECA
#    pip install git+https://github.com/YadiraF/DECA.git

# 2. Load weights in _get_deca():
from deca.decalib.deca import DECA
from deca.decalib.utils.config import cfg as deca_cfg
deca_cfg.pretrained_modelpath = "/weights/deca/deca_model.tar"
_deca = DECA(config=deca_cfg)

# 3. In _handle_flame_fit(), map DECA codedict to the output schema:
codedict = deca.encode(tensor)
return {
    "shape":      _pad(codedict["shape"],   300),
    "expression": _pad(codedict["exp"],     100),
    "pose":       _pad(codedict["pose"],      6),
    "tex":        _pad(codedict["tex"],      50),
}
```

No other backend files change. The `RunPodFlameFitter` already sends the right protocol.

### Replace LAM (Gaussian reconstructor)

Edit `worker/avatar_worker/handler.py`, function `_handle_reconstruct`:

```python
# 1. Install LAM (replace with real repo URL when available)
#    pip install git+https://github.com/XXXXXX/LAM.git

# 2. Load weights in _get_lam():
from lam import LAM
_lam = LAM.load("/weights/lam/lam_model.pt")

# 3. Map LAM output to the NPZ contract.
#    Key names depend on the actual LAM API — adapt as needed:
output = lam.reconstruct(tensor, shape=shape, expression=expression, pose=pose)
np.savez(buf,
    position    = output["means3D"].squeeze(0).cpu().numpy(),
    opacity     = output["opacity"].squeeze(0).cpu().numpy(),
    scale       = output["scales"].squeeze(0).cpu().numpy(),
    rotation    = output["rotations"].squeeze(0).cpu().numpy(),
    sh_dc       = output["shs"][:, :3].squeeze(0).cpu().numpy(),
    triangle_idx= output["binding_tri"].squeeze(0).cpu().numpy().astype(np.int32),
    barycentric = output["binding_bary"].squeeze(0).cpu().numpy(),
)
```

No other backend files change. The `RunPodReconstructor` already parses the NPZ and builds `GaussianSet`.

---

## API reference

### `POST /api/v1/avatar/upload`

Existing endpoint — **untouched**. Uploads any file to R2, returns a URL.

```
Content-Type: multipart/form-data
field: file  (photo or video)

→ { "video_url": "https://..." }
```

---

### `POST /api/v1/avatar/process`

Start the photo → FLAME-rigged Gaussian head pipeline.

```json
// Request
{ "photo_url": "https://...photo.jpg" }

// Response (immediate — pipeline runs in background)
{ "id": "avatar_pipeline_1234", "status": "processing", "progress": 0.0 }
```

---

### `GET /api/v1/avatar/job/{job_id}/status`

Poll pipeline progress.

```json
// In progress
{ "id": "...", "status": "processing", "progress": 0.55,
  "result": { "stage": "reconstruct" } }

// Done
{ "id": "...", "status": "done", "progress": 1.0,
  "result": { /* AvatarBundle */ } }

// Failed
{ "id": "...", "status": "failed", "error": "[no_face] No face detected..." }
```

---

### `GET /api/v1/avatar/job/{job_id}/preview`

UI shortcut — returns only the preview URL without requiring the caller to parse the full bundle.

```json
// 200 when done
{ "preview_url": "https://.../neutral_front.png", "job_id": "..." }

// 202 when still running
{ "detail": "Job not ready yet (status: processing, progress: 55%)" }

// 422 when failed
{ "detail": "[no_face] No face detected in the image" }
```

---

## Testing together — checklist

### Local (mocks, no GPU required)

- [ ] `cp .env.example .env` and set `MOCK_PIPELINE=true`
- [ ] Set R2 credentials (or local MinIO: `S3_ENDPOINT=http://localhost:9000`)
- [ ] `docker run -d -p 6379:6379 redis:7-alpine`
- [ ] `cd backend && source .venv/bin/activate && uvicorn app.main:app --reload`
- [ ] Upload a portrait photo via `POST /avatar/upload`
- [ ] Start pipeline via `POST /avatar/process` with the returned URL
- [ ] Poll `GET /avatar/job/{id}/status` — watch stages advance
- [ ] Check `GET /avatar/job/{id}/preview` returns `preview_url`
- [ ] Open `preview_url` in browser — should be a 512 × 512 face crop PNG
- [ ] Check `result.binding` points to a valid `.npz` — download and verify with NumPy

### Staging (RunPod, real GPU)

- [ ] Build and push `docker/avatar_worker.Dockerfile`
- [ ] Create RunPod Network Volume with DECA + LAM weights at `/weights`
- [ ] Deploy FLAME endpoint (`RUNPOD_FLAME_ENDPOINT_ID`) and test raw RunPod call
- [ ] Deploy reconstruct endpoint (`RUNPOD_RECONSTRUCT_ENDPOINT_ID`) and test raw RunPod call
- [ ] Set both endpoint IDs in `.env`, `MOCK_PIPELINE=false`
- [ ] Restart backend — logs should show `Using RunPodFlameFitter` and `Using RunPodReconstructor`
- [ ] Run the same curl flow as local — pipeline now calls real GPU
- [ ] Verify `neutral_front.png` looks like a proper aligned face
- [ ] Verify `gaussians.ply` loads in a Gaussian viewer (e.g. SuperSplat)
- [ ] Load `gaussian_flame_binding.npz` and check `barycentric.sum(axis=1)` ≈ 1.0 for all rows

### Ingest rejection tests

```bash
# No face
curl -X POST .../avatar/process -d '{"photo_url": "url-to-blank-image"}'
# → status: failed, error: "[no_face] No face detected"

# Multiple faces
curl -X POST .../avatar/process -d '{"photo_url": "url-to-group-photo"}'
# → status: failed, error: "[multiple_faces] Found 2 faces; exactly one face is required"

# Too small
curl -X POST .../avatar/process -d '{"photo_url": "url-to-100x100-image"}'
# → status: failed, error: "[too_small] Image 100×100 is below the 256px minimum"
```

### Frontend

- [ ] Open `http://localhost:3000`
- [ ] Upload a portrait photo in the "Photo → FLAME-rigged Gaussian head" section
- [ ] Progress bar advances through stages with readable labels
- [ ] When done: 512 × 512 preview image appears under "FLAME-rigged head — neutral front preview"
- [ ] Bundle links (gaussians.ply, binding.npz, flame_params.json) are clickable
- [ ] "Unmodeled" line shows `tongue, mouth_interior_detail`
- [ ] Legacy video section still works independently

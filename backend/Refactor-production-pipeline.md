# Refactor Plan — High-Realism 3D Talking Avatar Pipeline

**Source of truth:** `Boosted-production-pipeline`  
**Current state:** single-photo → mediapipe Delaunay → flat Gaussian platter  
**Target state:** photo/video → MICA identity → EMOCA face → SMPL-X body → GLB + ARKit 52 blendshapes → Three.js browser runtime → LivePortrait talking head

---

## Why the current pipeline fails

| Symptom | Root cause |
|---|---|
| Flat "plato" face | mediapipe gives 478 2D landmarks; sphere inflation of 50 mm is a math hack, not real geometry |
| No hair / ears / neck / shoulders | Delaunay triangulates only the face oval; nothing outside 478 landmarks |
| Washed-out colours | 50 K Gaussians on a flat surface overlap ×200 per pixel → compositing error → white blowout |
| No working teeth / tongue | `_teeth_glb()` returns an 80-byte empty GLB placeholder |
| Lip sync = jaw hack | `jaw_disp = amplitude * factor * 0.025` shifts Y-position, not a real blendshape |
| Binding FLAME triangle_idx meaningless | Positions come from mediapipe 2D, not from the actual 5 023 FLAME mesh vertices |
| Raw WebGPU renderer | Re-invents what Three.js already does (blendshapes, GLB, camera) in 400 lines of WGSL |

---

## Architecture: before vs. after

```
BEFORE (current)                       AFTER (target)
─────────────────────────────────      ────────────────────────────────────────────────────
photo                                  photo ─── or ─── video
  ↓                                      ↓                    ↓
ingest (face detect)                   ingest (face detect)  keyframe extractor
  ↓                                      ↓
preprocess (512×512 crop)              multi-view synthesis  ← OpenAI Images 2 / nanoBanana
  ↓                                      ↓
LocalFlameFitter (mediapipe pose)      MICA  ← identity, stable FLAME shape params
  ↓                                      ↓
LocalReconstructor (Delaunay+sphere)   EMOCA / DECA  ← detailed face mesh + expression space
  ↓                                      ↓
50 K Gaussian PLY                      Avatar Completion
  ↓                                        ├─ eyes (explicit geometry, iris shader)
raw WebGPU renderer                        ├─ teeth (upper + lower dental arch GLB)
  ↓                                        ├─ neck (generated geometry)
jaw-only talking                           └─ shoulders + torso (SMPL-X)
                                         ↓
                                       ARKit 52 Blendshape Generation
                                         ↓
                                       GLB + GLTF export
                                         ↓
                                       [Optional] Gaussian Avatar (GaussianAvatars / InstantSplat)
                                         ↓
                                       Three.js / React Three Fiber runtime
                                         ↓
                                       LivePortrait / MuseTalk  ←  TTS audio
                                         ↓
                                       Real-time browser talking avatar
```

---

## Technology map

| Pipeline stage | Technology | GPU required | Runs where |
|---|---|---|---|
| Identity reconstruction | **MICA** | Yes (PyTorch) | RunPod endpoint |
| Detailed face mesh | **EMOCA** (primary) / **DECA** (fallback) | Yes (PyTorch) | RunPod endpoint |
| Body (neck, shoulders, torso) | **SMPL-X** | No (parametric) | Local CPU |
| Eyes | Procedural mesh + PBR shader | No | Local CPU |
| Teeth | Procedural template OBJ | No | Local CPU |
| Multi-view synthesis | **OpenAI gpt-image-1** / nanoBanana | No (API) | API call |
| Video keyframe extraction | **OpenCV** | No | Local CPU |
| ARKit blendshapes | FLAME expression basis mapping | No | Local CPU |
| GLB export | **trimesh** + **pygltflib** | No | Local CPU |
| Gaussian (optional) | GaussianAvatars / InstantSplat | Yes | RunPod endpoint |
| Talking head animation | **LivePortrait** / MuseTalk / Hallo2 | Yes | RunPod endpoint |
| Browser renderer | **Three.js / React Three Fiber** | No (GPU via browser) | Browser |
| CPU fallback (no RunPod) | Current LocalReconstructor + mediapipe | No | Local CPU |

---

## Phase 0 — Stabilise current Gaussian renderer *(done / in-progress)*

Fixes already applied or in-progress to keep the current pipeline usable while the new one is built:

- [x] Depth sorting: per-frame CPU back-to-front sort → upload 200 KB index buffer
- [x] Opacity encoding: store `logit(desired)` not raw float
- [x] Sphere depth: 50 mm protrusion
- [x] mediapipe 0.10+ Tasks API: `detect_face_landmarks()` helper with auto-downloaded model
- [x] Hair/neck extension: convex hull scaled 40% outward

**No new work required.** Phase 0 is the production fallback for users without RunPod access.

---

## Phase 1 — Input acquisition + multi-view synthesis

### 1.1 Video input support

**New file:** `pipeline/video_ingest.py`

```python
class VideoKeyframes(BaseModel):
    frames: dict[str, bytes]  # {"left_90": jpeg, "left_45": jpeg, "frontal": jpeg, ...}
    fps: float
    duration_seconds: float

def extract_keyframes(video_bytes: bytes) -> VideoKeyframes:
    """OpenCV: detect 7 canonical head poses from video frames."""
```

Logic:
- Use mediapipe FaceMesh on each frame to estimate yaw/pitch
- Bin frames into 7 pose buckets: {-90°, -45°, -30°, 0°, +30°, +45°, +90°}
- Pick the sharpest (Laplacian variance) frame per bucket
- Return at most 7 frames; frontal is mandatory

### 1.2 Multi-view synthesis (photo input only)

**New file:** `pipeline/multiview_generator.py`

```python
TARGET_ANGLES = [
    (-90, 0), (-60, 0), (-30, 0), (0, 0), (30, 0), (60, 0), (90, 0),  # horizontal
    (0, 15),  # up
    (0, -15), # down
]  # (yaw_deg, pitch_deg) — 9 synthetic views + original frontal = 10 total

class MultiViewGenerator:
    async def generate(self, frontal_bytes: bytes) -> dict[str, bytes]:
        """
        Returns {angle_key: jpeg_bytes} for each generated view.
        Uses OpenAI images.edit with identity-preserving prompt.
        Falls back to mirror/warp for angles where API fails.
        """

ANGLE_PROMPTS = {
    (-90, 0): "The exact same person's head turned 90 degrees to the left, profile view, same lighting, photorealistic, high resolution",
    (-60, 0): "The exact same person's head turned 60 degrees to the left, same lighting, photorealistic",
    ...
}
```

**Important constraint (from Boosted doc):**
> Generated views are reconstruction aids only. Do not use them directly for rendering.

They are passed to MICA/EMOCA for better shape estimation, not texture-mapped into the final avatar.

### 1.3 Processing UX animation (frontend)

**New component:** `frontend/src/components/MultiViewOrbit.tsx`

While reconstruction runs, display the generated views in a clockwise-orbit animation converging to the frontal. This is a pure visual effect — it shows the user that multiple angles were analysed.

```
┌─────────────────────────────────────────────────────┐
│                 ← views orbit clockwise →            │
│   [side]  [45°]  [front★]  [45°]  [side]            │
│              ↓ converge animation                     │
└─────────────────────────────────────────────────────┘
```

**No effect on pipeline.** Stage gate: multiview images arrive via SSE stream before reconstruction finishes.

---

## Phase 2 — Identity + detailed face reconstruction (MICA + EMOCA/DECA on RunPod)

### 2.1 MICA identity reconstruction

**New file:** `pipeline/runpod_mica.py`

```python
class MICAResult(BaseModel):
    flame_shape: list[float]   # 300-dim stable identity coefficients
    identity_image: str        # URL to canonical neutral-expression render

class RunPodMICAFitter(FlameFitter):
    """
    Sends the frontal image (+ up to 5 side views) to MICA on RunPod.
    Returns stable FLAME identity shape coefficients — much better than DECA
    for multi-view consistency.
    """
```

**RunPod worker changes (`worker/avatar_worker/handler.py`):**
- New handler type: `"mica_fit"` 
- Downloads + runs `https://github.com/Zielon/MICA`
- Accepts multiple images, outputs FLAME shape parameters
- Fallback: DECA single-image fit (current behaviour)

### 2.2 EMOCA detailed face mesh

**New file:** `pipeline/runpod_emoca.py`

```python
class EMOCAResult(BaseModel):
    flame_params: FlameParams           # shape + expression + pose + tex
    detail_displacement_map: str        # URL to 512×512 float32 EXR
    albedo_texture: str                  # URL to 1024×1024 RGB JPEG
    expression_basis: list[list[float]] # (100, 5023*3) FLAME expression PCA basis

class RunPodEMOCAReconstructor(Reconstructor):
    """
    Preferred reconstructor. Outputs:
    - High-quality FLAME mesh with per-pixel detail (wrinkles, pores)
    - Full expression PCA basis for blendshape computation
    - Albedo texture (skin, eyes, lips separated)
    """
```

**DECA fallback** (current `RunPodFlameFitter`): kept for when EMOCA quota is exceeded.

**Worker Dockerfile changes:**
```dockerfile
# Add EMOCA + dependencies
RUN pip install emoca  # or clone from source
RUN pip install pytorch3d kornia face-alignment
```

---

## Phase 3 — Avatar completion (eyes, teeth, neck, SMPL-X body)

This phase runs **entirely on CPU** — no GPU required.

### 3.1 Explicit eye geometry

**New file:** `pipeline/eye_builder.py`

```python
class EyeGeometry(BaseModel):
    left_eyeball_glb: bytes    # sphere mesh with iris texture
    right_eyeball_glb: bytes

def build_eyes(flame_params: FlameParams, albedo_texture: bytes) -> EyeGeometry:
    """
    - Extract eye region colour from albedo texture at FLAME eye UV coordinates
    - Generate two sphere meshes (radius 12 mm) centred at FLAME eye landmark positions
    - Add iris disc with PBR material (specular, refraction approximation)
    - Embed as separate GLB meshes parented to head bone
    """
```

Shader: simple PBR sphere with iris texture + specular highlight. No raytracing needed.

### 3.2 Teeth with proper geometry

**New file:** `pipeline/teeth_builder.py` *(replaces current placeholder)*

```python
def build_teeth(flame_params: FlameParams, mouth_landmarks: np.ndarray) -> bytes:
    """
    Returns a GLB with two meshes:
      - teeth_upper: static 16-tooth arch, parented to head
      - teeth_lower: static 16-tooth arch, parented to jaw bone
    
    Steps:
    1. Use FLAME jaw pose to estimate mouth opening angle
    2. Scale standard teeth arch template to fit mouth width from landmarks
    3. Position arches: upper at hard palate depth, lower at jaw position
    4. Apply procedural ivory/enamel PBR material
    5. Add tongue plane (deformable via tongueOut blendshape)
    """
```

Static template files needed:
```
data/teeth_upper_arch.npz   # (32, 3) verts, (30, 3) faces — upper arch
data/teeth_lower_arch.npz   # same for lower
data/tongue_base.npz        # simple plane, displaced by blendshape
```

### 3.3 Neck + shoulders (SMPL-X)

**New file:** `pipeline/body_builder.py`

```python
class BodyResult(BaseModel):
    body_glb: bytes            # neck + shoulders + upper chest mesh
    body_texture: bytes        # texture sampled from original photo (lower neck area)

def build_upper_body(
    flame_params: FlameParams,
    original_photo: bytes,     # full padded crop, not just face oval
    height_cm: float = 170,    # optional, defaults to average
) -> BodyResult:
    """
    Uses SMPL-X parametric body model to generate neck + shoulders.
    
    Local CPU approach (no GPU):
    1. Load SMPL-X neutral template mesh (static OBJ, included in data/)
    2. Scale neck radius from FLAME head size
    3. Rotate to match FLAME head pose
    4. Texture neck from original photo below chin landmarks
    5. Shoulders: use SMPL-X joint positions scaled to average proportions
    6. Export as GLB submesh to be composited with head GLB
    """
```

SMPL-X requires registration at https://smpl-x.is.tue.mpg.de/ — include download script in `data/download_smplx.py`.

---

## Phase 4 — ARKit 52 blendshapes + animation rig

### 4.1 Blendshape builder

**New file:** `pipeline/blendshape_builder.py`

```python
ARKIT_52 = [
    "eyeBlinkLeft", "eyeLookDownLeft", "eyeLookInLeft", "eyeLookOutLeft", "eyeLookUpLeft",
    "eyeSquintLeft", "eyeWideLeft",
    "eyeBlinkRight", "eyeLookDownRight", "eyeLookInRight", "eyeLookOutRight", "eyeLookUpRight",
    "eyeSquintRight", "eyeWideRight",
    "jawForward", "jawLeft", "jawRight", "jawOpen",
    "mouthClose", "mouthFunnel", "mouthPucker", "mouthLeft", "mouthRight",
    "mouthSmileLeft", "mouthSmileRight", "mouthFrownLeft", "mouthFrownRight",
    "mouthDimpleLeft", "mouthDimpleRight", "mouthStretchLeft", "mouthStretchRight",
    "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper",
    "mouthPressLeft", "mouthPressRight", "mouthLowerDownLeft", "mouthLowerDownRight",
    "mouthUpperUpLeft", "mouthUpperUpRight",
    "browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
    "cheekPuff", "cheekSquintLeft", "cheekSquintRight",
    "noseSneerLeft", "noseSneerRight", "tongueOut",
]

def build_blendshapes(
    flame_expression_basis: np.ndarray,  # (100, 5023*3) from EMOCA
    neutral_verts: np.ndarray,           # (5023, 3) FLAME neutral mesh
) -> np.ndarray:
    """
    Returns (52, 5023, 3) float16 delta array.
    
    Method:
    1. Use the FLAME→ARKit mapping matrix (data/flame_to_arkit_52.npy, 100×52)
       to project FLAME expression PCA basis onto ARKit blendshapes
    2. Each of the 52 blendshapes = linear combination of FLAME expression vectors
    3. Compute vertex deltas: delta[i] = flame_basis @ arkit_weights[:, i]
    4. Store as float16 to reduce bundle size (~10 MB for full set)
    """
```

Source for `data/flame_to_arkit_52.npy`: computed offline from EMOCA correspondence table (included as static 50 KB file in repo).

### 4.2 GLB assembly

**New file:** `pipeline/glb_builder.py` *(replaces package.py for the mesh pipeline)*

```python
def build_avatar_glb(
    flame_mesh: FlameMesh,              # verts + faces + UV
    albedo_texture: bytes,              # 1024×1024 JPEG from EMOCA
    detail_displacement: bytes | None,  # optional EXR
    blendshapes: np.ndarray,            # (52, 5023, 3) float16
    eyes: EyeGeometry,
    teeth_glb: bytes,
    body_glb: bytes,
) -> bytes:
    """
    Assembles a single production-ready GLB containing:
      - Head mesh (FLAME topology, 9976 triangles)
      - 52 morph targets (ARKit blendshapes) embedded in mesh primitives
      - Skeleton: head bone + jaw bone + eye_L / eye_R bones
      - Eyes (submesh, rigid children of head bone)
      - Teeth upper (submesh, child of head) + teeth lower (child of jaw)
      - Body/shoulders (submesh, child of neck bone)
      - PBR material: albedo + normal (from displacement) + specular
    
    Uses: pygltflib for GLB assembly, trimesh for mesh ops
    """
```

### 4.3 AvatarBundle schema update

```python
class AvatarBundle(BaseModel):
    version: str = "2.0"
    coordinate_system: str = "y_up_right_handed"
    
    # Primary deliverable (Phase 2+)
    avatar_glb: str | None = None      # URL to complete rigged GLB
    
    # Legacy Gaussian deliverable (Phase 0 fallback)
    gaussians: str | None = None       # URL to gaussians.ply
    
    flame: AvatarBundleFlame
    blendshapes: str | None = None     # URL to blendshapes.npz (52×N×3 float16)
    expression_basis: str = "ARKit_52"
    unmodeled: list[str]               # ["tongue_detail", "hair_interior"]
    preview: str
    pipeline_version: str              # "gaussian_v0" | "mesh_v2"
```

---

## Phase 5 — Talking head animation (LivePortrait / MuseTalk on RunPod)

### 5.1 LivePortrait integration

**New file:** `backend/app/api/animate.py` *(update existing stub)*

```python
class AnimateRequest(BaseModel):
    job_id: str
    audio_url: str               # TTS output from ElevenLabs
    expression_driver: Literal["liveportrait", "musetalk", "blendshape"] = "liveportrait"

class AnimateResponse(BaseModel):
    animation_url: str           # URL to output video (MP4) or blendshape stream
    driver_used: str
```

Two modes:
1. **Video mode** (LivePortrait/MuseTalk): avatar rendered as MP4 video → play in `<video>` tag, high quality, 1–5 sec latency
2. **Real-time blendshape mode**: TTS → phoneme-to-blendshape mapping → drive ARKit blendshapes at 30 fps in Three.js (no video rendering, <100ms latency)

**RunPod worker additions:**
```python
# worker/avatar_worker/handler.py
elif job_type == "liveportrait":
    return _handle_liveportrait(job_input)

def _handle_liveportrait(inp):
    # Clone github.com/KwaiVGI/LivePortrait
    # Feed: source image (avatar preview) + driving audio
    # Output: MP4 video
```

### 5.2 Real-time blendshape driving (no-GPU path)

**New file:** `frontend/src/engine/blendshape_driver.ts`

```typescript
// Maps phonemes → ARKit blendshape weights
// Uses Web Audio API amplitude + FFT to estimate phoneme category
// Then lerps blendshape weights for smooth animation

const PHONEME_BLENDSHAPES: Record<string, Partial<BlendshapeWeights>> = {
    "AA": { jawOpen: 0.7, mouthFunnel: 0.3 },
    "EE": { jawOpen: 0.4, mouthSmileLeft: 0.3, mouthSmileRight: 0.3 },
    "OO": { jawOpen: 0.5, mouthPucker: 0.6 },
    "M":  { mouthClose: 0.8, mouthPressLeft: 0.3, mouthPressRight: 0.3 },
    // ... all English phonemes
};
```

---

## Phase 6 — Three.js / React Three Fiber renderer *(replaces raw WebGPU)*

**New file:** `frontend/src/engine/AvatarScene.tsx`

```tsx
import { Canvas } from '@react-three/fiber'
import { useGLTF, useAnimations, PerspectiveCamera } from '@react-three/drei'

export function AvatarScene({ glbUrl, blendshapeWeights }: Props) {
    const { scene } = useGLTF(glbUrl)
    
    // Apply ARKit blendshape weights every frame
    useFrame(() => {
        scene.traverse(node => {
            if (node.isMesh && node.morphTargetInfluences) {
                ARKit52.forEach((name, i) => {
                    node.morphTargetInfluences[i] = blendshapeWeights[name] ?? 0
                })
            }
        })
    })
    
    return (
        <Canvas>
            <PerspectiveCamera fov={45} position={[0, 0.05, 0.4]} />
            <primitive object={scene} />
            <ambientLight intensity={0.5} />
            <directionalLight position={[1, 2, 3]} />
        </Canvas>
    )
}
```

Three.js handles:
- GLB loading + material setup
- Morph target (blendshape) animation
- Skinned mesh (jaw bone, eye bones)
- Shadow mapping
- Camera orbit

This replaces the 400-line raw WebGPU renderer. Gaussian remains as optional premium view via the existing WebGPU renderer (toggle button).

---

## Phase 7 — Optional Gaussian Avatar (premium)

Use the GLB mesh from Phase 3 as input to generate a Gaussian representation:

**Candidate projects:**
- **GaussianAvatars** (`https://shenhanxu.github.io/gaussian-avatars/`) — FLAME-rigged 3DGS
- **InstantSplat** — fast 3DGS from multi-view images

**Trigger:** `POST /avatar/{job_id}/generate_gaussian` → background RunPod job  
**Output:** `gaussians.ply` added to existing bundle  
**Display:** toggle button in `AvatarScene` switches between Three.js GLB and WebGPU Gaussian

---

## New file structure

```
backend/app/
  pipeline/
    ── KEEP ──
    ingest.py
    preprocess.py
    interfaces.py
    schemas.py          (extend for AvatarBundle v2)
    rig.py              (extend for SMPL-X body triangles)
    package.py          (extend to emit GLB + blendshapes.npz)
    publish.py
    mediapipe_utils.py
    local_fitter.py     (CPU fallback)
    local_reconstructor.py  (CPU fallback, Phase 0)

    ── NEW ──
    video_ingest.py         Phase 1: keyframe extraction from video
    multiview_generator.py  Phase 1: OpenAI multi-view synthesis
    runpod_mica.py          Phase 2: MICA identity on RunPod
    runpod_emoca.py         Phase 2: EMOCA face mesh on RunPod
    eye_builder.py          Phase 3: explicit eye geometry
    teeth_builder.py        Phase 3: dental arch GLB (replaces placeholder)
    body_builder.py         Phase 3: SMPL-X neck + shoulders
    blendshape_builder.py   Phase 4: ARKit 52 blendshape deltas
    glb_builder.py          Phase 4: GLB assembly (head + eyes + teeth + body + blendshapes)
    flame_template.py       Phase 2: load FLAME 2023 OBJ + UV

  api/
    animate.py              Phase 5: LivePortrait / blendshape drive (update existing stub)
    avatar.py               extend for video upload

  workers/
    pipeline_worker.py      extend: new stages + dual mesh/Gaussian output
    generate_worker.py      extend: add gaussian_premium job type

data/   (static assets, committed to repo, ~5 MB total)
  flame2023_template.npz    FLAME 5023 verts + 9976 faces + UVs
  teeth_upper_arch.npz
  teeth_lower_arch.npz
  tongue_base.npz
  flame_to_arkit_52.npy     (100, 52) FLAME→ARKit mapping matrix
  smplx_neutral_torso.npz   upper body only (~2000 verts)

frontend/src/
  engine/
    webgpu_renderer.ts      KEEP (Gaussian premium)
    splat_loader.ts         KEEP
    camera.ts               KEEP
    blendshape_driver.ts    NEW Phase 5: audio → ARKit weights
  components/
    AvatarScene.tsx         NEW Phase 6: Three.js / R3F renderer
    MultiViewOrbit.tsx      NEW Phase 1: processing UX animation
  pages/
    AvatarViewer.tsx        extend: toggle Gaussian / Mesh renderer

worker/
  avatar_worker/
    handler.py              extend: mica / emoca / liveportrait handlers
    download_weights.py     extend: MICA + EMOCA weights
  Dockerfile                extend: add EMOCA, MICA, LivePortrait
```

---

## Dependencies to add

```
# backend/requirements.txt additions
pygltflib>=1.16.0       # GLB/GLTF assembly
trimesh>=4.0.0          # mesh operations (merge, UV, normals)
opencv-python>=4.8.0    # video keyframe extraction
imageio[ffmpeg]>=2.33   # video decode
smplx>=0.1.28           # parametric body model (CPU)
httpx>=0.25.2           # already present

# frontend/package.json additions
three                   # Three.js
@react-three/fiber      # R3F
@react-three/drei       # R3F helpers (useGLTF, OrbitControls, etc.)

# worker/requirements.txt additions (RunPod image)
emoca                   # EMOCA face reconstruction
mica                    # MICA identity reconstruction (pip install or clone)
liveportrait            # talking head (clone from KwaiVGI/LivePortrait)
```

---

## Sprint plan

### Sprint 1 — Multi-view + UX animation (1–2 days, no GPU needed)
1. `multiview_generator.py` — OpenAI Images 2 API for 9 angles
2. `frontend/src/components/MultiViewOrbit.tsx` — processing UX animation
3. Wire into `pipeline_worker.py` as new stage 2b
4. **Deliverable:** user uploads photo → sees 9 synthetic views orbiting while processing

### Sprint 2 — Real teeth + eye geometry (1 day, no GPU)
5. `teeth_builder.py` — real dental arch GLB from mouth landmarks
6. `eye_builder.py` — eyeball spheres from FLAME UV landmarks
7. Basic `glb_builder.py` using current mediapipe mesh as input (no EMOCA yet)
8. **Deliverable:** exported GLB has real teeth and eyes; Three.js renders it

### Sprint 3 — Three.js renderer + blendshapes (2 days)
9. `npm install three @react-three/fiber @react-three/drei`
10. `AvatarScene.tsx` — GLB load + ARKit blendshape animation
11. `blendshape_driver.ts` — audio amplitude → ARKit weights (mouth shapes)
12. `blendshape_builder.py` — generate 52 blendshape deltas from FLAME expression basis
13. **Deliverable:** avatar opens mouth correctly, lip shapes match phonemes

### Sprint 4 — MICA + EMOCA on RunPod (2–3 days, GPU required)
14. `runpod_mica.py` + worker MICA handler
15. `runpod_emoca.py` + worker EMOCA handler
16. Update `pipeline_worker.py` to use MICA/EMOCA when RunPod endpoints configured
17. **Deliverable:** photo → real face shape + expression basis → dramatically better quality

### Sprint 5 — SMPL-X body + full GLB pipeline (1–2 days)
18. `body_builder.py` — SMPL-X neck + shoulders
19. Full `glb_builder.py` — composites head + eyes + teeth + body
20. `AvatarBundle` schema v2 with `avatar_glb` field
21. **Deliverable:** avatar is a full upper body, not a floating head

### Sprint 6 — LivePortrait talking head (2 days, GPU required)
22. RunPod LivePortrait handler
23. `animate.py` endpoint update
24. Frontend: toggle between real-time blendshape and video mode
25. **Deliverable:** click "Make it Talk" → photorealistic talking video of avatar

### Sprint 7 — Gaussian premium (optional, 2–3 days)
26. `POST /avatar/{id}/generate_gaussian` endpoint
27. GaussianAvatars / InstantSplat RunPod handler
28. Frontend toggle: mesh view ↔ Gaussian view
29. **Deliverable:** premium quality Gaussian splat avatar generated from the mesh

---

## Keys / credentials needed

| Service | Key env var | Notes |
|---|---|---|
| OpenAI Images 2 | `OPENAI_API_KEY` | Already in `.env` |
| RunPod (MICA) | `RUNPOD_MICA_ENDPOINT_ID` | New; create endpoint |
| RunPod (EMOCA) | `RUNPOD_EMOCA_ENDPOINT_ID` | New; create endpoint |
| RunPod (LivePortrait) | `RUNPOD_LIVEPORTRAIT_ENDPOINT_ID` | New; create endpoint |
| nanoBanana (fallback) | `NANOBANANA_API_KEY` | Only needed if OpenAI unavailable |
| SMPL-X license | n/a | Free academic; register at smpl-x.is.tue.mpg.de |
| FLAME 2023 | n/a | Free research license; register at flame.is.tue.mpg.de |

---

## What stays, what goes

| Component | Fate | Reason |
|---|---|---|
| `LocalReconstructor` | KEEP as fallback | Phase 0 works with zero cloud deps |
| `WebGPU renderer` | KEEP as Gaussian premium view | Still needed for 3DGS display |
| Raw `_teeth_glb()` placeholder | REPLACE in Sprint 2 | Phase 3 |
| Jaw-only animation hack | REPLACE in Sprint 3 | ARKit blendshapes |
| `MockFlameFitter` / `MockReconstructor` | KEEP | Test suite uses them |
| `gemini_image.py` enhancement | KEEP | Optional pre-step, harmless |
| `elevenlabs.py` TTS | KEEP | Used by Sprint 6 |
| FLAME schema/interfaces | KEEP + EXTEND | Foundation stays the same |

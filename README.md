# 🎭 Gaussian Avatar Platform - MVP

A complete end-to-end platform for creating and animating 3D Gaussian avatars from video, with real-time WebGPU rendering.

## 🧠 System Overview

The platform consists of 3 critical layers:

1. **🔴 RECONSTRUCTION LAYER** (SplattingAvatar + gsplat)
   Converts real-world video → 3D Gaussian Avatar

2. **🔵 ANIMATION LAYER** (GaussianSpeech)
   Converts audio → Gaussian deformations

3. **🟢 RUNTIME LAYER** (WebGPU Renderer)
   Real-time Gaussian splatting in browser

## 📁 Project Structure

```
avatar-platform/
├── backend/           # FastAPI server
│   ├── app/
│   │   ├── api/      # REST endpoints
│   │   ├── services/ # Queue, storage, RunPod client
│   │   └── models/   # Data models
│
├── worker/            # RunPod GPU workers
│   ├── reconstruction/  # COLMAP + SplattingAvatar + gsplat
│   └── animation/       # GaussianSpeech
│
├── frontend/          # React + WebGPU renderer
│   └── src/
│       ├── engine/   # WebGPU rendering engine
│       └── pages/    # UI components
│
├── docker/           # Docker configurations
└── scripts/          # Setup scripts
```

## 🚀 Quick Start

### Prerequisites

- Docker & Docker Compose
- RunPod account (for GPU processing)
- Node.js 18+ (for frontend development)
- Python 3.10+ (for local development)

### 1. Clone and Setup

```bash
cd /Users/marcelo/Documents/avatar-platform
cp .env.example .env
# Edit .env with your RunPod credentials
```

### 2. Start Local Services

```bash
docker-compose up -d
```

This starts:
- **Backend API** on `http://localhost:8000`
- **Frontend** on `http://localhost:3000`
- **Redis** on `localhost:6379`
- **MinIO** on `http://localhost:9000`

### 3. Setup RunPod Worker

```bash
chmod +x scripts/setup_runpod.sh
./scripts/setup_runpod.sh
```

### Follow the instructions to deploy the worker to RunPod.
### probar en dev: 
### 4. Kill front y Back Y lanzar npm local 
# reinicia npm run dev para que el backend tome el endpoint nuevo del .env
kill $(lsof -ti tcp:8000) $(lsof -ti tcp:3000) 2>/dev/null
cd /Users/mac/Documents/avatar-platform && npm run dev

cd /Users/mac/Documents/avatar-platform
npm run dev

## 🔧 Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Worker (Local Testing)

```bash
cd worker
python runpod_worker.py
```

## 📡 API Endpoints

### Create Avatar

```bash
POST /api/v1/avatar/create
{
  "video_url": "https://...",
  "mode": "head"
}
```

### Upload Video

```bash
POST /api/v1/avatar/upload
Content-Type: multipart/form-data
```

### Animate Avatar

```bash
POST /api/v1/animate
{
  "avatar_id": "avatar_123",
  "audio_url": "https://..."
}
```

### Stream Animation

```bash
WebSocket: ws://localhost:8000/api/v1/stream/{avatar_id}
```

## 🧱 Technology Stack

### Backend
- Python 3.10+
- FastAPI
- Redis (job queue)
- S3/MinIO (storage)

### GPU Pipeline (RunPod)
- PyTorch 2.x
- CUDA 11.8+
- COLMAP (pose estimation)
- gsplat (Gaussian splatting)
- SplattingAvatar
- GaussianSpeech

### Frontend
- React + TypeScript
- Vite
- WebGPU API (with WebGL2 fallback)

## 🎯 MVP Success Criteria

✅ Upload video
✅ Generate Gaussian avatar
✅ Render in browser (WebGPU)
✅ Animate with audio

## 🔴 Critical Pipeline: Reconstruction

### Input
Video file (MP4)

### Steps
1. Extract frames (ffmpeg)
2. COLMAP pose estimation
3. SplattingAvatar preprocessing
4. gsplat training (30k iterations)
5. Export `.ply` file

### Output
- `gaussians.ply` - Gaussian parameters
- `metadata.json` - Model info

## 🔵 Critical Pipeline: Animation

### Input
- Avatar ID
- Audio file (WAV)

### Steps
1. Load avatar gaussians
2. Extract audio features
3. GaussianSpeech inference
4. Generate deformation sequence

### Output
WebSocket stream of deformations

## 🟢 Critical Pipeline: Runtime

### WebGPU Renderer

Located in: [`frontend/src/engine/webgpu_renderer.ts`](frontend/src/engine/webgpu_renderer.ts)

**Pipeline:**
1. Load Gaussian splats from `.ply`
2. Upload to GPU buffers
3. Compute passes:
   - Frustum culling
   - Projection to screen space
   - GPU radix sort (depth sorting)
4. Render pass:
   - Splat each Gaussian as billboard quad
   - Gaussian falloff in fragment shader

**Render Loop:**
```typescript
requestAnimationFrame(() => {
  updateCamera()
  updateDeformations() // From animation stream
  runComputePasses()
  renderFrame()
})
```

## 📦 Data Contracts

### Avatar Format
```json
{
  "id": "avatar_123",
  "gaussians_url": "https://...",
  "rig": {},
  "type": "head",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### Animation Format
```json
{
  "id": "anim_123",
  "avatar_id": "avatar_123",
  "stream_url": "wss://..."
}
```

### Deformation Update
```json
{
  "timestamp": 0.033,
  "positions": [...],  // Float32Array
  "rotations": [...]   // Float32Array (quaternions)
}
```

## ⚠️ Important Notes

### TODO: Research Papers Implementation

The worker code contains scaffolding for:

1. **SplattingAvatar**
   Paper: [SplattingAvatar: Realistic Real-Time Human Avatars with Mesh-Embedded Gaussian Splatting](https://arxiv.org/abs/2403.05087)
   - Needs actual implementation of FLAME fitting
   - Head segmentation
   - Canonical space mapping

2. **GaussianSpeech**
   - Audio-driven facial animation
   - Requires audio feature extraction (HuBERT/Wav2Vec)
   - Motion prediction network

3. **gsplat**
   Uses: [nerfstudio-project/gsplat](https://github.com/nerfstudio-project/gsplat)
   - Already has PyPI package
   - May need custom training loop

### WebGPU Compatibility

- Check support: `navigator.gpu`
- Fallback to WebGL2 if unavailable
- Current implementation is simplified for MVP
- Full sorting pipeline needs GPU radix sort implementation

### Performance Optimization (Post-MVP)

- [ ] GPU radix sort for depth ordering
- [ ] Hierarchical culling
- [ ] LOD system
- [ ] Streaming compression
- [ ] Batch processing

## 🐳 Docker Deployment

### Build Worker Image

```bash
docker build -f docker/worker.Dockerfile -t avatar-worker .
```

### Build Backend Image

```bash
docker build -f docker/backend.Dockerfile -t avatar-backend .
```

### Production Deployment

```bash
docker-compose -f docker-compose.prod.yml up -d
```

## 🔐 Environment Variables

See [`.env.example`](.env.example) for all configuration options.

Required for RunPod:
- `RUNPOD_API_KEY` - Your RunPod API key
- `RUNPOD_ENDPOINT_ID` - Deployed endpoint ID

## 📚 Additional Resources

- [RunPod Serverless Docs](https://docs.runpod.io/serverless/overview)
- [WebGPU Fundamentals](https://webgpufundamentals.org/)
- [3D Gaussian Splatting Paper](https://repo-sam.inria.fr/fungraph/3d-gaussian-splatting/)
- [gsplat GitHub](https://github.com/nerfstudio-project/gsplat)

## 🛠️ Troubleshooting

### Backend won't start
- Check Redis connection: `redis-cli ping`
- Check MinIO: `curl http://localhost:9000/minio/health/live`

### Worker fails
- Check CUDA availability: `nvidia-smi`
- Verify COLMAP installation: `colmap -h`

### WebGPU not available
- Check browser support: Chrome 113+, Edge 113+
- Enable flag: `chrome://flags/#enable-unsafe-webgpu`

### Animation not streaming
- Check WebSocket connection in browser console
- Verify Redis queue is processing jobs

## 🚧 Known Limitations (MVP)

- No user authentication
- No database (using Redis only)
- Simplified WebGPU shaders
- No production optimization
- Limited error handling
- No testing suite

## 📈 Next Steps (Post-MVP)

1. Implement full SplattingAvatar pipeline
2. Integrate real GaussianSpeech model
3. Optimize WebGPU renderer (full sorting)
4. Add user management
5. Implement database (PostgreSQL)
6. Add monitoring & logging
7. Performance profiling
8. Production deployment setup

## 📄 License

MIT

---

**Built with Claude Code** 🤖

Aquí tienes el PR (Project Requirements) listo para pegar en VSCode/Codex/agent AI. Está diseñado para que un agente pueda construir un MVP funcional end-to-end sin ambigüedad.

⸻

📦 PR — MVP Gaussian Avatar Platform (Codex-ready)

🧠 0. OBJETIVO DEL SISTEMA

Construir un MVP que permita:

📹 Subir un video → generar avatar 3D Gaussian → reproducirlo en browser → animarlo con audio

El sistema se compone de 3 capas críticas:

⸻

🔴 1. RECONSTRUCTION LAYER

(SplattingAvatar + gsplat)

Convierte mundo real → 3D Gaussian Avatar

⸻

🔵 2. ANIMATION LAYER

(GaussianSpeech)

Convierte audio → deformación del avatar 3D

⸻

🟢 3. RUNTIME LAYER

(WebGPU Renderer)

Convierte Gaussian → render realtime en browser

⸻

🧱 1. STACK TECNOLÓGICO

🧠 Backend

* Python 3.10+
* FastAPI
* Redis (cola de jobs)
* S3 compatible storage (MinIO o AWS S3)

⸻

🧠 GPU Pipeline (RunPod)

* PyTorch 2.x
* CUDA 11.8+
* COLMAP
* gsplat (nerfstudio-project)
* SplattingAvatar repo
* GaussianSpeech repo (o implementación equivalente)

⸻

🌐 Frontend

* React + Vite
* TypeScript
* WebGPU API
* fallback: WebGL2
* Three.js (solo wrapper utilitario, NO motor principal)

⸻

📡 Infra

* RunPod (GPU workers)
* Docker containers
* REST API + WebSocket streaming

⸻

📁 2. ESTRUCTURA DEL PROYECTO

avatar-platform/
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── avatar.py
│   │   │   ├── animate.py
│   │   │   ├── stream.py
│   │   ├── services/
│   │   │   ├── queue.py
│   │   │   ├── storage.py
│   │   │   ├── runpod_client.py
│   │   ├── models/
│   │   ├── config.py
│
├── worker/
│   ├── runpod_worker.py
│   ├── reconstruction/
│   │   ├── splatting_avatar.py
│   │   ├── colmap_runner.py
│   │   ├── gsplat_trainer.py
│   ├── animation/
│   │   ├── gaussian_speech.py
│
├── frontend/
│   ├── src/
│   │   ├── engine/
│   │   │   ├── webgpu_renderer.ts
│   │   │   ├── splat_loader.ts
│   │   │   ├── animation_stream.ts
│   │   ├── ui/
│   │   ├── pages/
│
├── shared/
│   ├── types.ts
│   ├── avatar_schema.json
│
├── docker/
│   ├── worker.Dockerfile
│   ├── backend.Dockerfile
│
├── scripts/
│   ├── setup_runpod.sh
│
└── README.md

⸻

⚙️ 3. FUNCIONALIDADES MVP

🟢 3.1 Avatar Creation

Endpoint

POST /avatar/create

Input

{
  "video_url": "...",
  "mode": "head"
}

Flow

1. Descargar video
2. Extraer frames (ffmpeg)
3. RunPod job:
    * COLMAP pose estimation
    * SplattingAvatar reconstruction
    * gsplat optimization
4. Export:
    * gaussian .ply
    * metadata JSON

⸻

🔵 3.2 Avatar Animation

Endpoint

POST /avatar/animate

Input

{
  "avatar_id": "...",
  "audio_url": "..."
}

Flow

1. Audio preprocessing
2. GaussianSpeech inference
3. Generate deformation stream

⸻

🟢 3.3 Runtime Streaming

Endpoint

GET /avatar/{id}/stream

Output

* WebSocket stream:
    * deformation updates OR frame buffers

⸻

🧠 4. RUNPOD WORKER (CRÍTICO)

worker/runpod_worker.py

Responsabilidades:

RECONSTRUCTION MODE

* input: video
* output: gaussian splats

Pipeline:

COLMAP → SplattingAvatar → gsplat optimization → export

⸻

ANIMATION MODE

* input: audio + avatar
* output: deformation stream

Pipeline:

GaussianSpeech → motion field → update gaussians

⸻

🌐 5. FRONTEND (WEBGPU RUNTIME)

engine/webgpu_renderer.ts

Debe implementar:

CORE PIPELINE

1. Load Gaussian splats
2. Upload GPU buffers
3. Run compute passes:
    * culling
    * projection
    * sorting (GPU radix)
4. Render splats (fragment shader)

⸻

Render loop:

requestAnimationFrame(() => {
  updateCamera()
  runComputePasses()
  renderFrame()
})

⸻

fallback:

* WebGL renderer si WebGPU no disponible

⸻

📡 6. API SERVICES

backend/services/runpod_client.py

* submit job
* poll status
* retrieve results

⸻

backend/services/storage.py

* upload video/audio
* store gaussian outputs
* return signed URLs

⸻

backend/services/queue.py

* Redis queue
* job states:
    * pending
    * processing
    * done
    * failed

⸻

📦 7. DATA CONTRACT (IMPORTANT)

Avatar format

{
  "id": "avatar_123",
  "gaussians_url": "...",
  "rig": {},
  "type": "head",
  "created_at": ""
}

⸻

Animation format

{
  "id": "anim_123",
  "avatar_id": "avatar_123",
  "stream_url": "wss://..."
}

⸻

⚠️ 8. CRÍTICO (NO OLVIDAR)

Tu sistema tiene 3 partes críticas:

⸻

🔴 1. Reconstruction (SplattingAvatar + gsplat)

convierte mundo real → 3D Gaussian

⸻

🔵 2. Animation (GaussianSpeech)

convierte audio → deformación 3D

⸻

🟢 3. Runtime (WebGPU)

convierte Gaussian → realtime rendering

⸻

🚀 9. MVP DEFINITION (SUCCESS CRITERIA)

El MVP está completo cuando:

✔️ Subes un video
✔️ Se genera avatar Gaussian
✔️ Se puede renderizar en browser
✔️ Se puede animar con audio

⸻

💣 10. INSTRUCCIÓN FINAL PARA EL AGENTE

Implementar primero vertical slice completo:
video → avatar → render básico → animation simple

NO optimizar.
NO escalar.
NO abstraer demasiado.

Solo flujo funcional end-to-end.

⸻

Si quieres, el siguiente paso puedo darte:

* 🔧 Dockerfiles listos para RunPod (copiar/pegar)
* ⚡ implementación mínima del WebGPU renderer
* 📡 o el sistema de streaming realtime (lo más difícil del producto)

Ahí es donde esto se vuelve startup real.
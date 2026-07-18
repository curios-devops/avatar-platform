# A1 — Generación de clips base (offline, una vez por avatar)

Scripts del plan (`docs/nueva_arquitectura.md` §A1):
- `make_clips.py` — avatar.jpg → idle_a/idle_b/listen/gesture_enum/gesture_open
- `prep_clips.py` — normaliza color, construye `clip_graph.json`, renderiza
  `_preview_chain.mp4` (criterio de aceptación: encadenado sin salto visible)

## Dónde corre cada cosa
- `make_clips.py`: **pod GPU RunPod** (no serverless: es un job largo una vez
  por avatar). Wan2.2-S2V-14B ≥ 40 GB (A6000/A100/L40S 48GB) · EchoMimicV3
  ≥ 16 GB (4090/A5000). Pin CUDA 12.1–12.6 como los workers (lección LAM).
- `prep_clips.py`: CPU (mac o pod). `pip install mediapipe opencv-python`.

## Runbook pod (Wan2.2-S2V)
```bash
# pod 48GB, imagen pytorch 2.x cu121
git clone https://github.com/Wan-Video/Wan2.2 && cd Wan2.2 && pip install -r requirements.txt
huggingface-cli download Wan-AI/Wan2.2-S2V-14B --local-dir /workspace/Wan2.2-S2V-14B
python /workspace/avatar-platform/worker/clips_gen/make_clips.py \
  --photo /workspace/avatar.jpg --out /workspace/clips \
  --backend wan --repo /workspace/Wan2.2 --ckpt /workspace/Wan2.2-S2V-14B
python prep_clips.py --clips /workspace/clips
```
Foto de entrada: la del intake existente (reframe half con Nano Banana da el
encuadre medio-cuerpo que piden los prompts).

## ⚠️ Verificar en el pod (escrito contra docs, sin GPU local)
- Flags exactos de `generate.py --task s2v-14B` (tamaño `704*1280`, nombre de
  `--save_file`) y de `infer.py` de EchoMimicV3 — ajustar si el repo difiere.
- VRAM real con `--offload_model True`; si OOM en 48 GB → EchoMimicV3.
- Duración: S2V genera la longitud del audio (silencio de N s) por segmentos.

## Estado
- [x] Scripts escritos (2026-07-18)
- [ ] Ejecutados en pod GPU → clips reales
- [ ] `prep_clips.py` validado sobre clips reales (aceptación A1)

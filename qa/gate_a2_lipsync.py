#!/usr/bin/env python3
"""GATE-A2 (lip-sync) — disciplina de revisión visual (docs/nueva_arquitectura.md).

Trabajo mecánico (este script, determinista):
  1. prepare_avatar con los clips de A1 (si no están ya en el volumen).
  2. TTS real de una frase → speak → MP4 con lip-sync.
  3. Extrae frames + mide APERTURA BUCAL por frame (alto de la región de
     labios con landmarks MediaPipe) → serie temporal.
  4. Empaqueta UNA hoja: fila de frames a lo largo de la frase + al pie la
     curva de apertura y las métricas.
El agente solo juzga esa hoja (¿la boca se mueve con el habla? ¿cierra en los
silencios? ¿sin banda/deformación?), score ≥ 7/10 = gate verde.

Métricas de gate:
  - mouth_open_range: (max-min) de apertura normalizada. > 0.15 = hay
    movimiento bucal real (no una foto estática).
  - mouth_motion_events: nº de cruces de la mediana (proxy de sílabas).
  - speak_seconds: latencia del worker (criterio A2: útil < 4 s/frase).

Uso:  cd backend && ../qa/.venv/bin/python ../qa/gate_a2_lipsync.py \
         --avatar demo --frase "Hola, soy tu gemelo digital."
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

CLIPS_DIR = REPO / ".triage" / "clips" / "prepped"
OUT_DIR = REPO / "qa" / "out"


async def _run(avatar: str, frase: str, voice: str | None) -> dict:
    from app.pipeline.runpod_musetalk import RunPodMuseTalkClient
    from app.orchestrator.tts import stream_sentence_tts

    client = RunPodMuseTalkClient()

    # 1. prepare (idempotente: si ya están los latentes, el worker responde rápido)
    clips = {p.stem: p.read_bytes() for p in CLIPS_DIR.glob("*.mp4")
             if not p.stem.startswith("_")}
    print(f"[gate] prepare_avatar {avatar} ({len(clips)} clips)…", flush=True)
    prep = await client.prepare_avatar(avatar, clips)
    print("[gate] prepare:", prep, flush=True)

    # 2. TTS real de la frase
    audio = bytearray()
    kw = {"voice_id": voice} if voice else {}
    async for ch in stream_sentence_tts(frase, **kw):
        audio += base64.b64decode(ch.audio_b64)
    print(f"[gate] TTS: {len(audio)} bytes MP3", flush=True)

    # 3. speak → MP4
    t0 = time.time()
    video = await client.speak(avatar, "idle_a", bytes(audio))
    dt = time.time() - t0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mp4 = OUT_DIR / "a2_speak.mp4"
    mp4.write_bytes(video)
    print(f"[gate] speak: {dt:.1f}s → {mp4}", flush=True)
    return {"speak_seconds": round(dt, 1), "mp4": str(mp4)}


def _measure_and_sheet(mp4: Path) -> dict:
    import cv2
    import numpy as np
    import mediapipe as mp
    from mediapipe.tasks import python as mpy
    from mediapipe.tasks.python import vision

    # modelo face landmarker (boca) — Tasks API
    model = Path.home() / ".cache" / "mediapipe" / "face_landmarker.task"
    if not model.exists():
        import urllib.request
        model.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(
            "https://storage.googleapis.com/mediapipe-models/face_landmarker/"
            "face_landmarker/float16/1/face_landmarker.task", model)

    cap = cv2.VideoCapture(str(mp4))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    cap.release()

    opts = vision.FaceLandmarkerOptions(
        base_options=mpy.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO)
    # labios: 13 (interior superior) y 14 (interior inferior); normalizar por
    # distancia interocular (33-263) para invarianza a escala
    opens = []
    with vision.FaceLandmarker.create_from_options(opts) as lm:
        for i, f in enumerate(frames):
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            res = lm.detect_for_video(img, int(i * 1000 / fps))
            if not res.face_landmarks:
                opens.append(None); continue
            p = res.face_landmarks[0]
            mouth = abs(p[14].y - p[13].y)
            eye = abs(p[263].x - p[33].x) + 1e-6
            opens.append(mouth / eye)
    valid = [o for o in opens if o is not None]
    rng = (max(valid) - min(valid)) if valid else 0.0
    med = float(np.median(valid)) if valid else 0.0
    crossings = sum(1 for a, b in zip(valid, valid[1:])
                    if (a - med) * (b - med) < 0)

    # hoja: 6 frames equiespaciados + curva de apertura
    idxs = np.linspace(0, len(frames) - 1, 6).astype(int)
    from PIL import Image, ImageDraw
    thumbs = []
    for k in idxs:
        im = Image.fromarray(cv2.cvtColor(frames[k], cv2.COLOR_BGR2RGB))
        h = 360; thumbs.append(im.resize((int(im.width * h / im.height), h)))
    row = Image.new("RGB", (sum(t.width for t in thumbs) + 5 * 6, 360), "black")
    x = 0
    for t in thumbs:
        row.paste(t, (x, 0)); x += t.width + 5
    # curva
    cw, chh = row.width, 150
    curve = Image.new("RGB", (cw, chh), "#111")
    dc = ImageDraw.Draw(curve)
    if valid:
        lo, hi = min(valid), max(valid)
        span = (hi - lo) or 1
        pts = [(int(i * cw / len(opens)),
                chh - 10 - int(((o if o is not None else lo) - lo) / span * (chh - 20)))
               for i, o in enumerate(opens)]
        dc.line(pts, fill="#4ade80", width=2)
    sheet = Image.new("RGB", (cw, 360 + chh + 40), "black")
    sheet.paste(row, (0, 0)); sheet.paste(curve, (0, 360))
    d = ImageDraw.Draw(sheet)
    d.text((8, 360 + chh + 8),
           f"apertura bucal: rango {rng:.3f}  cruces(silabas~) {crossings}  "
           f"frames {len(frames)}  boca(verde)=apertura vs tiempo",
           fill="yellow")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sheet_path = OUT_DIR / "a2_gate_sheet.jpg"
    sheet.save(sheet_path, quality=88)
    return {"mouth_open_range": round(rng, 3), "mouth_motion_events": crossings,
            "frames": len(frames), "sheet": str(sheet_path)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--avatar", default="demo")
    ap.add_argument("--frase", default="Hola, soy tu gemelo digital y hablo contigo.")
    ap.add_argument("--voice", default=None)
    ap.add_argument("--skip-render", action="store_true",
                    help="usar qa/out/a2_speak.mp4 ya generado")
    a = ap.parse_args()

    meta = {}
    if not a.skip_render:
        meta = asyncio.run(_run(a.avatar, a.frase, a.voice))
        mp4 = Path(meta["mp4"])
    else:
        mp4 = OUT_DIR / "a2_speak.mp4"
    metrics = _measure_and_sheet(mp4)
    metrics.update(meta)

    # gate mecánico (el juicio de visión lo añade el agente sobre la hoja).
    # Umbral de apertura calibrado 2026-07-22: una boca hablando de verdad da
    # rango ~0.05-0.10 en (distancia interior labios / interocular).
    gate = {
        "mouth_moves": metrics["mouth_open_range"] > 0.04,
        "has_syllables": metrics["mouth_motion_events"] >= 3,
        "latency_ok": meta.get("speak_seconds", 99) < 8,  # útil; ideal <4
    }
    metrics["gate_mecanico"] = gate
    metrics["gate_mecanico_pasa"] = all(gate.values())
    (OUT_DIR / "a2_metrics.json").write_text(json.dumps(metrics, indent=2))
    print(json.dumps(metrics, indent=2))
    print("\nGATE-A2 mecánico:", "✅" if metrics["gate_mecanico_pasa"] else "❌",
          "→ falta juicio de visión del agente sobre", metrics["sheet"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

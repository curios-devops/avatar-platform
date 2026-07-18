"""Validación A0 (criterio de aceptación de docs/nueva_arquitectura.md):

  - pipeline texto→audio con primer chunk de audio < 1.5 s tras el
    primer token del LLM
  - visemas presentes en cada mensaje (de audio)

Uso:  cd backend && .venv/bin/python scripts/test_orchestrator.py [texto]
Guarda el audio concatenado en /tmp/a0_reply.mp3 para escucharlo.
"""
import asyncio
import base64
import json
import sys
import time

import websockets

WS = "ws://localhost:8000/api/v1/converse/ws"
PROMPT = sys.argv[1] if len(sys.argv) > 1 else \
    "Hola, preséntate en un par de frases y dime qué puedes hacer."


async def main() -> int:
    audio = b""
    n_audio_msgs = 0
    n_with_visemes = 0
    lat_reported = None
    t_send = time.monotonic()
    t_first_audio = None
    sentences = []

    async with websockets.connect(WS, max_size=16 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "user_text", "text": PROMPT}))
        while True:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=60)
            except asyncio.TimeoutError:
                print("TIMEOUT esperando mensajes"); return 1
            msg = json.loads(raw)
            if msg.get("type") == "error":
                print("ERROR:", msg); return 1
            if msg.get("type"):        # transcript u otros auxiliares
                continue
            estado = msg.get("estado")
            if msg.get("audio_chunk"):
                n_audio_msgs += 1
                if t_first_audio is None:
                    t_first_audio = time.monotonic()
                if msg.get("lat_primer_chunk_ms") is not None:
                    lat_reported = msg["lat_primer_chunk_ms"]
                if msg.get("visemas"):
                    n_with_visemes += 1
                audio += base64.b64decode(msg["audio_chunk"])
                if msg.get("texto_frase") and msg["texto_frase"] not in sentences:
                    sentences.append(msg["texto_frase"])
            if msg.get("fin_de_respuesta"):
                break

    open("/tmp/a0_reply.mp3", "wb").write(audio)
    e2e = (t_first_audio - t_send) if t_first_audio else None
    print(f"frases: {len(sentences)}")
    for s in sentences:
        print(f"  · {s}")
    print(f"mensajes de audio: {n_audio_msgs}  (con visemas: {n_with_visemes})")
    print(f"latencia primer-token→primer-audio (servidor): {lat_reported} ms")
    print(f"latencia e2e envío→primer-audio (cliente):     {e2e*1000:.0f} ms" if e2e else "sin audio")
    print(f"audio total: {len(audio)/1024:.0f} KiB → /tmp/a0_reply.mp3")

    ok = (lat_reported is not None and lat_reported < 1500
          and n_audio_msgs > 0 and n_with_visemes == n_audio_msgs)
    print("ACEPTACIÓN A0:", "✅ PASA" if ok else "❌ NO PASA")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))

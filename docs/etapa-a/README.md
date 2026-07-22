# ETAPA A — Híbrido de video (docs/nueva_arquitectura.md)

## Estado
- ✅ **Fase 0 — Contrato compartido**: `backend/app/orchestrator/contract.py`
- ✅ **A0 — Orquestador conversacional** (validado 2026-07-18)
- ⬜ A1 clips base · ⬜ A2 MuseTalk · ⬜ A3 cliente Feed · ⬜ A4 UX

## A0 — qué hay y cómo se ejecuta
WebSocket `ws://localhost:8000/api/v1/converse/ws` (router `app/api/converse.py`).

Pipeline por respuesta (`app/orchestrator/`):
`user_text|user_audio` → [STT faster-whisper] → LLM streaming (`llm.py`) →
troceo por frases (`sentences.py`) → TTS streaming con timestamps por carácter
(`tts.py`, ElevenLabs `stream/with-timestamps`) → visemas (`visemes.py`,
grafema→visema Oculus 15) → mensajes del contrato por chunk de audio.

- Persona: **clon digital de la persona de la foto** (primera persona, nunca
  "asistente virtual") — prompt en `llm.py`, sobreescribible con
  `ORCH_SYSTEM_PROMPT`.
- Config (`app/config.py`): `ORCH_LLM_PROVIDER` (openai|gemini),
  `ORCH_OPENAI_MODEL` (gpt-4o-mini), `ORCH_GEMINI_MODEL`,
  `ORCH_WHISPER_MODEL` (base).
- Visemas: del alignment real del TTS (sin latencia extra; sustituye a Azure
  visemes del plan; Rhubarb queda como refinamiento offline opcional).
  `t_ms` relativo al inicio del audio de la frase; timeline acumulada en cada
  mensaje (el último de la frase lleva la completa).
- Barge-in: `{"type":"interrupt"}` cancela la respuesta → estado
  `escuchando` + gesto `listen` (lo que A3 conecta al VAD).

Requisitos host: `brew install ffmpeg` (STT decodifica webm/mp3→wav);
faster-whisper baja el modelo (~145 MB) en el primer uso y queda residente.

Validación (reproducible):
```bash
cd backend && .venv/bin/python scripts/test_orchestrator.py "Hola, ¿quién eres tú?"
```

## Latencias medidas (M4 Pro, 2026-07-18)
| Métrica | Medido | Criterio |
|---|---|---|
| Primer token LLM → primer chunk audio (servidor) | **612–836 ms** | < 1500 ms ✅ |
| Envío texto → primer audio (cliente, e2e) | 1.8–2.4 s | — |
| STT en caliente (clip ~13 s) | 0.9 s | — |
| Voz → primer audio (e2e con STT) | 2.3 s | — |
| Visemas presentes en cada mensaje de audio | 17/17, 19/19 | todos ✅ |
| Barge-in: chunks tras interrupt | 0 | corte limpio ✅ |

## Limitaciones conocidas
- Visemas por grafema (es/en aproximado): suficiente para modo 3D/depurar;
  el modo Feed usa MuseTalk (A2) y no los consume.
- STT serializado (un whisper a la vez por proceso); para multi-sesión real
  mover a worker propio o aumentar instancias.
- `estado: "idle"` cubre también "pensando" (A3 lo pinta con indicador sutil).
- Historial de conversación en memoria del proceso (ventana de 12 turnos);
  se pierde al reiniciar — suficiente para A0.

## A2 — Worker de lip-sync (MuseTalk) — VALIDADO 2026-07-22

Serverless RunPod, **deps en la imagen** (`devopsavatar/musetalk-worker:w8`) +
**pesos en network volume** (`musetalk-w1`, US-IL-1; ~9,3 GB). Endpoint
`do0duporweapns` (0-2 workers, FlashBoot, idle 300). Cliente
`app/pipeline/runpod_musetalk.py`.

Jobs: `bootstrap` (baja pesos de 6 repos HF al volumen, una vez), `warmup`
(modelos residentes), `prepare_avatar` (latentes por clip, persistentes en el
volumen; **1 clip/request** por el límite de payload de /run), `speak`
(audio de frase → MP4 H.264 9:16 con audio muxeado, vía `/runsync`).

### Validación (gate visual, no "corrió sin errores")
`qa/gate_a2_lipsync.py`: prepara 5 clips → TTS real → speak → mide apertura
bucal por frame (face landmarker) → hoja `qa/out/a2_gate_sheet.jpg`.
- **Juicio de visión: PASA.** Boca articula formas de vocal/consonante
  (cerrada/abierta/redondeada), identidad intacta, sin deformación de banda,
  parpadeo natural del clip base. Curva: 10 cruces silábicos + silencios.
- Métrica: `mouth_open_range` 0.073, `mouth_motion_events` 10 (umbral 0.04).
- MP4 de muestra: `qa/out/a2_speak.mp4` (720×1280, 25fps, audio AAC).

### Latencias (4090, caliente)
| Métrica | Medido | Objetivo |
|---|---|---|
| speak /run (polling) | 6,7 s | — |
| speak /runsync | **5,3–5,8 s** | < 4 s ⚠️ |
| prepare (5 clips) | ~una vez por avatar | — |

**Sobre el objetivo <4 s:** 5,3 s caliente es el suelo de MuseTalk para una
frase completa en esta GPU. Mitigaciones: (1) el **pipelining** (frase N se
renderiza mientras N-1 se reproduce) oculta la latencia tras la 1ª frase;
(2) primera frase corta; (3) híbrido audio-primero (sonar el audio <1 s y
cambiar al vídeo con lip-sync al estar listo). Aceptable para el POC.

### Cadena de errores resuelta (packaging, ~15 ciclos → disciplina de gate)
pip --target indeterminista → **re-arquitectura deps-en-imagen** → hub 1.24.0
(runpod lo subía; pin 0.30.2 como último paso) → pesos multi-repo → mirror
`hf-mirror.com` roto + `pip -U` en download_weights.sh → gdown/Drive falla →
**mirror HF** para face-parse → globals de MuseTalk (`fp=FaceParsing`) →
ruta `./results/v15/avatars` hardcodeada (symlink al volumen). Cada fallo se
detectó con evidencia, sin cantar victoria en falso.

### Limitaciones conocidas
- Latencia 5,3 s/frase > 4 s objetivo (ver mitigaciones).
- Concurrencia ≥3 sesiones/GPU: no medida aún (workersMax 2, escala por cola).
- `listen` con boca entreabierta a media (irrelevante: MuseTalk repinta al hablar).

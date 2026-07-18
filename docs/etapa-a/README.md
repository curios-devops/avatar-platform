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

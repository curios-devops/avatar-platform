# QA 2026-11-02: MEYA y Avatar Studio

Pruebas en local. No se publicó nada, no se cambió ningún `.env`, RunPod ni código de los repos, y no hay commits.
Los parches de esta carpeta se validaron en copias desechables. Aplicar con `git apply -p0 reports/qa_2026-11-02/<archivo>.patch`.

## Avatar Studio

| # | Sev. | Hallazgo | Evidencia | Estado |
|---|---|---|---|---|
| A1 | Alta | Sin LAM el pipeline cae en silencio a un fallback CPU: cara borrosa y deformada con "Your avatar is ready!" | Job real con Gemini 403, MICA 404 y LAM sin workers; `pipeline_worker.py` hace fallback en cualquier excepción | Falta decidir |
| A2 | Alta | Si el lip-sync falla, la respuesta se pierde: ni audio ni texto, aunque el log dice "solo audio" | 409 real de RunPod, 0 mensajes de audio | Parche 02 validado |
| A3 | Alta | Se pierde la primera frase con lip-sync: el cambio de estado pisa el `src` (`AbortError`) | Backend simulado con 3 clips reales | Parche 01 validado |
| A4 | Alta | La última frase queda oculta 0,2 s después de empezar y su audio suena sobre el clip en reposo | Mismo test | Parche 01 validado |
| A5 | Alta | Subtítulo y estado "hablando" terminan al acabar el envío: 1 s de 7,5 s de audio | Medido en navegador | Parche 01 validado |
| A6 | Alta si se publica | Sin auth ni rate limit; `/avatar/analyze` y `/reframe` descargan cualquier URL (SSRF confirmado en loopback) | Petición recibida en un servidor local | Pendiente |
| A7 | Media | Imagine roto: `gpt-image-1` retirado y `response_format` rechazado; la UI solo dice "Something went wrong" | 400 real | Parche 03 validado |
| A8 | Media | 4 de 5 clips del Feed en MPEG-4 Part 2: Chrome no reproduce pensando, escuchando ni gestos | `ffprobe` + `NotSupportedError` en `idle_b` | Pendiente: recodificar a H.264 |
| A9 | Media | `/avatar/upload` no valida tipo ni tamaño y guarda todo como `.mp4` | Aceptó un HTML de 12 MB | Pendiente |
| A10 | Media | `.env` desactualizado: MICA da 404 y falta `RUNPOD_LHM_ENDPOINT_ID` (existe `avatar-lhm-v1`) | API de RunPod | Pendiente |
| A11 | Media | Modo Video llama a `/avatar/create`, pipeline antiguo; endpoint `avatar-platform` con max 0 | Lectura de código, no ejecutado | Revisar si sigue vivo |
| A12 | Media | Barge-in no detiene un vídeo con lip-sync en curso: `micDown` solo para el audio MSE | Lectura de código, no ejecutado | Pendiente |
| A13 | Baja | `npm run build` falla por 35 errores TS (31 de WebGPU); `vite build` funciona | `tsc` real | Pendiente |
| A14 | Baja | `analyze` falla sin avisar; `user_text` vacío gasta LLM; `speak` con espacios gasta TTS; JSON inválido tumba el WS; `onWheel` da error passive | Probado | Pendiente |

Funciona: A0 con OpenAI (462 ms primer token a primer audio, visemas en 25/25), Whisper, barge-in por WS, ElevenLabs, visor WebGPU a 120 fps, Make it Talk, zoom, repetir, traversal bloqueado.
Regresión 3D: ArcFace frontal 0,2271 (base 0,227), huecos ≤45° 0,54%, tope 1%.
No probado: compartir con clic real, micrófono real, lip-sync con GPU real, creación de avatar con LAM real.

## MEYA

| # | Sev. | Hallazgo | Evidencia | Estado |
|---|---|---|---|---|
| M1 | Alta | Video de presentación bloqueado: el Space público pide 480 s de ZeroGPU y la cuota anónima no alcanza | Mismo error con el modo más rápido y audio de 2 s | Falta `HF_TOKEN` con cuota |
| M2 | Alta | Con `REQUIRE_PRESENTATION_VIDEO=false` el video se encola y nadie lo consulta, y gasta crédito | Sin `GET /api/presentations` en el log | Pendiente |
| M3 | Alta | Fotos privadas accesibles por URL, y siguen después de borrar el ser, con caché pública de 1 año | 200 tras borrar | Pendiente |
| M4 | Media | Imagen > 6 MB rompe toda la página; no hay `error.tsx` en la app | Reproducido con 7 MB | Pendiente |
| M5 | Media | `gpt-image-1` retirado: "Generar con IA" falla | 400 real; con `gpt-image-1-mini` funciona en 30 s | Pendiente |
| M6 | Media | Dev login solo se bloquea con `VERCEL_ENV=production`: fuera de Vercel depende de que `AUTH_DEV_LOGIN` no esté activo | `auth-flags.ts` | Pendiente antes de Cloudflare |
| M7 | Media | Límite de invitado por `x-forwarded-for`, falsificable según el host; en Cloudflare usar `cf-connecting-ip` | Lectura de código | Pendiente antes de publicar |
| M8 | Baja | Se pierde `next` tras la bienvenida; error genérico sin proveedor de imágenes; log de imagen sin causa; "está listo" sin concordancia; ".." en instrucciones; texto de publicar incorrecto si falta consentimiento; títulos genéricos en varias páginas | Probado | Pendiente |

Funciona: 46 tests web, 85 runtime, typecheck, lint, build; landing EN/ES; registro, feed y acciones sociales; IA real (chat, memoria, propuesta, imagen, voz); privacidad entre usuarios; moderación; consentimiento de Twin; invitado limitado a 8; móvil 390 px sin desbordes; Lighthouse 96/100/100.
Nota: arrancar con `--hostname 127.0.0.1` provoca un bucle 307 en inglés. Usar sin hostname o `--hostname localhost`.

## Cloudflare (solo pruebas locales, sin cuenta)

- MEYA compila con OpenNext tras subir Next 16.3.8 a 16.4.4. Con esa versión pasan typecheck, 46 tests y lint.
- En `workerd`: `proxy.ts`, i18n, assets, optimizador y `/technology` funcionan. Las páginas con datos dan 500 solo porque PGlite no puede escribir en disco; con Neon ese camino no se usa, pero queda por verificar.
- Bundle 2,73 MiB gzip, muy cerca del límite de 3 MiB del plan gratuito.
- Almacenamiento: Vercel Blob o un adaptador nuevo para R2; sin ninguno, `putMedia` escribe en disco y falla en Workers.
- El runtime Python necesita un host persistente.
- El frontend de Avatar va a Pages; su backend necesita Tunnel o un host persistente, con auth antes de exponerlo.

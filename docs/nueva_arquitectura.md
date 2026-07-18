# Proyecto: Avatar conversacional — Plan maestro de implementación
# Agente: Claude Opus 4.8 (Claude Code)

## Visión
Avatar generado desde UNA foto que conversa en tiempo real.
Dos renderers sobre un mismo backend conversacional:
- **Modo Feed (Etapa A, prioridad):** híbrido de video — clips base
  fotorrealistas pregenerados + lip-sync en vivo con MuseTalk.
- **Modo 3D (Etapa B, refactor después):** avatar Gaussian interactivo
  (LHM cuerpo + LAM cabeza + Spark 2.0) con órbita y zoom en cliente.
El cambio entre modos es una acción de UX explícita (nunca un morph
automático a mitad de un plano).

## Regla de oro
Sin entrenamiento ni fine-tuning. Solo inferencia con pesos publicados.
Cada fase se ejecuta y valida de forma independiente antes de continuar.

## Contrato compartido (implementar PRIMERO, en Etapa A, Fase 0)
Mensaje interno del orquestador que ambos renderers consumen:
```json
{
  "session_id": "...",
  "seq": 42,
  "estado": "hablando | escuchando | idle",
  "audio_chunk": "<opus/pcm base64 o URL>",
  "visemas": [{"t_ms": 0, "id": "PP", "peso": 1.0}, ...],
  "gesto": "idle_a | listen | gesture_enum | ...",
  "texto_frase": "..."
}
```
El modo Feed usa audio+estado+gesto; el modo 3D usará visemas+estado+gesto.

═══════════════════════════════════════════════════════════
# ETAPA A — HÍBRIDO DE VIDEO (producto core)
═══════════════════════════════════════════════════════════

## A0 — Orquestador conversacional (backend compartido)
1. Servicio (Python/FastAPI + WebSocket) que encadena en streaming:
   STT (faster-whisper) → LLM (API, streaming de tokens, troceo por
   frases con regex de puntuación) → TTS streaming.
2. TTS: usar un TTS que emita visemas con timestamps (Azure Speech) y,
   como fallback open source, audio + Rhubarb para estimar visemas.
3. Emitir el mensaje del contrato por frase.
✅ Acepta: pipeline texto→audio con primer chunk de audio < 1.5 s
   tras el primer token del LLM; visemas presentes en cada mensaje.

## A1 — Biblioteca de clips base (offline, una vez por avatar)
1. `make_clips.py`: desde `avatar.jpg`, generar con Wan2.2-S2V-14B
   (o EchoMimicV3 si la VRAM < 40 GB):
   - `idle_a.mp4`, `idle_b.mp4` (loops 8-10 s, micro-movimiento, SIN hablar)
   - `listen.mp4` (atención, asentir suave)
   - `gesture_enum.mp4`, `gesture_open.mp4` (manos visibles)
   Prompt/pose: encuadre medio cuerpo fijo, fondo neutro, cámara estática.
2. Post-proceso (`prep_clips.py`):
   - estabilizar encuadre, normalizar color entre clips (match histograma)
   - detectar frames de corte compatibles entre clips (pose similar por
     landmarks de MediaPipe) y guardar `clip_graph.json` (máquina de
     estados: nodos=clips, aristas=frames de transición válidos)
✅ Acepta: reproducir idle_a→gesture_enum→idle_b encadenados por el
   clip_graph sin salto visible de pose/color.

## A2 — Worker de lip-sync (GPU persistente)
1. Servicio con MuseTalk precargado en VRAM (proceso residente).
2. Entrada: mensaje del contrato (audio de una frase + gesto elegido).
   Proceso: scheduler toma frames del clip_graph según `gesto` y estado;
   MuseTalk repinta la región bucal frame a frame con el audio.
3. Salida: chunks de video H.264 por frase (2-4 s cada uno).
4. Pipelining: procesar frase N mientras se reproduce la N-1.
✅ Acepta: latencia foto-a-primer-chunk < 4 s; una GPU de 24 GB
   sostiene ≥ 3 sesiones concurrentes a 25 fps.

## A3 — Cliente Feed (móvil-first, web)
1. Player de chunks (MVP: MSE con fMP4 encadenados; objetivo: WebRTC).
2. Barge-in: VAD en cliente (silero-vad wasm o webrtcvad) → al detectar
   voz del usuario, enviar `interrupt` → orquestador corta LLM/TTS,
   worker salta a clip `listen`.
3. Estados visuales: hablando (video con lip-sync), escuchando (listen
   loop), pensando (idle + indicador sutil).
✅ Acepta: conversación completa por voz con interrupción funcional;
   sin frames congelados entre frases.

## A4 — UX del modo Feed
1. Pantalla de respuesta: avatar a pantalla completa vertical (9:16),
   pregunta del usuario como overlay superior, transcripción en vivo
   como subtítulos (palabra a palabra sincronizada con el audio).
2. Controles: mantener pulsado para hablar (o toggle mic), botón de
   repetir respuesta, compartir clip (exporta el video de la respuesta
   ya renderizado — es gratis, ya existe).
3. Zoom con pellizco = zoom digital sobre el video (máx 2x). NUNCA
   cambia de renderer.
4. Botón "Ver en 3D" (icono cubo) visible pero deshabilitado con
   tooltip "próximamente" hasta que exista la Etapa B (feature flag).
✅ Acepta: test de usabilidad interno: un usuario nuevo hace una
   pregunta por voz y entiende los estados sin explicación.

═══════════════════════════════════════════════════════════
# ETAPA B — MODO 3D INTERACTIVO (feature diferenciador)
═══════════════════════════════════════════════════════════

## B1 — Generación (offline)
`generate.py`: foto → `body.ply` (LHM, github.com/aigc3d/LHM) +
`head.ply` (LAM, github.com/aigc3d/LAM) + parámetros SMPL-X/FLAME
y cámaras en `meta.json`. Misma foto que la Etapa A.
✅ Acepta: ambos .ply válidos en un visor de splats.

## B2 — Fusión cabeza-cuerpo (offline; el trabajo duro)
`fuse.py`:
 a. Eliminar splats de cabeza de LHM (peso de skinning dominante en
    huesos head/neck), dejando banda de solape ~2 cm bajo mandíbula.
 b. Registro rígido FLAME↔SMPL-X (SMPL-X incorpora topología FLAME:
    usar vértices/landmarks compartidos, Procrustes; normalizar escala
    por distancia interpupilar ANTES de optimizar; priorizar mandíbula
    y orejas sobre coronilla).
 c. Rampa de opacidad en la banda de solape (fade cruzado).
 d. Match de estadísticas de color en la zona de unión.
 e. Exportar `avatar_body.spz` + `avatar_head.spz` + `rig.json`
    (esqueleto, pesos, blendshapes FLAME).
✅ Acepta: render 360° estático sin costura visible a distancia de
   medio cuerpo; sin splats flotantes.
⚠️ Si el registro se atasca: visualizar ambos esqueletos superpuestos
   ANTES de seguir optimizando.

## B3 — Runtime Spark (cliente)
1. SparkRenderer (github.com/sparkjsdev/spark v2.x) + Three.js:
   cargar ambos .spz, cabeza parentada al hueso head. La cabeza LAM es
   la ÚNICA cabeza siempre (no hay swap por zoom; el LoD de Spark
   asigna presupuesto de splats automáticamente al acercarse).
2. Cuerpo: clips SMPL-X (idle loop + gestos) con interpolación,
   mapeados desde el campo `gesto` del contrato.
3. Cara: visemas del contrato → tabla viseme→coeficientes FLAME →
   desplazamiento de splats (shader graph de Spark), suavizado 60-80 ms,
   parpadeo procedural.
4. Cámara: órbita ±30° yaw / ±10° pitch + zoom continuo.
✅ Acepta: 30+ FPS en móvil de gama media; desfase audio-labios
   < 100 ms; zoom a la cara sin pop de LoD.

## B4 — UX del modo 3D y transiciones
1. Entrada: botón "Ver en 3D" en el modo Feed. Transición: CORTE o
   fade ≤ 300 ms; el avatar 3D aparece en pose frontal equivalente al
   último frame del video (misma cámara inicial). Nunca morph.
2. Dentro del modo: arrastrar = orbitar, pellizco = zoom, doble tap =
   volver a encuadre frontal. La conversación continúa sin cortarse
   (mismo orquestador; solo cambia el renderer que consume el contrato).
3. Salida: botón cerrar → corte a modo Feed reencuadrado frontal.
4. Primer uso: hint de 2 s ("arrastra para girar") una sola vez.
5. Degradación: si el dispositivo no sostiene 30 FPS (medir 3 s),
   reducir presupuesto N de splats del LoD; si sigue bajo, ocultar el
   botón 3D en ese dispositivo.
✅ Acepta: entrar y salir del modo 3D en mitad de una respuesta sin
   perder audio ni estado de la conversación.
═══════════════════════════════════════════════════════════
## B1.5 — Multiview sintético y reconstrucción reforzada (offline)
═══════════════════════════════════════════════════════════
Objetivo: eliminar los huecos/artefactos por oclusión del splat de
cabeza generando vistas nuevas ANTES de reconstruir, en vez de
reconstruir desde una sola foto.

### Paso 1 — Generación de vistas (`make_views.py`)
1. Entrada: `avatar.jpg` (misma foto de A1/B1), recorte de cabeza
   con margen (detección con MediaPipe/InsightFace).
2. Generar vistas sintéticas de la cabeza en estos ángulos mínimos:
   yaw = {-60°, -45°, -30°, -15°, +15°, +30°, +45°, +60°},
   pitch = {-10°, +10°} para los yaw = {±30°}.
   (Cubrimos ±45° de uso real con margen de +15° extra.)
3. Implementar DOS backends intercambiables y comparar:
   a. **Video órbita:** modelo image-to-video (SV3D o Wan con prompt
      de rotación de cámara) → extraer frames en los ángulos objetivo
      (estimar pose de cabeza por frame con un estimador 6DoF).
   b. **Multiview directo:** modelo multiview humano/cabeza
      (MVD-HuGaS o equivalente disponible en HuggingFace; verificar
      pesos publicados antes de elegir).
4. Control de calidad automático por vista generada:
   - similitud de identidad vs foto original (embedding ArcFace,
     coseno > 0.35 como umbral inicial, ajustable)
   - descartar vistas con score bajo; requerir mínimo 6 vistas válidas.
5. Salida: `views/` (imágenes + pose estimada por vista en
   `views_meta.json`).
✅ Acepta: ≥ 6 vistas que pasan el filtro de identidad; inspección
   visual: mismos rasgos, peinado y tono de piel en todas las vistas.

### Paso 2 — Reconstrucción con múltiples vistas (`reconstruct.py`)
1. Ruta preferente: reconstructor de cabeza que acepte entradas
   dispersas/sin restricciones (Avat3r u otro con pesos publicados)
   alimentado con foto original + vistas sintéticas.
2. Ruta fallback (si no hay reconstructor multiview utilizable
   out-of-the-box): mantener LAM como generador base y usar las
   vistas sintéticas como supervisión de refinamiento: renderizar el
   splat LAM en las poses de `views_meta.json`, optimizar SOLO los
   Gaussians de baja opacidad/alta incertidumbre en las regiones
   laterales contra las vistas sintéticas (L1 + SSIM), congelando la
   región frontal para no degradar la semejanza.
3. La salida sustituye a `head.ply` de B1; B2 (fusión) no cambia.
✅ Acepta (criterio del proyecto): render del splat de cabeza rotando
   yaw ±45° y pitch ±10° SIN líneas negras, huecos ni splats
   flotantes; identidad frontal intacta (ArcFace coseno vs foto
   original ≥ el del splat LAM sin refinar, tolerancia -0.02).

### Comparación obligatoria antes de cerrar la fase
Generar un GIF lado a lado (mismo barrido de cámara ±45°):
  [LAM solo] vs [LAM + B1.5]
y guardarlo en `reports/b15_comparison.gif` con métricas en
`reports/b15_metrics.json` (ArcFace por ángulo, % de píxeles de
fondo visibles a través del splat como proxy de huecos).

### Riesgos y mitigaciones
- Vistas inconsistentes entre sí (perfil izq/der con detalles
  distintos) → es esperable; el filtro de identidad + congelar el
  frontal limita el daño. No perseguir consistencia perfecta.
- El refinamiento degrada la cara frontal → si ArcFace frontal cae
  más de 0.02, reducir learning rate o máscara de optimización.
- Pelo largo/volumen → es el caso más difícil; documentar como
  limitación si los laterales del pelo quedan blandos.

### Dependencias e impacto en el plan
- Requiere B1 terminado. B2 consume el nuevo head.ply sin cambios.
- Actualizar B3/B4: si B1.5 pasa, ampliar la órbita de cámara de
  ±30° a ±45° yaw (mantener ±10° pitch).
- GPU: ≥ 24 GB (los dos backends del Paso 1 caben; el refinamiento
  del Paso 2 es ligero).
═══════════════════════════════════════════════════════════
# Orden de ejecución y dependencias
═══════════════════════════════════════════════════════════
A0 → A1 → A2 → A3 → A4  (lanzable como producto)
B1 → B2 → B3 → B4 → B5  (requiere A0 terminado; nada más de A)
MVP de validación temprana: A0 mínimo + A1 con solo
idle_a y listen + A2 con chunks MP4 + player básico.

## Infraestructura
- Offline A1: GPU ≥ 40 GB (Wan2.2-S2V) o ≥ 16 GB (EchoMimicV3).
- Offline B1-B2: GPU CUDA ≥ 24 GB.
- Runtime A2: GPU 24 GB persistente (multi-sesión).
- Runtime B3: 100% cliente (WebGL2).

## Documentar en README de cada etapa
Comandos exactos, VRAM por paso, latencias medidas, y limitaciones
conocidas (A: suavidad bucal en primeros planos extremos;
B: manos borrosas, espalda alucinada, ropa rígida, boca aproximada).
# Ronda 4: resumen ejecutivo (2026-11-13)

**Objetivo:** probar un flujo de personaje 3D sin costo de APIs, que vaya de una imagen a un medio cuerpo 3D que conversa, y comparar dos formas de mover la cara: nuestros visemas en three.js y NVIDIA Audio2Face-3D.

**Personaje:** Jasom, un personaje original y ficticio. Atardecer costero, camiseta blanca sin mangas y cadena. No copia a ningún personaje existente.

## Flujo probado (todo gratis salvo 0,055 USD de GPU)

1. **Imagen base:** Z-Image-Turbo en el Mac (8 bits, 768x1152, 131 s).
2. **Gemelo 3D:** el servicio humano ajusta la cara y proyecta la textura (10 s en CPU). El cuerpo sale del horneado de la GLB (0,1 s; 3,3 MB más una textura de 5 MB).
3. **Voz:** voces de macOS (gratis). Los tiempos por palabra salen de whisper local (1,6 s).
4. **Conversación:** 16,9 s, con dos turnos de Jasom y medio cuerpo en three.js. El cuerpo, la mirada, el parpadeo y la respiración son los mismos en los dos motores; solo cambia la cara.

## Resultado

| | three.js (visemas) | NVIDIA Audio2Face-3D v3.0 |
|---|---|---|
| Sincronía de la mandíbula con la voz (r) | **0,71** | 0,69 |
| Desfase | 83 ms tarde | **a tiempo** (−17 ms) |
| Boca cerrada en silencio | sí (0,046) | sí (0,045) |
| Partes de la cara | solo la boca | **cara completa** (más de 20 formas: cejas, labios, mejillas) |
| Lectura visual en nuestro modelo | **clara**, se ve que habla | apretada: los pesos vienen de su propia cara de referencia y hay que calibrarlos para la nuestra |
| Necesita el texto o sus tiempos | sí | **no**, solo el audio |
| Dónde corre | navegador del usuario, 105 fps en el M2 Pro | GPU NVIDIA (CUDA y TensorRT); no corre en Mac |
| Velocidad | tiempo real | 16,9 s de audio en 0,50 s (34 veces el tiempo real) con el solver en GPU; 41 s con el solver en CPU |
| Puesta en marcha | nada | unos 25 min la primera vez (TensorRT, 6,9 GB de descarga; compilación, 70 s; motor, 34 s) |
| Espacio | GLB de 3,3 MB y textura de 5 MB por personaje | unos 13 GB (TensorRT 11 GB, modelo 0,7 GB, motor 0,7 GB); se podría reducir dejando solo las bibliotecas de ejecución |
| Costo | 0 USD | 0,055 USD en RunPod (RTX 3090, 0,22 USD/h, unos 15 min de uso) |
| Licencia | nuestra | SDK MIT; modelo con licencia NVIDIA Open Model, uso comercial permitido |

## Decisión

- **three.js con visemas sigue siendo el motor principal.** Es gratis, corre en el equipo del usuario y en nuestro modelo se lee mejor.
- **Audio2Face queda como mejora para la cara.** Llega a tiempo, no necesita el texto y mueve toda la cara. Antes de llevarlo a producto hay que:
  1. calibrar las ganancias por blendshape (abrir más la mandíbula y aflojar el cierre y el apretado de labios);
  2. medirlo en streaming;
  3. decidir si vale tener una GPU de servidor por llamada. Con 34 veces el tiempo real, una 3090 alcanza para muchas llamadas a la vez.
- **Arreglo para three.js:** el retraso de unos 80 ms se puede corregir adelantando los visemas.

## Calibración de Audio2Face para nuestro modelo (2026-11-14)

**Causa de la boca apretada:**
- Algunas formas no vuelven a cero en reposo: mouthRollLower queda en 0,23 (labio inferior recogido) y mouthPress y mouthStretch rondan 0,09.
- mouthClose sube junto con la mandíbula. En la cara de referencia de NVIDIA eso compensa la apertura; en la nuestra cierra los labios.

**Perfil de calibración** (`lab/a2f/a2f_calibrate.py` → `a2f_calib.json`):
- Por cada forma, se le resta su valor en reposo y se multiplica por una ganancia.
- La ganancia de jawOpen se calcula para que abra igual que nuestros visemas (×1,61).
- Ganancias bajas para mouthClose (×0,25), mouthRollLower (×0,3) y mouthPress (×0,5).
- Las cejas se suavizan (×0,7).
- Es un JSON por modelo, y se aplica en el navegador sin volver a correr la GPU.

**Medido sobre el render** (`arena4_render_metric.py`): porcentaje de dientes o interior de la boca visibles en el recorte de los labios.

| | three.js | A2F sin calibrar | **A2F calibrado** |
|---|---|---|---|
| Apertura visible al hablar | 3,3 % | 0,55 % | **2,7 %** |
| Apertura en silencio | 0,7 % | 0,1 % | 0,5 % |
| Sigue a la voz (r) | 0,70 | 0,28 | **0,60** |

**Resultado:**
- Con la calibración, Audio2Face ya se lee como que habla: abre cinco veces más y sigue mucho mejor a la voz.
- Queda cerca de three.js, pero todavía no lo supera.
- Archivos: `arena4_calibracion_3.mp4` (los tres lado a lado) y `arena4_calib_mouths.jpg`.

## Laboratorio local (Mac M2 Pro, 16 GB)

- **Z-Image-Turbo:**
  - 8 bits: 131 s y 8 GB de memoria.
  - 4 bits: 127 s y 5 GB, con calidad equivalente.
  - Como 4 bits no baja el tiempo, queda 8 bits, y 4 bits solo para equipos de 8 GB.
- **Vídeo local (Wan):**
  - Los "menos de 2 GB" del modelo 1.3B solo cuentan el transformer. El codificador de texto umT5 suma 3,7 GB más en Q4.
  - La versión T2V-1.3B no recibe imagen, así que no mantiene la cara del personaje. La que sirve para clips es VACE-1.3B (Q4_K_M, 1,5 GB), que sí acepta una imagen de referencia.
  - Wan2.2 TI2V-5B (MLX, 19,6 GB) pide 32 GB o más.
  - No lo probé todavía.

## Archivos

- `arena4_threejs_vs_a2f.mp4`: los dos lado a lado, con audio.
- `arena4_frames.jpg`, `arena4_jaw_vs_voice.png`, `arena4_metrics.json`.
- `a2f/`: pesos ARKit por cuadro, nombres de las formas y tiempos.
- `../local_image/q8_vs_q4.jpg`.
- Código:
  - `lab/a2f/` (`a2f_dump.cpp`, `setup_a2f.sh`, `arena4_metrics.py`, `lab_files.py`);
  - la página `?human=arena4` en `avatar-platform-human/frontend/src/human/Arena4.tsx`.

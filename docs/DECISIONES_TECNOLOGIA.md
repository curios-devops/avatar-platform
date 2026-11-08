# Decisiones de tecnología del ser digital (2026-11-07)

Qué usa el código activo en cada caso de uso, qué queda de respaldo y qué pasa al laboratorio.

- **Activo:** lo que usa el producto hoy.
- **Respaldo:** lo que entra si el ganador falla o no aplica.
- **Laboratorio:** se conserva en su rama o detrás de un interruptor apagado, para revisarlo cuando salgan versiones nuevas, pero el código activo no lo llama.

Las decisiones salen de una comparación con la misma imagen y el mismo audio por caso (unos 6 s). Vídeos y métricas en `.triage/decide/`: `CMP_*.mp4` y `metrics.json`.

## Casos de uso

| Caso | Ganador | Respaldo | Notas |
|---|---|---|---|
| **1A** · fotorrealista (foto/vídeo real o foto IA realista), medio cuerpo, conversación | MuseTalk (Etapa A), **en laboratorio hasta reactivar RunPod** | three.js Twin | Mientras MuseTalk esté apagado, el modo activo es el Twin. |
| **1B** · fotorrealista, cuerpo completo | **3b:** PINOC + Splat Engine para el cuerpo en vivo, más primeros planos pregenerados con Pruna Pro cuando habla | three.js Twin | Pruna solo pregenerado, porque no hace streaming. |
| **2A** · personaje animado, medio cuerpo | **three.js** | MuseTalk, en laboratorio | El clip base para MuseTalk ya está grabado (`2a_threejs_idle_base.mp4`). |
| **2B** · personaje animado, cuerpo completo | **Humanos:** three.js. **Criaturas:** kit SDF (LLM → three.js) | **Humanos:** PINOC + Splat Engine | PINOC solo genera personas. Criaturas: el kit SDF es la única vía. |

### Métricas de la comparación
La identidad se mide con ArcFace frente a la imagen común del caso. La boca, en rango de apertura dividido por la distancia entre ojos.

| Clip | Identidad | Boca | En vivo |
|---|---|---|---|
| 1A MuseTalk (clip antiguo, otra frase) | 0,74 | 0,11 | sí |
| 1A Pruna Pro | 0,70 | 0,34 | no (~48 s por cada 8 s) |
| 1A three.js Twin | 0,28 | 0,34 | sí |
| 1B 3b splat + Pruna | 0,90 | 0,25 | el cuerpo sí; al hablar, pregenerado |
| 1B PINOC | 0,78 | 0,06 (no habla) | sí |
| 1B three.js Twin | −0,16 | 0,25 | sí |
| 2A three.js, antes / después de la mejora de boca | 0,91 / 0,90 | 0,36 / 0,31 | sí |
| 2B three.js | 0,92 | 0,32 | sí |
| 2B PINOC (desde el render de three.js) | 0,51 | 0,08 | sí |
| 2B kit SDF (capibara) | — | mandíbula por visemas | sí |

La sincronía boca/audio del 2A sube de 0,36 a 0,47 con el suavizado nuevo.

## Laboratorio (fuera del código activo)

| Tecnología | Dónde vive | Por qué está aquí | Cuándo revisarla |
|---|---|---|---|
| MuseTalk 1.5 (RunPod) | `worker/musetalk_worker`, apagado con `ORCH_MUSETALK_ENABLED=false` | RunPod sin saldo y 191 trabajos atascados en cola | **2026-11-08:**<br>• La cola de la cuenta original ya está purgada (quedaban 28 trabajos) y esa cuenta se queda de respaldo.<br>• En la cuenta nueva (`RUNPOD_K_API_KEY`) está creado el endpoint `klnp0003oyai3e`: imagen w9, 0–1 workers, apagado a los 60 s.<br>• Su primer worker quedó en estado "unhealthy" y no llegó a ejecutar nada. Se limitó a CUDA 12.0–12.6, como el original; falta reintentar 1A y 2A.<br>• Gasto: 0,03 USD.<br><br>No hay versión nueva: la 1.5 es la última (último commit 26-9-2025). |
| Híbrido cuerpo PINOC + cara Twin | `exp/pinoc-3dgs`, `pinoc/web/hybrid.html` | Habla en vivo, pero la cara se ve CG sobre un cuerpo foto | Si mejora la piel del Twin |
| TripoSplat + esqueleto Anny | `exp/splat-human` | Identidad 0,30–0,35 y boca sin interior | Si sale un modelo de cabeza mejor |
| SHARP (Apple), foto → 3DGS | `~/Documents/lab/sharp` (fuera de los repos) | **Pesos solo para investigación no comercial.** Estático, sin esqueleto, 66 MB por escena. Sustituido por la réplica propia (`splat/livephoto`) | Ver «SHARP» abajo |
| PINOC / Viggle JST-2 | `exp/pinoc-3dgs` | Es el respaldo de 1B y 2B. El plan gratuito solo permite uso no comercial; el producto necesita plan de pago o la API (0,25 USD por personaje). Su biblioteca solo regala animaciones, no personajes | Antes de usarlo en el producto |
| Vork | — (lista de vigilancia) | Renderizador CLI nativo (PNG/MP4), no corre en el navegador | Si publica una salida web/glTF |
| EDGAR | — (lista de vigilancia) | Refina avatares gaussianos de cabeza que ya no usamos. Licencia no comercial, empeora la identidad, necesita GPU alquilada | Si vuelven las cabezas gaussianas |

Spark (World Labs) ya está en la última versión, 2.4.0. La copia en `splat/viewer/lib/spark.module.js` es idéntica byte a byte al paquete de npm.

## Mejoras hechas en esta ronda

### Palmas oscuras en PINOC
- **Causa:** PINOC rellena con splats oscuros lo que la foto de origen no muestra. En la foto de Mei las palmas están pegadas a los muslos. El color está horneado: los `.vsplat` de personaje no llevan armónicos esféricos, así que no es un problema de iluminación ni del motor.
- **Arreglo:** `pinoc/web/index.html` incluye un gancho de color. Los splats cerca de cada mano que son mucho más oscuros que el antebrazo se llevan hacia el tono de piel, que se lee del propio fotograma.
  - Activo por defecto; `?palmfix=0` lo apaga.
  - Evidencia: `.triage/decide/palm_fix_before_after.jpg` y `palm_fix_live.jpg`.
- **Prevención:** generar personajes con las palmas visibles en la foto, o con varias fotos (PINOC acepta de 1 a 5).

### Habla poco natural en three.js
- **Causas:**
  - Dientes y lengua se iluminaban como la cara, así que la boca abierta se veía rosa plano y sin profundidad.
  - Los incisivos superiores quedaban ocultos tras el labio.
  - Los visemas cambiaban con un fundido fijo de 70 ms.
- **Arreglo** (`frontend/src/human/engine.ts`, `visemes.ts`):
  - oclusión de la cavidad según la profundidad detrás de los incisivos y la apertura de la mandíbula;
  - dentadura y lengua bajadas un 5 % de la distancia entre ojos (unos 3 mm);
  - suavizado de visemas con ataque de 35 ms y relajación de 60 ms;
  - el labio superior sube algo en a/e/i.
- **Evidencia:** `.triage/decide/mouth_before_after.jpg` y `CMP_2A_habla_antes_despues.mp4`.
- **Dientes (2026-11-08):** la textura de MakeHuman es un modelo dental, con esmalte gris amarillento, manchas oscuras y encía roja, y de cerca parecían dientes con caries.
  - El shader los repinta de un blanco uniforme y conserva el 12 % del sombreado pintado.
  - La encía se lleva a sombra y la penumbra con la boca casi cerrada se suaviza, así que una sonrisa se lee como una banda blanca.
  - Evidencia: `.triage/decide/teeth_before_after.jpg`.

## SHARP: resultado y propuesta
- **Prueba local en el M2 Pro (MPS):**
  - 25–63 s por imagen y 1,18 M gaussianas (66 MB).
  - Fotorrealista entre ±20° y ±40° de giro. Se rompe a partir de unos 60°: a 90° es una lámina y aparecen manchas del fondo.
  - Evidencia: `.triage/decide/SHARP_portrait_yaw_0_20_40_60_90_-40.jpg`.
- **Uso posible:** «fotos vivas» con paralaje (landing, tarjetas de personaje), no avatares. No se mueve y la licencia de los pesos impide usarlo en el producto.
- **Réplica propia, aprobada y hecha el 2026-11-08** (`exp/splat-human`, `splat/livephoto/make.py`):
  - **Profundidad:** Depth Anything V2 Small (Apache-2.0).
  - **Recorte:** umbral de Otsu sobre esa profundidad, limitado por la máscara de persona de DETR panoptic (Apache-2.0, nativo en `transformers`). BiRefNet (MIT) se descartó porque exige ejecutar código remoto.
  - **Gaussianas:** una por píxel del sujeto, retroproyectada con cámara pinhole. Las de borde se alargan en profundidad, con tope, para que no se abran grietas al girar.
  - **Salida:** `.splat` y SPZ v2 con codificador propio escrito a partir del formato público. Spark lo carga sin cambios.

| | SHARP | Réplica propia |
|---|---|---|
| Tiempo por imagen (M2 Pro, en caliente) | 25–63 s | 2–3 s sin máscara de persona, ~35 s con ella |
| Gaussianas | 1,18 M | 83–151 k |
| Tamaño | 66 MB (PLY) | **0,43–0,73 MB (SPZ)**, 2,7–4,8 MB (.splat) |
| ±20° | fotorrealista | fotorrealista, sujeto recortado y sin manchas de fondo |
| ±40° | aguanta | aguanta la cara; aparecen puntos sueltos en la silueta |
| ≥60° | se rompe | se rompe: los laterales quedan vacíos, porque no hay relleno de oclusiones |
| Licencia | no comercial | Apache-2.0 / MIT, válida para el producto |

- **Evidencia:** `.triage/decide/LIVEPHOTO_portrait_yaw_0_20_40_60_90_-40.jpg` y `LIVEPHOTO_mei_yaw_0_20_40_60_90_-40.jpg`, junto a la hoja de SHARP.
- **Uso:** fotos vivas con giro de ±20° (landing, tarjetas de personaje). No sirve para el avatar.
- **Pendiente:** un segmentador fino con licencia comercial y sin código remoto quitaría los puntos sueltos de la silueta y el resto de suelo bajo los pies.

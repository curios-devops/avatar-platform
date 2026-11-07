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
| MuseTalk 1.5 (RunPod) | `worker/musetalk_worker`, apagado con `ORCH_MUSETALK_ENABLED=false` | RunPod sin saldo y 191 trabajos atascados en cola | Al reactivar RunPod: **purgar primero la cola** y repetir 1A y 2A con el mismo audio. No hay versión nueva (la 1.5 es la última; último commit 26-9-2025). La imagen ya incluye sus arreglos. |
| Híbrido cuerpo PINOC + cara Twin | `exp/pinoc-3dgs`, `pinoc/web/hybrid.html` | Habla en vivo, pero la cara se ve CG sobre un cuerpo foto | Si mejora la piel del Twin |
| TripoSplat + esqueleto Anny | `exp/splat-human` | Identidad 0,30–0,35 y boca sin interior | Si sale un modelo de cabeza mejor |
| SHARP (Apple), foto → 3DGS | `~/Documents/lab/sharp` (fuera de los repos) | **Pesos solo para investigación no comercial.** Estático, sin esqueleto, 66 MB por escena | Ver «SHARP» abajo |
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

## SHARP: resultado y propuesta
- **Prueba local en el M2 Pro (MPS):**
  - 25–63 s por imagen y 1,18 M gaussianas (66 MB).
  - Fotorrealista entre ±20° y ±40° de giro. Se rompe a partir de unos 60°: a 90° es una lámina y aparecen manchas del fondo.
  - Evidencia: `.triage/decide/SHARP_portrait_yaw_0_20_40_60_90_-40.jpg`.
- **Uso posible:** «fotos vivas» con paralaje (landing, tarjetas de personaje), no avatares. No se mueve y la licencia de los pesos impide usarlo en el producto.
- **Replicar el principio sin copiarlo:**
  - Ruta: profundidad monocular con una licencia comercial (por ejemplo Depth Anything V2 Small, Apache-2.0), retroproyectar cada píxel a una gaussiana orientada a la cámara, recortar el sujeto y comprimir a SPZ.
  - Daría el mismo paralaje de ±20° con unos pocos MB, sin rellenar oclusiones. Pendiente de aprobación.

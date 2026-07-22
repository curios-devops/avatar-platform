# ETAPA B — Modo 3D interactivo

Avatar Gaussian interactivo (cabeza LAM + cuerpo LHM + runtime Spark). Comparte
el backend conversacional de la Etapa A; solo cambia el renderer que consume el
contrato.

## Estado real (2026-07-22)

Ver `reports/qa0_audit.md` para el detalle. Resumen:

| Fase | Estado | Artefacto |
|---|---|---|
| **B1 cabeza (LAM)** | ✅ **cerrado** | `avatar-lam-v4`, `.triage/lam_head_v7.ply`, baseline ArcFace=0.227 validado con harness |
| B1 cuerpo (LHM) | 🟡 POC apagado — validar 360° justo antes de B2 | `avatar-lhm-v1` |
| B1.5 Paso 1 (vistas sintéticas) | ✅ **cerrado** — 10/10 vistas válidas, score visión 8/10 | `worker/b15/make_views.py` → `qa/out/b15/views/` |
| B1.5 Paso 2 (reconstrucción reforzada) | 🟡 código listo, **pendiente correr en GPU** | `worker/b15/reconstruct.py` (FaceLift) |
| B2 fusión (`fuse.py`) | 🟡 código listo + 6/6 tests unitarios pasan, **pendiente correr en GPU** | `worker/b2/fuse.py` |
| B3 runtime Spark | ❌ no migrado | hoy: `frontend/src/engine/webgpu_renderer.ts` (propio) |
| B4 UX 3D | 🟡 botón deshabilitado en Feed | — |
| **Harness QA visual** | ✅ **listo** | `qa/` |

## B1.5 — vistas sintéticas + reconstrucción reforzada

### Paso 1 — `worker/b15/make_views.py` (✅ cerrado)
Reutiliza `MultiViewGenerator` (Nano Banana 2 Lite vía Vertex express) para
generar 10 vistas (yaw ±15/30/45/60°, pitch ±10°) de `.triage/test_portrait.jpg`,
con QC de identidad ArcFace (umbral 0.35, mínimo 6 válidas). Resultado real:
**10/10 válidas**, ArcFace 0.59–0.78 — muy por encima del splat LAM (0.22).
Evidencia: `reports/approved/B1.5-paso1_views_qc.png`.

```bash
backend/.venv/bin/python worker/b15/make_views.py \
    --photo .triage/test_portrait.jpg --out qa/out/b15/views
```

### Paso 2 — `worker/b15/reconstruct.py` (🟡 código listo, sin correr)

**Investigación de reconstructores** (antes de escribir código): se evaluaron
4 candidatos con verificación directa en GitHub (no solo el paper) —

| Candidato | Veredicto | Por qué |
|---|---|---|
| **Avat3r** | ❌ descartado | Repo placeholder: README vacío, 0 releases, "Initial commit"; issues #1/#2 piden el código sin respuesta 8 meses (nov 2025 → jul 2026) |
| FlexAvatar (mismo autor, CVPR'26) | opción de respaldo | pesos reales (TUM), pero cadena pesada: Pixel3DMM + pytorch3d-desde-fuente + nvdiffrast ("prone to errors"); salida = avatar code, no confirmé `.ply` portable |
| CAP4D (CVPR'25 Oral) | opción de respaldo | pesos reales, salida `.ply` **FLAME-rigged** vía GaussianAvatars (mejor encaje futuro con B2) — pero exige **cuenta FLAME** + MMDM "toma horas, >64GB RAM" |
| **FaceLift** (ICCV'25, Adobe Research) | ✅ **elegido** | Apache-2.0, sin gate, setup liviano (torch 2.4/cu124 + diff-gaussian-rasterization), pesos auto-descarga HuggingFace, salida `gaussians.ply` **3DGS estándar** — confirmado en código (`inference.py:264 save_ply`), directamente compatible con `qa/splat_io.py` |

FaceLift **genera** la cabeza desde cero (foto → sus propias 6 vistas internas
→ GS-LRM → `.ply`) — no refina el splat LAM con las vistas del Paso 1. Se trata
como **generador alterno** a comparar contra el baseline LAM con el mismo
harness, no como refinamiento incremental. Si su identidad lateral no supera a
LAM, CAP4D queda como plan B (mejor encaje con B2 por venir FLAME-rigged, a
costa de mucha más fricción de setup).

**Ejecución (sesión GPU dedicada — NO corre en Mac):**
```bash
git clone https://github.com/weijielyu/FaceLift
cd FaceLift && bash setup_env.sh   # torch 2.4.0+cu124 + diff-gaussian-rasterization
# checkpoints se auto-descargan de HuggingFace (wlyu/OpenFaceLift) al primer uso

python worker/b15/reconstruct.py \
    --facelift-dir /path/to/FaceLift \
    --photo .triage/test_portrait.jpg \
    --out-ply .triage/facelift_head_v1.ply
# invoca automáticamente qa/run_all.sh al terminar → hoja comparativa vs baseline LAM
```
Criterio de éxito (GATE-B1.5): huecos <1%, ArcFace frontal ≥0.207 (baseline−0.02),
y a simple vista el estiramiento lateral en ±45° debe reducirse vs
`reports/approved/GATE-B1.5_baseline_lam.png`.

## B2 — fusión cabeza-cuerpo (`worker/b2/fuse.py`, 🟡 código listo)

"El trabajo duro" del doc. Algoritmo (a→e del doc, mapeado a operaciones concretas):

1. **Segmentación del cuerpo (geométrica, no skinning weights)** — LHM no
   expone pesos de skinning por-gaussiano en su salida. En vez de eso:
   `worker/b2/smplx_body.py` construye la malla SMPL-X canónica del cuerpo
   (paquete `smplx` + `betas`) y usa la segmentación estándar de vértices
   (`worker/b2/assets/smplx_vert_segmentation.json`, partes `head`/`neck`,
   11 971 vértices etiquetados en 27 partes) para ubicar la región cabeza/cuello.
2. **Hallazgo de auditoría (corregido):** `LHM/runners/infer/human_lrm.py`
   calcula `smplx_params['betas']` para construir los gaussianos, pero el
   worker original **los descartaba** — solo exportaba el `.ply`. Sin
   parche, B2 no tendría con qué construir el cuerpo SMPL-X. Fix:
   `worker/lhm_worker/patch_export_betas.py` (aplicado en el Dockerfile al
   build) vuelca un sidecar `<nombre>_betas.npy`; `handler.py` y
   `RunPodLHMClient.reconstruct_with_betas()` lo propagan. **Además**, el
   Dockerfile no bajaba `LHM_prior_model.tar` (contiene los assets SMPL-X que
   `human_lrm.py` necesita EN INFERENCIA, no solo entrenamiento) — probable
   causa de que el POC nunca produjera un `body.ply` válido. Ya corregido.
3. **Correspondencia FLAME↔SMPL-X:** `SMPL-X__FLAME_vertex_ids.npy`, que **ya
   viene con `LHM_prior_model.tar`** (LHM la usa internamente — sin fetch de
   licencia aparte). Fallback si faltara: nearest-vertex KDTree contra la
   segmentación (self-contained, menos preciso).
4. **Registro rígido (b):** Procrustes con escala+rotación+traslación sobre 4
   landmarks (ojos, nariz, mentón — mandíbula/ojos pesan 1.5×, nariz 1.0×;
   sin "coronilla" en este set). Normaliza por distancia interpupilar ANTES
   de optimizar (paso explícito del doc). Landmarks del lado cuerpo vía
   `smplx.create(..., use_face_contour=True)` (estándar del paquete); del
   lado cabeza, heurística geométrica sobre la nube de splats (splats oscuros
   = ojos, punto más protuberante en +Z = nariz, punto más bajo de piel =
   mentón) — mismo principio que el blink-mask ya validado en
   `webgpu_renderer.ts` ("dark facial splats"), generalizado en vez de
   hardcodeado a una foto.
5. **Eliminar splats de cabeza del cuerpo + rampa de opacidad (a, c):**
   `carve_and_ramp()` — corta el cuerpo por encima de la costura (mentón −
   5mm) y aplica rampa lineal de opacidad en la banda de solape de 2cm
   (`OVERLAP_BAND_M`), en vez de un corte duro.
6. **Match de color en la costura (d):** `match_color_seam()` — mismo Reinhard
   LAB que `worker/clips_gen/prep_clips.py::match_color`, ponderado por
   distancia a la costura.
7. **Exporta:** `avatar_head.ply` + `avatar_body.ply` + `fused.ply` (preview
   para el harness) + `rig.json` (transform de registro, landmarks de AMBOS
   lados, betas — para "visualizar los dos esqueletos superpuestos" si el
   registro se atasca, tal como pide el doc). **Desviación del doc:** exporta
   `.ply` en vez de `.spz` — mismo formato que ya lee/escribe todo el harness;
   `.spz` es compresión de entrega para B3, no afecta la corrección que este
   gate evalúa.

**Verificado sin GPU** (numpy puro, datos sintéticos, `worker/b2/fuse.py`
funciones geométricas): Procrustes recupera una transformación ground-truth
conocida a precisión de máquina (escala/R/t con error <1e-3), `apply_transform`
preserva cuaterniones unitarios, `carve_and_ramp` corta y rampea
correctamente, `match_color_seam` desplaza el color hacia el cuerpo cerca de
la costura. **6/6 tests pasan.** Lo que NO se puede probar sin GPU+assets
reales: los heurísticos de detección de landmarks sobre splats reales — eso
lo juzga el gate visual (GATE-B2) cuando se corra.

**Ejecución (misma sesión GPU dedicada de B1.5 — requiere body.ply primero,
validación 360° del cuerpo LHM que quedó pendiente antes de B2):**
```bash
# 1. generar body.ply + betas (worker LHM parcheado, imagen reconstruida con
#    el fix de LHM_prior_model.tar) — esto TAMBIÉN es la validación 360°
#    del cuerpo LHM que se difirió al cierre de B1.
# 2. fusionar:
python worker/b2/fuse.py \
    --head .triage/lam_head_v7.ply --body <lhm_body.ply> \
    --betas <lhm_body_betas.npy> \
    --human-model-path /opt/LHM/pretrained_models/human_model_files \
    --out-dir qa/out/b2/fused_v1
qa/run_all.sh qa/out/b2/fused_v1/fused.ply b2_v1 .triage/test_portrait.jpg
```
Criterio de éxito (GATE-B2): ratio de costura <1.5, cero splats flotantes
visibles en la hoja, score visión ≥7/10 en primer plano del cuello.

## Harness de QA visual (`qa/`)

Disciplina: build → render → **hoja comparativa** → gate → autocorrección acotada.
"Corrió sin errores" NO es éxito; toda fase se valida con render real + hoja +
métrica + score de visión ≥ umbral (ver `feedback_visual_gates` en memoria).

### Un comando
```bash
qa/run_all.sh <head.ply> <tag> [ref.jpg]
# ej: qa/run_all.sh .triage/lam_head_v7.ply lam_v7 .triage/test_portrait.jpg
```
Produce `qa/out/sweep/<tag>/`: PNGs del sweep + `metrics.json` + `sheet.png`.

### Piezas
- `cameras.json` — barrido FIJO y versionado (yaw −45..+45, pitch ±10, 2
  distancias). NUNCA cambiar sin re-aprobar gates.
- `splat_io.py` — lector de PLY 3DGS (formato INRIA/LAM) en numpy.
- `raster.py` — **rasterizador 3DGS offline en CPU** (EWA splatting, Jacobiano de
  perspectiva, compositing front-to-back near→far). Determinista, sin GPU/browser.
- `render_sweep.py` — renderiza el sweep → PNG + cover buffer por cámara.
- `metrics.py` — ArcFace coseno vs foto (insightface CPU), % huecos (del cover
  buffer), ratio de costura (solo B2).
- `make_sheet.py` — UNA hoja PNG: referencia arriba + sweep abajo + métricas al pie.
- `review.py` — diario `reports/reviews.jsonl` (gate, ciclo, score, decisión, acción).
- `gates.json` — umbrales GATE-B1.5/B2/B3/B4 (ajustar solo vía `refine-params`,
  registrando el cambio).

### Regla de proceso (QA4)
Cualquier cambio futuro a B1–B4 (código o parámetros) exige re-correr
`qa/run_all.sh` y adjuntar la hoja nueva antes de mergear.

## Latencias / recursos medidos
- Sweep completo (12 cámaras, CPU mac): ~15 s.
- Métricas ArcFace (12 vistas, CPU): ~6 s (tras descargar buffalo_l una vez).
- Reconstrucción LAM (cabeza): 28.4 s en caliente (endpoint `avatar-lam-v4`).

## Limitaciones conocidas
- Cabeza LAM: estiramiento lateral en ±45° (objetivo de B1.5); ArcFace absoluto
  bajo por el suavizado del splat + 20 k gaussianos (el harness compara en relativo).
- Cuerpo LHM (cuando se valide): manos borrosas, espalda alucinada, ropa rígida.

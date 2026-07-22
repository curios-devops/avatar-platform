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
| B2 fusión (`fuse.py`) | ❌ pendiente | "el trabajo duro" |
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

# ETAPA B — Modo 3D interactivo

Avatar Gaussian interactivo (cabeza LAM + cuerpo LHM + runtime Spark). Comparte
el backend conversacional de la Etapa A; solo cambia el renderer que consume el
contrato.

## Estado real (2026-07-22)

Ver `reports/qa0_audit.md` para el detalle. Resumen:

| Fase | Estado | Artefacto |
|---|---|---|
| B1 cabeza (LAM) | ✅ real | `avatar-lam-v4`, `.triage/lam_head_v7.ply` (28.4s caliente) |
| B1 cuerpo (LHM) | 🟡 POC apagado | `avatar-lhm-v1` |
| B1.5 multiview + refinamiento | ❌ pendiente | (existe `multiview_generator.py`, pero para MICA) |
| B2 fusión (`fuse.py`) | ❌ pendiente | "el trabajo duro" |
| B3 runtime Spark | ❌ no migrado | hoy: `frontend/src/engine/webgpu_renderer.ts` (propio) |
| B4 UX 3D | 🟡 botón deshabilitado en Feed | — |
| **Harness QA visual** | ✅ **listo** | `qa/` |

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

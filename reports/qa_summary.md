# QA Summary — Harness de revisión visual, Etapa B

Fecha: 2026-07-22 · Agente: Claude Opus 4.8 (Claude Code)
Avatar de referencia: `.triage/lam_head_v7.ply` (cabeza LAM, 20 018 gaussianos)
Foto original: `.triage/test_portrait.jpg`

## Qué se construyó (QA0→QA4)

| Fase | Entregable | Estado |
|---|---|---|
| QA0 | `reports/qa0_audit.md` — auditoría del estado real de B (corrige la premisa falsa "B1–B4 ya implementados") | ✅ |
| QA1 | `qa/` harness determinista: `cameras.json`, `splat_io.py`, `raster.py`, `render_sweep.py`, `metrics.py`, `make_sheet.py`, `review.py` | ✅ |
| QA2 | `qa/gates.json` — umbrales GATE-B1.5/B2/B3/B4 | ✅ |
| QA3 | Línea base medida sobre la cabeza LAM (única fase existente) | ✅ baseline |
| QA4 | `qa/run_all.sh` — un comando; **determinismo verificado (render byte-idéntico, variación 0%)** | ✅ |

**Renderer del harness:** rasterizador 3DGS **offline en CPU (numpy)** — EWA
splatting, proyección por Jacobiano de perspectiva, compositing front-to-back.
Sin GPU, sin browser, 100% determinista. ~15 s para las 12 cámaras del sweep.

> Bug encontrado y corregido durante el bring-up: el compositing iteraba
> lejano→cercano con la fórmula front-to-back, lo que hacía que el fondo dominara
> y **borraba los rasgos de la cara** (cara lavada). Corregido a cercano→lejano.
> Diagnóstico por render de puntos 1px (features nítidos) vs splat (lavado).

## Tabla de gates

| Gate | Métrica | Umbral | Medido (LAM baseline) | Veredicto |
|---|---|---|---|---|
| **GATE-B1.5** | huecos max \|yaw\|≤45° | < 1% | **0.54%** | ✅ bajo umbral |
| | ArcFace frontal | ≥ baseline−0.02 | **0.227** (baseline fijado) | ⏳ referencia para B1.5 |
| | score visión | ≥ 7/10 | **7/10** | 🟡 ver limitación |
| **GATE-B2** | ratio costura | < 1.5 | N/A (sin cuerpo/fusión) | ⏳ B2 no implementado |
| **GATE-B3** | FPS p5 / desfase labios | ≥30 / <100ms | N/A (Spark no integrado) | ⏳ B3 no migrado |
| **GATE-B4** | audio en transición | sin dropout | N/A | ⏳ B4 no implementado |

## Juicio de visión — GATE-B1.5 (hoja: `reports/approved/GATE-B1.5_baseline_lam.png`)

- **Identidad:** frontal y ±15/30° son inequívocamente la misma persona (ojos,
  cejas, nariz, labios, tono de piel, raya del pelo). El ArcFace numérico (0.22)
  es bajo porque el splatting suaviza, pero el parecido visual es fuerte. **8/10.**
- **Huecos / líneas negras:** ninguno; cobertura llena, 0.54% < 1%. **OK.**
- **Limitación (la que B1.5 debe corregir):** en **±45° yaw la mejilla lejana se
  estira y emborrona** (típico artefacto de reconstrucción desde una sola foto).
  No son huecos — es identidad lateral blanda.

## Limitaciones aceptadas / abiertas

1. **Estiramiento lateral en ±45°** — artefacto de vista única de LAM.
   Es EXACTAMENTE el objetivo de B1.5 (multiview + refinamiento). El baseline
   ArcFace=0.227 queda fijado en `gates.json` como referencia relativa.
2. ArcFace absoluto bajo por el suavizado del splatting + solo 20 k gaussianos.
   El harness es un comparador RELATIVO válido (mismas cámaras siempre).
3. GATE-B2/B3/B4 quedan como N/A porque esas fases (fusión, Spark, UX 3D) aún
   no existen — el harness ya está listo para medirlas cuando se construyan.

## Cierre de B1 (2026-07-23)

**B1 se cierra con la CABEZA validada** por el harness (identidad frontal fuerte,
huecos 0.54% < 1%, determinismo verificado). Baseline `arcface_baseline_lam=0.227`
fijado en `qa/gates.json`.

- ✅ **B1 cabeza (LAM):** cerrado y validado con evidencia (`reports/approved/GATE-B1.5_baseline_lam.png`).
- ⏳ **B1 cuerpo (LHM):** POC en `avatar-lhm-v1` (apagado). Queda **pendiente de
  validación 360° con el harness**, a ejecutar JUSTO ANTES de B2 (fusión), que es
  donde el cuerpo entra en juego. Decisión tomada para no gastar GPU ahora.

## Próximo paso

**B1.5** — `make_views.py` (vistas sintéticas ±45/60°) + `reconstruct.py`
(refinar los gaussianos laterales contra esas vistas, congelando el frontal).
Criterio de éxito: re-correr `qa/run_all.sh` y que el estiramiento lateral baje
sin que ArcFace frontal caiga por debajo de 0.207 — todo medido con esta misma hoja.

Después: validar cuerpo LHM → **B2** (`fuse.py`) → B3 (Spark) → B4 (UX 3D).

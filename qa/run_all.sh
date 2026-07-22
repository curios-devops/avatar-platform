#!/usr/bin/env bash
# QA4 — un solo comando: sweep + métricas + hoja para un head.ply dado.
#   qa/run_all.sh <ply> <tag> [ref.jpg]
# Debe terminar en pocos minutos en CPU. Re-correrlo dos veces debe dar
# métricas estables (variación < 5%) — el rasterizador es determinista.
set -euo pipefail
cd "$(dirname "$0")/.."

PLY="${1:-.triage/lam_head_v7.ply}"
TAG="${2:-lam_v7}"
REF="${3:-.triage/test_portrait.jpg}"
PY="backend/.venv/bin/python"

echo "== QA run_all: ply=$PLY tag=$TAG ref=$REF =="
$PY qa/render_sweep.py --ply "$PLY" --tag "$TAG"
$PY qa/metrics.py      --tag "$TAG" --ref "$REF" 2>/dev/null
$PY qa/make_sheet.py   --tag "$TAG" --ref "$REF"
echo "== hoja: qa/out/sweep/$TAG/sheet.png · métricas: qa/out/sweep/$TAG/metrics.json =="

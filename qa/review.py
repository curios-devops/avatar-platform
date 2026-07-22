#!/usr/bin/env python3
"""QA1 — review.py: registra cada ciclo de revisión en reports/reviews.jsonl.

El agente, tras mirar la hoja del ciclo, llama a `log_review(...)` (o se usa por
CLI) con el gate, ciclo, métricas, score de visión, decisión y acción tomada.
Es el diario auditable del harness (Principio 4: autocorrección acotada, máx 6
ciclos por gate → request-input).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

REVIEWS = Path(__file__).resolve().parents[1] / "reports" / "reviews.jsonl"
VALID_ACTIONS = {"refine-params", "refine-code", "request-input", "stop", "pass"}


def log_review(gate: str, ciclo: int, metricas: dict, score_vision,
               decision: str, accion: str, notas: str = "") -> dict:
    if accion not in VALID_ACTIONS:
        raise ValueError(f"acción inválida {accion!r}; usar {VALID_ACTIONS}")
    REVIEWS.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "gate": gate, "ciclo": ciclo, "metricas": metricas,
        "score_vision": score_vision, "decision": decision,
        "accion": accion, "notas": notas,
    }
    with REVIEWS.open("a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    n = sum(1 for _ in REVIEWS.open())
    print(f"[review] {gate} ciclo {ciclo}: {accion} (score={score_vision}) → {REVIEWS} [{n} entradas]")
    return entry


def cycles_for(gate: str) -> int:
    """Cuántos ciclos se han registrado para un gate (para el límite de 6)."""
    if not REVIEWS.exists():
        return 0
    return sum(1 for line in REVIEWS.open() if json.loads(line).get("gate") == gate)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gate", required=True)
    ap.add_argument("--ciclo", type=int, required=True)
    ap.add_argument("--score", required=True)
    ap.add_argument("--decision", required=True)
    ap.add_argument("--accion", required=True, choices=sorted(VALID_ACTIONS))
    ap.add_argument("--notas", default="")
    ap.add_argument("--metrics-json", type=Path, default=None,
                    help="opcional: metrics.json a incrustar")
    args = ap.parse_args()
    m = json.loads(args.metrics_json.read_text())["summary"] if args.metrics_json else {}
    try:
        score = float(args.score)
    except ValueError:
        score = args.score
    log_review(args.gate, args.ciclo, m, score, args.decision, args.accion, args.notas)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

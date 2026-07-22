#!/usr/bin/env python3
"""B1.5 Paso 2 — reconstruct.py: cabeza gaussiana alterna vía FaceLift.

FaceLift (ICCV 2025, weijielyu/FaceLift, Apache-2.0) es un reconstructor
feed-forward: 1 foto → 6 vistas sintéticas INTERNAS (su propia difusión
multi-vista) → GS-LRM → `gaussians.ply` (3DGS estándar, mismo formato que
`qa/splat_io.py` ya lee). Elegido sobre las alternativas evaluadas:

  - Avat3r: descartado — repo placeholder, sin código/pesos (issues #1 #2
    abiertos 8 meses sin respuesta).
  - FlexAvatar / CAP4D: FLAME-nativos y rigged (mejor encaje futuro con B2),
    pero cadena de dependencias pesada (Pixel3DMM + pytorch3d-desde-fuente) y
    CAP4D exige cuenta FLAME + MMDM de horas / >64GB RAM. Quedan como opción
    si FaceLift no da suficiente calidad lateral.
  - FaceLift: sin gate, setup liviano (torch 2.4/cu124 + diff-gaussian-
    rasterization), salida .ply directa — MENOR fricción de integración.

Nota: FaceLift GENERA la cabeza desde cero (no refina el splat LAM con las
vistas validadas de make_views.py). Este script lo trata como GENERADOR
ALTERNO a comparar contra el baseline LAM con el mismo harness — no como un
refinamiento incremental. Las vistas de B1.5 Paso 1 sirven aquí solo como
referencia de identidad adicional (no como entrada al modelo).

Requiere GPU CUDA (torch 2.4.0+cu124) — NO corre en este Mac. Ejecutar en una
sesión dedicada (pod RunPod u otro host CUDA):

    git clone https://github.com/weijielyu/FaceLift
    cd FaceLift && bash setup_env.sh    # instala torch cu124 + diff-gaussian-rasterization
    # los checkpoints se auto-descargan de HuggingFace (wlyu/OpenFaceLift) al primer uso

    python worker/b15/reconstruct.py \
        --facelift-dir /path/to/FaceLift \
        --photo .triage/test_portrait.jpg \
        --out-ply .triage/facelift_head_v1.ply

Tras generar el .ply, este script invoca automáticamente el harness
(qa/run_all.sh) para producir la hoja comparativa contra el baseline LAM.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def run_facelift(facelift_dir: Path, photo: Path, work_dir: Path, python_bin: str) -> Path:
    """Corre inference.py de FaceLift sobre UNA foto. Devuelve el path del
    gaussians.ply que produce (ver inference.py: save_ply(.../gaussians.ply))."""
    input_dir = work_dir / "input"
    output_dir = work_dir / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(photo, input_dir / photo.name)

    cmd = [python_bin, str(facelift_dir / "inference.py"),
           "--input_dir", str(input_dir), "--output_dir", str(output_dir)]
    print(f"[reconstruct] corriendo FaceLift: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd=str(facelift_dir))

    image_name = photo.stem
    ply = output_dir / image_name / "gaussians.ply"
    if not ply.exists():
        # inference.py normaliza nombres; buscar cualquier gaussians.ply producido
        found = list(output_dir.glob("*/gaussians.ply"))
        if not found:
            raise FileNotFoundError(f"FaceLift no produjo gaussians.ply en {output_dir}")
        ply = found[0]
    print(f"[reconstruct] → {ply}")
    return ply


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--facelift-dir", required=True, type=Path,
                    help="path al repo weijielyu/FaceLift clonado y con setup_env.sh corrido")
    ap.add_argument("--photo", type=Path, default=ROOT / ".triage/test_portrait.jpg")
    ap.add_argument("--out-ply", type=Path, default=ROOT / ".triage/facelift_head_v1.ply")
    ap.add_argument("--python-bin", default=sys.executable,
                    help="intérprete con el entorno de FaceLift activo (torch cu124)")
    ap.add_argument("--tag", default="facelift_v1", help="tag para qa/run_all.sh")
    ap.add_argument("--skip-qa", action="store_true", help="no correr el harness al final")
    args = ap.parse_args()

    if not (args.facelift_dir / "inference.py").exists():
        raise SystemExit(f"no se encontró inference.py en {args.facelift_dir} "
                         "(¿clonaste weijielyu/FaceLift y corriste setup_env.sh?)")

    work_dir = ROOT / "qa" / "out" / "b15" / "facelift_work"
    ply = run_facelift(args.facelift_dir, args.photo, work_dir, args.python_bin)

    args.out_ply.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(ply, args.out_ply)
    print(f"[reconstruct] copiado → {args.out_ply}")

    if not args.skip_qa:
        print(f"[reconstruct] corriendo harness QA (tag={args.tag}) para comparar vs baseline LAM…")
        subprocess.run(["bash", str(ROOT / "qa/run_all.sh"), str(args.out_ply),
                        args.tag, str(args.photo)], check=True, cwd=str(ROOT))
        print(f"[reconstruct] hoja → qa/out/sweep/{args.tag}/sheet.png "
              f"— comparar contra qa/out/sweep/lam_v7/sheet.png (o reports/approved/GATE-B1.5_baseline_lam.png)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

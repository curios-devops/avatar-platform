#!/usr/bin/env python3
"""A1.1 — Biblioteca de clips base del avatar (offline, una vez por avatar).

Desde `avatar.jpg` genera los clips que el modo Feed encadena (contrato:
gesto ∈ idle_a|idle_b|listen|gesture_enum|gesture_open):

  idle_a.mp4, idle_b.mp4   loops 8-10 s, micro-movimiento, SIN hablar
  listen.mp4               atención, asentir suave
  gesture_enum.mp4         enumerar con las manos visibles
  gesture_open.mp4         gesto abierto, manos visibles

Backends (elegir por VRAM/infra disponible):
  veo        Veo 2 (Vertex AI, curios-vertex) — API, corre desde el portátil,
             consume créditos GCP (~8 s/clip). Sin pod. RECOMENDADO para
             validar A1 rápido.
  wan        Wan2.2-S2V-14B  (≥ 40 GB VRAM) — repo Wan2.2, task s2v-14B
  echomimic  EchoMimicV3     (≥ 16 GB VRAM) — repo EchoMimicV3
(self-hosted = economía por avatar en producción; veo = velocidad hoy)

Ambos son audio-driven: para clips SIN habla se les da un WAV de silencio
de la duración objetivo y el prompt lleva la instrucción de actitud/gesto.
Encuadre fijo del plan: medio cuerpo, fondo neutro, cámara estática.

Uso (en el pod GPU, con el repo del backend clonado al lado):
  python make_clips.py --photo avatar.jpg --out clips/ --backend wan \
      --repo /workspace/Wan2.2 --ckpt /workspace/Wan2.2-S2V-14B
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import wave
from pathlib import Path

# (nombre, duración_s, prompt de actitud — encuadre/cámara van en BASE_PROMPT)
CLIP_SPECS: list[tuple[str, int, str]] = [
    ("idle_a", 9, "standing calmly, subtle natural body sway, gentle breathing, "
                  "occasional slow blink, mouth closed, relaxed friendly face, not talking"),
    ("idle_b", 9, "standing relaxed, tiny weight shift between feet, soft smile, "
                  "slow blink, mouth closed, not talking"),
    ("listen", 8, "attentive listening pose, small slow nods, warm interested "
                  "expression, eyebrows slightly raised, mouth closed, not talking"),
    ("gesture_enum", 6, "explaining and enumerating points with visible hands, "
                        "counting gesture with fingers, engaged expression, mouth closed"),
    ("gesture_open", 6, "open welcoming hand gesture with both palms visible, "
                        "friendly confident expression, mouth closed"),
]

BASE_PROMPT = (
    "medium shot, upper body from waist up, person facing camera, static camera, "
    "locked framing, plain neutral light-gray background, soft even studio "
    "lighting, photorealistic, 4k"
)
NEGATIVE = "talking, moving lips, speech, camera motion, zoom, pan, cuts, text"


def silent_wav(path: Path, seconds: float, rate: int = 16000) -> Path:
    """WAV de silencio — entrada de audio para clips sin habla."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(struct.pack("<h", 0) * int(rate * seconds))
    return path


def run_wan(repo: Path, ckpt: Path, photo: Path, wav: Path, prompt: str, out: Path) -> None:
    """Wan2.2 oficial: generate.py --task s2v-14B (imagen ref + audio)."""
    cmd = [sys.executable, "generate.py", "--task", "s2v-14B",
           "--ckpt_dir", str(ckpt), "--offload_model", "True",
           "--convert_model_dtype", "--size", "704*1280",
           "--image", str(photo), "--audio", str(wav),
           "--prompt", f"{prompt}, {BASE_PROMPT}",
           "--save_file", str(out)]
    subprocess.run(cmd, cwd=repo, check=True)


def run_echomimic(repo: Path, photo: Path, wav: Path, prompt: str, out: Path) -> None:
    """EchoMimicV3 (BadToBest): infer.py con imagen ref + audio.

    El repo usa configs YAML; aquí invocamos su script de inferencia estándar.
    Ajustar --config si el repo cambia de layout (verificar en el pod).
    """
    cmd = [sys.executable, "infer.py",
           "--ref_image", str(photo), "--audio", str(wav),
           "--prompt", f"{prompt}, {BASE_PROMPT}", "--negative_prompt", NEGATIVE,
           "--output", str(out)]
    subprocess.run(cmd, cwd=repo, check=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--backend", choices=["veo", "wan", "echomimic"], required=True)
    ap.add_argument("--repo", type=Path, help="clon del repo del backend (wan/echomimic)")
    ap.add_argument("--ckpt", type=Path, help="dir de pesos (wan)")
    ap.add_argument("--only", nargs="*", help="generar solo estos clips")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    for name, seconds, attitude in CLIP_SPECS:
        if args.only and name not in args.only:
            continue
        out = args.out / f"{name}.mp4"
        if out.exists():
            print(f"[skip] {out} ya existe"); continue
        print(f"[gen ] {name} ({seconds}s, {args.backend})…")
        if args.backend == "veo":
            from veo_backend import generate_clip
            generate_clip(args.photo, f"{attitude}, {BASE_PROMPT}", out, seconds)
        elif args.backend == "wan":
            assert args.repo and args.ckpt, "--repo y --ckpt requeridos para wan"
            wav = silent_wav(args.out / f"_{name}_silence.wav", seconds)
            run_wan(args.repo, args.ckpt, args.photo, wav, attitude, out)
        else:
            assert args.repo, "--repo requerido para echomimic"
            wav = silent_wav(args.out / f"_{name}_silence.wav", seconds)
            run_echomimic(args.repo, args.photo, wav, attitude, out)
        print(f"[ok  ] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

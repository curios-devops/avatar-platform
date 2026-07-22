#!/usr/bin/env python3
"""A1.2 — Post-proceso de la biblioteca de clips + clip_graph.json.

1. Normaliza color entre clips (match de histograma contra el clip de
   referencia idle_a, en LAB, solo canales de color — no rompe la luz).
2. Detecta frames de corte compatibles entre cada par de clips: pose
   similar por landmarks de MediaPipe (cara + hombros), y guarda
   `clip_graph.json`: nodos=clips, aristas=(frame_salida, frame_entrada,
   coste) — la máquina de estados que el scheduler de A2 recorre.

Corre en CPU (mac o pod):  python prep_clips.py --clips clips/
Criterio de aceptación A1: reproducir idle_a→gesture_enum→idle_b por el
clip_graph sin salto visible de pose/color (ver preview_transition()).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

# Landmarks de pose que definen "misma postura" para un corte limpio:
# cara (nariz, ojos, orejas) + hombros + muñecas (gestos de manos)
_POSE_IDS = [0, 2, 5, 7, 8, 11, 12, 15, 16]
_STRIDE = 3          # analizar 1 de cada 3 frames (25fps → ~8/s)
_TOP_EDGES = 3       # aristas por par de clips


def read_frames(path: Path, stride: int = 1) -> tuple[list[np.ndarray], float]:
    cap = cv2.VideoCapture(str(path))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frames = []
    i = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % stride == 0:
            frames.append(frame)
        i += 1
    cap.release()
    return frames, fps


# ── 1. normalización de color ────────────────────────────────────────────────

def match_color(src: np.ndarray, ref_stats: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    """Reinhard color transfer en LAB hacia las estadísticas del clip ref."""
    lab = cv2.cvtColor(src, cv2.COLOR_BGR2LAB).astype(np.float32)
    mean, std = lab.reshape(-1, 3).mean(0), lab.reshape(-1, 3).std(0) + 1e-6
    rmean, rstd = ref_stats
    out = (lab - mean) * (rstd / std) + rmean
    return cv2.cvtColor(np.clip(out, 0, 255).astype(np.uint8), cv2.COLOR_LAB2BGR)


def normalize_colors(clips: dict[str, Path], out_dir: Path, ref_name: str = "idle_a") -> dict[str, Path]:
    ref_frames, _ = read_frames(clips[ref_name], stride=10)
    ref_lab = cv2.cvtColor(ref_frames[len(ref_frames) // 2], cv2.COLOR_BGR2LAB).astype(np.float32)
    ref_stats = (ref_lab.reshape(-1, 3).mean(0), ref_lab.reshape(-1, 3).std(0) + 1e-6)

    normalized = {}
    for name, path in clips.items():
        out = out_dir / f"{name}.mp4"
        if name == ref_name:
            if path.resolve() != out.resolve():
                out.write_bytes(path.read_bytes())
            normalized[name] = out
            continue
        frames, fps = read_frames(path)
        h, w = frames[0].shape[:2]
        # cv2 mp4v = MPEG-4 Part 2, que los navegadores RECHAZAN. Escribir a un
        # tmp y transcodificar a H.264 web-safe con ffmpeg.
        tmp = out.with_suffix(".mp4v.mp4")
        vw = cv2.VideoWriter(str(tmp), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for f in frames:
            vw.write(match_color(f, ref_stats))
        vw.release()
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                        "-movflags", "+faststart", str(out)], check=True)
        tmp.unlink()
        normalized[name] = out
        print(f"[color] {name} normalizado (H.264) → {out}")
    return normalized


# ── 2. clip_graph por pose ───────────────────────────────────────────────────

_POSE_MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                   "pose_landmarker_lite/float16/1/pose_landmarker_lite.task")


def _pose_model() -> Path:
    """Descarga (una vez) el modelo de la Tasks API — mediapipe ≥0.10.14
    eliminó la API legacy `solutions`."""
    dest = Path.home() / ".cache" / "mediapipe" / "pose_landmarker_lite.task"
    if not dest.exists():
        import urllib.request
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[pose ] descargando modelo → {dest}")
        urllib.request.urlretrieve(_POSE_MODEL_URL, dest)
    return dest


def pose_series(path: Path):
    """Vector de pose por frame analizado (landmarks normalizados)."""
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision

    frames, fps = read_frames(path, stride=_STRIDE)
    opts = vision.PoseLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(_pose_model())),
        running_mode=vision.RunningMode.VIDEO,
    )
    vecs = []
    with vision.PoseLandmarker.create_from_options(opts) as lmk:
        for i, f in enumerate(frames):
            img = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            ts_ms = int(i * _STRIDE * 1000 / fps)
            res = lmk.detect_for_video(img, ts_ms)
            if not res.pose_landmarks:
                vecs.append(None)
                continue
            lm = res.pose_landmarks[0]
            vecs.append(np.array([[lm[j].x, lm[j].y] for j in _POSE_IDS]).flatten())
    return vecs, fps


def build_graph(clips: dict[str, Path]) -> dict:
    poses = {}
    for name, path in clips.items():
        poses[name], fps = pose_series(path)
        print(f"[pose ] {name}: {len(poses[name])} frames analizados")

    edges = []
    names = list(clips)
    for a in names:
        for b in names:
            if a == b:
                continue
            costs = []
            for ia, va in enumerate(poses[a]):
                if va is None:
                    continue
                for ib, vb in enumerate(poses[b]):
                    if vb is None:
                        continue
                    costs.append((float(np.linalg.norm(va - vb)), ia, ib))
            costs.sort()
            for cost, ia, ib in costs[:_TOP_EDGES]:
                edges.append({"from": a, "frame_out": ia * _STRIDE,
                              "to": b, "frame_in": ib * _STRIDE,
                              "cost": round(cost, 4)})
    return {"nodes": names, "stride": _STRIDE, "edges": edges}


def preview_transition(graph: dict, clips: dict[str, Path], seq: list[str], out: Path) -> None:
    """Renderiza seq encadenada por las mejores aristas — inspección visual A1."""
    all_frames: list[np.ndarray] = []
    fps = 25.0
    for i, name in enumerate(seq):
        frames, fps = read_frames(clips[name])
        start = 0
        if i > 0:
            prev = seq[i - 1]
            edge = min((e for e in graph["edges"] if e["from"] == prev and e["to"] == name),
                       key=lambda e: e["cost"], default=None)
            if edge:
                all_frames = all_frames[: len(all_frames) - (len(read_frames(clips[prev])[0]) - edge["frame_out"])]
                start = edge["frame_in"]
        all_frames += frames[start:]
    h, w = all_frames[0].shape[:2]
    vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in all_frames:
        vw.write(f)
    vw.release()
    print(f"[prev ] {' → '.join(seq)} → {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, type=Path, help="dir con *.mp4 de make_clips")
    ap.add_argument("--out", type=Path, default=None, help="dir de salida (def: clips/prepped)")
    args = ap.parse_args()

    out_dir = args.out or (args.clips / "prepped")
    out_dir.mkdir(parents=True, exist_ok=True)
    clips = {p.stem: p for p in sorted(args.clips.glob("*.mp4")) if not p.stem.startswith("_")}
    if "idle_a" not in clips:
        print("falta idle_a.mp4 (clip de referencia)"); return 1

    normalized = normalize_colors(clips, out_dir)
    graph = build_graph(normalized)
    (out_dir / "clip_graph.json").write_text(json.dumps(graph, indent=2))
    print(f"[graph] {len(graph['edges'])} aristas → {out_dir/'clip_graph.json'}")

    wanted = [c for c in ("idle_a", "gesture_enum", "idle_b") if c in normalized]
    if len(wanted) == 3:
        preview_transition(graph, normalized, wanted, out_dir / "_preview_chain.mp4")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Round 4 arena, measured on the RENDER (not on the weights): how much the mouth visibly opens, and whether it follows
Jasom's voice. Per video: colour mouth crop at 30 fps; aperture = share of crop pixels that are teeth (bright, unsaturated) or the
dark mouth interior, which closed lips and skin never are, so head sway inside the crop does not count.
Reports Pearson r against the voice envelope at the best lag within +-250 ms, mean aperture speaking and silent.
    python3 lab/a2f/arena4_render_metric.py threejs a2f a2fcal
"""
import json, pathlib, subprocess, sys, wave
import numpy as np

LAB = pathlib.Path(__file__).resolve().parents[1]
I, R = LAB / "inputs/round4/jasom", LAB / "benchmark/results/round4"
X, Y, W, H, FPS = 318, 345, 96, 56, 30

w = wave.open(str(I / "jasom_only_16k.wav")); x = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768.0
def envelope(n):
    e = np.array([np.sqrt(np.mean(x[int(i * 16000 / FPS):int((i + 1) * 16000 / FPS)] ** 2) + 1e-12) for i in range(n)])
    return np.nan_to_num(e)

res = {}
for mode in sys.argv[1:] or ["threejs", "a2f", "a2fcal"]:
    v = R / f"arena4_{mode}.mp4"
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(v), "-vf", f"fps={FPS},crop={W}:{H}:{X}:{Y},format=rgb24",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    f = np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(np.float32)
    n = min(len(f), int(len(x) / 16000 * FPS)); f = f[:n]; env = envelope(n)
    speaking = env > 0.02
    mx, mn = f.max(-1), f.min(-1); sat = (mx - mn) / np.maximum(mx, 1)
    ap = (((mx > 165) & (sat < 0.22)) | (mx < 45)).mean(axis=(1, 2))
    best = max(((np.corrcoef(np.roll(ap, -L), env)[0, 1], L) for L in range(-7, 8)), key=lambda p: p[0])
    res[mode] = {"r": round(float(best[0]), 3), "lag_ms": round(best[1] * 1000 / FPS),
                 "aperture_speaking": round(float(ap[speaking].mean()), 4), "aperture_silent": round(float(ap[~speaking].mean()), 4),
                 "aperture_p95": round(float(np.percentile(ap, 95)), 4)}
    np.save(R / f"render_aperture_{mode}.npy", ap)
json.dump(res, open(R / "arena4_render_metrics.json", "w"), indent=1)
print(json.dumps(res, indent=1))

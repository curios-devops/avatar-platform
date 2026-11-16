"""Round 4 arena metrics: how well each face driver's jaw follows Jasom's voice.

  threejs  jawOpen from the viseme timeline (visemes.ts weights, 70 ms crossfade, engine.ts attack 35 / release 60 ms)
  a2f      jawOpen from Audio2Face-3D v3.0 (GPU blendshape solve, 60 fps)
Against the RMS envelope of Jasom's track: Pearson r at the best lag in +-250 ms, and the mean jaw opening while he is
silent (the other person talking, pauses), which should be ~0.
    python3 lab/a2f/arena4_metrics.py
"""
import json, pathlib, wave
import numpy as np

LAB = pathlib.Path(__file__).resolve().parents[1]
I, R = LAB / "inputs/round4/jasom", LAB / "benchmark/results/round4"
FPS = 60
JAW = {"TH": .16, "DD": .2, "kk": .24, "CH": .15, "SS": .07, "nn": .14, "RR": .15, "aa": .55, "E": .32, "ih": .22,
       "oh": .42, "ou": .2, "FF": .08}  # jawOpen per viseme, from frontend/src/human/visemes.ts

w = wave.open(str(I / "jasom_only_16k.wav")); x = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768.0
n = int(len(x) / 16000 * FPS); t = np.arange(n) / FPS
env = np.array([np.sqrt(np.mean(x[int(i * 16000 / FPS):int((i + 1) * 16000 / FPS)] ** 2) + 1e-12) for i in range(n)])
env = np.convolve(env, np.ones(3) / 3, "same")
speaking = env > 0.02

cues = json.load(open(I / "visemes_threejs.json"))["cues"]
def viseme_jaw(now):
    i = len(cues) - 1
    while i > 0 and cues[i]["t"] > now: i -= 1
    a = cues[i]
    if a["t"] > now: return 0.0
    b = cues[i + 1] if i + 1 < len(cues) else None
    k = 1 - (b["t"] - now) / .07 if b and b["t"] - now < .07 else 0
    return JAW.get(a["id"], 0) * (1 - k) + (JAW.get(b["id"], 0) * k if b else 0)
tj, cur = np.zeros(n), 0.0
for i, ti in enumerate(t):
    to = viseme_jaw(ti); tau = .035 if to > cur else .06
    cur += (to - cur) * (1 - np.exp(-(1 / FPS) / tau)); tj[i] = cur

names = json.load(open(I / "a2f_pose_names.json"))
a = np.loadtxt(I / "a2f_weights.csv", delimiter=",")
aj = np.interp(t, a[:, 0], a[:, 1 + names.index("jawOpen")])

def score(j):
    best = max(((np.corrcoef(np.roll(j, -L), env)[0, 1], L) for L in range(-15, 16)), key=lambda p: p[0])
    return {"r": round(float(best[0]), 3), "lag_ms": round(best[1] * 1000 / FPS), "r_lag0": round(float(np.corrcoef(j, env)[0, 1]), 3),
            "jaw_mean_speaking": round(float(j[speaking].mean()), 3), "jaw_mean_silent": round(float(j[~speaking].mean()), 3),
            "jaw_p95": round(float(np.percentile(j, 95)), 3)}

res = {"threejs": score(tj), "a2f": score(aj), "frames": n, "fps": FPS, "speaking_s": round(speaking.sum() / FPS, 2)}
active = lambda col: int((a[:, 1 + names.index(col)] > 0.05).sum())
res["a2f_active_shapes"] = sorted(((nm, active(nm)) for nm in names), key=lambda p: -p[1])[:12]
json.dump(res, open(R / "arena4_metrics.json", "w"), indent=1)
print(json.dumps(res, indent=1))

try:
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(12, 3.2))
    ax.fill_between(t, 0, env / env.max(), color="#bbb", label="voz de Jasom (energía)")
    ax.plot(t, tj / max(tj.max(), 1e-6), lw=1.2, label=f"three.js visemas  r={res['threejs']['r']}")
    ax.plot(t, aj / max(aj.max(), 1e-6), lw=1.2, label=f"Audio2Face-3D  r={res['a2f']['r']}")
    ax.set_xlabel("s"); ax.set_ylabel("apertura (normalizada)"); ax.legend(loc="upper left", fontsize=8); fig.tight_layout()
    fig.savefig(R / "arena4_jaw_vs_voice.png", dpi=130)
except ImportError:
    pass

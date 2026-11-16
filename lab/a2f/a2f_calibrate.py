"""Audio2Face-3D -> our three.js face (Anny rig): per-shape calibration profile.

A2F v3.0 solves ARKit weights against NVIDIA's own reference face (Mark). On our rig two things make the mouth read
clenched: shapes that never return to zero at rest (mouthRollLower ~0.23, press/stretch ~0.09), and mouthClose, which
rises with jawOpen (on Mark it compensates the jaw; on our rig it seals the lips). The profile per shape is
    w' = clamp(gain * max(0, w - rest), 0, 1)
rest = median while Jasom is silent (the shape's bias), gain = per-shape (below). jawOpen's gain is solved so its p95
matches our viseme jaw (0.42), so both drivers open the mouth by the same amount.
    python3 lab/a2f/a2f_calibrate.py   ->  inputs/round4/jasom/a2f_calib.json
"""
import json, pathlib, wave
import numpy as np

LAB = pathlib.Path(__file__).resolve().parents[1]
I = LAB / "inputs/round4/jasom"
TARGET_JAW_P95 = 0.42  # p95 of the three.js viseme jaw in arena4_metrics.json

GAIN = {  # everything not listed keeps gain 1
    "mouthClose": 0.25, "mouthRollLower": 0.3, "mouthRollUpper": 0.5, "mouthPressLeft": 0.5, "mouthPressRight": 0.5,
    "mouthShrugLower": 0.6, "mouthLowerDownLeft": 1.3, "mouthLowerDownRight": 1.3,
    "browInnerUp": 0.7, "browOuterUpLeft": 0.7, "browOuterUpRight": 0.7,  # expressive, but not surprised every word
}

names = json.load(open(I / "a2f_pose_names.json"))
a = np.loadtxt(I / "a2f_weights.csv", delimiter=",")
w = wave.open(str(I / "jasom_only_16k.wav")); x = np.frombuffer(w.readframes(w.getnframes()), np.int16) / 32768.0
env = np.array([np.sqrt(np.mean(x[int(t * 16000):int(t * 16000) + 267] ** 2) + 1e-12) for t in a[:, 0]])
silent = env <= 0.02

prof = {}
for i, n in enumerate(names):
    v = a[:, 1 + i]
    rest = float(np.median(v[silent]))
    g = GAIN.get(n, 1.0)
    if n == "jawOpen":
        g = TARGET_JAW_P95 / max(np.percentile(np.maximum(0, v - rest), 95), 1e-6)
    prof[n] = {"rest": round(rest, 4), "gain": round(float(g), 3)}
json.dump({"rig": "anny", "source": "audio2face-3d-v3.0 Mark", "shapes": prof}, open(I / "a2f_calib.json", "w"), indent=1)
print({n: p for n, p in prof.items() if p["rest"] > 0.01 or p["gain"] != 1})

"""Visual quality of each benchmark video, measured the same way for every engine.

  identity   ArcFace (InsightFace buffalo_l) cosine between the source portrait and the face in the video, every 5th
             frame: mean and p10 (the worst moments). 1.0 = same embedding; > 0.5 is usually the same person.
  lipsync    mouth opening (InsightFace 106-point landmarks: mouth height over face height) against the audio's loudness, 40 ms steps:
             the best Pearson correlation within +-200 ms, and at which lag (positive = mouth late).
  sharpness  variance of the Laplacian on the face crop resized to 256 px (higher = more detail; compare, don't trust
             in absolute).
  motion     how alive the head is: std of the nose tip, in % of the face width.
  body       how alive the rest is (torso, shoulders, hands): mean absolute change between frames 0.2 s apart in the
             frame below the face, grey levels 0-255 (0 = a still picture; the face's own motion is excluded).
  faces      share of sampled frames where a face was found.

    backend/.venv/bin/python lab/benchmark/metrics.py lab/benchmark/results/*.mp4  ->  results/metrics.json
"""
import json, pathlib, subprocess, sys

import cv2
import numpy as np

HERE = pathlib.Path(__file__).parent
INPUTS = HERE.parent / "inputs"


def face_app():
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"], allowed_modules=["detection", "landmark_2d_106", "recognition"])
    app.prepare(ctx_id=-1, det_size=(320, 320))
    return app


def biggest(app, img):
    faces = app.get(img)
    return max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1])) if faces else None


def embed(app, img):
    f = biggest(app, img)
    return (f.normed_embedding, f.bbox.astype(int)) if f is not None else (None, None)


def audio_rms(video: pathlib.Path, fps: float, n: int) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32)
    hop = int(16000 / fps)
    return np.array([np.sqrt((a[i * hop:(i + 1) * hop] ** 2).mean()) if (i + 1) * hop <= len(a) else 0 for i in range(n)])


def lipsync(openness: np.ndarray, rms: np.ndarray, fps: float):
    ok = ~np.isnan(openness)
    best = (-1.0, 0)
    for lag in range(-5, 6):
        o = np.roll(openness, -lag)
        m = ok & np.roll(ok, -lag)
        m[:5] = False; m[-5:] = False
        if m.sum() < 20 or np.std(o[m]) == 0 or np.std(rms[m]) == 0:
            continue
        c = float(np.corrcoef(o[m], rms[m])[0, 1])
        if c > best[0]:
            best = (c, lag)
    return round(best[0], 3), int(round(best[1] * 1000 / fps))


def measure(app, video: pathlib.Path) -> dict:
    case = video.stem.rsplit("_", 1)[-1]  # <engine>_<case>.mp4
    ref, _ = embed(app, cv2.imread(str(INPUTS / f"{case}.png")))
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        frames.append(f)
    if not frames:
        return {"error": "no frames"}
    h, w = frames[0].shape[:2]
    sims, sharp, noses, found = [], [], [], 0
    openness = np.full(len(frames), np.nan)
    chin = None
    for i, f in enumerate(frames):
        face = biggest(app, f)
        if face is None:
            continue
        box = face.bbox.astype(int)
        chin = chin or int(box[3] + 0.1 * (box[3] - box[1]))
        face_h, face_w = max(1, box[3] - box[1]), max(1, box[2] - box[0])
        mouth = face.landmark_2d_106[52:72]
        openness[i] = (mouth[:, 1].max() - mouth[:, 1].min()) / face_h
        noses.append((face.kps[2][0] / face_w, face.kps[2][1] / face_w))
        if i % 5 == 0:
            found += 1
            sims.append(float(np.dot(ref, face.normed_embedding)))
            x0, y0, x1, y1 = np.clip(box, 0, [w, h, w, h])
            crop = cv2.cvtColor(cv2.resize(f[y0:y1, x0:x1], (256, 256)), cv2.COLOR_BGR2GRAY)
            sharp.append(cv2.Laplacian(crop, cv2.CV_64F).var())
    body = []
    for i in range(5, len(frames), 5):  # below the chin of the first face found, to the bottom of the frame
        y = int(min(h - 2, (chin or h * 0.45)))
        a = cv2.cvtColor(cv2.resize(frames[i - 5][y:], (160, 160)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        b = cv2.cvtColor(cv2.resize(frames[i][y:], (160, 160)), cv2.COLOR_BGR2GRAY).astype(np.float32)
        body.append(float(np.abs(a - b).mean()))
    rms = audio_rms(video, fps, len(frames))
    corr, lag_ms = lipsync(openness, rms, fps)
    noses = np.array(noses) if noses else np.zeros((1, 2))
    return {
        "case": case, "resolution": f"{w}x{h}", "fps": round(fps, 1), "seconds": round(len(frames) / fps, 2),
        "identity_mean": round(float(np.mean(sims)), 3) if sims else None,
        "identity_p10": round(float(np.percentile(sims, 10)), 3) if sims else None,
        "lipsync_corr": corr, "lipsync_lag_ms": lag_ms,
        "sharpness": round(float(np.median(sharp)), 1) if sharp else None,
        "motion_pct": round(float(np.std(noses, axis=0).mean() * 100), 2),
        "body_motion": round(float(np.mean(body)), 2) if body else None,
        "faces": round(found / max(1, len(range(0, len(frames), 5))), 2),
    }


def main():
    app = face_app()
    out_file = HERE / "results" / "metrics.json"
    out = json.loads(out_file.read_text()) if out_file.exists() else {}
    for v in map(pathlib.Path, sys.argv[1:]):
        out[v.stem] = measure(app, v)
        print(v.stem, json.dumps(out[v.stem]), flush=True)
    out_file.write_text(json.dumps(out, indent=2))


main()

"""Composite dumped FlashHead faces (fh_dump.py) onto the body clips, offline, with the round 2 (v2) and round 3 (v3)
anchoring, so the ghost can be measured and seen without a GPU.
  python compose_offline.py <fh_raw> <clips_dir> <out_dir> "greet@0,emphasis@5.6,explain@13.8" [audio.wav]
Per version: <out>/compose_<v>.mp4, anchor residual (mean / p95 / max px on the 720x1280 canvas) and, for the frames
where v2 is worst, a crop sheet v2 | v3. 'talking' comes from fh_raw.json; the schedule says which clip each answer uses.
"""
import json, pathlib, subprocess, sys
import cv2, numpy as np
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from body_layer import BodyClips, FPS, CANVAS_W, CANVAS_H, landmarks, face_mesh

raw, clips_dir, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)
sched = sorted((float(t), s) for s, t in (x.split("@") for x in sys.argv[4].split(",")))
audio = sys.argv[5] if len(sys.argv) > 5 else None
# optional 6th arg: the answers' texts "t|text;;t|text" (v3 then plans a clip per sentence and thinks before each answer)
turns = [(float(x.split("|", 1)[0]), x.split("|", 1)[1]) for x in sys.argv[6].split(";;")] if len(sys.argv) > 6 else []
meta = json.load(open(str(raw) + ".json")); talking = meta["talking"]
cap, faces = cv2.VideoCapture(str(raw) + ".mp4"), []
while True:
    ok, f = cap.read()
    if not ok:
        break
    faces.append(cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
clips = {p.stem: str(p) for p in clips_dir.glob("*.mp4")}
# smooth the per-frame audio flag like the live clock does (a breath inside a sentence is not silence)
res, frames_by_v = {}, {}
for v in ("v2", "v3"):
    body = BodyClips(clips, version=v)
    w = cv2.VideoWriter(str(out / f"compose_{v}.avi"), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (CANVAS_W, CANVAS_H))
    keep = []
    for n, (face, talk) in enumerate(zip(faces, talking)):
        t = n / FPS
        if v == "v3" and turns:  # round 3: a clip per sentence from each answer's text, 'think' while it is coming
            for k, (t0, text) in enumerate(turns):
                if abs(t - t0) < 0.5 / FPS:
                    body.set_plan(text, first_turn=k == 0)
                if abs(t - (t0 - 0.8)) < 0.5 / FPS:
                    body.thinking()
        else:
            cur = [s for t0, s in sched if t0 <= t + 1e-6]
            if cur and talk:
                body.set_turn(cur[-1])
        frame = body(face, n, talk)
        w.write(frame); keep.append(frame)
    w.release()
    r = np.array(body.residual)
    h = np.array(body.halo)
    res[v] = {"anchor_mean_px": round(float(r.mean()), 2), "anchor_p95_px": round(float(np.percentile(r, 95)), 2),
              "halo_mean_pct": round(100 * float(h.mean()), 2), "halo_p95_pct": round(100 * float(np.percentile(h, 95)), 2)}
    r = h  # the worst frames are picked by halo (face pasted outside the clip's face = the visible ghost)
    frames_by_v[v] = (keep, r)
    args = ["ffmpeg", "-loglevel", "error", "-y", "-i", str(out / f"compose_{v}.avi")] + (["-i", audio, "-shortest"] if audio else []) + \
           ["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", str(out / f"compose_{v}.mp4")]
    subprocess.run(args, check=True); (out / f"compose_{v}.avi").unlink()
print(json.dumps(res))
json.dump(res, open(out / "anchor_residual.json", "w"))
# worst v2 frames: face crops v2 above v3
k2, r2 = frames_by_v["v2"]; k3, _ = frames_by_v["v3"]
worst = sorted(np.argsort(r2)[-6:])
det = face_mesh(static=True); tiles = []
for i in worst:
    p = landmarks(det, k3[i]); cx, cy = (p[1] if p is not None else (CANVAS_W / 2, 330))
    x0, y0 = int(np.clip(cx - 130, 0, CANVAS_W - 260)), int(np.clip(cy - 150, 0, CANVAS_H - 300))
    a, b = k2[i][y0:y0 + 300, x0:x0 + 260], k3[i][y0:y0 + 300, x0:x0 + 260]
    for im, lab in ((a, f"v2 halo {100 * r2[i]:.0f}%"), (b, "v3")):
        cv2.putText(im, lab, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
    tiles.append(np.vstack([a, b]))
cv2.imwrite(str(out / "worst_frames_v2_vs_v3.jpg"), np.hstack(tiles))
# side by side
subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(out / "compose_v2.mp4"), "-i", str(out / "compose_v3.mp4"), "-filter_complex",
                "[0:v]scale=540:960[a];"
                "[1:v]scale=540:960[b];[a][b]hstack",
                *(["-map", "1:a?"] if audio else []), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", str(out / "compose_v2_vs_v3.mp4")], check=True)

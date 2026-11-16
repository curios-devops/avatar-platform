"""Pose session, step 2: the recorded takes become body clips in the round 3 format, ready for the gesture layer
(flashhead/body_layer.py) and LiveTalking's body states (musetalk/patch_states.py), side by side with the Pruna clips.

    backend/.venv/bin/python lab/poses/prepare.py <name> [--explain-from 3 --explain-len 7]

In:  lab/inputs/poses/<name>/raw/{listen,greet,explain,emphasis,think}.{webm,mp4}   (record.html + server.py)
Out: lab/inputs/poses/<name>/clips/
       <pose>.mp4        480x704, 24 fps, H.264, no audio (same as inputs/round3/jin/clips)
       <pose>.mp3        the line said in greet / explain / emphasis (the live engine drives the mouth with it)
       voice_sample.wav  the whole explain take, mono 44.1 kHz: the sample for cloning the voice
       sheet.jpg         three frames per pose, to check framing and continuity at a glance
       prepare.json      crop, durations and the recording checks

One crop for all five takes, from the median face across them, so the clips meet at the same framing (the gesture
layer cuts between them). The face sits a third of the way down, at about the size it has in Jin's clips.
Light: ffmpeg plus MediaPipe on every 4th frame; a few seconds on the Mac, nothing heavy.
"""
import argparse
import json
import pathlib
import subprocess
import tempfile

import cv2
import mediapipe as mp
import numpy as np

LAB = pathlib.Path(__file__).resolve().parent.parent
POSES = ("listen", "greet", "explain", "emphasis", "think")
SPEAKING = ("greet", "explain", "emphasis")
W, H, FPS = 480, 704, 24
FACE_FRACTION = 0.24  # face height / clip height, about Jin's in round 3
FACE_Y = 0.33         # face centre, from the top of the clip
MODEL = pathlib.Path.home() / ".cache/mediapipe/face_landmarker.task"


def run(*cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def faces(path: pathlib.Path, every=4):
    """Face boxes (x0, y0, x1, y1 in pixels) on every few frames, and the frame size."""
    opts = mp.tasks.vision.FaceLandmarkerOptions(base_options=mp.tasks.BaseOptions(model_asset_path=str(MODEL)),
                                                 running_mode=mp.tasks.vision.RunningMode.IMAGE, num_faces=1)
    boxes, size = [], None
    with mp.tasks.vision.FaceLandmarker.create_from_options(opts) as lm:
        cap = cv2.VideoCapture(str(path))
        i = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            size = frame.shape[1], frame.shape[0]
            if i % every == 0:
                img = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                r = lm.detect(img)
                if r.face_landmarks:
                    pts = np.array([(p.x * size[0], p.y * size[1]) for p in r.face_landmarks[0]])
                    boxes.append((*pts.min(0), *pts.max(0)))
            i += 1
        cap.release()
    return np.array(boxes), size


def crop_for(boxes: np.ndarray, size):
    fw, fh = size
    x0, y0, x1, y1 = np.median(boxes, axis=0)
    ch = min(fh, (y1 - y0) / FACE_FRACTION)
    cw = ch * W / H
    if cw > fw:  # a narrow source: the width decides
        cw, ch = fw, fw * H / W
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    left = float(np.clip(cx - cw / 2, 0, fw - cw))
    top = float(np.clip(cy - FACE_Y * ch, 0, fh - ch))
    even = lambda v: int(v) // 2 * 2
    return {"w": even(cw), "h": even(ch), "x": even(left), "y": even(top)}


def sheet(clips: dict[str, pathlib.Path], out: pathlib.Path):
    rows = []
    for pose, path in clips.items():
        cap = cv2.VideoCapture(str(path))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        row = []
        for f in (0.1, 0.5, 0.9):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * f))
            ok, frame = cap.read()
            frame = cv2.resize(frame, (240, 352)) if ok else np.zeros((352, 240, 3), np.uint8)
            cv2.putText(frame, pose, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            row.append(frame)
        cap.release()
        rows.append(np.hstack(row))
    cv2.imwrite(str(out), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--explain-from", type=float, default=3.0, help="where the explain body clip starts, in seconds")
    ap.add_argument("--explain-len", type=float, default=7.0, help="explain body clip length (round 3: about 7 s)")
    a = ap.parse_args()
    base = LAB / "inputs/poses" / a.name
    raw, out = base / "raw", base / "clips"
    out.mkdir(parents=True, exist_ok=True)
    takes = {p: next(iter(sorted(raw.glob(f"{p}.webm")) + sorted(raw.glob(f"{p}.mp4"))), None) for p in POSES}
    missing = [p for p, t in takes.items() if t is None]
    if missing:
        raise SystemExit(f"missing takes: {', '.join(missing)} (record them in record.html)")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        # MediaRecorder writes variable frame timing: make each take constant 24 fps first.
        cfr = {}
        for p, t in takes.items():
            cfr[p] = tmp / f"{p}.mp4"
            run("ffmpeg", "-y", "-i", str(t), "-vf", f"fps={FPS}", "-an", "-c:v", "libx264", "-crf", "16", "-preset", "fast", str(cfr[p]))
        all_boxes, size, found = [], None, {}
        for p, path in cfr.items():
            boxes, size = faces(path)
            found[p] = len(boxes)
            if len(boxes):
                all_boxes.append(boxes)
        if not all_boxes:
            raise SystemExit("no face found in any take")
        crop = crop_for(np.vstack(all_boxes), size)
        vf = f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']},scale={W}:{H}:flags=lanczos,format=yuv420p"
        clips = {}
        for p, path in cfr.items():
            trim = ["-ss", str(a.explain_from), "-t", str(a.explain_len)] if p == "explain" else []
            clips[p] = out / f"{p}.mp4"
            run("ffmpeg", "-y", *trim, "-i", str(path), "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                "-movflags", "+faststart", str(clips[p]))
            if p in SPEAKING:
                run("ffmpeg", "-y", *trim, "-i", str(takes[p]), "-vn", "-ac", "1", "-ar", "44100", "-b:a", "160k", str(out / f"{p}.mp3"))
        run("ffmpeg", "-y", "-i", str(takes["explain"]), "-vn", "-ac", "1", "-ar", "44100", str(out / "voice_sample.wav"))

    sheet(clips, out / "sheet.jpg")
    dur = lambda f: float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                                         capture_output=True, text=True).stdout.strip() or 0)
    checks = {p: json.loads((raw / f"{p}.checks.json").read_text() or "{}") if (raw / f"{p}.checks.json").exists() else {} for p in POSES}
    report = {"name": a.name, "source_size": size, "crop": crop, "faces_found": found,
              "clips": {p: round(dur(c), 2) for p, c in clips.items()}, "voice_sample_s": round(dur(out / "voice_sample.wav"), 1),
              "recording_checks": checks}
    (out / "prepare.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

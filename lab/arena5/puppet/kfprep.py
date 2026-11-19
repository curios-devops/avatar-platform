"""Arena 5 puppet, pilot 2: gate, colour-match and mesh the expression keyframes made by kf.py (CPU, MediaPipe).

    backend/.venv/bin/python lab/arena5/puppet/kfprep.py gate <char>              # score every raw keyframe
    backend/.venv/bin/python lab/arena5/puppet/kfprep.py adopt <char> pose[=raw] ...  # chosen raw -> kf/<pose>.png
    backend/.venv/bin/python lab/arena5/puppet/kfprep.py sheet <char>             # one image of the adopted keyframes

gate   for each chars/<id>/kf/raw/*.png against the portrait:
         stable  mean landmark distance on points outside the mouth, jaw and eyes (forehead, brows' outer ends,
                 nose bridge, temples), as % of the face width: a moved, scaled or turned head;
         out     mean absolute pixel difference outside the face oval grown by 12 % (hair, ears, clothes, backdrop),
                 after removing the mean tone shift there (reported as tone; adopt corrects tone);
       -> kf/raw/gate.json and a printed table. Pass: stable <= 2.5 % (4 % for aa and laugh, whose brows, nose and cheeks move) and out <= 9 (0-255). The eye check of each
       image stays: the numbers only catch drift, not a bad mouth.
adopt  rest=<raw> first replaces portrait.png by an edited neutral face (clay, crochet); then
       resizes the raw image to the portrait's size, moves its face-oval colour mean 80 % toward the portrait's
       (edit models shift the tone a little; blended frames would flicker), runs the landmarks again and writes
       kf/<pose>.png and kf/index.json ({w, h, poses: {pose: {points}}}; rest is the portrait itself).
"""
import json
import pathlib
import sys

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import BaseOptions, vision

HERE = pathlib.Path(__file__).resolve().parent
MODEL = pathlib.Path.home() / ".cache/mediapipe/face_landmarker.task"
OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148,
        176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
STABLE = [10, 151, 9, 8, 168, 6, 197, 195, 5, 4, 1, 109, 338, 67, 297, 103, 332, 54, 284, 21, 251, 162, 389, 127, 356,
          234, 454, 70, 300]
BIG = ("aa", "laugh")  # the brows, nose and cheeks move in these: a looser stable bar
POSES = ["talk_mid", "aa", "OU", "E", "MBP", "laugh", "blink"]


def detector():
    return vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1, output_face_blendshapes=True))


def detect(det, rgb):
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb)))
    if not res.face_landmarks:
        return None, {}
    h, w = rgb.shape[:2]
    pts = np.array([[p.x * w, p.y * h, p.z * w] for p in res.face_landmarks[0]])
    bs = {b.category_name: round(b.score, 3) for b in res.face_blendshapes[0]} if res.face_blendshapes else {}
    return pts, bs


def load(path, size=None):
    im = cv2.cvtColor(cv2.imread(str(path)), cv2.COLOR_BGR2RGB)
    if size and im.shape[:2] != (size, size):
        im = cv2.resize(im, (size, size), interpolation=cv2.INTER_AREA if im.shape[0] > size else cv2.INTER_LANCZOS4)
    return im


def oval_mask(pts, shape, grow=1.0):
    o = pts[OVAL, :2]
    c = o.mean(0)
    poly = (c + (o - c) * grow).astype(np.int32)
    m = np.zeros(shape[:2], np.uint8)
    cv2.fillPoly(m, [poly], 255)
    return m


def gate(cid):
    d = HERE / "chars" / cid
    det = detector()
    raws = sorted((d / "kf" / "raw").glob("*.png"))
    size = load(raws[0]).shape[0]
    port = load(d / "portrait.png", size)
    P, _ = detect(det, port)
    fw = np.linalg.norm(P[454, :2] - P[234, :2])
    outside = oval_mask(P, port.shape, 1.12) == 0
    rows = {}
    for r in raws:
        im = load(r, size)
        Q, bs = detect(det, im)
        if Q is None:
            rows[r.stem] = {"face": False, "pass": False}
            print(f"{r.stem:16s} NO FACE")
            continue
        stable = float(np.linalg.norm(Q[STABLE, :2] - P[STABLE, :2], axis=1).mean() / fw * 100)
        both_out = outside & (oval_mask(Q, im.shape, 1.12) == 0)
        # structure, not tone: the edit model lifts the backdrop a little everywhere; that is matched, not rejected
        A, B = im.astype(np.float32)[both_out], port.astype(np.float32)[both_out]
        tone = float(np.abs(A.mean(0) - B.mean(0)).mean())
        out = float(np.abs(A - A.mean(0) + B.mean(0) - B).mean())
        chin = float((Q[152, 1] - P[152, 1]) / fw * 100)
        ok = stable <= (4.0 if r.stem.split("_")[0] in BIG else 2.5) and out <= 9
        rows[r.stem] = {"face": True, "stable_pct": round(stable, 2), "out_abs": round(out, 2), "tone": round(tone, 1), "chin_down_pct": round(chin, 1),
                        "jawOpen": bs.get("jawOpen"), "smile": round((bs.get("mouthSmileLeft", 0) + bs.get("mouthSmileRight", 0)) / 2, 2),
                        "blink": round((bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2, 2),
                        "squint": round((bs.get("eyeSquintLeft", 0) + bs.get("eyeSquintRight", 0)) / 2, 2), "pass": ok}
        x = rows[r.stem]
        print(f"{r.stem:16s} stable {stable:4.1f} %  out {out:5.1f} (tone {tone:4.1f})  chin {chin:+5.1f} %  jaw {x['jawOpen']:.2f} smile "
              f"{x['smile']:.2f} blink {x['blink']:.2f} squint {x['squint']:.2f}  {'PASS' if ok else 'FAIL'}")
    (d / "kf" / "raw" / "gate.json").write_text(json.dumps(rows, indent=1))


def adopt(cid, specs):
    d = HERE / "chars" / cid
    det = detector()
    port = load(d / "portrait.png")
    S = port.shape[0]
    for spec in [x for x in specs if x.startswith("rest=")]:
        # replacement-face styles: an edited neutral face replaces the portrait, so every face shares one surface
        # (the clay portrait's tool marks differed from all the edits); the original stays as portrait_orig.png
        if not (d / "portrait_orig.png").exists():
            (d / "portrait_orig.png").write_bytes((d / "portrait.png").read_bytes())
        port = load(d / "kf" / "raw" / f"{spec[5:]}.png", S)
        cv2.imwrite(str(d / "portrait.png"), cv2.cvtColor(port, cv2.COLOR_RGB2BGR))
        print(f"rest <- raw/{spec[5:]}.png (portrait.png replaced; run prepare.py for landmarks.json)")
    specs = [x for x in specs if not x.startswith("rest=")]
    P, _ = detect(det, port)
    idx_path = d / "kf" / "index.json"
    index = json.loads(idx_path.read_text()) if idx_path.exists() else {"w": S, "h": S, "poses": {}}
    index["poses"]["rest"] = {"src": "portrait.png", "points": np.round(P, 2).tolist()}
    pm = oval_mask(P, port.shape, 0.9) > 0
    for spec in specs:
        pose, _, raw = spec.partition("=")
        im = load(d / "kf" / "raw" / f"{raw or pose}.png", S)
        Q, _ = detect(det, im)
        if Q is None:
            print(pose, "NO FACE")
            continue
        qm = oval_mask(Q, im.shape, 0.9) > 0
        # do not count the mouth and eyes in the colour statistics
        for loop in ([61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291, 409, 270, 269, 267, 0, 37, 39, 40, 185],
                     [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246],
                     [263, 249, 390, 373, 374, 380, 381, 382, 362, 398, 384, 385, 386, 387, 388, 466]):
            for pts, m in ((P, pm), (Q, qm)):
                t = np.zeros(m.shape, np.uint8)
                c = pts[loop, :2].mean(0)
                cv2.fillPoly(t, [(c + (pts[loop, :2] - c) * 1.3).astype(np.int32)], 1)
                m &= t == 0
        shift = port[pm].astype(np.float32).mean(0) - im[qm].astype(np.float32).mean(0)
        im = np.clip(im.astype(np.float32) + 0.8 * shift, 0, 255).astype(np.uint8)
        Q, _ = detect(det, im)
        cv2.imwrite(str(d / "kf" / f"{pose}.png"), cv2.cvtColor(im, cv2.COLOR_RGB2BGR))
        index["poses"][pose] = {"src": f"raw/{raw or pose}.png", "colour_shift": np.round(0.8 * shift, 1).tolist(),
                                "points": np.round(Q, 2).tolist()}
        print(f"{pose} <- raw/{raw or pose}.png, colour shift {np.round(0.8 * shift, 1).tolist()}")
    idx_path.write_text(json.dumps(index, separators=(",", ":")))


def sheet(cid):
    d = HERE / "chars" / cid
    index = json.loads((d / "kf" / "index.json").read_text())
    tiles = []
    for pose in ["rest"] + POSES:
        if pose not in index["poses"]:
            continue
        im = load(d / ("portrait.png" if pose == "rest" else f"kf/{pose}.png"), 512)
        pts = np.array(index["poses"][pose]["points"])[:, :2] * 512 / index["w"]
        c = pts.mean(0)
        x0, y0 = int(max(0, min(512 - 300, c[0] - 150))), int(max(0, min(512 - 300, c[1] - 140)))
        t = im[y0:y0 + 300, x0:x0 + 300].copy()
        cv2.putText(t, pose, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(t)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)]
    out = d / "shots" / "kf_poses.png"
    out.parent.mkdir(exist_ok=True)
    cv2.imwrite(str(out), cv2.cvtColor(np.vstack(rows), cv2.COLOR_RGB2BGR))
    print(out)


if __name__ == "__main__":
    cmd, cid = sys.argv[1], sys.argv[2]
    {"gate": lambda: gate(cid), "adopt": lambda: adopt(cid, sys.argv[3:] or POSES), "sheet": lambda: sheet(cid)}[cmd]()

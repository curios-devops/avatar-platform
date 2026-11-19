"""Arena 5 puppet: landmarks computed once per character (MediaPipe Face Landmarker, Apache-2.0), on the CPU.

    backend/.venv/bin/python lab/arena5/puppet/prepare.py            # every chars/<id>/portrait.png -> landmarks.json
    backend/.venv/bin/python lab/arena5/puppet/prepare.py check <id>  # how far img2img moved the mouth of each sprite

Writes chars/<id>/landmarks.json ({w, h, points: 478 x [x px, y px, z px]}), mesh/tess.json (the 852 face triangles of
MediaPipe's tessellation, the same for every face) and chars/index.json (what the page lists). The page can also run the
same model in the browser (tasks-vision 0.10.14, ?detect=1) to show it gives the same points; this file only saves the
round trip. Model: ~/.cache/mediapipe/face_landmarker.task (3.7 MB, already on disk).
"""
import json
import pathlib
import sys

import mediapipe as mp
from mediapipe.tasks.python import BaseOptions, vision
from mediapipe.tasks.python.vision import FaceLandmarksConnections as C

HERE = pathlib.Path(__file__).resolve().parent
MODEL = pathlib.Path.home() / ".cache/mediapipe/face_landmarker.task"
STYLES = {"film": "Animated Feature Film", "game": "Realistic Game Character", "anime": "Anime 3D",
          "semi": "Semi-realistic Illustration", "clay": "Clay Stop Motion", "crochet": "Crochet Amigurumi"}
NAMES = {"film_w": "Lia", "film_m": "Teo", "game_w": "Mei", "game_m": "Rowan", "anime_w": "Sora", "anime_m": "Kai",
         "semi_m": "Dario", "clay_w": "Greta", "crochet_m": "Bruno"}
LIPS = [78, 191, 80, 81, 82, 13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95,
        61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291, 375, 321, 405, 314, 17, 84, 181, 91, 146]


def detector():
    opts = vision.FaceLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)), num_faces=1,
                                        output_face_blendshapes=True)
    return vision.FaceLandmarker.create_from_options(opts)


def detect(det, path):
    img = mp.Image.create_from_file(str(path))
    res = det.detect(img)
    if not res.face_landmarks:
        return None
    w, h = img.width, img.height
    pts = [[round(p.x * w, 2), round(p.y * h, 2), round(p.z * w, 2)] for p in res.face_landmarks[0]]
    bs = {b.category_name: round(b.score, 3) for b in res.face_blendshapes[0]} if res.face_blendshapes else {}
    return {"w": w, "h": h, "points": pts, "blendshapes": bs}


def main():
    det = detector()
    if len(sys.argv) > 2 and sys.argv[1] == "check":
        cid = sys.argv[2]
        for pre in sorted((HERE / "chars" / cid / "pre").glob("*.png")):
            spr = HERE / "chars" / cid / "mouth" / pre.name
            a, b = detect(det, pre), detect(det, spr) if spr.exists() else None
            if not (a and b):
                print(pre.stem, "no face" if a else "no pre face", flush=True)
                continue
            mw = abs(a["points"][291][0] - a["points"][61][0])
            d = [((a["points"][i][0] - b["points"][i][0]) ** 2 + (a["points"][i][1] - b["points"][i][1]) ** 2) ** 0.5 for i in LIPS]
            gap = lambda r: r["points"][14][1] - r["points"][13][1]
            print(f"{pre.stem}: lip points moved mean {sum(d) / len(d) / mw * 100:.1f} % / max {max(d) / mw * 100:.1f} % "
                  f"of mouth width; inner gap pre {gap(a):.0f} px, sprite {gap(b):.0f} px; jawOpen pre "
                  f"{a['blendshapes'].get('jawOpen', 0):.2f} sprite {b['blendshapes'].get('jawOpen', 0):.2f}")
        return
    (HERE / "mesh").mkdir(exist_ok=True)
    t = [(c.start, c.end) for c in C.FACE_LANDMARKS_TESSELATION]
    tris = [t[i][0] for i in range(0, len(t))]  # triples (a,b),(b,c),(c,a): the starts are a, b, c
    (HERE / "mesh" / "tess.json").write_text(json.dumps(tris))
    index = []
    for d in sorted((HERE / "chars").iterdir()):
        if not (d / "portrait.png").exists():
            continue
        r = detect(det, d / "portrait.png")
        if not r:
            print(d.name, "NO FACE FOUND")
            continue
        (d / "landmarks.json").write_text(json.dumps(r, separators=(",", ":")))
        style = d.name.split("_")[0]
        sprites = sorted(p.stem for p in (d / "mouth").glob("*.png") if not p.stem.startswith("_")) if (d / "mouth").exists() else []
        index.append({"id": d.name, "name": NAMES.get(d.name, d.name), "style": style, "styleName": STYLES.get(style, style),
                      "voice": "imani_en_t" if d.name.endswith("_m") else "nova_es_t", "sprites": sprites,
                      "kf": sorted(json.loads((d / "kf" / "index.json").read_text())["poses"]) if (d / "kf" / "index.json").exists() else [],
                      "kfMode": "replace" if style in ("clay", "crochet") else "morph"})
        p = r["points"]
        print(f"{d.name}: face width {abs(p[454][0] - p[234][0]):.0f} px, mouth width {abs(p[291][0] - p[61][0]):.0f} px, "
              f"inner gap {p[14][1] - p[13][1]:.1f} px, jawOpen {r['blendshapes'].get('jawOpen', 0):.2f}, "
              f"eyeBlink {r['blendshapes'].get('eyeBlinkLeft', 0):.2f}/{r['blendshapes'].get('eyeBlinkRight', 0):.2f}")
    (HERE / "chars" / "index.json").write_text(json.dumps(index, indent=1))


if __name__ == "__main__":
    main()

"""Jin round 3: a new look closer to the tech-creator reference (navy tee with the MEYA logo, glasses, blue tech studio).
OpenAI image edit with our logo as the only input image. Key from backend/.env, never printed.
    backend/.venv/bin/python gen.py <n>"""
import base64, json, pathlib, sys, time, random, concurrent.futures as cf
import httpx
HERE = pathlib.Path(__file__).parent
ENV = dict(l.split("=", 1) for l in (HERE.parents[3] / "backend/.env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["OPENAI_API_KEY"].strip().strip('"')
MODEL = "gpt-image-2.6-sunburst"
PROMPT = ("Photorealistic vertical video-call frame of Jin, an original fictional tech creator for MEYA (not a real or famous "
          "person): an East Asian man around thirty, short neat black hair with a soft side part, thin black rectangular "
          "glasses, clean-shaven, friendly face, a warm closed-lip smile, looking straight into the lens. He wears a plain "
          "navy blue crew-neck t-shirt with a small chest logo on the left side of his chest: exactly the dotted M mark and "
          "the word MEYA from the attached image, printed small in off-white. A black smartwatch on his left wrist. "
          "He sits facing the camera, centred, framed from just above the head to the waist, both hands relaxed and visible "
          "in front of his stomach, fingers loosely together. Background: his tech studio at night, softly out of focus, "
          "blue ambient LED light on dark shelves with gadgets, a camera, a small speaker, a game controller and a glowing "
          "monitor. Soft key light on his face, sharp focus on the face and glasses, no glare on the lenses. Shot on a 35mm "
          "lens at eye level. No other text, no other logos.")

def one(i):
    t = time.time()
    r = httpx.post("https://api.openai.com/v1/images/edits", headers={"Authorization": f"Bearer {KEY}"}, timeout=300,
                   data={"model": MODEL, "prompt": PROMPT, "size": "1024x1536", "quality": "medium", "n": "1"},
                   files=[("image[]", ("meya_logo.png", (HERE / "meya_logo.png").read_bytes(), "image/png"))])
    if r.is_error:
        return {"i": i, "error": r.text[:300]}
    d = r.json(); u = d.get("usage", {})
    name = f"jin3_{time.strftime('%H%M%S')}_{random.randint(0, 999)}.png"
    (HERE / name).write_bytes(base64.b64decode(d["data"][0]["b64_json"]))
    return {"file": name, "seconds": round(time.time() - t, 1), "usage": u}

with cf.ThreadPoolExecutor(4) as ex:
    res = list(ex.map(one, range(int(sys.argv[1]))))
for x in res: print(json.dumps(x))
(HERE / "gen_log.jsonl").open("a").write("".join(json.dumps(x) + "\n" for x in res))

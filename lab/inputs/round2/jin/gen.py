"""Jin, MEYA's tech creator (round 2): portraits from the OpenAI 2.6 image model, with the real token cost. Key from backend/.env."""
import base64, json, pathlib, sys, time, concurrent.futures as cf
import httpx
HERE = pathlib.Path(__file__).parent
ENV = dict(l.split("=", 1) for l in (HERE.parents[3] / "backend/.env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["OPENAI_API_KEY"].strip().strip('"')
PROMPT = ("Photorealistic vertical photo of Jin, an original MEYA tech creator who talks about AI, gadgets, apps and nerd "
          "culture: an East Asian man around twenty-eight with short textured black hair, warm dark eyes, expressive "
          "eyebrows, clean-shaven, a friendly open smile with lips closed. He wears an olive green knit sweater over a white "
          "tee collar. He sits at a light wooden desk in a bright, cosy home office in daylight, centred, facing the camera "
          "and looking into the lens, both forearms resting on the desk with relaxed open hands visible. Behind him, softly "
          "out of focus: a large window with daylight, wooden bookshelves with books, small retro robot figures and plants, "
          "a desk lamp, a mechanical keyboard and a monitor at the side. Framed from just above the head to the waist, "
          "natural soft window light, shot on 35mm. No text, no logos, no brand names, not a real or famous person.")
PRICE_OUT, PRICE_IN_TXT = 30 / 1e6, 5 / 1e6

def one(model, quality="medium"):
    t = time.time()
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {KEY}"}, timeout=300,
                   json={"model": model, "prompt": PROMPT, "size": "1024x1536", "quality": quality, "n": 1})
    if r.is_error:
        return {"model": model, "error": r.text[:300]}
    d = r.json(); u = d.get("usage", {})
    (HERE / f"jin_{model}_{quality}_{time.strftime('%H%M%S')}_{__import__('random').randint(0,999)}.png").write_bytes(base64.b64decode(d["data"][0]["b64_json"]))
    cost = u.get("output_tokens", 0) * PRICE_OUT + u.get("input_tokens", 0) * PRICE_IN_TXT
    return {"model": model, "quality": quality, "seconds": round(time.time() - t, 1), "usage": u, "usd": round(cost, 4)}

jobs = [(m, q) for m in sys.argv[1].split(",") for q in sys.argv[2].split(",")]
with cf.ThreadPoolExecutor(4) as ex:
    res = list(ex.map(lambda a: one(*a), jobs))
for x in res: print(json.dumps(x))
(HERE / "gen_log.jsonl").open("a").write("".join(json.dumps(x) + "\n" for x in res))

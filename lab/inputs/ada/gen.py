"""Ada, MEYA's tech creator: one portrait per OpenAI 2.6 image model, with the real token cost. Key from backend/.env."""
import base64, json, pathlib, sys, time, concurrent.futures as cf
import httpx
HERE = pathlib.Path(__file__).parent
ENV = dict(l.split("=", 1) for l in (HERE.parents[2] / "backend/.env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["OPENAI_API_KEY"].strip().strip('"')
PROMPT = ("Photorealistic vertical photo of Ada, an original MEYA tech creator who talks about AI, new gadgets and nerd "
          "culture: a Latina woman around thirty with a short dark brown wavy bob, warm brown eyes, light freckles, small "
          "silver ear cuffs, natural makeup, a confident friendly smile with lips closed. She wears a charcoal crewneck "
          "sweatshirt. She sits at a light wooden desk in her home tech studio, centred, facing the camera and looking into "
          "the lens, both forearms resting on the desk with relaxed open hands visible. Behind her, softly out of focus: a "
          "ring light, a podcast microphone on a boom arm at the side of the frame not covering her face, a monitor with "
          "colourful code, a shelf with a small retro robot figure and plants, warm amber and cool blue LED accents. Framed "
          "from just above the head to the waist, natural soft key light, shot on 35mm. No text, no logos, no brand names, "
          "not a real or famous person.")
PRICE_OUT, PRICE_IN_TXT = 30 / 1e6, 5 / 1e6

def one(model, quality="medium"):
    t = time.time()
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {KEY}"}, timeout=300,
                   json={"model": model, "prompt": PROMPT, "size": "1024x1536", "quality": quality, "n": 1})
    if r.is_error:
        return {"model": model, "error": r.text[:300]}
    d = r.json(); u = d.get("usage", {})
    (HERE / f"ada_{model}_{quality}.png").write_bytes(base64.b64decode(d["data"][0]["b64_json"]))
    cost = u.get("output_tokens", 0) * PRICE_OUT + u.get("input_tokens", 0) * PRICE_IN_TXT
    return {"model": model, "quality": quality, "seconds": round(time.time() - t, 1), "usage": u, "usd": round(cost, 4)}

jobs = [(m, q) for m in sys.argv[1].split(",") for q in sys.argv[2].split(",")]
with cf.ThreadPoolExecutor(4) as ex:
    res = list(ex.map(lambda a: one(*a), jobs))
for x in res: print(json.dumps(x))
(HERE / "gen_log.jsonl").open("a").write("".join(json.dumps(x) + "\n" for x in res))

"""MuseTalk needs a short video of the being, not a photo: this makes it from the portrait (the e2e prep step). Was Imani's for real-time lip sync (MuseTalk): 10 s, energetic personal trainer, same identity as the film
portrait. MuseTalk repaints the mouth, so the mouth stays closed and the lower face visible; eyes open, on the lens.
Pruna p-video, 720p (about 0.02 USD/s). Key from backend/.env, never printed.

    backend/.venv/bin/python lab/musetalk/make_clip.py <portrait.png> <out.mp4>
"""
import json, pathlib, sys, time
import httpx

HERE = pathlib.Path(__file__).parent
SRC = pathlib.Path(sys.argv[1])
OUT = pathlib.Path(sys.argv[2])
ENV = dict(l.split("=", 1) for l in pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env").read_text().splitlines()
           if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["PRUNA_K_API_KEY"].strip().strip('"')
SECONDS = 8
PROMPT = ("Static locked-off camera, no zoom, no cut, the background stays the same, sharp focus on her face. The "
          "same woman is on a calm, friendly video call: she looks straight into the "
          "lens the whole time with attentive, kind eyes and a gentle closed-lip smile. She listens and gives slow, "
          "reassuring nods, tilts her head slightly, blinks naturally and breathes calmly. Her head stays centred, her "
          "whole face stays in frame and in focus, nothing is added to her face. Hands stay low, out of frame. Slow, composed, "
          "natural motion, no fast movement. She is the same person in every frame.")


def main():
    t0 = time.time()
    with httpx.Client(timeout=240) as c:
        up = c.post("https://api.pruna.ai/v1/files", headers={"apikey": KEY},
                    files={"content": (SRC.name, SRC.open("rb"), "image/jpeg")})
        up.raise_for_status()
        u = up.json()
        img = u.get("urls", {}).get("get") or u.get("url") or u.get("id")
        r = c.post("https://api.pruna.ai/v1/predictions", headers={"apikey": KEY, "Model": "p-video", "Try-Sync": "true"},
                   json={"input": {"image": img, "prompt": PROMPT, "duration": SECONDS, "resolution": "720p"}})
        print("status", r.status_code, r.text[:300] if r.is_error else "", flush=True)
        r.raise_for_status()
        cost = r.headers.get("x-cost") or r.headers.get("x-pruna-cost")
        d = r.json()
        for _ in range(120):
            url = d.get("generation_url") or (d.get("output") if isinstance(d.get("output"), str) else None)
            if url:
                v = c.get(url, headers={"apikey": KEY}); v.raise_for_status()
                out = OUT
                out.write_bytes(v.content)
                print(json.dumps({"ok": True, "file": out.name, "seconds": round(time.time() - t0, 1), "x_cost": cost}))
                return
            if d.get("status") in ("failed", "canceled", "cancelled") or not d.get("get_url"):
                raise RuntimeError(str(d)[:300])
            time.sleep(3)
            g = c.get(d["get_url"], headers={"apikey": KEY})
            cost = cost or g.headers.get("x-cost")
            d = {**d, **g.json()}
        raise RuntimeError("timeout")


main()

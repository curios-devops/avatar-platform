"""Render the being's side of a live call (10 s of the call tape) with the hosted avatar APIs, for the arena.

  pruna   p-video-2-pro-avatar: portrait + our audio -> talking video with hands (768p, 0.04 USD/s)
  boson   higgs-avatar: portrait + our audio -> talking video (480x640 portrait, batch)
Wall time from request to downloaded file goes to <out>/api_times.jsonl. Keys from backend/.env, never printed.

    backend/.venv/bin/python lab/api_avatars/render.py <portrait.jpg> <audio.wav> <out_dir> [pruna] [boson]
"""
import concurrent.futures as cf, json, pathlib, sys, time
import httpx

ENV = dict(l.split("=", 1) for l in pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env").read_text().splitlines()
           if "=" in l and not l.lstrip().startswith("#"))
key = lambda k: ENV[k].strip().strip('"')
PROMPT = ("A friendly young man in an olive green sweater talks directly to the camera in a bright home office, lips in sync "
          "with the speech, with a relaxed, enthusiastic delivery and natural hand gestures.")


def pruna(img, wav, out):
    t0, k = time.time(), key("PRUNA_K_API_KEY")
    model = ENV.get("PRUNA_AVATAR_MODEL", "p-video-2-pro-avatar").strip().strip('"')
    with httpx.Client(timeout=300) as c:
        up = lambda p, mime: (lambda u: u.get("urls", {}).get("get") or u.get("url") or u.get("id"))(
            c.post("https://api.pruna.ai/v1/files", headers={"apikey": k}, files={"content": (p.name, p.open("rb"), mime)}).raise_for_status().json())
        i_url, a_url = up(img, "image/jpeg"), up(wav, "audio/wav")
        r = c.post("https://api.pruna.ai/v1/predictions", headers={"apikey": k, "Model": model, "Try-Sync": "true"},
                   json={"input": {"image": i_url, "audio": a_url, "prompt": PROMPT, "resolution": "768p"}})
        if r.is_error:
            return {"engine": "pruna-avatar", "error": f"{r.status_code} {r.text[:300]}"}
        d = r.json()
        for _ in range(200):
            url = d.get("generation_url") or (d.get("output") if isinstance(d.get("output"), str) else None)
            if url:
                (out / "render-pruna-avatar_jin.mp4").write_bytes(c.get(url, headers={"apikey": k}).raise_for_status().content)
                return {"engine": "pruna-avatar", "model": model, "wall_s": round(time.time() - t0, 1), "resolution": "768p"}
            if d.get("status") in ("failed", "canceled", "cancelled") or not d.get("get_url"):
                return {"engine": "pruna-avatar", "error": str(d)[:300]}
            time.sleep(2)
            d = {**d, **c.get(d["get_url"], headers={"apikey": k}).json()}
    return {"engine": "pruna-avatar", "error": "timeout"}


def boson(img, wav, out):
    t0, h = time.time(), {"Authorization": "Bearer " + key("BOSON_K_API_KEY")}
    r = httpx.post("https://api.boson.ai/v1/videos", headers=h, timeout=120, data={"model": "higgs-avatar", "size": "480x640"},
                   files={"ref_image": (img.name, img.read_bytes(), "image/jpeg"), "input": (wav.name, wav.read_bytes(), "audio/wav")})
    if r.is_error:
        return {"engine": "boson", "error": f"{r.status_code} {r.text[:300]}"}
    v = r.json()
    while v["status"] not in ("completed", "failed"):
        time.sleep(2); v = httpx.get(f"https://api.boson.ai/v1/videos/{v['id']}", headers=h, timeout=30).json()
    if v["status"] != "completed":
        return {"engine": "boson", "error": str(v)[:300]}
    c = httpx.get(f"https://api.boson.ai/v1/videos/{v['id']}/content", headers=h, timeout=120, follow_redirects=True)
    (out / "render-boson_jin.mp4").write_bytes(c.content)
    return {"engine": "boson", "wall_s": round(time.time() - t0, 1), "size": "480x640"}


if __name__ == "__main__":
    img, wav, out = map(pathlib.Path, sys.argv[1:4]); out.mkdir(parents=True, exist_ok=True)
    which = sys.argv[4:] or ["pruna", "boson"]
    with cf.ThreadPoolExecutor(2) as ex:
        res = list(ex.map(lambda f: f(img, wav, out), [globals()[w] for w in which]))
    for x in res:
        print(json.dumps(x))
    (out / "api_times.jsonl").open("a").write("".join(json.dumps(x) + "\n" for x in res))

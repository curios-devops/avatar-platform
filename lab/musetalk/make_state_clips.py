"""The being's body clips, one per moment of a call (listening, explaining, emphasis), all starting from its portrait so
they meet at the same pose. Pruna p-video-2-pro-reference (first_frame_image = the portrait), 10 s, 768p, mode "cost".
The lips stay closed: the live face engine paints the mouth. Key from backend/.env, never printed.

    backend/.venv/bin/python lab/musetalk/make_state_clips.py <portrait.jpg> <out_dir> [listen explain emphasis]
"""
import concurrent.futures as cf, json, pathlib, sys, time
import httpx

ENV = dict(l.split("=", 1) for l in pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env").read_text().splitlines()
           if "=" in l and not l.lstrip().startswith("#"))
KEY = ENV["PRUNA_K_API_KEY"].strip().strip('"')
MODEL = ENV.get("PRUNA_VIDEO_MODEL", "p-video-2-pro-reference").strip().strip('"')
BASE = ("One continuous wide shot from a static locked-off camera on a tripod: no zoom, no push-in, no close-up, no cut, the framing never changes, the same room, light and framing as the first frame, sharp focus on his "
        "face. The same young man sits at his desk on a friendly video call. ")
TAIL = (" His lips stay closed the whole time, he does not speak, no talking. His whole face stays in frame. Subtle, human, "
        "unhurried motion, nothing cartoonish. He is the same person in every frame.")
STATES = {
    "listen": "He listens: he breathes calmly so his shoulders rise and fall softly, gives small attentive nods, tilts his "
              "head a little, glances briefly to the side as if thinking and back to the lens, blinks naturally, a warm "
              "closed-lip smile. His hands rest on the desk with tiny relaxed finger movements.",
    "explain": "He explains something with his body, calm and engaged: natural open-hand gestures just above the desk, palms "
               "up, one hand tracing a small shape in the air, light head movements and eyebrow raises, leaning slightly "
               "forward, then his hands come back to rest on the desk.",
    "emphasis": "He makes a point with emphasis: he leans a little toward the camera, raises his eyebrows, counts on his "
                "fingers one, two, three, then an enthusiastic open-palms gesture and a firm small nod, then relaxes back "
                "with his hands on the desk.",
}


def one(c, img_url, state, out_dir):
    t0 = time.time()
    r = c.post("https://api.pruna.ai/v1/predictions", headers={"apikey": KEY, "Model": MODEL, "Try-Sync": "true"},
               json={"input": {"prompt": BASE + STATES[state] + TAIL, "first_frame_image": img_url, "duration": 10,
                               "resolution": "768p", "mode": "cost", "aspect_ratio": "adaptive", "prompt_upsampler": "off"}})
    if r.is_error:
        return {"state": state, "error": f"{r.status_code} {r.text[:300]}"}
    d = r.json()
    for _ in range(200):
        url = d.get("generation_url") or (d.get("output") if isinstance(d.get("output"), str) else None)
        if url:
            v = c.get(url, headers={"apikey": KEY}); v.raise_for_status()
            (out_dir / f"{state}.mp4").write_bytes(v.content)
            return {"state": state, "seconds": round(time.time() - t0, 1), "bytes": len(v.content)}
        if d.get("status") in ("failed", "canceled", "cancelled") or not d.get("get_url"):
            return {"state": state, "error": str(d)[:300]}
        time.sleep(3)
        d = {**d, **c.get(d["get_url"], headers={"apikey": KEY}).json()}
    return {"state": state, "error": "timeout"}


def main():
    src, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); out_dir.mkdir(parents=True, exist_ok=True)
    states = sys.argv[3:] or list(STATES)
    with httpx.Client(timeout=300) as c:
        up = c.post("https://api.pruna.ai/v1/files", headers={"apikey": KEY}, files={"content": (src.name, src.open("rb"), "image/jpeg")})
        up.raise_for_status(); u = up.json()
        img = u.get("urls", {}).get("get") or u.get("url") or u.get("id")
        with cf.ThreadPoolExecutor(3) as ex:
            res = list(ex.map(lambda s: one(c, img, s, out_dir), states))
    for x in res:
        print(json.dumps(x))
    (out_dir / "clips_log.jsonl").open("a").write("".join(json.dumps({**x, "model": MODEL}) + "\n" for x in res))


main()

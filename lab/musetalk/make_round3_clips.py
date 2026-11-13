"""Jin's body clips, round 3: five moments of a call, all starting from the same portrait so they meet at one pose.

  speaking  greet / explain / emphasis: Pruna p-video-2-pro-avatar from a short line in Jin's voice (ElevenLabs), so the
            hands and head move WITH speech rhythm. The live face engine repaints the mouth with the real answer.
  silent    listen / think: Pruna p-video-2-pro-reference, lips closed (first_frame_image = portrait).
480p ("cost" mode for reference): avatar 0.02 USD/s, reference 0.015 USD/s. Keys from backend/.env, never printed.

    backend/.venv/bin/python lab/musetalk/make_round3_clips.py <portrait.jpg> <out_dir> [greet explain emphasis listen think]
"""
import concurrent.futures as cf, json, pathlib, sys, time
import httpx

ENV = dict(l.split("=", 1) for l in pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env").read_text().splitlines()
           if "=" in l and not l.lstrip().startswith("#"))
key = lambda k: ENV[k].strip().strip('"')
PK = key("PRUNA_K_API_KEY")
VOICE = "U9TSK9KHMlMU2qkeXlQP"  # "Brian - Social Media": young, clear, casual Latin American Spanish
LOOK = ("Jin, a young East Asian man with glasses in a navy MEYA t-shirt, sits in his blue-lit tech studio. One continuous "
        "shot from a locked-off camera on a tripod: no zoom, no push-in, no cut, the framing, light and room never change, "
        "he stays seated and centred, his whole head and both hands stay in frame. ")
SPEAK = {
    "greet": ("¡Hola! ¿Qué tal? Soy Jin. Cuéntame, ¿de qué nos ponemos nerds hoy?",
              "He greets the viewer warmly: a small friendly wave with one hand at chest height, a big smile, then both "
              "hands come together in front of him, inviting."),
    "explain": ("Mira, la idea es súper simple: este modelo corre en tu teléfono, sin internet, y te resume cualquier video "
                "en segundos.",
                "He explains calmly and clearly, with natural open-hand gestures in front of his chest that follow the "
                "rhythm of his words, light head movements and eyebrow raises."),
    "emphasis": ("Tres cosas: primero, la batería. Segundo, la cámara. Y tercero, ojo, ¡el precio! Eso es lo importante.",
                 "He makes a point with emphasis: counts on his fingers one, two, three in front of his chest, leans "
                 "slightly toward the camera on the key word, then an open-palms gesture and a firm small nod."),
}
SILENT = {
    "listen": "He listens to someone on a video call: calm breathing, small attentive nods, a slight head tilt, natural "
              "blinks, a warm closed-lip smile, hands relaxed together in front of him with tiny finger movements.",
    "think": "He thinks about a question before answering: looks up and slightly to the side, purses his lips a little, "
             "taps his chin once with one finger, then looks back to the lens with a small nod as if he has the answer.",
}
CLOSED = " His lips stay closed the whole time, he does not speak. Subtle, human, unhurried motion. Same person in every frame."


def tts(text, path):
    for attempt in range(6):  # the account allows few TTS requests at once: 409/429 -> wait and retry
        r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}?output_format=mp3_44100_128", timeout=120,
                       headers={"xi-api-key": key("ELEVENLAB_API_KEY")},
                       json={"text": text, "model_id": "eleven_multilingual_v2",
                             "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.45, "speed": 1.03}})
        if r.status_code not in (409, 429):
            break
        time.sleep(4 + 4 * attempt)
    r.raise_for_status(); path.write_bytes(r.content)


def upload(c, path, mime):
    u = c.post("https://api.pruna.ai/v1/files", headers={"apikey": PK}, files={"content": (path.name, path.open("rb"), mime)}).raise_for_status().json()
    return u.get("urls", {}).get("get") or u.get("url") or u.get("id")


def predict(c, model, inp, out):
    t0 = time.time()
    for attempt in range(2):
        r = c.post("https://api.pruna.ai/v1/predictions", headers={"apikey": PK, "Model": model, "Try-Sync": "true"}, json={"input": inp})
        if not r.is_error:
            break
        time.sleep(5)
    if r.is_error:
        return {"error": f"{r.status_code} {r.text[:200]}"}
    d = r.json()
    for _ in range(300):
        url = d.get("generation_url") or (d.get("output") if isinstance(d.get("output"), str) else None)
        if url:
            out.write_bytes(c.get(url, headers={"apikey": PK}).raise_for_status().content)
            return {"seconds": round(time.time() - t0, 1)}
        if d.get("status") in ("failed", "canceled", "cancelled") or not d.get("get_url"):
            return {"error": str(d)[:200]}
        time.sleep(3)
        d = {**d, **c.get(d["get_url"], headers={"apikey": PK}).json()}
    return {"error": "timeout"}


def job(c, img, state, out_dir):
    if state in SPEAK:
        text, act = SPEAK[state]
        mp3 = out_dir / f"{state}.mp3"; tts(text, mp3)
        res = predict(c, "p-video-2-pro-avatar", {"image": img, "audio": upload(c, mp3, "audio/mpeg"), "prompt": LOOK + act,
                                                  "resolution": "480p", "prompt_upsampling": False}, out_dir / f"{state}.mp4")
    else:
        res = predict(c, "p-video-2-pro-reference", {"prompt": LOOK + SILENT[state] + CLOSED, "first_frame_image": img,
                                                     "duration": 5, "resolution": "480p", "mode": "cost",
                                                     "aspect_ratio": "adaptive", "prompt_upsampler": "off"}, out_dir / f"{state}.mp4")
    return {"state": state, **res}


def main():
    src, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); out_dir.mkdir(parents=True, exist_ok=True)
    states = sys.argv[3:] or [*SPEAK, *SILENT]
    with httpx.Client(timeout=300) as c:
        img = upload(c, src, "image/jpeg")
        with cf.ThreadPoolExecutor(5) as ex:
            res = list(ex.map(lambda s: job(c, img, s, out_dir), states))
    for x in res:
        print(json.dumps(x))
    (out_dir / "clips_log.jsonl").open("a").write("".join(json.dumps(x) + "\n" for x in res))


main()

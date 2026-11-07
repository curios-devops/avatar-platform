"""Option 3b: PINOC splat close-up → Pruna p-video-2-pro-avatar 768p talking clip (one call, ≤ ~$0.18)."""
import asyncio, base64, json, subprocess, sys, time
import httpx
sys.path.insert(0, "/Users/mac/Documents/avatar-platform/backend")
from app.config import settings
from app.orchestrator.tts import stream_sentence_tts

D = "/Users/mac/Documents/avatar-platform/.triage/pinoc/opt3b"
SRC = "/Users/mac/Documents/avatar-platform/.triage/pinoc/10_opt3b_portrait.jpeg"
TEXT = "Hola, soy Mei. Encantada de conocerte. ¿Empezamos?"
PROMPT = "The woman talks to the camera in a calm, friendly way. Static camera, plain studio background."
KEY = settings.PRUNA_API_KEY
MAX_S, PRICE = 4.6, 0.04


def dur(path):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]))


async def upload(c, path, mime):
    r = await c.post("https://api.pruna.ai/v1/files", headers={"apikey": KEY},
                     files={"content": (path.rsplit("/", 1)[1], open(path, "rb"), mime)})
    r.raise_for_status(); u = r.json()["urls"]
    return u.get("get") or next(iter(u.values()))


async def main():
    audio = b"".join([base64.b64decode(ch.audio_b64) async for ch in stream_sentence_tts(TEXT)])
    open(f"{D}/audio.mp3", "wb").write(audio)
    secs = dur(f"{D}/audio.mp3")
    print(f"audio {secs:.2f}s → est ${secs * PRICE:.3f}")
    if secs > MAX_S:
        sys.exit("audio too long, not calling Pruna")
    # 1440x1838 screenshot → centred 9:16 crop
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", SRC, "-vf", "crop=ih*9/16:ih,scale=768:-2", "-q:v", "2",
                    f"{D}/portrait.jpg"], check=True)
    t0 = time.time()
    async with httpx.AsyncClient(timeout=120) as c:
        img, aud = await upload(c, f"{D}/portrait.jpg", "image/jpeg"), await upload(c, f"{D}/audio.mp3", "audio/mpeg")
        r = await c.post("https://api.pruna.ai/v1/predictions",
                         headers={"apikey": KEY, "Model": "p-video-2-pro-avatar", "Try-Sync": "true"},
                         json={"input": {"image": img, "audio": aud, "prompt": PROMPT, "resolution": "768p"}})
        if r.status_code >= 400:
            sys.exit(f"pruna {r.status_code}: {r.text[:400]}")
        data = r.json()
        for _ in range(300):
            url = data.get("generation_url") or (data.get("output") if isinstance(data.get("output"), str) else None)
            if url:
                v = await c.get(url, headers={"apikey": KEY}); v.raise_for_status()
                open(f"{D}/pruna_pro_768p.mp4", "wb").write(v.content)
                break
            if data.get("status") in ("failed", "canceled", "cancelled"):
                sys.exit(f"pruna failed: {str(data)[:400]}")
            await asyncio.sleep(2)
            data = {**data, **(await c.get(data["get_url"], headers={"apikey": KEY})).json()}
        else:
            sys.exit("pruna timeout")
    out = {"text": TEXT, "audio_s": round(secs, 2), "est_usd": round(secs * PRICE, 3), "wall_s": round(time.time() - t0, 1)}
    json.dump(out, open(f"{D}/run.json", "w"), indent=1); print(out)

asyncio.run(main())

"""Three short ElevenLabs clips WITH character timestamps, for method C and the live-mode replay.

Uses the endpoint the product would use for timed visemes (`stream/with-timestamps`), the product model
(eleven_v4_turbo, no audio tags so the alignment is only the spoken text) and three of MEYA's own voices.
Saves, per clip, the mp3, the merged alignment and the stream as it arrived (chunk sizes, alignment per chunk and
arrival time in ms), which `index.html` replays in live mode. Hard cap: 3 requests per run, and it refuses to run
again if the clips already exist. The key is read from backend/.env and never printed.

    python3 lab/arena5/lipsync/fetch_timed.py
"""
import base64, json, pathlib, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ENV = HERE.parents[2] / "backend/.env"
CLIPS = [  # id, language, voice (from ManyMe/digital-humans/*.json), text
    ("nova_es_t", "es", "U9tZtg3uJtVgXPkvosWR", "¡Hola! Pregúntame lo que quieras sobre el espacio."),
    ("hana_es_t", "es", "UOxKeHS7lixzgw35mtAR", "¿Te cuento un cuento? Primero dime tu nombre."),
    ("imani_en_t", "en", "hHjbwzYZW17oh0p05AKv", "Hi, I'm Imani. What would you like to understand today?"),
]
MODEL = "eleven_v4_turbo"


def key():
    for line in ENV.read_text().splitlines():
        if line.startswith("ELEVENLAB_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ELEVENLAB_API_KEY not in backend/.env")


def get(path, k):
    req = urllib.request.Request("https://api.elevenlabs.io/v1" + path, headers={"xi-api-key": k})
    return json.load(urllib.request.urlopen(req, timeout=30))


def main():
    out = HERE / "clips"
    out.mkdir(exist_ok=True)
    if all((out / f"{c[0]}.json").exists() for c in CLIPS):
        raise SystemExit("clips already fetched; delete clips/*_t.* to fetch again")
    k = key()
    before = get("/user/subscription", k).get("character_count")
    for n, (cid, lang, voice, text) in enumerate(CLIPS):
        if n >= 3:
            break
        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream/with-timestamps"
               "?output_format=mp3_44100_128")
        body = json.dumps({"text": text, "model_id": MODEL,
                           "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"xi-api-key": k, "Content-Type": "application/json"})
        t0 = time.time()
        audio, chunks = b"", []
        chars, starts, ends = [], [], []
        with urllib.request.urlopen(req, timeout=60) as resp:
            for raw in resp:
                line = raw.strip()
                if not line:
                    continue
                obj = json.loads(line)
                b = base64.b64decode(obj.get("audio_base64") or "")
                a = obj.get("alignment") or {}
                chunks.append({"arrival_ms": round((time.time() - t0) * 1000), "bytes": len(b),
                               "n_chars": len(a.get("characters") or [])})
                audio += b
                chars += a.get("characters") or []
                starts += a.get("character_start_times_seconds") or []
                ends += a.get("character_end_times_seconds") or []
        (out / f"{cid}.mp3").write_bytes(audio)
        json.dump({"id": cid, "lang": lang, "text": text, "model": MODEL, "voice": voice,
                   "alignment": {"characters": chars, "character_start_times_seconds": starts,
                                 "character_end_times_seconds": ends},
                   "stream": chunks}, open(out / f"{cid}.json", "w"), ensure_ascii=False, indent=1)
        print(cid, f"{len(audio)} bytes, {len(chunks)} chunks, {len(chars)} chars aligned, "
              f"first chunk {chunks[0]['arrival_ms'] if chunks else '-'} ms")
    after = get("/user/subscription", k).get("character_count")
    print("characters billed:", (after - before) if isinstance(before, int) and isinstance(after, int) else "unknown")


if __name__ == "__main__":
    main()

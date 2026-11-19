"""Nico's four voice lines (2026-11-19): ElevenLabs stream/with-timestamps, exactly as lab/arena5/lipsync/fetch_timed.py
(eleven_v4_turbo, no audio tags, mp3 44.1 kHz 128 kbps, character alignment + stream log), voice Liam (premade,
"young American, social media creator"). Nico is an AI character and says so; his home is Sol Harbor, an invented
coastal city. Each line's laugh ("Ha ha") is marked in the JSON as `laughs` (start, duration in s of heard audio, from the
alignment), which the puppet page turns into its laugh channel. Writes ../lipsync/clips/nico_*.{mp3,json}; refuses to
run again once they exist; prints the characters billed. The key is read from backend/.env and never printed.

    python3 lab/arena5/puppet/nico_voice.py
"""
import base64, json, pathlib, re, time, urllib.request

HERE = pathlib.Path(__file__).resolve().parent
ENV = HERE.parents[2] / "backend/.env"
OUT = HERE.parent / "lipsync" / "clips"
VOICE = "TX3LPaxmHKxFdv7VOQHJ"  # Liam, ElevenLabs premade: young, American, confident, social media
MODEL = "eleven_v4_turbo"
CLIPS = [
    ("nico_en_1", "en", "Yo, what's up, Sol Harbor! Nico here, your favorite AI, so I have zero excuses for crashing. "
                        "Ha ha! Quick tip: park the getaway car facing the exit. Trust me."),
    ("nico_en_2", "en", "Real talk: stop driving into the ocean. The jet ski is right there, man. Stick around and I'll "
                        "show you where."),
    ("nico_es_1", "es", "¡Qué onda, Sol Harbor! Soy Nico, una IA con muy buen gusto. Tip rápido: guarda el coche antes "
                        "de la misión. De nada, bro."),
    ("nico_es_2", "es", "Sí, ya sé: otra vez perdiste la moto en el puerto. Tranqui, en treinta segundos te enseño dónde "
                        "reaparece."),
]


def key():
    for line in ENV.read_text().splitlines():
        if line.startswith("ELEVENLAB_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ELEVENLAB_API_KEY not in backend/.env")


def get(path, k):
    req = urllib.request.Request("https://api.elevenlabs.io/v1" + path, headers={"xi-api-key": k})
    return json.load(urllib.request.urlopen(req, timeout=30))


def laughs(text, starts, ends):
    out = []
    for m in re.finditer(r"\b[Hh]a(?:,? ha)+\b[!.]?", text):
        out.append({"at": round(starts[m.start()], 3), "dur": round(max(0.9, ends[m.end() - 1] - starts[m.start()] + 0.5), 3)})
    return out


def main():
    OUT.mkdir(exist_ok=True)
    if all((OUT / f"{c[0]}.json").exists() for c in CLIPS):
        raise SystemExit("clips already fetched; delete clips/nico_* to fetch again")
    k = key()
    before = get("/user/subscription", k).get("character_count")
    for cid, lang, text in CLIPS:
        url = (f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/stream/with-timestamps"
               "?output_format=mp3_44100_128")
        body = json.dumps({"text": text, "model_id": MODEL,
                           "voice_settings": {"stability": 0.45, "similarity_boost": 0.75}}).encode()
        req = urllib.request.Request(url, data=body, method="POST",
                                     headers={"xi-api-key": k, "Content-Type": "application/json"})
        t0 = time.time()
        audio, chunks, chars, starts, ends = b"", [], [], [], []
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
        (OUT / f"{cid}.mp3").write_bytes(audio)
        lg = laughs(text, starts, ends) if "".join(chars) == text else []
        json.dump({"id": cid, "lang": lang, "text": text, "model": MODEL, "voice": VOICE, "voice_name": "Liam",
                   "laughs": lg, "alignment": {"characters": chars, "character_start_times_seconds": starts,
                                               "character_end_times_seconds": ends},
                   "stream": chunks}, open(OUT / f"{cid}.json", "w"), ensure_ascii=False, indent=1)
        print(cid, f"{len(audio)} bytes, {len(chars)} chars aligned, {ends[-1] if ends else 0:.1f} s, laughs {lg}")
    after = get("/user/subscription", k).get("character_count")
    print("characters billed:", (after - before) if isinstance(before, int) and isinstance(after, int) else "unknown")


if __name__ == "__main__":
    main()

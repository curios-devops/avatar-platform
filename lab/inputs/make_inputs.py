"""Benchmark inputs, identical for every engine: a portrait and a ~12 s line in the being's own voice.

  imani : one of MEYA's beings (her film portrait, her ElevenLabs voice).
  noa   : our new companion, created the way MEYA creates a being: described -> drawn by the runtime's image model.
  nueva : the upload case. A licensed stock photo (Pexels, as if a person uploaded it) -> MEYA's image model turns
          it into a being's portrait (OpenAI images/edits, the runtime's model) -> an ElevenLabs voice -> the same line.

Writes lab/inputs/<case>.png (1024 square) and <case>.wav (16 kHz mono), plus prep.json with times and costs.
Keys from backend/.env, never printed.  Run: backend/.venv/bin/python lab/inputs/make_inputs.py [--only imani|nueva]
"""
import json, pathlib, subprocess, sys, time

import httpx

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
ENV = dict(l.split("=", 1) for l in (ROOT / "backend/.env").read_text().splitlines() if "=" in l and not l.lstrip().startswith("#"))
key = lambda k: ENV.get(k, "").strip().strip('"')
EL = key("ELEVENLABS_API_KEY") or key("ELEVENLAB_API_KEY")

CASES = {
    "imani": dict(
        photo=pathlib.Path("/Users/mac/Documents/avatar-platform/.triage/landing/film/doctora_real.jpg"),
        voice="hHjbwzYZW17oh0p05AKv", settings=dict(stability=0.6, similarity_boost=0.8, style=0.25, speed=0.88),
        line="[calmly] Hola, soy Imani. Vamos a mirar tus resultados con calma. El colesterol salió en doscientos "
             "cuarenta, un poco alto, pero tiene solución. Te explico qué significa y qué puedes hacer desde hoy."),
    "noa": dict(
        generate=("Photorealistic portrait of Noa, an original MEYA companion: a woman in her mid twenties with long "
                  "straight hair dyed a vivid deep teal-violet, soft natural makeup, light freckles, warm grey-green eyes, "
                  "a relaxed kind half smile with lips closed. She wears a soft oversized cream knit cardigan over a plain "
                  "white tee. Cosy bedroom at night behind her, warm string lights and a bedside lamp softly out of focus. "
                  "Head and shoulders, facing the camera, looking into the lens, natural soft light, shot on 50mm. "
                  "No text, no logos, not a real or famous person."),
        voice="p5EUznrYaWnafKvUkNiR", settings=dict(stability=0.5, similarity_boost=0.8, style=0.4, speed=0.98),
        line="[warmly] ¡Hola! Qué bien que viniste, de verdad. Soy Noa. Me encanta cuando la noche se pone tranquila y "
             "podemos hablar de lo que sea: música, ideas raras o cómo te fue hoy. Cuéntame, ¿cómo estás?"),
    "nueva": dict(
        upload=pathlib.Path("/Users/mac/Documents/ManyMe/apps/web/public/media/humans/sofia.jpg"),
        prompt=("Turn this photo into the portrait of a MEYA digital being, keeping the same person and face: "
                "photorealistic editorial portrait, natural soft light, head and shoulders, facing the camera, looking "
                "into the lens, mouth closed, neutral friendly expression, plain softly lit background. No text, no logos."),
        voice="JddqVF50ZSIR7SRbJE6u", settings=dict(stability=0.5, similarity_boost=0.8, style=0.35, speed=1.0),
        line="[warmly] ¡Hola! Soy Sofía, encantada. Acabo de nacer en MEYA a partir de una foto, y ya puedo hablar "
             "contigo. Cuéntame, ¿qué te gustaría que hiciéramos juntas hoy?"),
}


def square(src: pathlib.Path, dst: pathlib.Path):
    """Centre square crop biased to the top (faces sit high in a portrait), 1024 px."""
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-vf",
                    "crop='min(iw,ih)':'min(iw,ih)':(iw-min(iw\\,ih))/2:(ih-min(iw\\,ih))/5,scale=1024:1024", str(dst)], check=True)


def portrait_from_upload(case: dict, dst: pathlib.Path) -> dict:
    t0 = time.time()
    up = HERE / "nueva_upload.png"
    square(case["upload"], up)
    with httpx.Client(timeout=240) as c:
        r = c.post("https://api.openai.com/v1/images/edits", headers={"Authorization": f"Bearer {key('OPENAI_API_KEY')}"},
                   data={"model": "gpt-image-2.6-sunburst", "prompt": case["prompt"], "size": "1024x1024", "quality": "medium", "n": "1"},
                   files={"image[]": (up.name, up.read_bytes(), "image/png")})
        if r.is_error:
            raise RuntimeError(f"images/edits HTTP {r.status_code}: {r.text[:300]}")
        d = r.json()
    import base64
    dst.write_bytes(base64.b64decode(d["data"][0]["b64_json"]))
    usage = d.get("usage", {})
    return {"seconds": round(time.time() - t0, 1), "usage": usage}


def portrait_from_text(case: dict, dst: pathlib.Path) -> dict:
    """MEYA's create flow: the being is described, the runtime's image model draws it."""
    import base64
    t0 = time.time()
    r = httpx.post("https://api.openai.com/v1/images/generations", headers={"Authorization": f"Bearer {key('OPENAI_API_KEY')}"}, timeout=240,
                   json={"model": "gpt-image-2.6-sunburst", "prompt": case["generate"], "size": "1024x1024", "quality": "medium", "n": 1})
    if r.is_error:
        raise RuntimeError(f"images/generations HTTP {r.status_code}: {r.text[:300]}")
    d = r.json()
    dst.write_bytes(base64.b64decode(d["data"][0]["b64_json"]))
    return {"seconds": round(time.time() - t0, 1), "usage": d.get("usage", {})}


def speak(case: dict, dst: pathlib.Path) -> dict:
    t0 = time.time()
    r = httpx.post(f"https://api.elevenlabs.io/v1/text-to-speech/{case['voice']}?output_format=pcm_16000",
                   headers={"xi-api-key": EL}, timeout=120,
                   json={"text": case["line"], "model_id": "eleven_v4_turbo", "voice_settings": case["settings"]})
    r.raise_for_status()
    raw = dst.with_suffix(".pcm"); raw.write_bytes(r.content)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "s16le", "-ar", "16000", "-ac", "1", "-i", str(raw), str(dst)], check=True)
    raw.unlink()
    return {"seconds": round(time.time() - t0, 1), "audio_s": round(len(r.content) / 32000, 2), "characters": len(case["line"])}


def main():
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    prep_file = HERE / "prep.json"
    prep = json.loads(prep_file.read_text()) if prep_file.exists() else {}
    for name, case in CASES.items():
        if only and name != only:
            continue
        png, wav = HERE / f"{name}.png", HERE / f"{name}.wav"
        p = {}
        if "generate" in case:
            p["portrait"] = portrait_from_text(case, png)
        elif "upload" in case:
            p["portrait"] = portrait_from_upload(case, png)
        else:
            square(case["photo"], png)
        p["voice"] = speak(case, wav)
        prep[name] = p
        print(name, json.dumps(p))
    prep_file.write_text(json.dumps(prep, indent=2))


main()

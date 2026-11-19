"""Arena 5 puppet, pilot 2: full-face expression keyframes with FLUX.2 [klein] 4B (Apache-2.0, mflux q4) on the Mac.

    <mflux-venv>/bin/python -u lab/arena5/puppet/kf.py serve           # loads the model once, works through the queue
    <mflux-venv>/bin/python lab/arena5/puppet/kf.py add portrait semi_m [seed ...]
    <mflux-venv>/bin/python lab/arena5/puppet/kf.py add kf film_w [pose ...] [--seed N] [--tag r2]
    <mflux-venv>/bin/python lab/arena5/puppet/kf.py quit
    (kfrun.sh wraps serve with caffeinate and the watchdog)

serve keeps one process with the model in memory and takes jobs from chars/.queue/*.json in name order, one at a time,
with a cool-down and a heat / memory-pressure check between jobs; it exits on `quit` or after 25 idle minutes.
Every finished job appends a line to chars/<id>/kf/gen.jsonl (prompt, seed, size, seconds, MLX peak), the record of
how each keyframe was made (PNGs are not in git).

portrait  text-to-image, a new original character (no reference image, no brand, no real person).
kf        image edit: the character's portrait.png is the only reference image; the prompt keeps identity, hair,
          clothes, background, light and framing and changes the whole face to one key pose.
          -> chars/<id>/kf/raw/<pose>[_<tag>].png; kfprep.py gates, colour-matches and adopts them.
"""
import gc
import json
import os
import pathlib
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CHARS = HERE / "chars"
QUEUE = CHARS / ".queue"
MODEL = "mflux-community/flux2-klein-4b-mflux-q4"
STEPS = 4

NEW_COMMON = ("Front-facing head-and-shoulders portrait, the face centred and filling the upper middle of the square "
              "frame, head straight and level, eyes open looking straight into the camera, neutral relaxed "
              "expression, lips gently closed. Plain backdrop with no objects, no text, no logo, no watermark, no hands. "
              "Natural asymmetry in the face; no airbrushed plastic skin; not a glossy generic render.")

# style, seed, portrait prompt, age wrinkles in expressions, what a mouth is made of in this style
PEOPLE = {
    "film_w": ("film", 11, None, False, None),  # existing portrait (gen.py); in her twenties: no wrinkles
    "semi_m": ("semi", 41,
               "Semi-realistic painted game illustration, an original character. Cel-painted shading in flat planes with "
               "visible brush strokes, ink-defined lines on the eyelids, nose, lips and jaw, a strong warm orange key light "
               "from the left and a cool blue rim light on the right edge of the face and hair, shadows slightly "
               "desaturated. A man of about 40 with warm olive skin, short dark brown hair greying at the temples, a short "
               "dark stubble beard, dark brown eyes, a slightly crooked nose and one eyebrow a little higher than the "
               "other, visible crow's feet at the outer eye corners and faint lines from the nose to the mouth corners, "
               "wearing a rust-red henley shirt. Backdrop: muted dark teal. " + NEW_COMMON,
               True, "painted lips and individual painted teeth with ink outlines, matching the illustration"),
    "clay_w": ("clay", 51,
               "Photograph of a real plasticine stop-motion animation puppet on a small studio set, an original "
               "character. A woman made of modelling clay: matte clay skin in a warm peach tone with visible fingerprints "
               "and small sculpting tool marks, slightly uneven hand-made surfaces, chunky sculpted dark auburn hair in "
               "a short bob made of clay strands, round glossy bead eyes with painted brown irises, a small rounded nose, "
               "wearing a mustard clay sweater with sculpted knit grooves. Smooth young clay face with no wrinkles. A "
               "small softbox key light from the upper left and a warm practical light from the right, shallow depth of "
               "field, a real macro photograph of a physical puppet. Backdrop: a painted pale blue card. " + NEW_COMMON,
               False, "sculpted from the same matte plasticine as the face, lips as simple rounded shapes, teeth as small "
                      "separate hand-pressed plasticine pieces"),
    "crochet_m": ("crochet", 61,
                  "Photograph of a real handmade amigurumi crochet doll, an original character. A man made entirely of "
                  "crocheted cotton yarn: visible rows of single-crochet stitches, slightly fuzzy yarn, warm light-brown "
                  "yarn for the skin, short hair made of dark brown yarn loops, a short beard of brushed dark yarn, black "
                  "safety-bead eyes, eyebrows embroidered in dark thread, a small round crocheted nose, a simple mouth "
                  "embroidered in dark red yarn, wearing a crocheted forest-green sweater. No wrinkles. Soft daylight "
                  "from a window on the left, a real photograph of a physical toy. Backdrop: plain warm grey fabric. "
                  + NEW_COMMON,
                  False, "a shape cut from dark red felt and stitched onto the crochet face, with small separate white "
                         "felt teeth stitched in where teeth show"),
}

# nico (2026-11-19): 4:5, head to mid-chest (SIZE=768x960 portrait, 640x800 edits); about 30, so only light crow's feet
# and laugh lines, and only when smiling; a closed-mouth listening smirk as a 9th key pose
NICO_FRAME = ("Front-facing portrait framed from just above the top of the head down to mid-chest, the head centred in "
              "the upper part of the tall frame, head straight and level, shoulders square to the camera, eyes open "
              "looking straight into the camera, lips closed. Plain dark backdrop with no objects, no text, no letters, "
              "no logo, no watermark, no title, no hands. Natural asymmetry in the face; no airbrushed plastic skin; "
              "not a glossy generic render.")
# round 2 of the portrait: round 1 (seeds 71-74, gen.jsonl) read as clean vector comic art with thin even lines
NICO = ("Hand-painted crime-game loading-screen artwork, an original character. Gouache-like painting with thick visible "
        "brush strokes and posterized colour planes in the skin, hair and t-shirt, cel-painted shadows, black ink lines "
        "of varying weight on the eyelids, nose, lips, jaw and t-shirt folds, not vector art and not a flat comic, a "
        "gritty painted texture, a strong warm "
        "orange key light from the left and a cool cyan-blue rim light on the right edge of the face, hair and shoulder, "
        "high contrast. A handsome American man of about 30 with the face of a social-media star: fair light skin with "
        "a little pink in the cheeks, a strong defined square jaw and chin, a few days of dark stubble, short dark-brown "
        "hair slightly messy on top, light blue eyes, thick straight dark eyebrows, a straight nose, one eyebrow a "
        "little higher than the other. A confident relaxed look with a hint of mischief in the eyes, the mouth closed "
        "with the corners very slightly up. Smooth skin with no wrinkles. He wears a plain white crew-neck cotton "
        "t-shirt with no print and no logo, and a silver metal chain necklace with chunky links lying clearly visible "
        "on the t-shirt below the collar. Backdrop: plain dark charcoal blue. " + NICO_FRAME)
PEOPLE["nico"] = ("semi", 76, NICO, True, "painted lips and individual softly shaded teeth, separated by thin gaps, with fine "
                                           "ink outlines, matching the illustration")

KEEP = ("Keep exactly the same character and identity, the same face shape, hair, clothes, background, lighting, colours "
        "and rendering style, the same camera, framing, head size and head position, still looking into the camera. "
        "Change only the facial expression: ")
POSES = {
    "talk_mid": "the mouth is slightly open as in the middle of a spoken word, lips parted a little, the edges of the upper "
                "front teeth just visible, the jaw relaxed.",
    "aa": "the mouth is open wide as when saying 'ah': the jaw drops so the chin moves clearly down, the upper front teeth "
          "are visible as separate individual teeth, the lower teeth are mostly hidden behind the lower lip, the tongue "
          "rests low in a dark mouth.",
    "OU": "the lips are rounded and pushed forward into a small round 'oo' shape with a small dark opening, the jaw "
          "slightly lowered, the cheeks a little drawn in.",
    # round 3 for semi_m: its talk_mid showed both rows of teeth clenched, a grimace in every consonant
    "talk_soft": "the lips parted a little as in the middle of a spoken word, a small dark gap between the lips with only "
                 "the lower edge of the upper front teeth showing, the lower teeth hidden, the jaw slightly lowered, "
                 "relaxed lips, no smile, no clenched teeth.",
    # round 2 (2026-11-19): stronger wording where round 1 kept teeth or stayed a grin
    "OU2": "the lips are puckered and pushed forward into a small tight round 'oo' shape as when whistling, the mouth "
           "corners drawn in toward the centre, a small dark round opening in the middle, no teeth visible, no smile.",
    "MBP2": "the lips are pressed firmly together as when saying 'm', slightly flattened and rolled in, the mouth fully "
            "closed, no teeth visible, no smile.",
    "laugh2": "a big open-mouthed laugh in the middle of a loud 'ha!': the jaw dropped so the chin moves down and the mouth "
              "is open wide and tall, the whole upper row of individual teeth visible with natural separation and soft "
              "shading and a hint of gum above them, the lower row partly hidden by the lower lip, the dark mouth and "
              "the tongue visible below the upper teeth, the cheeks pushed up, the eyes narrowed into happy crescents "
              "with the lower eyelids raised.",
    "E": "a warm smile while saying 'eh': the mouth corners pulled up and back, the whole upper row of front teeth visible "
         "as separate individual teeth with thin dark gaps and soft shading, the lower teeth barely visible, the cheeks "
         "slightly raised.",
    "MBP": "the lips are pressed firmly together as when saying 'm', slightly flattened and rolled in, the mouth closed.",
    "laugh": "laughing openly and genuinely: the mouth wide open, the upper row of individual teeth fully visible with "
             "natural separation and soft shading, the lower row partly hidden by the lower lip, a hint of gum above the "
             "upper teeth, the cheeks pushed up, the eyes narrowed into happy crescents with the lower eyelids raised, "
             "the head tilted back very slightly.",
    # nico: the 9th key pose (listening) and a grin for E
    "OU3": "the lips gently rounded into a small 'oo' shape as in the word 'you', a small dark round opening, the lips "
           "only slightly forward, not puckered, not pouting, no teeth visible, no smile, the jaw slightly lowered.",
    "smirk": "a confident closed-mouth smirk while listening: the lips stay closed with no teeth showing, one mouth "
             "corner pulled up a little higher than the other, the cheeks lifted a little, the eyes slightly narrowed "
             "with amusement, the eyebrows relaxed, a charming, slightly mischievous look.",
    "E2": "a wide charismatic grin while saying 'eh': the mouth corners pulled up and back, the whole upper row of front "
          "teeth visible as separate individual teeth with thin gaps and soft shading, the lower teeth barely visible, "
          "the cheeks raised, the eyes a little narrowed with confidence and a hint of mischief.",
    "rest": "a neutral relaxed expression, lips gently closed, eyes open looking into the camera.",
    "blink": "both eyes fully closed in a relaxed blink, the eyelids smooth and soft, the mouth closed and neutral exactly "
             "as before.",
}
AGE = {"talk_soft": " The faint lines from the nose to the mouth corners stay visible.",
       "laugh2": " Deep nasolabial folds from the nose to the mouth corners and clear crow's feet wrinkles fanning out "
                  "from the outer eye corners, as on a man of forty.",
       "E": " Crow's feet wrinkles at the outer eye corners and the lines from the nose to the mouth corners deepen.",
       "laugh": " Deep nasolabial folds from the nose to the mouth corners and clear crow's feet wrinkles fanning out from "
                "the outer eye corners, as on a man of forty.",
       "talk_mid": " The faint lines from the nose to the mouth corners stay visible."}
AGE_NICO = {"E2": " Only light crow's feet at the outer eye corners and soft laugh lines beside the mouth appear with the "
                   "grin, as on a man of thirty; the forehead and the rest of the face stay smooth.",
            "laugh2": " Only a few light crow's feet at the outer eye corners and soft laugh lines beside the mouth, as on "
                      "a man of thirty; no lines on the forehead, no creases between the eyebrows or on the nose.",
            "smirk": " A faint laugh line at the raised mouth corner and a hint of crow's feet, as on a man of thirty; the "
                     "forehead stays smooth."}
# round 2 (nico): round 1's "smooth skin" line shaved off his stubble and airbrushed the face in talk, OU and MBP;
# the laugh got forehead lines; OU2 became duck lips
SMOOTH30 = " No wrinkles, as on a man of thirty."
NICO_KEEP = (" Keep the same few days of dark stubble on the jaw, chin, cheeks and upper lip, and the same painted "
             "brush-stroke texture and ink lines. The silver chain necklace and the plain white t-shirt stay exactly the "
             "same and fully visible.")

# round 3 for clay (2026-11-19): rounds 1 and 2 kept a realistic human face under clay hair, so every expression came
# with human creases (crow's feet, forehead folds); a simpler stop-motion head, and expressions made of simple shapes
CLAY3 = ("Photograph of a real plasticine stop-motion animation puppet on a small studio set, an original character. "
         "A woman puppet head sculpted in modelling clay with simplified rounded cartoon features: a smooth rounded "
         "peach clay face with visible fingerprints and small sculpting tool marks, a small round nose, large round "
         "glossy bead eyes with painted brown irises, simple sculpted eyebrows as two clay strips, simple clay lips, "
         "chunky sculpted dark auburn hair in a short bob made of thick clay strands, a mustard clay sweater with "
         "sculpted knit grooves. No realistic skin detail and no wrinkles. A small softbox key light from the upper "
         "left and a warm practical light from the right, shallow depth of field, a real macro photograph of a "
         "physical puppet. Backdrop: a painted pale blue card. " + NEW_COMMON)
CLAY_POSES = {
    "E3": "a happy smile while saying 'eh': the clay mouth corners pushed up, a row of small separate upper clay teeth "
          "visible, the cheeks two smooth round balls pushed up, no creases.",
    "laugh3": "a big open-mouthed laugh: the jaw dropped and the mouth open wide and tall, a row of small separate upper "
              "clay teeth with a hint of pink clay gum above them, the lower teeth partly hidden by the lower lip, a dark "
              "mouth and a simple clay tongue, the eyes closed as two simple upward-curved lines, the cheeks two smooth "
              "round balls pushed up, no creases and no wrinkles anywhere.",
    "aa3": "the mouth open wide as when saying 'ah': the jaw dropped so the chin moves down, small separate upper clay "
           "teeth, a dark mouth and a simple clay tongue, the eyebrows relaxed, no creases.",
}
# round 2 (2026-11-19): round 1 turned the clay face into smooth human skin and grey lip blobs, and frowned
MATERIAL = {"clay": " Keep the material exactly as in the reference: matte plasticine with visible fingerprints and small "
                    "sculpting tool marks all over the face, hand-made and slightly uneven, never smooth human skin. The "
                    "eyebrows stay relaxed, not frowning.",
            "crochet": " Keep the material exactly as in the reference: every surface is crocheted yarn with visible "
                       "stitches, the eyes stay black beads, the nose stays a small crocheted ball, the beard stays yarn. "
                       "The eyebrows stay relaxed, not frowning."}
LIPS = {"semi": "painted with ink outlines, matching the illustration", "clay": "a sculpted plasticine lip piece",
        "crochet": "a felt lip piece stitched onto the crochet face"}
SMOOTH = " The face stays smooth, with no wrinkles and no folds."


def kf_prompt(cid: str, pose: str) -> str:
    style, _, _, aged, mouth = PEOPLE[cid]
    p = KEEP + (CLAY_POSES.get(pose) or POSES[pose.rstrip("3")] if style == "clay" and pose.endswith("3") else POSES[pose])
    if cid == "nico":
        p += AGE_NICO.get(pose, "" if pose == "blink" else SMOOTH30) + NICO_KEEP
    elif aged:
        p += AGE.get(pose, "")
    elif style in ("clay", "crochet"):
        p += SMOOTH + MATERIAL[style]
    if mouth and pose not in ("blink", "MBP", "MBP2", "OU2", "talk_soft", "smirk", "OU3"):  # round 1 put teeth into MBP and OU through this line
        p += f" The mouth is {mouth}."
    elif mouth and pose in ("MBP2", "OU2", "smirk", "OU3"):
        p += f" The lips are {LIPS[style]}, with no teeth showing."
    return p


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def calm() -> bool:
    t = sh("pmset -g therm")
    hot = "CPU_Speed_Limit" in t and not any(l.strip().endswith("= 100") for l in t.splitlines() if "CPU_Speed_Limit" in l)
    level = int(sh("sysctl -n kern.memorystatus_vm_pressure_level").strip() or 1)
    free = int(sh("memory_pressure | awk -F': ' '/free percentage/{gsub(\"%\",\"\",$2); print $2}'").strip() or 100)
    return not hot and level <= 1 and free >= 25


def now() -> str:
    return time.strftime("%H:%M:%S")


def add(argv):
    QUEUE.mkdir(parents=True, exist_ok=True)
    kind, cid, rest = argv[0], argv[1], argv[2:]
    tag = seed = None
    if "--tag" in rest:
        i = rest.index("--tag"); tag = rest[i + 1]; rest = rest[:i] + rest[i + 2:]
    if "--seed" in rest:
        i = rest.index("--seed"); seed = int(rest[i + 1]); rest = rest[:i] + rest[i + 2:]
    size = os.environ.get("SIZE", "768")  # N or WxH
    size = [int(x) for x in size.split("x")] if "x" in size else int(size)
    jobs = []
    if kind == "portrait":
        for s in rest or [PEOPLE[cid][1]]:
            jobs.append({"kind": kind, "char": cid, "pose": "portrait", "seed": int(s), "size": size,
                         "prompt": CLAY3 if cid == "clay_w" and int(s) >= 53 else PEOPLE[cid][2], "ref": None, "out": f"chars/{cid}/portrait_s{s}.png"})
    else:
        for pose in rest or list(POSES):
            sfx = f"_{tag}" if tag else ""
            jobs.append({"kind": kind, "char": cid, "pose": pose.rstrip("0123456789"), "seed": seed or PEOPLE[cid][1], "size": size, "tag": tag,
                         "prompt": kf_prompt(cid, pose), "ref": f"chars/{cid}/kf/ref.png",
                         "out": f"chars/{cid}/kf/raw/{pose}{sfx}.png"})
    for j in jobs:
        name = f"{time.time_ns()}_{j['char']}_{j['pose']}.json"
        (QUEUE / name).write_text(json.dumps(j))
    print(f"queued {len(jobs)}")


def serve():
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    status = CHARS / ".status"
    QUEUE.mkdir(parents=True, exist_ok=True)
    while not calm():
        print(f"{now()} waiting before loading: heat or memory", flush=True)
        time.sleep(30)
    status.write_text("loading")
    import mlx.core as mx
    from mflux.models.common.config.model_config import ModelConfig
    from mflux.models.common.vae.tiling_config import TilingConfig
    from mflux.models.flux2.variants import Flux2Klein, Flux2KleinEdit
    mx.set_cache_limit(int(os.environ.get("MLX_CACHE_MB", "256")) << 20)
    idle_since, done = time.time(), 0
    while True:
        if (QUEUE / "quit").exists():
            (QUEUE / "quit").unlink()
            break
        batch = [(p, json.loads(p.read_text())) for p in sorted(QUEUE.glob("*.json"))]
        batch = [(p, j) for p, j in batch if (j["ref"] is None) == (batch[0][1]["ref"] is None)] if batch else batch
        if not batch:
            status.write_text("idle")
            if time.time() - idle_since > 25 * 60:
                print(f"{now()} idle 25 min: exiting", flush=True)
                break
            time.sleep(3)
            continue
        # one batch: weights (memory-mapped, ~1 s), every prompt encoded, the 4B text encoder dropped before denoising
        status.write_text("loading")
        t0 = time.time()
        # text-to-image (new portraits) and edit (keyframes) are separate classes over the same weights
        cls = Flux2KleinEdit if batch[0][1]["ref"] else Flux2Klein
        model = cls(model_config=ModelConfig.flux2_klein_4b(), model_path=MODEL)
        model.tiling_config = TilingConfig()  # tiled VAE encode/decode: the 5.3 GB peak of an edit tripped the watchdog
        enc = {}
        for _, j in batch:
            if j["prompt"] not in enc:
                e = model._encode_prompt_pair(prompt=j["prompt"], negative_prompt=None, guidance=1.0)
                mx.eval(e[0], e[1])
                enc[j["prompt"]] = e
        model._encode_prompt_pair = lambda *, prompt, negative_prompt, guidance: enc[prompt]
        model.text_encoder = None
        gc.collect()
        mx.clear_cache()
        print(f"{now()} batch of {len(batch)}: model + {len(enc)} prompts in {time.time() - t0:.0f} s, MLX active "
              f"{mx.get_active_memory() / 2**30:.1f} GB after dropping the text encoder", flush=True)
        for jf, j in batch:
            status.write_text("cooling")
            while not calm():
                print(f"{now()} waiting: heat or memory", flush=True)
                time.sleep(20)
            out = HERE / j["out"]
            out.parent.mkdir(parents=True, exist_ok=True)
            status.write_text(f"running {j['out']}")
            t1 = time.time()
            mx.reset_peak_memory()
            try:
                kw = {"image_paths": [str(HERE / j["ref"])]} if j["ref"] else {}
                img = model.generate_image(seed=j["seed"], prompt=j["prompt"], num_inference_steps=STEPS,
                                           width=j["size"][0] if isinstance(j["size"], list) else j["size"],
                                           height=j["size"][1] if isinstance(j["size"], list) else j["size"], guidance=1.0, **kw)
                img.save(path=str(out), export_json_metadata=False)
            except Exception as exc:  # one bad job must not end the queue
                print(f"{now()} FAILED {j['out']}: {exc!r}", flush=True)
                jf.unlink()
                continue
            secs = time.time() - t1
            peak = mx.get_peak_memory() / 2**30
            rec = {**j, "model": MODEL, "steps": STEPS, "seconds": round(secs, 1), "mlx_peak_gb": round(peak, 2),
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            log = CHARS / j["char"] / "kf" / "gen.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            with log.open("a") as f:
                f.write(json.dumps(rec) + "\n")
            jf.unlink()
            done += 1
            print(f"{now()} done {j['out']} in {secs:.0f} s, MLX peak {peak:.1f} GB", flush=True)
            gc.collect()
            mx.clear_cache()
            status.write_text("cooling")
            time.sleep(int(os.environ.get("COOL_DOWN", "15")))
        del model, enc
        gc.collect()
        mx.clear_cache()
        idle_since = time.time()
    status.unlink(missing_ok=True)
    print(f"{now()} KF_DONE {done} jobs", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "serve":
        serve()
    elif cmd == "add":
        add(sys.argv[2:])
    elif cmd == "quit":
        QUEUE.mkdir(parents=True, exist_ok=True)
        (QUEUE / "quit").write_text("")
    else:
        raise SystemExit("serve | add portrait|kf <char> ... | quit")

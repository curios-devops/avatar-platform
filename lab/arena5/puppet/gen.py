"""Arena 5, styled portrait puppet: the images, made once per character with Z-Image-Turbo on the Mac (mflux q4).

    <mflux-venv>/bin/python lab/arena5/puppet/gen.py portraits [id[@seed] ...]
    <mflux-venv>/bin/python lab/arena5/puppet/gen.py mouths <char> [shape ...]
    (run.sh wraps both with the watchdog watch.sh)

portraits  6 original characters, 2 per MEYA style, 1024x1024, front-facing, neutral, mouth closed. Writes
           chars/<id>/portrait_s<seed>.png; the chosen one is copied to portrait.png by hand after looking at it.
mouths     image-to-image on the mouth: the browser puppet renders the character at each mouth shape with the drawn
           inner mouth (chars/<char>/pre/<shape>.png, geometry already right); a crop around the mouth is refined at
           512x512 with a low strength and a mouth-only prompt, then pasted back with a feathered edge
           -> chars/<char>/mouth/<shape>.png. The geometry stays the puppet's, so the sprite lines up with the warp.

Same pattern as lab/backgrounds/gen.py (CLAUDE.md: one heavy task at a time): one process, model loaded once, every
prompt encoded first and the text encoder dropped, one image at a time with a cool-down, --low-ram, MLX cache 1 GB,
pauses on heat or memory pressure, HF_HUB_OFFLINE. STATUS file chars/.status for watch.sh.
"""
import gc
import json
import os
import pathlib
import subprocess
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")
HERE = pathlib.Path(__file__).resolve().parent
CHARS = HERE / "chars"

COMMON = ("Front-facing head-and-shoulders portrait, the face centred and filling the upper middle of the frame, head "
          "straight and level, eyes open looking straight into the camera, neutral relaxed expression, lips gently "
          "closed, both ears symmetric, even soft lighting on both sides of the face, plain smooth softly lit "
          "studio backdrop with no objects, no text, no logo, no watermark, no hands.")

STYLE = {
    "film": ("A character from a modern 3D animated feature film, original design. Stylised but believable human "
             "proportions, large expressive eyes that stay in proportion, soft smooth skin with gentle subsurface glow, "
             "finely sculpted hair with individual strands, cinematic warm key light and a soft rim light, high quality "
             "3D render."),
    "game": ("A realistic AAA video game character, original design, cinematic real-time render. Adult, realistic "
             "anatomy and skin pores, detailed hair cards, filmic lighting with a soft key light and subtle rim light, "
             "high-end game cinematic quality."),
    "anime": ("A 3D anime style character, original design, cel-shaded 3D render in a modern Japanese anime look. "
              "Large expressive glossy eyes with bright highlights, clean stylised skin, sculpted stylised hair "
              "locks with sharp highlights, soft colourful lighting."),
}

PEOPLE = {
    "film_w": ("film", 11, "A young adult woman in her twenties with warm light-brown skin and a few faint freckles, dark brown "
               "curly hair gathered in a loose high bun with soft curls framing her face, big warm brown eyes, "
               "full natural eyebrows, wearing a mustard yellow knit sweater. Backdrop: soft warm beige."),
    "film_m": ("film", 12, "A man in his thirties with deep dark-brown skin, short black tightly coiled hair with a neat fade, "
               "a short well-groomed black beard, big kind dark eyes, wearing a teal denim jacket over a white "
               "t-shirt. Backdrop: soft pale blue-grey."),
    "game_w": ("game", 21, "A woman in her early thirties of East Asian descent with light skin, straight black hair tied "
               "back in a low ponytail with a few loose strands, dark brown eyes, defined eyebrows, wearing a dark "
               "olive utility jacket with a high collar. Backdrop: neutral mid grey."),
    "game_m": ("game", 22, "A man in his forties with fair skin and light freckles, short auburn hair combed back, a "
               "trimmed auburn beard, light grey-green eyes, faint lines at the eyes, wearing a charcoal crew-neck "
               "wool sweater. Backdrop: dark blue-grey."),
    "anime_w": ("anime", 31, "A woman in her late twenties, clearly adult, with fair skin, long silver-lavender hair with "
                "straight bangs and two long front locks, large teal eyes, small silver earrings, wearing a cream "
                "knit cardigan over a pale blue shirt, office casual. Backdrop: soft pastel pink."),
    "anime_m": ("anime", 32, "A man around thirty, clearly adult, with tan brown skin, a defined jaw and light stubble, "
                "short spiky dark brown hair with warm orange highlights, amber eyes, wearing a dark green bomber "
                "jacket over a white t-shirt. Backdrop: soft pastel mint."),
}

# Mouth shapes refined by image-to-image. What the prompt says the mouth does; the rest of the face stays.
MOUTHS = {
    "aa": "The mouth is open wide as when saying 'ah': the jaw dropped, upper front teeth visible, the tongue resting low and "
          "pink inside a dark mouth.",
    "E": "The mouth is half open and stretched wide as when saying 'eh': the upper and lower front teeth visible, a narrow dark "
         "gap between them.",
    "O": "The lips are rounded into an open 'o' shape, pushed slightly forward, a dark round opening with the tip of the "
         "upper teeth just visible.",
    "FF": "The lower lip is tucked lightly under the upper front teeth as when saying 'f': the upper teeth rest on the lower "
          "lip, the mouth almost closed.",
    "mid": "The lips are slightly parted as in mid speech, the edges of the upper front teeth just visible in a small dark gap.",
}
MOUTH_STRENGTH = float(os.environ.get("MOUTH_STRENGTH", "0.42"))
COOL_DOWN = int(os.environ.get("COOL_DOWN", "60"))
# 1024 tripped the watchdog (pressure "warn" during denoising) with the usual apps open on 2026-11-16: 896 by default.
SIZE = int(os.environ.get("SIZE", "896"))


def now() -> str:
    return time.strftime("%H:%M:%S")


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def calm() -> bool:
    t = sh("pmset -g therm")
    hot = "CPU_Speed_Limit" in t and not any(l.strip().endswith("= 100") for l in t.splitlines() if "CPU_Speed_Limit" in l)
    level = int(sh("sysctl -n kern.memorystatus_vm_pressure_level").strip() or 1)
    free = int(sh("memory_pressure | awk -F': ' '/free percentage/{gsub(\"%\",\"\",$2); print $2}'").strip() or 100)
    return not hot and level <= 1 and free >= 30


def portrait_prompt(pid: str) -> str:
    style, _, who = PEOPLE[pid]
    return f"{STYLE[style]} {who} {COMMON}"


def mouth_prompt(char: str, shape: str) -> str:
    style, _, who = PEOPLE[char]
    return (f"{STYLE[style]} Close-up of the lower half of the face of the same character: {who.split('.')[0]}. "
            f"{MOUTHS[shape]} Same skin, same lip colour, same lighting, natural believable teeth.")


def mouth_box(char: str):
    """Square crop around the mouth in portrait pixels: nose tip to below the chin, centred on the lips."""
    lm = json.loads((CHARS / char / "landmarks.json").read_text())["points"]
    xs = [lm[i][0] for i in (61, 291, 152, 2)]
    ys = [lm[i][1] for i in (2, 152)]
    cx, cy = (lm[61][0] + lm[291][0]) / 2, (lm[13][1] + lm[14][1]) / 2
    side = max(max(xs) - min(xs), (max(ys) - min(ys))) * 1.5  # room for the dropped jaw of "aa"
    half, cy = int(side / 2), cy + side * 0.1
    return int(cx) - half, int(cy) - half, int(cx) + half, int(cy) + half


def main():
    mode = sys.argv[1]
    CHARS.mkdir(exist_ok=True)
    status = CHARS / ".status"
    jobs = []  # (prompt, seed, size, image_path, strength, out, paste_box)
    if mode == "portraits":
        for spec in sys.argv[2:] or list(PEOPLE):
            pid, _, seed = spec.partition("@")
            seed = int(seed or PEOPLE[pid][1])
            out = CHARS / pid / f"portrait_s{seed}.png"
            out.parent.mkdir(exist_ok=True)
            jobs.append((portrait_prompt(pid), seed, SIZE, None, None, out, None))
    elif mode == "mouths":
        char = sys.argv[2]
        from PIL import Image
        box = mouth_box(char)
        (CHARS / char / "mouth").mkdir(exist_ok=True)
        for shape in sys.argv[3:] or list(MOUTHS):
            pre = CHARS / char / "pre" / f"{shape}.png"
            crop = CHARS / char / "mouth" / f"_in_{shape}.png"
            Image.open(pre).convert("RGB").crop(box).resize((512, 512), Image.LANCZOS).save(crop)
            jobs.append((mouth_prompt(char, shape), PEOPLE[char][1], 512, str(crop), MOUTH_STRENGTH,
                         CHARS / char / "mouth" / f"{shape}.png", (str(pre), box)))
    else:
        raise SystemExit("mode: portraits | mouths")
    print(f"{now()} {mode}: {len(jobs)} images", flush=True)
    while not calm():
        print(f"{now()} waiting before loading: heat or memory", flush=True)
        time.sleep(30)

    status.write_text("loading")
    import mlx.core as mx
    from mflux.callbacks.callback_manager import CallbackManager
    from mflux.models.z_image.cli.z_image_turbo_generate import ZImageTurboCommand, build_parser

    sys.argv = ["gen", "--prompt", "x", "--width", "1024", "--height", "1024", "--steps", "9", "--seed", "1", "--model",
                "mflux-community/z-image-turbo-mflux-q4", "--base-model", "z-image-turbo", "--low-ram",
                "--mlx-cache-limit-gb", "1", "--vae-tiling"]
    args = build_parser().parse_args()
    t_all = t0 = time.time()
    model = ZImageTurboCommand.load(args)
    encoded = {}
    for prompt, *_ in jobs:
        if prompt not in encoded:
            enc = model._encode_prompts(prompt=prompt, negative_prompt=None, guidance=0.0)
            mx.eval(enc[0])
            encoded[prompt] = enc
    model._encode_prompts = lambda *, prompt, negative_prompt, guidance: encoded[prompt]
    model.text_encoder = None
    gc.collect()
    mx.clear_cache()
    args.seed = [1, 2]  # more than one seed: the low-RAM saver keeps the transformer between images
    saver = CallbackManager.register_callbacks(args=args, model=model, latent_creator=ZImageTurboCommand.latent_creator)
    print(f"{now()} model loaded and {len(encoded)} prompts encoded in {time.time() - t0:.0f} s", flush=True)

    for k, (prompt, seed, size, image_path, strength, out, paste) in enumerate(jobs):
        status.write_text("cooling")
        while not calm():
            print(f"{now()} waiting: heat or memory", flush=True)
            time.sleep(30)
        status.write_text(f"running {out.parent.name}/{out.name}")
        t0 = time.time()
        args.width = args.height = size
        args.image_path, args.image_strength = image_path, strength
        try:
            image = ZImageTurboCommand.generate(model, args, seed, prompt)
            image.save(path=str(out), export_json_metadata=False)
        except Exception as exc:  # one bad image must not end the queue
            print(f"{now()} FAILED {out}: {exc!r}", flush=True)
            continue
        if paste:  # back into the full pre-render with a feathered square edge
            from PIL import Image, ImageFilter
            pre, box = paste
            full = Image.open(pre).convert("RGB")
            side = box[2] - box[0]
            patch = Image.open(out).convert("RGB").resize((side, side), Image.LANCZOS)
            mask = Image.new("L", (side, side), 0)
            m = int(side * 0.12)
            mask.paste(255, (m, m, side - m, side - m))
            mask = mask.filter(ImageFilter.GaussianBlur(m / 2.5))
            full.paste(patch, box[:2], mask)
            full.save(out)
        gc.collect()
        mx.clear_cache()
        peak = mx.get_peak_memory() / 2**30 if hasattr(mx, "get_peak_memory") else -1
        print(f"{now()} done {out.parent.name}/{out.name} in {time.time() - t0:.0f} s, MLX peak {peak:.1f} GB", flush=True)
        if k < len(jobs) - 1:
            status.write_text("cooling")
            time.sleep(COOL_DOWN)
    status.unlink(missing_ok=True)
    print(f"{now()} GEN_DONE total {time.time() - t_all:.0f} s", flush=True)


if __name__ == "__main__":
    main()

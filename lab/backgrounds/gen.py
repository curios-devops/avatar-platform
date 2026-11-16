"""MEYA backgrounds, step 1: our own Meet-style scenes with Z-Image-Turbo on the Mac (mflux, pre-quantized q4).

    <mflux-venv>/bin/python lab/backgrounds/gen.py <out_dir> [id ...]      (run_all.sh wraps this with the watchdog)

No ids: every scene that has no PNG yet, in catalogue order, so a stopped run resumes. With ids: those, redone.
AFTER_EACH="command" in the environment runs after each finished image (run_all.sh publishes to the web there).

ONE process for the whole queue (CLAUDE.md: one heavy task at a time, never heat the Mac):
- The model loads once. Loading is the only memory spike (about 7 GB for 20 s on a 16 GB Mac); a process per image
  repeated that spike 13 times and the watchdog stopped it (2026-11-15).
- All the prompts are encoded first and the text encoder is dropped, so denoising runs with the transformer alone
  (peak MLX memory about 4.7 GB) and MLX keeps at most 1 GB of freed buffers (3 GB kept the Mac at pressure "warn").
- One image at a time, a 60 s cool-down after each, and a pause whenever macOS reports heat or memory pressure.
- 1024x768 (4:3): a 4:5 portrait and a 16:9 call both crop it from the centre; it sits behind a person, so it is
  published at 1280x960 without anyone noticing, and the smaller canvas keeps memory down.
- HF_HUB_OFFLINE: nothing is downloaded again by surprise.
STATUS file (<out_dir>/.status): "loading" while the model loads, then "running <id>" / "cooling"; watch.sh reads it.
"""
import gc
import os
import pathlib
import subprocess
import sys
import time

os.environ.setdefault("HF_HUB_OFFLINE", "1")

# Never mention a person, not even "where a person will sit": the model then draws one (first try, 2026-11-15).
COMMON = ("An empty, unoccupied scene with no people and no figures at all, photographed straight on from seated eye "
          "level, like the wall behind someone on a video call. The middle of the frame is open and plain; furniture "
          "and objects stay at the left and right edges, nothing in the foreground. Slightly out of focus, shallow "
          "depth of field, photorealistic, natural colours, no text, no logos, no watermark.")

SCENES = {
    # Nuevos (invierno)
    "snow-chalet": "The living room of a modern alpine chalet, light timber walls and ceiling beams, a wide picture window showing snow-covered peaks and pine trees under a pale blue sky, an armchair with a wool throw at the far left, bright cold daylight mixed with warm lamps.",
    "snowy-living": "A bright Scandinavian living room on a snowy day, large windows with soft falling snow and white garden trees outside, a light grey armchair with a knitted blanket at the far left, a floor lamp glowing warm at the right, white walls and pale oak floor.",
    "christmas-hearth": "A cosy living room at Christmas, a lit brick fireplace with a pine garland and stockings, a decorated Christmas tree with warm white lights to one side, candles and wrapped gifts, soft golden evening glow.",
    # Profesional
    "shelves-plants": "A home office wall of built-in light oak bookshelves, neatly arranged books, ceramics and trailing green plants, a warm white wall, soft afternoon daylight.",
    "tech-desk": "A modern tech workspace, a charcoal wall with floating shelves of cameras, headphones and gadgets at the left, a desk with a large blurred monitor and a slim lamp at the right, soft warm-white and cool blue accent lights, evening.",
    "study-library": "The library of a private study, floor-to-ceiling dark walnut bookcases full of leather-bound books, a brass library lamp glowing, a green leather armchair to one side, warm classic light.",
    # Casa acogedora
    "home-sofa": "A cosy home office corner with a soft beige sofa and cushions against the wall at the left, a round side table with a plant at the right, framed abstract prints on a warm white wall, sheer linen curtains, gentle morning daylight.",
    "home-desk": "A home study by a window, a light wooden desk with a small lamp and a potted plant against a warm white wall at the right, a simple shelf with a few books at the left, linen curtains, soft daylight.",
    "pool-terrace": "A sunny terrace of a modern white house with a turquoise swimming pool behind, a wooden deck, two sun loungers and potted palms to the sides, clear blue sky, bright summer light.",
    # Lugares
    "camping": "A campsite in a pine forest beside a mountain lake at golden hour, a canvas tent pitched to one side, a small campfire at the other side, light mist over the water, mountains in the distance.",
    # Fantasia
    "space-station": "The interior of a bright futuristic space station module, white curved panels with soft blue strip lights, a large round window to one side showing the Earth from orbit, cinematic science fiction.",
    "mars": "The surface of Mars seen from inside a habitat's panoramic window, red dunes and rocky ridges under a butterscotch sky, a small rover far away, the white edge of the habitat interior with soft lights.",
    "moon": "The surface of the Moon, grey regolith and soft craters, the Earth rising over the horizon in a black starry sky, a lunar lander far to one side, crisp sunlight with long shadows.",
}
SEED, COOL_DOWN = 7, 60


def now() -> str:
    return time.strftime("%H:%M:%S")


def sh(cmd: str) -> str:
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def calm() -> bool:
    hot = "CPU_Speed_Limit" in (t := sh("pmset -g therm")) and not any(l.strip().endswith("= 100") for l in t.splitlines() if "CPU_Speed_Limit" in l)
    level = int(sh("sysctl -n kern.memorystatus_vm_pressure_level").strip() or 1)
    free = int(sh("memory_pressure | awk -F': ' '/free percentage/{gsub(\"%\",\"\",$2); print $2}'").strip() or 100)
    return not hot and level <= 1 and free >= 30


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    status = out / ".status"
    ids = sys.argv[2:] or [i for i in SCENES if not (out / f"{i}.png").exists()]
    if unknown := [i for i in ids if i not in SCENES]:
        raise SystemExit(f"unknown scenes: {unknown}")
    if not ids:
        print("nothing to generate\nGEN_DONE", flush=True)
        return
    print(f"{now()} queue: {' '.join(ids)}", flush=True)
    while not calm():
        print(f"{now()} waiting before loading: heat or memory", flush=True)
        time.sleep(30)

    status.write_text("loading")
    import mlx.core as mx
    from mflux.callbacks.callback_manager import CallbackManager
    from mflux.models.z_image.cli.z_image_turbo_generate import ZImageTurboCommand, build_parser

    sys.argv = ["gen", "--prompt", "x", "--width", "1024", "--height", "768", "--steps", "9", "--seed", str(SEED), "--model",
                "mflux-community/z-image-turbo-mflux-q4", "--base-model", "z-image-turbo", "--low-ram", "--mlx-cache-limit-gb", "1"]
    args = build_parser().parse_args()
    t0 = time.time()
    model = ZImageTurboCommand.load(args)
    # Every prompt now, then the text encoder goes: the queue denoises with the transformer alone.
    encoded = {}
    for i in ids:
        prompt = f"{SCENES[i]} {COMMON}"
        enc = model._encode_prompts(prompt=prompt, negative_prompt=None, guidance=0.0)
        mx.eval(enc[0])
        encoded[prompt] = enc
    model._encode_prompts = lambda *, prompt, negative_prompt, guidance: encoded[prompt]
    model.text_encoder = None
    gc.collect()
    mx.clear_cache()
    args.seed = [SEED, SEED]  # more than one "seed": the low-RAM saver then keeps the transformer between images
    saver = CallbackManager.register_callbacks(args=args, model=model, latent_creator=ZImageTurboCommand.latent_creator)
    print(f"{now()} model loaded and {len(ids)} prompts encoded in {time.time() - t0:.0f} s", flush=True)

    for i in ids:
        status.write_text("cooling")
        while not calm():
            print(f"{now()} waiting: heat or memory", flush=True)
            time.sleep(30)
        status.write_text(f"running {i}")
        t0 = time.time()
        target = out / f"{i}.png"
        target.unlink(missing_ok=True)
        try:
            image = ZImageTurboCommand.generate(model, args, SEED, f"{SCENES[i]} {COMMON}")
            image.save(path=str(target), export_json_metadata=False)
        except Exception as exc:  # one bad image must not end the queue
            print(f"{now()} FAILED {i}: {exc!r}", flush=True)
            continue
        gc.collect()
        mx.clear_cache()
        print(f"{now()} done {i} in {time.time() - t0:.0f} s ({saver.memory_stats() if saver else ''})", flush=True)
        if os.environ.get("AFTER_EACH"):
            subprocess.run(os.environ["AFTER_EACH"], shell=True, capture_output=True)
        status.write_text("cooling")
        time.sleep(COOL_DOWN)
    status.unlink(missing_ok=True)
    print("GEN_DONE", flush=True)


if __name__ == "__main__":
    main()

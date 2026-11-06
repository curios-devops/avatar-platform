"""Text → creature spec with Claude, for tripo/viewer/kit.js (three.js, CPU, no Tripo).

    python tripo/creature_llm.py gen    <name> "<brief>"        → tripo/specs/<name>.json
    python tripo/creature_llm.py refine <name> <sheet.jpg> [stats.json] [--note "…"]
                                                               → the model looks at the render of its
                                                                 own spec and writes a corrected one;
                                                                 --note adds a person's feedback
    --model sonnet|haiku|opus (default sonnet)   --budget 0.25 (USD per day, default 0.25)

Every call is logged with its tokens and cost to .triage/tripo_capy/llm/costs.jsonl. Before each
call the day's spend plus the worst case of that call (all max_tokens at the output price) must fit
in the budget, or the script stops without calling. The key is CLAUDE_API_KEY in
avatar-platform/backend/.env.
"""
import base64
import json
import pathlib
import re
import sys
import time

import anthropic

HERE = pathlib.Path(__file__).resolve().parent
SPECS = HERE / "specs"
OUT = pathlib.Path("/Users/mac/Documents/avatar-platform/.triage/tripo_capy/llm")
ENV = pathlib.Path("/Users/mac/Documents/avatar-platform/backend/.env")
MODELS = {  # id, USD per million input / output tokens
    "haiku": ("claude-haiku-5-5", 0.10, 0.50),
    "sonnet": ("claude-sonnet-5-5", 2.0, 10.0),
    "opus": ("claude-opus-5-5", 4.0, 20.0),
}
MAX_TOKENS = 12000

SYSTEM = """You design 3D characters as JSON specs for a three.js kit. The kit fuses your shapes into ONE
smooth skinned mesh (signed distance fields joined with a smooth union, then meshed), colours it,
adds a procedural fur texture, attaches small rigid parts and plays your animation clips.

COORDINATES: metres, +Y up, ground at y = 0, the creature FACES +Z. Its LEFT side is +X, its right
side is -X. Describe the creature in its rest pose, in world coordinates. Size: about 0.6-1.0 m long
or tall. Everything is placed absolutely (not relative to bones).

SPEC (output exactly one JSON object):
{
  "name": "capybara_quad",
  "detail": 12000,                       // triangle target for the fused body (6000-20000)
  "palette": { "fur": "#8b5a3c", "belly": "#b98b66", "dark": "#4a3127" },   // name → hex
  "fur": { "scale": 3, "contrast": 0.35, "bump": 0.03 }, // strand texture: tiles per metre (2-5),
                                                         // albedo variation 0.2-0.45, bump 0-0.06
  "bones": [                             // pivots (joint positions) in world space; one root
    { "name": "hips", "parent": null, "pos": [0, 0.42, -0.1] },
    { "name": "thigh_L", "parent": "hips", "pos": [0.16, 0.34, -0.28], "mirror": true }
  ],
  "shapes": [                            // the body; each shape belongs to one bone
    { "type": "ellipsoid", "center": [x,y,z], "radii": [rx,ry,rz], "rot": [rxDeg,ryDeg,rzDeg],
      "bone": "hips", "color": "fur", "blend": 0.06 },
    { "type": "capsule", "a": [x,y,z], "b": [x,y,z], "r": 0.07, "r2": 0.05,   // r at a, r2 at b
      "bone": "shin_L", "color": "fur", "blend": 0.03, "mirror": true },
    { "type": "box", "center": [..], "size": [sx,sy,sz], "round": 0.03, "rot": [..], ... },
    { "op": "carve", "type": "ellipsoid", ... , "blend": 0.01 },   // subtracts (mouth line, nostril dents)
    { "op": "paint", "type": "ellipsoid", ..., "color": "belly", "soft": 0.04, "opacity": 0.9 }
                                         // recolours the surface inside it; no geometry
  ],
  "parts": [                             // separate rigid meshes, moved by their bone
    { "type": "ellipsoid", "center": [..], "radii": [..], "rot": [..], "bone": "head",
      "material": "eye" | "gloss" | "matte", "color": "#1a1210", "mirror": true },
    { "type": "cone", "center": [..], "r": 0.01, "length": 0.03, "rot": [..], ... },   // claws, teeth
    { "type": "box", "center": [..], "size": [..], ... }
  ],
  "clips": {
    "walk": { "period": 0.9, "tracks": [
      { "bone": "thigh_L", "ch": "rx", "amp": 0.45, "phase": 0, "harmonic": 1, "wave": "sin", "bias": 0 }
    ] }
  }
}

RULES
- "mirror": true on a bone, shape or part also creates its mirror at -X, swapping the name tokens
  L and R (thigh_L → thigh_R, and its bone/parent references too). Write left parts (+X) only.
- Union shapes must overlap their neighbours (no floating pieces): the mesh must be ONE piece.
  "blend" is the smooth-union radius in metres: 0.04-0.08 between big masses, 0.01-0.03 for
  details that must stay crisp (ears, toes, snout edge). Blobby shapes need a bigger blend.
- Smallest shape that survives meshing is about 2 cm; anything smaller goes in "parts".
- Eyes, nostrils, claws and teeth are "parts". Sink parts slightly into the body surface (about a
  third of their size inside) so they never float.
- Each shape's "bone" decides how it moves. Put a shape on the bone it hangs from: a thigh on the
  thigh bone, a shin on the knee bone, a foot on the ankle/knee bone. Bones sit at the joints.
- Body colour comes from the shapes' "color"; use "paint" volumes for belly, snout, inner ears,
  paws, so colour changes do not need extra geometry.
- The feet must reach y = 0 in the rest pose (the kit lifts the lowest point onto the ground).

ANIMATION
- Each track adds  bias + amp * wave(2*pi*harmonic*t/period + phase°)  to one channel of one bone:
  ch = rx | ry | rz (radians, around world-aligned axes through the bone's pivot) or px | py | pz
  (metres, added to the rest position). harmonic must be a whole number (the clip loops).
  wave: sin | abs (|sin|, bob twice per stride) | pos (max(0,sin)) | neg (min(0,sin)).
- Signs: +rx swings a limb that points DOWN towards -Z (backwards) and tips a forward-pointing head
  DOWN; -rx swings a downward limb forward. +ry turns the head to the creature's left (+X).
  +rz rolls towards -X (the creature's right side goes down).
- Rotations of a parent carry its children (hips → thighs → knees…). Keep limb swings within
  0.2-0.6 rad and knees bending in their natural direction (use pos/neg waves for knees).
- Quadruped walk: diagonal pairs move together (front-left with back-right), phase 0 and 180.
- Make clips readable but calm: bob 1-3 cm, head nod or turn 0.03-0.12 rad.

Think about proportions first (silhouette from the side and the front), then write the JSON.
Answer with the JSON only, inside one ```json block."""


def key():
    for line in ENV.read_text().splitlines():
        if line.startswith("CLAUDE_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("CLAUDE_API_KEY missing in backend/.env")


def spent_today():
    log, day = OUT / "costs.jsonl", time.strftime("%Y-%m-%d")
    if not log.exists():
        return 0.0
    rows = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    return sum(r["usd"] for r in rows if time.strftime("%Y-%m-%d", time.localtime(r["ts"])) == day)


def ask(content, label, model, budget):
    model_id, p_in, p_out = MODELS[model]
    parts = content if isinstance(content, list) else [{"type": "text", "text": content}]
    est_in = (len(SYSTEM) + sum(len(p.get("text", "")) for p in parts)) / 3 + 2000 * sum(p["type"] == "image" for p in parts)
    worst = (est_in * p_in + MAX_TOKENS * p_out) / 1e6
    spent = spent_today()
    if spent + worst > budget:
        raise SystemExit(f"budget: spent {spent:.3f} today + up to {worst:.3f} for this call > {budget} USD; not calling")
    client = anthropic.Anthropic(api_key=key())
    t0 = time.time()
    with client.messages.stream(model=model_id, max_tokens=MAX_TOKENS, system=SYSTEM,
                                messages=[{"role": "user", "content": content}],
                                extra_body={"output_config": {"effort": "low"}}) as s:
        msg = s.get_final_message()
    secs = time.time() - t0
    u = msg.usage
    usd = (u.input_tokens * p_in + u.output_tokens * p_out) / 1e6
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "costs.jsonl", "a") as f:  # logged before any parsing, so failed calls still count
        f.write(json.dumps({"label": label, "model": model_id, "in": u.input_tokens, "out": u.output_tokens,
                            "usd": round(usd, 4), "secs": round(secs, 1), "ts": time.time()}) + "\n")
    if msg.stop_reason not in ("end_turn", "stop_sequence"):
        raise SystemExit(f"stopped: {msg.stop_reason} after {usd:.3f} USD")
    text = "".join(b.text for b in msg.content if b.type == "text")
    m = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    spec = json.loads(m[-1] if m else text[text.index("{"): text.rindex("}") + 1])
    print(json.dumps({"label": label, "usd": round(usd, 4), "secs": round(secs, 1), "in": u.input_tokens,
                      "out": u.output_tokens, "shapes": len(spec.get("shapes", [])), "parts": len(spec.get("parts", []))}))
    return spec


def main():
    args = sys.argv[1:]
    opt = lambda flag, default: args.pop(args.index(flag) + 1) if flag in args else default  # noqa: E731
    note, model, budget = opt("--note", ""), opt("--model", "sonnet"), float(opt("--budget", 0.25))
    args = [a for a in args if a not in ("--note", "--model", "--budget")]
    cmd, name = args[0], args[1]
    SPECS.mkdir(exist_ok=True)
    path = SPECS / f"{name}.json"
    if cmd == "gen":
        brief = args[2]
        (SPECS / f"{name}.brief.txt").write_text(brief)
        spec = ask(brief, f"gen {name}", model, budget)
    elif cmd == "refine":
        args = args[2:]
        sheet = pathlib.Path(args[0])
        stats = pathlib.Path(args[1]).read_text() if len(args) > 1 else "{}"
        brief = (SPECS / f"{name}.brief.txt").read_text()
        old = path.read_text()
        n = len(list(SPECS.glob(f"{name}.v*.json")))
        (SPECS / f"{name}.v{n}.json").write_text(old)  # keep each round
        img = base64.standard_b64encode(sheet.read_bytes()).decode()
        spec = ask([
            {"type": "text", "text": f"BRIEF:\n{brief}\n\nYOUR CURRENT SPEC:\n```json\n{old}\n```\n\n"
                                     f"KIT STATS for it (pieces > 1 means floating shapes; lift is how far the "
                                     f"kit had to raise it to touch the ground):\n{stats}\n\n"
                                     "The image is the kit's render of that spec. Columns: front (yaw 0), its "
                                     "left side (yaw 90), 3/4 (yaw 40), back (yaw 180). Rows: rest pose, then "
                                     "two moments of each clip."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img}},
            {"type": "text", "text": "Judge it against the brief like an art director: silhouette, proportions, "
                                     "face (eyes, snout, ears), parts that float or sink, colours, and whether "
                                     "the clips read well without limbs passing through the body or the ground. "
                                     + (f"Feedback from the art director, which comes first: {note} " if note else "")
                                     + "List the 3-6 most important problems in one short paragraph, then write "
                                     "the complete corrected spec in one ```json block."},
        ], f"refine {name} r{n + 1}", model, budget)
    else:
        raise SystemExit(__doc__)
    path.write_text(json.dumps(spec, indent=1))
    print(path)


if __name__ == "__main__":
    main()

"""Same creature brief, OpenAI tiers instead of Claude: text only, no 3D.

    python tripo/creature_openai.py <spec_name> luna|sol|astra [...]   (--budget 0.10)

Sends the system prompt of creature_llm.py and the saved brief of <spec_name> to each tier, saves the
answer to tripo/specs/openai/<tier>_<spec_name>.json and checks it as text against the kit's format
(check() below). Before each call, the worst case (input estimate + max_completion_tokens at the
output price) plus what this run already spent must fit in --budget, or the call is skipped. Costs
go to .triage/tripo_capy/llm/costs.jsonl with the others. Keys: OPENAI_API_KEY (and OPENAI_ORG_ID /
OPENAI_PROJECT_ID if set) in avatar-platform/backend/.env.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request

import creature_llm as base

# USD per million input / output tokens: third-party lists checked 2026-11-06 (magora-systems,
# CloudZero); not OpenAI's own page, so treat the costs as estimates
TIERS = {"luna": ("gpt-6-luna", 0.10, 0.50), "sol": ("gpt-6.1-sol", 2.0, 10.0), "astra": ("gpt-6-astra", 10.0, 50.0)}
MAX_OUT = {"luna": 8000, "sol": 6000, "astra": 5000}  # includes reasoning tokens


def env():
    out = {}
    for line in base.ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"')
    return out


def call(tier, brief, spent, budget):
    model, p_in, p_out = TIERS[tier]
    est_in = (len(base.SYSTEM) + len(brief)) / 3.2
    worst = (est_in * p_in + MAX_OUT[tier] * p_out) / 1e6
    if spent + worst > budget:
        print(json.dumps({"tier": tier, "skipped": f"worst case {worst:.3f} + spent {spent:.3f} > budget {budget}"}))
        return None, 0.0
    e = env()
    headers = {"Authorization": f"Bearer {e['OPENAI_API_KEY']}", "Content-Type": "application/json"}
    if e.get("OPENAI_ORG_ID"):
        headers["OpenAI-Organization"] = e["OPENAI_ORG_ID"]
    if e.get("OPENAI_PROJECT_ID"):
        headers["OpenAI-Project"] = e["OPENAI_PROJECT_ID"]
    body = {"model": model, "reasoning_effort": "low", "max_completion_tokens": MAX_OUT[tier],
            "messages": [{"role": "system", "content": base.SYSTEM}, {"role": "user", "content": brief}]}
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", json.dumps(body).encode(), headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            res = json.loads(r.read())
    except urllib.error.HTTPError as err:
        print(json.dumps({"tier": tier, "http": err.code, "error": err.read()[:400].decode(errors="replace")}))
        return None, 0.0
    secs = time.time() - t0
    u = res["usage"]
    usd = (u["prompt_tokens"] * p_in + u["completion_tokens"] * p_out) / 1e6
    reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    with open(base.OUT / "costs.jsonl", "a") as f:
        f.write(json.dumps({"label": f"openai {tier}", "model": model, "in": u["prompt_tokens"], "out": u["completion_tokens"],
                            "reasoning": reasoning, "usd": round(usd, 4), "secs": round(secs, 1), "ts": time.time()}) + "\n")
    choice = res["choices"][0]
    return {"text": choice["message"].get("content") or "", "finish": choice.get("finish_reason"), "secs": round(secs, 1),
            "in": u["prompt_tokens"], "out": u["completion_tokens"], "reasoning": reasoning, "usd": round(usd, 4)}, usd


def check(text):
    """Static checks of a spec against the kit's format (what would break or look wrong in kit.js)."""
    issues, m = [], re.findall(r"```json\s*(\{.*?\})\s*```", text, re.S)
    raw = m[-1] if m else (text[text.find("{"): text.rfind("}") + 1] if "{" in text else "")
    try:
        spec = json.loads(raw)
    except ValueError as e:
        return None, {"json": f"invalid: {e}"}
    swap = lambda n: n and "_".join({"L": "R", "R": "L"}.get(t, t) for t in n.split("_"))  # noqa: E731
    bones = {}
    for b in spec.get("bones", []):
        bones[b["name"]] = b
        if b.get("mirror"):
            bones[swap(b["name"])] = {**b, "parent": swap(b.get("parent"))}
    roots = [n for n, b in bones.items() if not b.get("parent")]
    if len(roots) != 1:
        issues.append(f"{len(roots)} root bones")
    issues += [f"bone {n}: unknown parent {b['parent']}" for n, b in bones.items() if b.get("parent") and b["parent"] not in bones]
    pal = spec.get("palette", {})
    shapes = spec.get("shapes", [])
    need = {"ellipsoid": ["center", "radii"], "capsule": ["a", "b", "r"], "box": ["center", "size"]}
    low = []
    for i, s in enumerate(shapes + spec.get("parts", [])):
        kind = s.get("type")
        if kind not in need and not (kind == "cone" and s in spec.get("parts", [])):
            issues.append(f"#{i} unknown type {kind}")
            continue
        for k in need.get(kind, []):
            if k not in s:
                issues.append(f"#{i} {kind} missing {k}")
        if s.get("bone") and s["bone"] not in bones and swap(s["bone"]) not in bones:
            issues.append(f"#{i} unknown bone {s['bone']}")
        c = s.get("color")
        if c and not str(c).startswith("#") and c not in pal:
            issues.append(f"#{i} colour {c} not in palette")
        if (s.get("op") or "union") == "union" and s in shapes:
            if kind == "ellipsoid" and "center" in s and "radii" in s:
                low.append(s["center"][1] - s["radii"][1])
            elif kind == "capsule" and "a" in s and "b" in s:
                low.append(min(s["a"][1] - s["r"], s["b"][1] - s.get("r2", s["r"])))
    clips = spec.get("clips", {})
    for name, cl in clips.items():
        for t in cl.get("tracks", []):
            if t.get("bone") not in bones:
                issues.append(f"clip {name}: unknown bone {t.get('bone')}")
            if t.get("ch", "rx") not in ("rx", "ry", "rz", "px", "py", "pz"):
                issues.append(f"clip {name}: bad channel {t.get('ch')}")
            if float(t.get("harmonic", 1)) != int(float(t.get("harmonic", 1))):
                issues.append(f"clip {name}: non-integer harmonic")
    stats = {"shapes": len(shapes), "union": sum((s.get("op") or "union") == "union" for s in shapes),
             "paint": sum(s.get("op") == "paint" for s in shapes), "carve": sum(s.get("op") == "carve" for s in shapes),
             "parts": len(spec.get("parts", [])), "bones": len(bones), "clips": {k: len(v.get("tracks", [])) for k, v in clips.items()},
             "detail": spec.get("detail"), "min_y": round(min(low), 3) if low else None, "bytes": len(json.dumps(spec)),
             "issues": issues}
    return spec, stats


def main():
    args = sys.argv[1:]
    budget = float(args.pop(args.index("--budget") + 1)) if "--budget" in args else 0.10
    args = [a for a in args if a != "--budget"]
    name, tiers = args[0], args[1:]
    brief = (base.SPECS / f"{name}.brief.txt").read_text()
    outdir = base.SPECS / "openai"
    outdir.mkdir(exist_ok=True)
    spent, report = 0.0, {}
    ref = base.SPECS / f"{name}.v0.json"  # Claude's first answer to the same brief, for comparison
    if ref.exists():
        report["claude_opus_v0"] = check("```json\n" + ref.read_text() + "\n```")[1]
    for tier in tiers:
        res, usd = call(tier, brief, spent, budget)
        spent += usd
        if not res:
            continue
        spec, stats = check(res["text"])
        if spec:
            (outdir / f"{tier}_{name}.json").write_text(json.dumps(spec, indent=1))
        report[tier] = {**{k: v for k, v in res.items() if k != "text"}, **stats}
        print(json.dumps({"tier": tier, **report[tier]}))
    (outdir / f"report_{name}.json").write_text(json.dumps({"spent_usd": round(spent, 4), **report}, indent=1))
    print(json.dumps({"spent_usd": round(spent, 4)}))


if __name__ == "__main__":
    main()

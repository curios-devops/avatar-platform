"""Minimal Pruna client for the splat A/B: upload a file, run a prediction, download the output.

Uses PRUNA_K_API_KEY and falls back to PRUNA_API_KEY (both in backend/.env). Every call appends
its model, input and the x-cost header (when Pruna sends it) to <out>/costs.jsonl.

    python splat/pruna.py image --prompt "..." --aspect 9:16 --out seed.jpg
    python splat/pruna.py video --image seed.jpg --prompt "..." --duration 10 --out orbit.mp4
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[2] / "avatar-platform" / "backend" / ".env"
API = "https://api.pruna.ai/v1"


def keys() -> list[str]:
    env = dict(os.environ)
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip("'\""))
    return [env[k] for k in ("PRUNA_K_API_KEY", "PRUNA_API_KEY") if env.get(k)]


def log_cost(out: Path, entry: dict) -> None:
    with open(out.parent / "costs.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def predict(model: str, inp: dict, out: Path, timeout_s: int = 600) -> Path:
    last = None
    for i, key in enumerate(keys()):
        try:
            return _predict(key, model, inp, out, timeout_s, "K" if i == 0 else "fallback")
        except httpx.HTTPStatusError as e:  # auth or quota problem: try the fallback key
            last = e
            print(f"key {i} failed: {e.response.status_code} {e.response.text[:200]}", file=sys.stderr)
            if e.response.status_code not in (401, 402, 403, 429):
                raise
    raise RuntimeError(f"all Pruna keys failed: {last}")


def _predict(key: str, model: str, inp: dict, out: Path, timeout_s: int, which: str) -> Path:
    t0 = time.time()
    with httpx.Client(timeout=httpx.Timeout(120)) as c:
        r = c.post(f"{API}/predictions", headers={"apikey": key, "Model": model, "Try-Sync": "true"},
                   json={"input": inp})
        r.raise_for_status()
        data, cost = r.json(), r.headers.get("x-cost")
        while not (data.get("generation_url") or isinstance(data.get("output"), str)):
            if data.get("status") in ("failed", "canceled", "cancelled"):
                raise RuntimeError(f"Pruna failed: {data.get('error') or data}")
            if time.time() - t0 > timeout_s:
                raise TimeoutError("Pruna: not ready in time")
            time.sleep(3)
            r = c.get(data["get_url"], headers={"apikey": key})
            r.raise_for_status()
            data = {**data, **r.json()}
            cost = cost or r.headers.get("x-cost")
        url = data.get("generation_url") or data["output"]
        blob = c.get(url, headers={"apikey": key})
        blob.raise_for_status()
        out.write_bytes(blob.content)
    secs = round(time.time() - t0, 1)
    log_cost(out, {"model": model, "key": which, "input": {k: v for k, v in inp.items() if k != "image"},
                   "x_cost": cost, "seconds": secs, "file": out.name})
    print(f"{model}: {out} in {secs}s (x-cost {cost})")
    return out


def upload(path: Path) -> str:
    for key in keys():
        r = httpx.post(f"{API}/files", headers={"apikey": key}, files={"content": path.open("rb")}, timeout=120)
        if r.status_code < 400:
            return r.json()["urls"]["get"]
    r.raise_for_status()
    raise RuntimeError("upload failed")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["image", "video"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--aspect", default="9:16")
    ap.add_argument("--image", type=Path)
    ap.add_argument("--model")
    ap.add_argument("--duration", type=int, default=10)
    ap.add_argument("--resolution", default="720p")
    ap.add_argument("--draft", action="store_true")
    a = ap.parse_args()
    a.out.parent.mkdir(parents=True, exist_ok=True)
    if a.kind == "image":
        predict(a.model or "p-image", {"prompt": a.prompt, "aspect_ratio": a.aspect}, a.out)
    else:
        inp = {"prompt": a.prompt, "image": upload(a.image), "duration": a.duration,
               "aspect_ratio": a.aspect, "resolution": a.resolution}
        if a.draft:
            inp["draft"] = True
        predict(a.model or "p-video", inp, a.out)


if __name__ == "__main__":
    main()

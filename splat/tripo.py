"""Minimal Tripo API v3 client (global endpoint): upload, submit a task, poll it, download its files.

Uses TRIPO_API_KEY from backend/.env. Each finished task appends its type, credits and time to
<out dir>/costs.jsonl.

    python splat/tripo.py image-to-splat --image seed.jpg --out out_dir
    python splat/tripo.py text-to-model --prompt "a capybara" --out out_dir
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import httpx

ENV = Path(__file__).resolve().parents[2] / "avatar-platform" / "backend" / ".env"
API = "https://openapi.tripo3d.ai/v3"


def key() -> str:
    for line in ENV.read_text().splitlines():
        if line.strip().startswith("TRIPO_API_KEY="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return os.environ["TRIPO_API_KEY"]


def client() -> httpx.Client:
    return httpx.Client(base_url=API, headers={"Authorization": f"Bearer {key()}"}, timeout=120)


def ok(r: httpx.Response) -> dict:
    body = r.json()
    if r.status_code >= 400 or body.get("code") not in (0, None):
        raise RuntimeError(f"{r.request.url.path}: {r.status_code} {json.dumps(body)[:400]}")
    return body.get("data", body)


def balance() -> float:
    with client() as c:
        return float(ok(c.get("/account/balance"))["balance"])


def upload(path: Path) -> str:
    with client() as c:
        return ok(c.post("/files", files={"file": (path.name, path.read_bytes())}))["file_token"]


def run(path: str, payload: dict, out: Path, label: str, timeout_s: int = 900) -> dict:
    """Submit, poll until done, save every output file under out/<label>_*."""
    out.mkdir(parents=True, exist_ok=True)
    t0, before = time.time(), balance()
    with client() as c:
        task = ok(c.post(path, json=payload))["task_id"]
        print(f"{label}: task {task}")
        while True:
            d = ok(c.get(f"/tasks/{task}"))
            st = d.get("status")
            if st in ("success", "failed", "cancelled", "banned", "expired", "unknown"):
                break
            if time.time() - t0 > timeout_s:
                raise TimeoutError(f"{label}: still {st}")
            time.sleep(5)
        if st != "success":
            raise RuntimeError(f"{label}: {st} {json.dumps(d)[:400]}")
        files = []
        for k, v in (d.get("output") or {}).items():
            url = v if isinstance(v, str) else (v or {}).get("url") if isinstance(v, dict) else None
            if isinstance(url, str) and url.startswith("http"):
                ext = url.split("?")[0].rsplit(".", 1)[-1][:6]
                f = out / f"{label}_{k}.{ext}"
                f.write_bytes(httpx.get(url, timeout=300).content)
                files.append(f.name)
    entry = {"task": label, "type": path, "task_id": task, "seconds": round(time.time() - t0, 1),
             "credits": round(before - balance(), 2), "files": files}
    with open(out / "costs.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")
    (out / f"{label}_task.json").write_text(json.dumps(d, indent=1))
    print(json.dumps(entry))
    return {**d, "task_id": task}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kind", choices=["image-to-splat", "text-to-model", "rig-check", "rig", "retarget", "balance"])
    ap.add_argument("--image", type=Path)
    ap.add_argument("--prompt")
    ap.add_argument("--task")
    ap.add_argument("--json", default="{}", help="extra payload fields")
    ap.add_argument("--out", type=Path, default=Path("."))
    ap.add_argument("--label")
    a = ap.parse_args()
    extra = json.loads(a.json)
    if a.kind == "balance":
        print(balance())
    elif a.kind == "image-to-splat":
        run("/generation/image-to-splat", {"input": upload(a.image), **extra}, a.out, a.label or "triposplat")
    elif a.kind == "text-to-model":
        run("/generation/text-to-model", {"prompt": a.prompt, **extra}, a.out, a.label or "model")
    else:
        path = {"rig-check": "/animations/rig-check", "rig": "/animations/rig", "retarget": "/animations/retarget"}[a.kind]
        run(path, {"input": a.task, **extra}, a.out, a.label or a.kind)


if __name__ == "__main__":
    main()

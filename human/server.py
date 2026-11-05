"""Human creator service (exp/three-human): bakes Anny + MakeHuman CC0 assets into GLB on demand.

    cd human && .venv/bin/uvicorn server:app --port 8010

Separate from the main backend because Anny needs Python >= 3.10 (the backend venv is 3.9).
Runs on CPU: a bake is ~0.1 s of Anny plus GLB encoding.
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from pydantic import BaseModel, Field

import baker
from baker import ASSETS, Shape

app = FastAPI(title="human creator")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                   allow_methods=["*"], allow_headers=["*"])

CACHE = Path(__file__).parent / "out" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
PACKS = ["makehuman_system_assets_cc0", "skins01_cc0", "skins02_cc0", "hair01_cc0"]
# Proxies with missing pieces or non-human shapes stay out of the catalog.
SKIP = {"toon01", "young_caucasian_female_special_suit", "young_caucasian_male_special_suit", "learning_anime_hair"}


def _items(kind: str) -> list[dict]:
    out = []
    for pack in PACKS:
        for d in sorted((ASSETS / pack / kind).glob("*")) if (ASSETS / pack / kind).exists() else []:
            if not d.is_dir() or d.name in SKIP or d.name == "materials":
                continue
            entry = {"id": d.name, "pack": pack, "label": d.name.replace("_", " ")}
            thumb = next(d.glob("*.thumb"), None)
            if thumb:
                entry["thumb"] = str(thumb.relative_to(ASSETS))
            if kind == "skins":
                mat = next(d.glob("*.mhmat"), None)
                if not mat:
                    continue
                entry["material"] = baker._parse_mhmat(mat)
            else:
                mhclo = next(d.glob("*.mhclo"), None)
                if not mhclo:
                    continue
                entry["proxy"] = str(mhclo.relative_to(ASSETS))
            out.append(entry)
    return out


@app.get("/catalog")
def catalog():
    eyes = sorted((ASSETS / PACKS[0] / "eyes" / "materials").glob("*.mhmat"))
    face_prefixes = ("head", "neck", "nose", "mouth", "chin", "l-cheek", "r-cheek", "l-eye", "r-eye", "eyes", "l-ear", "r-ear", "forehead", "eyebrows")
    return {
        "phenotypes": ["gender", "age", "muscle", "weight", "height", "proportions", "african", "asian", "caucasian"],
        "faceChanges": [c for c in baker.models()[0].local_change_labels if c.startswith(face_prefixes)],
        "skins": _items("skins"),
        "hair": _items("hair"),
        "clothes": _items("clothes"),
        "eyebrows": _items("eyebrows"),
        "eyelashes": _items("eyelashes"),
        "eyeColors": [{"id": m.stem, "material": baker._parse_mhmat(m)} for m in eyes],
        "fixed": {
            "eyes": f"{PACKS[0]}/eyes/high-poly/high-poly.mhclo",
            "teeth": f"{PACKS[0]}/teeth/teeth_base/teeth_base.mhclo",
            "tongue": f"{PACKS[0]}/tongue/tongue01/tongue01.mhclo",
        },
        "license": "Anny (NAVER) Apache-2.0; MakeHuman assets CC0 1.0",
    }


class BakeIn(BaseModel):
    phenotype: dict[str, float] = Field(default_factory=dict)
    local: dict[str, float] = Field(default_factory=dict)
    proxies: list[str] = Field(default_factory=list)


@app.post("/bake")
def bake(body: BakeIn):
    for p in body.proxies:
        path = (ASSETS / p).resolve()
        if not path.is_relative_to(ASSETS.resolve()) or path.suffix != ".mhclo" or not path.exists():
            raise HTTPException(400, f"unknown proxy {p}")
    shape = Shape({k: min(1.0, max(0.0, v)) for k, v in body.phenotype.items()},
                  {k: min(1.0, max(-1.0, v)) for k, v in body.local.items()})
    key = baker.hashlib.sha1(json.dumps([shape.key(), sorted(body.proxies)]).encode()).hexdigest()[:20]
    file = CACHE / f"{key}.glb"
    t = time.time()
    if not file.exists():
        file.write_bytes(baker.bake(shape, body.proxies))
    return Response(file.read_bytes(), media_type="model/gltf-binary",
                    headers={"x-bake-ms": str(int((time.time() - t) * 1000)), "access-control-expose-headers": "x-bake-ms"})


@app.get("/asset/{path:path}")
def asset(path: str, size: int = 2048):
    src = (ASSETS / path).resolve()
    if not src.is_relative_to(ASSETS.resolve()) or not src.is_file():
        raise HTTPException(404)
    if src.suffix == ".thumb":
        return Response(src.read_bytes(), media_type="image/png", headers={"cache-control": "max-age=86400"})
    if src.suffix.lower() not in (".png", ".jpg", ".jpeg"):
        raise HTTPException(404)
    size = min(max(size, 256), 4096)
    stem = CACHE / f"tex_{baker.hashlib.sha1(f'{src}:{size}'.encode()).hexdigest()[:16]}"
    out = next((p for p in (stem.with_suffix(".jpg"), stem.with_suffix(".png")) if p.exists()), stem.with_suffix(".png"))
    if not out.exists():
        img = Image.open(src)
        img.thumbnail((size, size))
        has_alpha = img.mode in ("RGBA", "LA") and img.getextrema()[-1][0] < 255
        buf = io.BytesIO()
        if has_alpha:
            img.convert("RGBA").save(buf, "PNG", optimize=True)
        else:
            out = out.with_suffix(".jpg")
            img.convert("RGB").save(buf, "JPEG", quality=88)
        out.write_bytes(buf.getvalue())
    kind = "image/jpeg" if out.suffix == ".jpg" else "image/png"
    return Response(out.read_bytes(), media_type=kind, headers={"cache-control": "max-age=86400"})


@app.on_event("startup")
def warm():
    baker.models()


TWIN = Path(__file__).parent / "out" / "twin"


@app.post("/twin/fit")
async def twin_fit(request: Request):
    """Body: the photo bytes (jpeg/png). Returns the fitted shape and the URL of the projected skin texture."""
    data = await request.body()
    if not data or len(data) > 12_000_000:
        raise HTTPException(400, "photo required (max 12 MB)")
    # ~13 s of CPU: off the event loop, so bakes and textures keep being served meanwhile
    return await run_in_threadpool(_twin_fit, data)


def _twin_fit(data: bytes) -> dict:
    import twin

    try:
        img = Image.open(io.BytesIO(data)).convert("RGB")
    except Exception:
        raise HTTPException(400, "not an image")
    img.thumbnail((1400, 1400))
    path = TWIN / f"upload_{int(time.time() * 1000)}.jpg"
    img.save(path, quality=95)
    labels = [c for c in baker.models()[0].local_change_labels
              if c.startswith(("head", "nose", "mouth", "chin", "l-cheek", "r-cheek", "l-eye", "r-eye", "eyebrows", "forehead"))]
    try:
        res = twin.fit(path, labels)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    tex = twin.project_texture(path, res)
    res["texture"] = f"/twin/tex/{tex.name}"
    return res


@app.get("/twin/tex/{name}")
def twin_tex(name: str):
    path = (TWIN / name).resolve()
    if not path.is_relative_to(TWIN.resolve()) or not path.is_file():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/png")


# Studio cut-outs: characters, garments and hairstyles rendered by the creator itself on a transparent
# background (frontend ?human=gen), trimmed and stored as WebP. Generated once, then served as files.
STUDIO = Path(__file__).parent / "studio"
STUDIO.mkdir(exist_ok=True)
NAME = __import__("re").compile(r"^[a-z0-9_\-]{1,64}$")


@app.get("/studio/{name}.webp")
def studio_get(name: str):
    path = STUDIO / f"{name}.webp"
    if not NAME.match(name) or not path.is_file():
        raise HTTPException(404)
    return Response(path.read_bytes(), media_type="image/webp", headers={"cache-control": "public, max-age=3600"})


@app.post("/studio/{name}")
async def studio_put(name: str, request: Request):
    """Store a cut-out: trim the transparent border, keep a small margin, cap the height at 1100 px."""
    if not NAME.match(name):
        raise HTTPException(400, "bad name")
    img = Image.open(io.BytesIO(await request.body())).convert("RGBA")
    box = img.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not box:
        raise HTTPException(422, "empty image")
    img = img.crop(box)
    pad = max(4, img.height // 40)
    canvas = Image.new("RGBA", (img.width + 2 * pad, img.height + 2 * pad))
    canvas.paste(img, (pad, pad))
    if canvas.height > 1100:
        canvas = canvas.resize((round(canvas.width * 1100 / canvas.height), 1100), Image.LANCZOS)
    canvas.save(STUDIO / f"{name}.webp", "WEBP", quality=88, method=5)
    return {"name": name, "size": canvas.size}

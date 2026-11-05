"""Editor por texto o voz del humano three.js (exp/three-human, estudio).

El cliente manda la frase (o el audio) y lo que hay ahora mismo en pantalla:
estado actual + opciones del catálogo. El LLM devuelve una lista de
operaciones pequeñas que el cliente aplica tal cual. El servidor no conoce el
modelo 3D: solo traduce lenguaje a operaciones válidas y descarta el resto.
"""
from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..orchestrator.llm import complete_json
from ..orchestrator.stt import transcribe

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/human", tags=["human"])

PHENO = {"gender", "age", "muscle", "weight", "height", "proportions", "african", "asian", "caucasian"}
ACCESSORIES = {"hoops", "studs", "glasses", "sunglasses"}
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

_SYSTEM = """Traduces pedidos sobre un avatar 3D a operaciones JSON. Responde SOLO un objeto:
{"ops": [...], "say": "<confirmación de máximo 8 palabras, en el idioma del usuario>"}

Operaciones válidas (usa SOLO ids que aparezcan en "options"):
- {"op":"pheno","key":<gender|age|muscle|weight|height|proportions|african|asian|caucasian>,"value":0..1}
  gender 0=mujer 1=hombre; age 0.12≈8 años, 0.3≈15, 0.5≈30, 0.7≈50, 0.95≈75; weight/muscle/height 0..1 (0.5 medio).
  african/asian/caucasian son una mezcla: si cambias una, manda las tres (suman ~1).
- {"op":"face","key":<id de options.face>,"value":-1..1}
- {"op":"wear","id":<options.clothes>}  (conjuntos completos: ponerse uno quita el anterior; zapatos y sombreros se suman)
- {"op":"remove","id":<id puesto>}
- {"op":"tint","target":<id de prenda puesta | "clothes" | "hair">,"color":"#rrggbb"}
- {"op":"hair","id":<options.hair o "" para calvo>}
- {"op":"skin","id":<options.skins>}
- {"op":"eyes","id":<options.eyes>}
- {"op":"accessory","id":<hoops|studs|glasses|sunglasses>,"on":true|false,"color":"#rrggbb"?}
  aros/argollas/pendientes de aro = hoops; pendientes pequeños/topos = studs; gafas = glasses; gafas de sol = sunglasses.
- {"op":"expression","id":<options.expressions>}
- {"op":"background","id":<options.backgrounds>}
- {"op":"preset","id":<options.presets>}  (solo si piden otro personaje de la lista)

Reglas: aplica todo lo pedido en una frase ("pon aros y la camiseta blanca" = dos ops).
Colores en hex realistas (blanco #f4f2ee, negro #1c1c1e, rojo #b3262e, azul marino #23304d, beige #d9ccb4...).
"Cambiar el color" de algo (ropa, camiseta, polera, top, pantalón, zapatos, pelo) es SIEMPRE "tint" sobre lo que ya lleva puesto
(target = id puesto en state.wearing; "clothes" si no queda claro); NUNCA cambies de prenda por un color.
Solo usa "wear" cuando pidan otra prenda o estilo ("ponle traje", "ropa deportiva", "zapatos elegantes").
Los conjuntos cubren todo el cuerpo: no existe separar camiseta y pantalón; un color para "la camiseta" tiñe el conjunto.
Si algo no existe en options, no inventes ids: dilo en "say" y ofrece lo más parecido."""


class EditIn(BaseModel):
    text: Optional[str] = None
    audio_b64: Optional[str] = None
    mime: str = "audio/webm"
    state: dict = Field(default_factory=dict)
    options: dict = Field(default_factory=dict)


def _clean(ops: list, options: dict) -> list[dict]:
    """Descarta lo que no se puede aplicar: ids fuera del catálogo, valores fuera de rango."""
    ids = {k: set(map(str, options.get(k, []))) for k in
           ("clothes", "hair", "skins", "eyes", "face", "expressions", "backgrounds", "presets")}
    out = []
    for op in ops if isinstance(ops, list) else []:
        if not isinstance(op, dict):
            continue
        kind = op.get("op")
        try:
            if kind == "pheno" and op.get("key") in PHENO:
                out.append({"op": kind, "key": op["key"], "value": min(1.0, max(0.0, float(op["value"])))})
            elif kind == "face" and op.get("key") in ids["face"]:
                out.append({"op": kind, "key": op["key"], "value": min(1.0, max(-1.0, float(op["value"])))})
            elif kind in ("wear", "remove") and op.get("id") in ids["clothes"]:
                out.append({"op": kind, "id": op["id"]})
            elif kind == "tint" and HEX.match(str(op.get("color", ""))):
                out.append({"op": kind, "target": str(op.get("target") or "clothes"), "color": op["color"]})
            elif kind == "hair" and (op.get("id") == "" or op.get("id") in ids["hair"]):
                out.append({"op": kind, "id": op["id"]})
            elif kind in ("skin", "eyes", "expression", "background", "preset") and \
                    op.get("id") in ids[{"skin": "skins", "expression": "expressions", "background": "backgrounds",
                                         "preset": "presets"}.get(kind, kind)]:
                out.append({"op": kind, "id": op["id"]})
            elif kind == "accessory" and op.get("id") in ACCESSORIES:
                a = {"op": kind, "id": op["id"], "on": bool(op.get("on", True))}
                if HEX.match(str(op.get("color", ""))):
                    a["color"] = op["color"]
                out.append(a)
        except (TypeError, ValueError, KeyError):
            continue
    return out


@router.post("/edit")
async def edit(body: EditIn):
    text = (body.text or "").strip()
    if not text and body.audio_b64:
        suffix = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/wav": ".wav"}.get(
            body.mime.split(";")[0], ".webm")
        text = (await transcribe(base64.b64decode(body.audio_b64), suffix)).strip()
    if not text:
        raise HTTPException(400, "Sin texto")
    prompt = json.dumps({"request": text, "state": body.state, "options": body.options}, ensure_ascii=False)
    try:
        out = await complete_json(_SYSTEM, prompt, settings.HUMAN_EDIT_TIER)
    except Exception as exc:
        logger.warning("human/edit: LLM falló (%s)", exc)
        raise HTTPException(502, "El modelo de lenguaje no respondió") from exc
    return {"transcript": text, "ops": _clean(out.get("ops", []), body.options), "say": str(out.get("say", ""))[:120]}

"""Troceo por frases de un stream de tokens LLM (A0.1).

Acumula texto y emite frases completas en cuanto se cierran, para que el
TTS arranque con la primera frase sin esperar la respuesta entera.
"""
from __future__ import annotations

import re
from typing import AsyncIterator

# Cierre de frase: . ! ? … (+ cierres de comillas/paréntesis pegados),
# seguido de espacio. Evita partir decimales (3.14), ordinales ("1. ") y
# abreviaturas de una letra ("J. Smith").
_BOUNDARY = re.compile(r"([.!?…]+[\"”’)\]]*)\s+")
_MIN_CHARS = 12  # no emitir fragmentos ínfimos ("Sí.") sueltos — se agrupan


def _split_complete(buffer: str) -> tuple[list[str], str]:
    """Divide buffer en (frases_completas, resto_incompleto)."""
    sentences: list[str] = []
    start = 0
    for m in _BOUNDARY.finditer(buffer):
        end = m.end(1)
        candidate = buffer[start:end]
        before = m.group(1)
        prev = buffer[m.start(1) - 1] if m.start(1) > 0 else ""
        # no cortar tras dígito+punto (listas "1." / decimales) ni inicial "A."
        if before.startswith(".") and (prev.isdigit() or (len(candidate.strip()) > 1 and candidate.strip()[-2].isupper() and candidate.strip()[:-1].split()[-1:] == [candidate.strip()[-2]])):
            continue
        sentences.append(candidate.strip())
        start = m.end()
    return sentences, buffer[start:]


async def sentence_stream(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    """tokens LLM → frases completas (la última se emite al agotarse el stream)."""
    buffer = ""
    pending = ""  # fragmentos < _MIN_CHARS esperando agruparse
    async for tok in tokens:
        buffer += tok
        complete, buffer = _split_complete(buffer)
        for s in complete:
            joined = f"{pending} {s}".strip() if pending else s
            if len(joined) < _MIN_CHARS:
                pending = joined
                continue
            pending = ""
            yield joined
    tail = f"{pending} {buffer}".strip()
    if tail:
        yield tail

"""Visemas desde el alignment por carácter de ElevenLabs (A0.2).

ElevenLabs `stream/with-timestamps` devuelve, junto a cada chunk de audio,
los caracteres cubiertos con sus tiempos de inicio/fin. Mapear grafema→
visema (castellano/inglés aproximado) da visemas con timestamps REALES del
audio sin coste de latencia — cumple el papel de Azure visemes del plan.
(Rhubarb queda como refinamiento opcional offline; no está en el hot path.)

Set Oculus de 15 visemas — ver contract.VISEME_IDS.
"""
from __future__ import annotations

from .contract import Visema

# grafema (minúscula) → visema Oculus. Aproximación es-ES primero, en-US después.
_MAP = {
    "a": "aa", "á": "aa",
    "e": "E", "é": "E",
    "i": "ih", "í": "ih", "y": "ih",
    "o": "oh", "ó": "oh",
    "u": "ou", "ú": "ou", "ü": "ou", "w": "ou",
    "p": "PP", "b": "PP", "m": "PP",
    "f": "FF", "v": "FF",
    "z": "TH",  # es-ES: z/ce/ci ≈ θ — TH le va mejor que SS
    "d": "DD", "t": "DD",
    "k": "kk", "c": "kk", "q": "kk", "g": "kk", "j": "kk", "x": "kk",
    "ch": "CH", "ñ": "CH", "ll": "CH", "sh": "CH",
    "s": "SS",
    "n": "nn", "l": "nn",
    "r": "RR", "rr": "RR",
    "h": "sil",  # muda en castellano
}


def visemes_from_alignment(
    chars: list[str],
    starts_s: list[float],
    ends_s: list[float],
    t0_s: float = 0.0,
) -> list[Visema]:
    """Convierte el alignment de un chunk en eventos de visema.

    t0_s: tiempo (en s, escala de la frase) donde EMPIEZA este chunk de
    audio — los t_ms del resultado quedan relativos al chunk (contrato).
    Colapsa caracteres consecutivos con el mismo visema y añade `sil` en
    silencios > 120 ms (espacios/pausas) para que la boca cierre.
    """
    out: list[Visema] = []
    prev_id: str | None = None
    prev_end = t0_s
    i = 0
    while i < len(chars):
        ch = chars[i].lower()
        # dígrafos primero (ch/ll/rr)
        two = ch + (chars[i + 1].lower() if i + 1 < len(chars) else "")
        if two in ("ch", "ll", "rr"):
            vid, start, end = _MAP[two], starts_s[i], ends_s[i + 1]
            i += 2
        else:
            vid = _MAP.get(ch)
            start, end = starts_s[i], ends_s[i]
            i += 1
            if vid is None:  # espacios, puntuación, dígitos…
                if (end - prev_end) > 0.12 and prev_id != "sil":
                    out.append(Visema(t_ms=max(0, int((start - t0_s) * 1000)), id="sil", peso=1.0))
                    prev_id, prev_end = "sil", end
                continue
        if vid != prev_id:
            out.append(Visema(t_ms=max(0, int((start - t0_s) * 1000)), id=vid, peso=1.0))
            prev_id = vid
        prev_end = end
    return out

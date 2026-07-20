"""ETAPA A — Fase 0: contrato compartido del orquestador.

Mensaje interno que AMBOS renderers consumen (docs/nueva_arquitectura.md):
el modo Feed (video híbrido) usa audio+estado+gesto; el modo 3D usará
visemas+estado+gesto. Un mensaje por evento: cambio de estado o chunk de
audio de una frase.

Visemas: set Oculus de 15 ids — sil, PP, FF, TH, DD, kk, CH, SS, nn, RR,
aa, E, ih, oh, ou — estándar de lipsync y mapeable 1:1 a los mouth-shapes
de Rhubarb y a blendshapes ARKit. `t_ms` es relativo AL INICIO DEL AUDIO
DE LA FRASE (`texto_frase`): los chunks de una misma frase se concatenan
en orden de `seq`, y cada mensaje lleva la línea de tiempo de visemas
conocida hasta el momento (acumulada), así el último mensaje de la frase
trae la secuencia completa y cualquier mensaje basta para animar.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Estado = Literal["hablando", "escuchando", "idle"]

# Gestos que la biblioteca de clips (A1) debe cubrir. El orquestador solo
# emite ids de este enum; el scheduler de A2 los resuelve contra clip_graph.
Gesto = Literal["idle_a", "idle_b", "listen", "gesture_enum", "gesture_open"]

VISEME_IDS = (
    "sil", "PP", "FF", "TH", "DD", "kk", "CH", "SS",
    "nn", "RR", "aa", "E", "ih", "oh", "ou",
)


class Visema(BaseModel):
    t_ms: int = Field(ge=0, description="ms desde el inicio del audio_chunk de este mensaje")
    id: str = Field(description=f"uno de {VISEME_IDS}")
    peso: float = Field(default=1.0, ge=0.0, le=1.0)


class MensajeContrato(BaseModel):
    session_id: str
    seq: int = Field(ge=0, description="monotónico por sesión")
    estado: Estado
    audio_chunk: Optional[str] = Field(
        default=None, description="MP3 base64 (chunk de la frase actual) o None en cambios de estado"
    )
    visemas: list[Visema] = Field(default_factory=list)
    gesto: Gesto = "idle_a"
    texto_frase: Optional[str] = None

    # ── metadatos opcionales (no rompen el contrato mínimo) ──────────────
    # Modo Feed con lip-sync (A2): URL relativa del chunk MP4 H.264 de la
    # frase (video con el audio ya muxeado). El cliente lo prefiere sobre
    # audio_chunk cuando llega.
    video_chunk: Optional[str] = None
    # ms de audio ya emitidos de esta frase antes de este chunk — permite a
    # un cliente re-sincronizar si se pierde un mensaje.
    audio_t0_ms: Optional[int] = None
    # instrumentación: primer chunk de la respuesta lleva la latencia
    # medida desde el primer token del LLM (criterio de aceptación A0).
    lat_primer_chunk_ms: Optional[int] = None
    # transcripción en vivo (subtítulos A4) — texto acumulado de la respuesta
    fin_de_respuesta: bool = False

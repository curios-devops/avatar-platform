"""MEYA bridge: an ElevenLabs agent drives a LiveTalking avatar in real time.

The browser opens one WebRTC connection to LiveTalking: it sends its microphone and receives the avatar (video plus
the agent's voice, lip-synced by MuseTalk). This bridge, per session, opens the agent's WebSocket (a signed URL minted
by MEYA's runtime, so no key lives here):
  - microphone (48 kHz from WebRTC) -> 16 kHz PCM -> user_audio_chunk
  - agent audio (pcm_16000) -> 20 ms float frames -> avatar.put_audio_frame (lip sync and playback)
  - interruption -> avatar.flush_talk (the being stops at once)
  - transcripts, corrections and speaking/listening -> a data channel, for captions and the saved conversation
Everything the agent already does stays: turn-taking, barge-in, the being's voice and brain.
"""
import asyncio
import base64
import json
import time

import numpy as np
import websockets
from av.audio.resampler import AudioResampler

from utils.logger import logger

CHUNK = 320  # 20 ms at 16 kHz
MIC_BYTES = 3200  # 100 ms of 16 kHz s16 mono per user_audio_chunk


def attach(pc, avatar, agent: dict):
    """Wire a peer connection to an agent. Call before setRemoteDescription, so track/datachannel events are caught."""
    bridge = Bridge(avatar, agent)

    @pc.on("datachannel")
    def on_datachannel(channel):
        bridge.channel = channel
        bridge.flush()

    @pc.on("track")
    def on_track(track):
        if track.kind == "audio":
            asyncio.ensure_future(bridge.microphone(track))

    @pc.on("connectionstatechange")
    async def on_state():
        # The agent starts only once media flows, so its greeting is never spoken to nobody (or cut).
        if pc.connectionState == "connected" and not bridge.started:
            bridge.started = True
            asyncio.ensure_future(bridge.run())
        if pc.connectionState in ("failed", "closed"):
            await bridge.close()

    return bridge


class Bridge:
    def __init__(self, avatar, agent: dict):
        self.avatar = avatar
        self.agent = agent
        self.ws = None
        self.channel = None
        self.pending = []
        self.rest = np.zeros(0, np.float32)
        self.ready = False
        self.closed = False
        self.started = False
        self.heard_at = None  # when the last user transcript arrived, to time the answer

    # -- to the browser ------------------------------------------------------------------------------------------
    def send(self, event: dict):
        if self.channel is not None and self.channel.readyState == "open":
            self.channel.send(json.dumps(event, ensure_ascii=False))
        else:
            self.pending.append(event)

    def flush(self):
        pending, self.pending = self.pending, []
        for event in pending:
            self.send(event)

    # -- the agent -----------------------------------------------------------------------------------------------
    async def run(self):
        started = time.time()
        try:
            async with websockets.connect(self.agent["signedUrl"], max_size=None, open_timeout=10) as ws:
                self.ws = ws
                init = {"type": "conversation_initiation_client_data",
                        "dynamic_variables": self.agent.get("variables") or {}}
                override = {k: v for k, v in (("first_message", self.agent.get("firstMessage")),
                                              ("language", self.agent.get("language"))) if v}
                if override:
                    init["conversation_config_override"] = {"agent": override}
                await ws.send(json.dumps(init))
                watcher = asyncio.ensure_future(self.watch_speaking())
                async for raw in ws:
                    await self.on_event(json.loads(raw), started)
                watcher.cancel()
        except Exception as exc:  # a dropped agent ends the call; the browser is told
            logger.warning("bridge: agent connection ended: %s", exc)
        finally:
            self.closed = True
            self.send({"type": "ended"})

    async def on_event(self, m: dict, started: float):
        kind = m.get("type")
        if kind == "audio":
            if self.heard_at:
                logger.info(f"LATENCY agent first audio {time.time() - self.heard_at:.3f}s after the user transcript")
                self.heard_at = None
            self.speak(base64.b64decode(m["audio_event"]["audio_base_64"]))
        elif kind == "interruption":
            self.avatar.flush_talk()
            self.rest = np.zeros(0, np.float32)
            self.send({"type": "interruption"})
        elif kind == "ping":
            await self.ws.send(json.dumps({"type": "pong", "event_id": m["ping_event"]["event_id"]}))
        elif kind == "agent_response":
            self.send({"type": "agent", "text": m["agent_response_event"]["agent_response"]})
        elif kind == "agent_response_correction":
            e = m["agent_response_correction_event"]
            self.send({"type": "correction", "original": e["original_agent_response"], "corrected": e["corrected_agent_response"]})
        elif kind == "user_transcript":
            self.heard_at = time.time()
            self.send({"type": "user", "text": m["user_transcription_event"]["user_transcript"]})
        elif kind == "conversation_initiation_metadata":
            e = m["conversation_initiation_metadata_event"]
            logger.info(f"bridge: agent ready in {time.time() - started:.2f}s, in={e['user_input_audio_format']} out={e['agent_output_audio_format']}")
            self.ready = True
            self.send({"type": "ready"})

    def speak(self, pcm: bytes):
        audio = np.concatenate([self.rest, np.frombuffer(pcm, np.int16).astype(np.float32) / 32768.0])
        n = len(audio) // CHUNK
        for i in range(n):
            self.avatar.put_audio_frame(audio[i * CHUNK:(i + 1) * CHUNK], {})
        self.rest = audio[n * CHUNK:]

    async def watch_speaking(self):
        last = None
        while not self.closed:
            now = bool(getattr(self.avatar, "speaking", False))
            if now != last:
                self.send({"type": "mode", "mode": "speaking" if now else "listening"})
                last = now
            await asyncio.sleep(0.1)

    # -- the person ----------------------------------------------------------------------------------------------
    async def microphone(self, track):
        resampler = AudioResampler(format="s16", layout="mono", rate=16000)
        buf = bytearray()
        while not self.closed:
            try:
                frame = await track.recv()
            except Exception:
                return
            for out in resampler.resample(frame):
                buf += out.to_ndarray().tobytes()
            if len(buf) >= MIC_BYTES:
                chunk, buf = bytes(buf), bytearray()
                if self.ready and self.ws is not None:
                    try:
                        await self.ws.send(json.dumps({"user_audio_chunk": base64.b64encode(chunk).decode()}))
                    except Exception:
                        return

    async def close(self):
        self.closed = True
        if self.ws is not None:
            await self.ws.close()

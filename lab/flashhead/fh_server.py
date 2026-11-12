"""MEYA live call with SoulX-FlashHead Lite (real time, one session per process).

Speaks the same protocol as our LiveTalking server, so the web needs no change (only AVATAR_LIVE_URL):
  POST /offer {sdp, type, avatar, agent:{signedUrl, firstMessage, language, variables}} -> {sdp, type}
  data channel "meya": {type: agent|user|correction|mode|interruption|ready|ended}

Pipeline: browser mic -> 16 kHz -> ElevenLabs agent (signed URL, so no key here) -> agent audio -> FlashHead (24 frames
per 0.96 s chunk, streaming, stateful) -> the 512 px face pasted back onto the being's half-body canvas (720x1280) ->
WebRTC video + the same audio slice, on one 25 fps clock. Silence plays an idle loop generated at boot, so the GPU only
works while the being talks and an answer never waits behind silent chunks. Interruption drops everything queued.

The streaming engine is adapted from Mynah (github.com/honwee/mynah, workers/avatar/flashhead_engine.py, Apache-2.0).
Run inside the FlashHead checkout's venv:  FLASHHEAD_DIR=/workspace/fh python fh_server.py --portrait lexi_half.png
"""
import argparse, asyncio, base64, fractions, json, os, queue, sys, threading, time
from collections import deque

import cv2
import numpy as np
from aiohttp import web
from aiortc import MediaStreamTrack, RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
from av import AudioFrame, VideoFrame
from av.audio.resampler import AudioResampler

sys.path.insert(0, os.environ.get("FLASHHEAD_DIR", "/workspace/fh"))
import torch  # noqa: E402
import websockets  # noqa: E402
from flash_head.inference import get_audio_embedding, get_base_data, get_infer_params, get_pipeline, run_pipeline  # noqa: E402

FPS, SR = 25, 16000
CANVAS_W, CANVAS_H = 720, 1280
log = lambda *a: print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- the being's canvas and where its face goes
def canvas_and_box(portrait_path):
    """Half-body canvas (9:16) and the exact box FlashHead crops the face from (its own detector and geometry)."""
    from PIL import Image
    from flash_head.utils.cpu_face_handler import CPUFaceHandler
    src = Image.open(portrait_path).convert("RGB")
    w, h = src.size
    tw = min(w, int(h * 9 / 16))
    src = src.crop(((w - tw) // 2, 0, (w - tw) // 2 + tw, h)).resize((CANVAS_W, int(h * CANVAS_W / tw)))
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (250, 250, 250)); canvas.paste(src.crop((0, 0, CANVAS_W, min(src.height, CANVAS_H))), (0, 0))
    arr = np.array(canvas)
    boxes, _ = CPUFaceHandler()(arr)
    if len(boxes) == 0:
        raise SystemExit("no face in the portrait")
    b = boxes[0]; x1, y1, x2, y2 = b[0] * CANVAS_W, b[1] * CANVAS_H, b[2] * CANVAS_W, b[3] * CANVAS_H
    # Same as flash_head get_scaled_bbox (face_ratio 2.0), as replicated in Mynah's halfbody.py
    cx, cy, bw, bh = (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1
    side = max(bw, bh) * 2.0
    box = [int(max(0, cx - side / 2)), int(max(0, cy - side * 0.55)), int(min(CANVAS_W, cx + side / 2)), int(min(CANVAS_H, cy + side * 0.45))]
    path = "/tmp/canvas.png"; canvas.save(path)
    return path, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), box


def feather(w, h, edge=0.12):
    """A soft-edged mask so the generated head blends into the canvas without a seam."""
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    d = np.minimum.reduce([xs / (w * edge), (w - 1 - xs) / (w * edge), ys / (h * edge), (h - 1 - ys) / (h * edge)])
    return np.clip(d, 0, 1)[..., None]


class Compositor:
    def __init__(self, body_bgr, box):
        self.body, self.box = body_bgr, box
        x1, y1, x2, y2 = box
        self.mask = feather(x2 - x1, y2 - y1)

    def __call__(self, face_rgb):
        x1, y1, x2, y2 = self.box
        face = cv2.resize(cv2.cvtColor(face_rgb, cv2.COLOR_RGB2BGR), (x2 - x1, y2 - y1), interpolation=cv2.INTER_LINEAR)
        out = self.body.copy()
        roi = out[y1:y2, x1:x2].astype(np.float32)
        out[y1:y2, x1:x2] = (face * self.mask + roi * (1 - self.mask)).astype(np.uint8)
        return out


# ---------------------------------------------------------------- FlashHead, streaming (after Mynah's FlashHeadEngine)
class Engine:
    def __init__(self, ckpt_dir, wav2vec_dir, cond_path, model_type="lite"):
        t0 = time.time()
        self.pipe = get_pipeline(world_size=1, ckpt_dir=ckpt_dir, wav2vec_dir=wav2vec_dir, model_type=model_type)
        p = get_infer_params()
        self.motion = p["motion_frames_num"]
        self.slice_len = p["frame_num"] - self.motion
        self.chunk = self.slice_len * p["sample_rate"] // p["tgt_fps"]
        self.cached = p["sample_rate"] * p["cached_audio_duration"]
        self.end_idx = p["cached_audio_duration"] * p["tgt_fps"]
        self.start_idx = self.end_idx - p["frame_num"]
        self.cond = cond_path
        get_base_data(self.pipe, cond_image_path_or_dir=cond_path, base_seed=42, use_face_crop=True)
        self.reset()
        log(f"engine ready in {time.time() - t0:.1f}s, chunk {self.chunk} samples = {self.chunk / SR:.2f}s, {self.slice_len} frames")

    def reset(self):
        self.dq = deque([0.0] * self.cached, maxlen=self.cached)

    @torch.no_grad()
    def run(self, pcm):
        self.dq.extend(pcm.tolist())
        emb = get_audio_embedding(self.pipe, np.array(self.dq), self.start_idx, self.end_idx)
        return run_pipeline(self.pipe, emb)[self.motion:].cpu().numpy().astype(np.uint8)


# ---------------------------------------------------------------- one call
class Call:
    """Owns the playout clock: every 40 ms one video frame and 640 audio samples, speech if queued, else the idle loop."""

    def __init__(self, engine, compose, idle):
        self.e, self.compose, self.idle = engine, compose, idle
        engine.reset()  # a new call starts with no memory of the last one's audio
        self.pcm_in = queue.Queue()  # (gen, float32 pcm) from the agent
        self.out = queue.Queue()     # (gen, bgr frame, int16 audio[640]) ready to play
        self.gen, self.idle_i, self.closed = 0, 0, False
        self.channel, self.pending, self.ws = None, [], None
        self.video_q, self.audio_q = asyncio.Queue(maxsize=50), asyncio.Queue(maxsize=100)
        self.speaking, self.heard_at, self.first_sound = False, None, []
        threading.Thread(target=self.worker, daemon=True).start()

    # GPU thread: agent audio -> chunks -> frames
    def worker(self):
        buf, last = np.zeros(0, np.float32), time.time()
        while not self.closed:
            try:
                gen, pcm = self.pcm_in.get(timeout=0.05)
                if gen != self.gen:
                    continue
                buf = np.concatenate([buf, pcm]); last = time.time()
            except queue.Empty:
                # The agent paused: flush the tail of its sentence (padded with silence) so the last words show.
                if 0 < len(buf) < self.e.chunk and time.time() - last > 0.25:
                    buf = np.concatenate([buf, np.zeros(self.e.chunk - len(buf), np.float32)])
            while len(buf) >= self.e.chunk and not self.closed:
                g, piece, buf = self.gen, buf[:self.e.chunk], buf[self.e.chunk:]
                t = time.time(); frames = self.e.run(piece); dt = time.time() - t
                if g != self.gen:
                    break
                audio = (np.clip(piece, -1, 1) * 32767).astype(np.int16)
                for i, f in enumerate(frames):
                    self.out.put((g, self.compose(f), audio[i * 640:(i + 1) * 640]))
                log(f"chunk {dt:.3f}s for {self.e.chunk / SR:.2f}s audio ({self.e.chunk / SR / dt:.1f}x real time)")

    async def clock(self):
        t0, n, was = time.time(), 0, False
        silent = np.zeros(640, np.int16)
        while not self.closed:
            frame, audio = None, silent
            while not self.out.empty():
                g, f, a = self.out.get_nowait()
                if g == self.gen:
                    frame, audio = f, a
                    break
            talking = frame is not None
            if talking and self.heard_at:
                self.first_sound.append(time.time() - self.heard_at); log(f"LATENCY user transcript -> first lip-synced frame {self.first_sound[-1]:.2f}s"); self.heard_at = None
            if frame is None:
                frame = self.idle[self.idle_i % len(self.idle)]; self.idle_i += 1
            if talking != was:
                self.send({"type": "mode", "mode": "speaking" if talking else "listening"}); was = talking
            for q, item in ((self.video_q, frame), (self.audio_q, audio[:320]), (self.audio_q, audio[320:])):
                if q.full():
                    q.get_nowait()
                q.put_nowait(item)
            n += 1
            await asyncio.sleep(max(0, t0 + n / FPS - time.time()))

    def interrupt(self):
        self.gen += 1
        for q in (self.pcm_in, self.out):
            while not q.empty():
                q.get_nowait()
        self.e.reset()

    # to the browser
    def send(self, event):
        if self.channel is not None and self.channel.readyState == "open":
            self.channel.send(json.dumps(event, ensure_ascii=False))
        else:
            self.pending.append(event)

    # the agent (same protocol as el_bridge.py)
    async def agent(self, cfg):
        try:
            async with websockets.connect(cfg["signedUrl"], max_size=None, open_timeout=10) as ws:
                self.ws = ws
                init = {"type": "conversation_initiation_client_data", "dynamic_variables": cfg.get("variables") or {}}
                over = {k: v for k, v in (("first_message", cfg.get("firstMessage")), ("language", cfg.get("language"))) if v}
                if over:
                    init["conversation_config_override"] = {"agent": over}
                await ws.send(json.dumps(init))
                async for raw in ws:
                    m = json.loads(raw); kind = m.get("type")
                    if kind == "audio":
                        pcm = np.frombuffer(base64.b64decode(m["audio_event"]["audio_base_64"]), np.int16).astype(np.float32) / 32768
                        self.pcm_in.put((self.gen, pcm))
                    elif kind == "interruption":
                        self.interrupt(); self.send({"type": "interruption"})
                    elif kind == "ping":
                        await ws.send(json.dumps({"type": "pong", "event_id": m["ping_event"]["event_id"]}))
                    elif kind == "agent_response":
                        self.send({"type": "agent", "text": m["agent_response_event"]["agent_response"]})
                    elif kind == "agent_response_correction":
                        e = m["agent_response_correction_event"]
                        self.send({"type": "correction", "original": e["original_agent_response"], "corrected": e["corrected_agent_response"]})
                    elif kind == "user_transcript":
                        self.heard_at = time.time(); self.send({"type": "user", "text": m["user_transcription_event"]["user_transcript"]})
                    elif kind == "conversation_initiation_metadata":
                        self.send({"type": "ready"})
        except Exception as exc:
            log("agent ended:", exc)
        finally:
            self.send({"type": "ended"})

    async def microphone(self, track):
        rs, buf = AudioResampler(format="s16", layout="mono", rate=SR), bytearray()
        while not self.closed:
            try:
                frame = await track.recv()
            except Exception:
                return
            for o in rs.resample(frame):
                buf += o.to_ndarray().tobytes()
            if len(buf) >= 3200 and self.ws is not None:
                chunk, buf = bytes(buf), bytearray()
                try:
                    await self.ws.send(json.dumps({"user_audio_chunk": base64.b64encode(chunk).decode()}))
                except Exception:
                    return


class Video(MediaStreamTrack):
    kind = "video"

    def __init__(self, call):
        super().__init__(); self.call, self.n = call, 0

    async def recv(self):
        bgr = await self.call.video_q.get()
        f = VideoFrame.from_ndarray(bgr, format="bgr24"); f.pts, f.time_base = self.n, fractions.Fraction(1, FPS); self.n += 1
        return f


class Audio(MediaStreamTrack):
    kind = "audio"

    def __init__(self, call):
        super().__init__(); self.call, self.n = call, 0

    async def recv(self):
        pcm = await self.call.audio_q.get()
        f = AudioFrame(format="s16", layout="mono", samples=320); f.planes[0].update(pcm.tobytes())
        f.sample_rate, f.pts, f.time_base = SR, self.n * 320, fractions.Fraction(1, SR); self.n += 1
        return f


# ---------------------------------------------------------------- HTTP
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "content-type", "Access-Control-Allow-Methods": "POST, OPTIONS"}


def make_app(engine, compose, idle):
    state = {"call": None}

    async def offer(request):
        if request.method == "OPTIONS":
            return web.Response(headers=CORS)
        body = await request.json()
        if state["call"] and not state["call"].closed:
            return web.json_response({"code": -1, "msg": "engine busy"}, status=503, headers=CORS)
        call = Call(engine, compose, idle); state["call"] = call
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")]))
        pc.addTrack(Audio(call)); pc.addTrack(Video(call))

        @pc.on("datachannel")
        def on_dc(ch):
            call.channel = ch
            for e in call.pending:
                call.send(e)
            call.pending = []

        @pc.on("track")
        def on_track(track):
            if track.kind == "audio":
                asyncio.ensure_future(call.microphone(track))

        @pc.on("connectionstatechange")
        async def on_state():
            log("pc", pc.connectionState)
            if pc.connectionState == "connected" and body.get("agent"):
                asyncio.ensure_future(call.clock()); asyncio.ensure_future(call.agent(body["agent"]))
            if pc.connectionState in ("failed", "closed"):
                call.closed = True
                if call.ws:
                    await call.ws.close()
                await pc.close()

        await pc.setRemoteDescription(RTCSessionDescription(sdp=body["sdp"], type=body["type"]))
        await pc.setLocalDescription(await pc.createAnswer())
        return web.json_response({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid": 0}, headers=CORS)

    app = web.Application()
    app.router.add_route("*", "/offer", offer)
    app.router.add_get("/", lambda r: web.Response(text="meya flashhead ok"))
    return app


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--portrait", required=True)
    ap.add_argument("--ckpt", default="/workspace/models/SoulX-FlashHead-1_3B")
    ap.add_argument("--wav2vec", default="/workspace/models/wav2vec2-base-960h")
    ap.add_argument("--model", default="lite")
    ap.add_argument("--port", type=int, default=8010)
    a = ap.parse_args()
    cond, body, box = canvas_and_box(a.portrait)
    compose = Compositor(body, box)
    engine = Engine(a.ckpt, a.wav2vec, cond, a.model)
    t0 = time.time()
    idle = []
    for _ in range(4):  # warm-up (pays torch.compile) and the idle loop: ~3.8 s of the being listening
        idle += [compose(f) for f in engine.run(np.zeros(engine.chunk, np.float32))]
    idle = idle[len(idle) // 4:] + idle[len(idle) // 4:][::-1]  # ping-pong, skipping the first warm-up chunk
    engine.reset()
    log(f"warm-up and idle loop in {time.time() - t0:.1f}s ({len(idle)} frames); listening on :{a.port}")
    web.run_app(make_app(engine, compose, idle), port=a.port, print=None)


if __name__ == "__main__":
    main()

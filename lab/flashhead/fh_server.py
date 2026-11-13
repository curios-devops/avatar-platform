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


class BodyLoop:
    """Gesture layer: a pre-made half-body clip of the being (breathing, nods, head tilts, hand gestures; lips closed)
    plays in a ping-pong loop under the live face, while she listens AND while she talks. Offline, once: her face is
    tracked in every frame of the clip (MediaPipe: box + eyes), smoothed, and turned into a similarity transform
    (scale, tilt, shift) from the portrait's face. Per frame: FlashHead's 512 face is warped to where her face is in
    that frame, colour-matched to the clip's light and pasted with a soft ellipse over the inner face only (brows to
    chin), so hair, ears, neck and body stay the clip's own.
    """

    def __init__(self, clip_path, ref_bgr, box, smooth=7):
        import mediapipe as mp
        det = mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.3)
        self.box = box
        ref = self._face(det, ref_bgr)
        if ref is None:
            raise SystemExit("no face in the portrait")
        cap, frames = cv2.VideoCapture(clip_path), []
        src_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
        while True:
            ok, f = cap.read()
            if not ok:
                break
            frames.append(self._fit(f))
        idx = np.round(np.arange(0, len(frames), src_fps / FPS)).astype(int)
        frames = [frames[min(i, len(frames) - 1)] for i in idx]
        tracks, missed = [], 0
        for f in frames:
            t = self._face(det, f)
            if t is None:
                missed += 1; t = tracks[-1] if tracks else ref
            tracks.append(t)
        t = np.array(tracks, np.float32)  # cx, cy, w, angle
        t[:, 3] = np.unwrap(t[:, 3])
        k = np.ones(smooth, np.float32) / smooth
        t = np.stack([np.convolve(np.pad(t[:, j], smooth // 2, mode="edge"), k, mode="valid") for j in range(4)], 1)
        x1, y1, x2, y2 = box
        c0 = np.array(ref[:2], np.float32)
        self.M = []
        for cx, cy, w, ang in t:
            sc, th = w / ref[2], ang - ref[3]
            A = sc * np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]], np.float32)
            b = A @ (np.array([x1, y1], np.float32) - c0) + np.array([cx, cy], np.float32)
            self.M.append(np.hstack([A, b[:, None]]))
        self.frames = frames + frames[-2:0:-1]
        self.M = self.M + self.M[-2:0:-1]
        # inner-face ellipse in the crop box's coordinates
        # (inside the hairline on purpose: pasting the portrait's hair over the clip's moving hair ghosts)
        fw = ref[2]
        ecx, ecy, ax, ay = ref[0] - x1, ref[1] - y1 + 0.75 * fw, 1.0 * fw, 1.4 * fw  # fw = eye distance: brows to chin
        self.ebox = ex1, ey1, ex2, ey2 = (max(0, int(ecx - ax - 2)), max(0, int(ecy - ay - 2)),
                                          min(x2 - x1, int(ecx + ax + 3)), min(y2 - y1, int(ecy + ay + 3)))
        ys, xs = np.mgrid[ey1:ey2, ex1:ex2].astype(np.float32)
        d = np.sqrt(((xs - ecx) / ax) ** 2 + ((ys - ecy) / ay) ** 2)
        self.alpha = np.clip((1.0 - d) / 0.3, 0, 1).astype(np.float32)
        sc = [m[0, 0] ** 2 + m[1, 0] ** 2 for m in self.M]
        log(f"body loop: {len(frames)} frames ({len(frames) / FPS:.1f}s, ping-pong {len(self.frames)}), face missed in "
            f"{missed}, scale {np.sqrt(min(sc)):.2f}-{np.sqrt(max(sc)):.2f}, tilt {np.degrees(t[:, 3].min() - ref[3]):.0f}..{np.degrees(t[:, 3].max() - ref[3]):.0f} deg")

    @staticmethod
    def _fit(bgr):
        h, w = bgr.shape[:2]
        tw = min(w, int(h * 9 / 16))
        crop = bgr[:, (w - tw) // 2:(w - tw) // 2 + tw]
        crop = cv2.resize(crop, (CANVAS_W, int(h * CANVAS_W / tw)), interpolation=cv2.INTER_AREA)
        out = np.full((CANVAS_H, CANVAS_W, 3), 250, np.uint8)
        out[:min(CANVAS_H, crop.shape[0])] = crop[:CANVAS_H]
        return out

    @staticmethod
    def _face(det, bgr):
        r = det.process(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        if not r.detections:
            return None
        d = max(r.detections, key=lambda x: x.score[0]).location_data
        bb, kp = d.relative_bounding_box, d.relative_keypoints
        H, W = bgr.shape[:2]
        (rx, ry), (lx, ly) = (kp[0].x * W, kp[0].y * H), (kp[1].x * W, kp[1].y * H)  # right eye, left eye
        ang = np.arctan2(ly - ry, lx - rx)
        return [(rx + lx) / 2, (ry + ly) / 2, float(np.hypot(lx - rx, ly - ry)), ang]  # eyes: centre, distance, tilt

    def __call__(self, face_rgb, n):
        i = n % len(self.frames)
        out = self.frames[i].copy()
        if face_rgb is None:
            return out
        x1, y1, x2, y2 = self.box
        ex1, ey1, ex2, ey2 = self.ebox
        bw, bh, ew, eh = x2 - x1, y2 - y1, ex2 - ex1, ey2 - ey1
        A, b = self.M[i][:, :2], self.M[i][:, 2] + self.M[i][:, :2] @ np.array([ex1, ey1], np.float32)
        corners = A @ np.array([[0, ew, 0, ew], [0, 0, eh, eh]], np.float32) + b[:, None]
        rx1, ry1 = max(0, int(corners[0].min())), max(0, int(corners[1].min()))
        rx2, ry2 = min(CANVAS_W, int(np.ceil(corners[0].max()))), min(CANVAS_H, int(np.ceil(corners[1].max())))
        if rx2 <= rx1 or ry2 <= ry1:
            return out
        # only the ellipse's part of FlashHead's face, at canvas scale
        H, W = face_rgb.shape[:2]
        sub = face_rgb[int(ey1 * H / bh):int(np.ceil(ey2 * H / bh)), int(ex1 * W / bw):int(np.ceil(ex2 * W / bw))]
        face = cv2.cvtColor(cv2.resize(sub, (ew, eh), interpolation=cv2.INTER_LINEAR), cv2.COLOR_RGB2BGR)
        Ml = np.hstack([A, (b - (rx1, ry1))[:, None]])
        size = (rx2 - rx1, ry2 - ry1)
        f = cv2.warpAffine(face, Ml, size, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
        a = cv2.warpAffine(self.alpha, Ml, size, flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
        roi = out[ry1:ry2, rx1:rx2].astype(np.float32)
        m = a[..., 0] > 0.5
        if m.sum() > 50:  # match the face's colour to the clip's light in this frame
            mu_f, mu_r = f[m].mean(0), roi[m].mean(0)
            sd_f, sd_r = f[m].std(0) + 1e-3, roi[m].std(0) + 1e-3
            f = (f - mu_f) * np.clip(sd_r / sd_f, 0.85, 1.15) + mu_f + np.clip(mu_r - mu_f, -20, 20)
        out[ry1:ry2, rx1:rx2] = np.clip(f * a + roi * (1 - a), 0, 255).astype(np.uint8)
        return out


class StillBody:
    """No clip: the static half-body canvas (the V2 behaviour)."""

    def __init__(self, compositor):
        self.c = compositor

    def __call__(self, face_rgb, n):
        return self.c(face_rgb) if face_rgb is not None else self.c.body.copy()


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
        self.tape = []  # her side of the call as played (speech and silences), for the offline engines
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
                    self.out.put((g, f, audio[i * 640:(i + 1) * 640]))
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
            frame = self.compose(frame, n)
            if talking != was:
                self.send({"type": "mode", "mode": "speaking" if talking else "listening"}); was = talking
            self.tape.append(audio)
            for q, item in ((self.video_q, frame), (self.audio_q, audio[:320]), (self.audio_q, audio[320:])):
                if q.full():
                    q.get_nowait()
                q.put_nowait(item)
            n += 1
            await asyncio.sleep(max(0, t0 + n / FPS - time.time()))

    def save_tape(self):
        if not self.tape or getattr(self, "saved", False):
            return
        import wave
        self.saved = True; os.makedirs("/workspace/out", exist_ok=True)
        path = time.strftime("/workspace/out/call_%H%M%S.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes(np.concatenate(self.tape).tobytes())
        log(f"tape {path} {len(self.tape) / FPS:.1f}s")

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
            await asyncio.sleep(2); self.save_tape()

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
                call.save_tape()
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
    ap.add_argument("--body", default=None, help="half-body gesture clip (mp4) to play under the live face")
    ap.add_argument("--port", type=int, default=8010)
    a = ap.parse_args()
    cond, body, box = canvas_and_box(a.portrait)
    compose = BodyLoop(a.body, body, box) if a.body else StillBody(Compositor(body, box))
    engine = Engine(a.ckpt, a.wav2vec, cond, a.model)
    t0 = time.time()
    idle = []
    for _ in range(4):  # warm-up (pays torch.compile) and the idle loop: ~3.8 s of the being listening
        idle += list(engine.run(np.zeros(engine.chunk, np.float32)))
    idle = idle[len(idle) // 4:] + idle[len(idle) // 4:][::-1]  # ping-pong, skipping the first warm-up chunk
    engine.reset()
    log(f"warm-up and idle loop in {time.time() - t0:.1f}s ({len(idle)} frames); listening on :{a.port}")
    web.run_app(make_app(engine, compose, idle), port=a.port, print=None)


if __name__ == "__main__":
    main()

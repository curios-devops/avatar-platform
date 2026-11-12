"""MuseTalk (LiveTalking, real time) on the benchmark's audio: plays the browser's part over WebRTC (aiortc), sends the
same WAV the other engines get through /humanaudio, records what comes back (video + audio) and measures the time
from sending the audio to the first audible frame. Runs on the pod, inside the meya-livetalking image.

    python bench_client.py <avatar_id> <audio.wav> <out.mp4>
"""
import asyncio, json, sys, time, wave

import aiohttp, numpy as np
from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration
from aiortc.contrib.media import MediaRecorder
from aiortc.mediastreams import MediaStreamTrack

BASE = "http://127.0.0.1:8010"
AVATAR, WAV, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
with wave.open(WAV) as w:
    AUDIO_S = w.getnframes() / w.getframerate()


class Proxy(MediaStreamTrack):
    def __init__(self, kind, q):
        super().__init__(); self.kind = kind; self.q = q

    async def recv(self):
        return await self.q.get()


async def main():
    pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
    pc.addTransceiver("video", direction="recvonly")
    pc.addTransceiver("audio", direction="recvonly")
    feed = {"video": asyncio.Queue(), "audio": asyncio.Queue()}
    rec = MediaRecorder(OUT)
    rec.addTrack(Proxy("video", feed["video"])); rec.addTrack(Proxy("audio", feed["audio"]))
    stats = {"video": 0, "sent": None, "first_audio": None, "first_video": None}

    @pc.on("track")
    def on_track(track):
        async def pump():
            while True:
                try:
                    f = await track.recv()
                except Exception:
                    return
                if track.kind == "video":
                    stats["video"] += 1
                    stats["first_video"] = stats["first_video"] or time.time()
                elif stats["sent"] and not stats["first_audio"] and np.abs(f.to_ndarray()).max() > 800:
                    stats["first_audio"] = time.time()
                await feed[track.kind].put(f)
        asyncio.ensure_future(pump())

    t_offer = time.time()
    await pc.setLocalDescription(await pc.createOffer())
    async with aiohttp.ClientSession() as s:
        r = await s.post(f"{BASE}/offer", json={"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "avatar": AVATAR})
        ans = await r.json(content_type=None)
        await pc.setRemoteDescription(RTCSessionDescription(sdp=ans["sdp"], type=ans["type"]))
        await rec.start()
        await asyncio.sleep(2)  # the idle loop first, as a call would show it
        form = aiohttp.FormData(); form.add_field("sessionid", str(ans["sessionid"]))
        form.add_field("file", open(WAV, "rb"), filename="line.wav", content_type="audio/wav")
        stats["sent"] = time.time()
        await s.post(f"{BASE}/humanaudio", data=form)
        await asyncio.sleep(AUDIO_S + 2.5)
        t_end = time.time()
        await rec.stop(); await pc.close()
    print(json.dumps({
        "engine": "musetalk", "avatar": AVATAR, "audio_s": round(AUDIO_S, 2),
        "first_frame_after_offer_s": round(stats["first_video"] - t_offer, 3) if stats["first_video"] else None,
        "latency_audio_to_first_sound_s": round(stats["first_audio"] - stats["sent"], 3) if stats["first_audio"] else None,
        "fps_received": round(stats["video"] / (t_end - stats["first_video"]), 1) if stats["first_video"] else 0,
    }))


asyncio.run(main())

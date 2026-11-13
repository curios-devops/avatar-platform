"""Dump FlashHead's raw 512 px face frames for an audio file (the live engine, chunk by chunk, silences included), so the
compositing can be tuned offline on a laptop (compose_offline.py). Writes <out>.mp4 (near lossless) and <out>.json
(per-frame 'talking' from the audio level, chunk timings).
    FLASHHEAD_DIR=/workspace/fh python fh_dump.py --portrait jin.jpg --audio talk.wav --out /workspace/out/fh_raw
"""
import argparse, json, subprocess, time
import numpy as np, soundfile as sf
from fh_server import Engine, canvas_and_box, SR, FPS

ap = argparse.ArgumentParser()
ap.add_argument("--portrait"); ap.add_argument("--audio"); ap.add_argument("--out")
ap.add_argument("--ckpt", default="/workspace/models/SoulX-FlashHead-1_3B"); ap.add_argument("--wav2vec", default="/workspace/models/wav2vec2-base-960h")
a = ap.parse_args()
cond, _, _ = canvas_and_box(a.portrait)
e = Engine(a.ckpt, a.wav2vec, cond, "lite")
for _ in range(2):
    e.run(np.zeros(e.chunk, np.float32))
e.reset()
pcm, sr = sf.read(a.audio, dtype="float32")
assert sr == SR, sr
pcm = np.concatenate([pcm, np.zeros((-len(pcm)) % e.chunk, np.float32)])
ff = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "512x512", "-r", str(FPS),
                       "-i", "-", "-c:v", "libx264", "-crf", "8", "-pix_fmt", "yuv444p", a.out + ".mp4"], stdin=subprocess.PIPE)
talking, times = [], []
for k in range(0, len(pcm), e.chunk):
    piece = pcm[k:k + e.chunk]
    t = time.time(); frames = e.run(piece); times.append(round(time.time() - t, 3))
    for i, f in enumerate(frames):
        ff.stdin.write(np.ascontiguousarray(f).tobytes())
        s = piece[i * 640:(i + 1) * 640]
        talking.append(bool(np.sqrt((s ** 2).mean()) > 0.01))
ff.stdin.close(); ff.wait()
json.dump({"talking": talking, "chunk_s": times, "chunk_audio_s": e.chunk / SR}, open(a.out + ".json", "w"))
print("frames", len(talking), "chunks", len(times), "mean chunk", np.mean(times))

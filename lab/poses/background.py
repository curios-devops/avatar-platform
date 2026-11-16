"""Backgrounds on body clips, frame by frame: the recorded poses (prepare.py) or any other clips of a being, placed on
the same scene its photo uses, so the live call keeps one background while the clips change underneath the face.

    backend/.venv/bin/python lab/poses/background.py <clips_dir> <scene.webp|png|jpg|blur> <out_dir>

Same cut-out as the web (MediaPipe selfie multiclass: hair is its own class), plus what a video needs and a photo
does not: the mask is smoothed over time (an exponential average) so edges do not shimmer from frame to frame.
Audio files next to the clips are copied as they are. CPU only, about a second per second of clip at 480x704.
"""
import pathlib
import shutil
import subprocess
import sys
import urllib.request

import cv2
import mediapipe as mp
import numpy as np

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite"
MODEL = pathlib.Path.home() / ".cache/mediapipe/selfie_multiclass_256x256.tflite"
SMOOTH = 0.6  # weight of the new mask per frame


def model() -> str:
    if not MODEL.exists():
        MODEL.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(MODEL_URL, MODEL)  # 16 MB, once
    return str(MODEL)


def scene_for(arg: str, w: int, h: int):
    if arg == "blur":
        return None
    img = cv2.imread(arg)
    if img is None:
        raise SystemExit(f"cannot read background {arg}")
    s = max(w / img.shape[1], h / img.shape[0])
    img = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    t, l = (img.shape[0] - h) // 2, (img.shape[1] - w) // 2
    return img[t:t + h, l:l + w].astype(np.float32)


def smoothstep(p):
    x = np.clip((p - 0.3) / 0.4, 0, 1)
    return x * x * (3 - 2 * x)


def clip_on_scene(src: pathlib.Path, dst: pathlib.Path, bg_arg: str, seg):
    cap = cv2.VideoCapture(str(src))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scene = scene_for(bg_arg, w, h)
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
                           "-i", "-", "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(dst)],
                          stdin=subprocess.PIPE)
    prev, i = None, 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        r = seg.segment_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)), int(i * 1000 / fps))
        person = 1 - r.confidence_masks[0].numpy_view()
        person = cv2.resize(person, (w, h), interpolation=cv2.INTER_LINEAR)
        prev = person if prev is None else SMOOTH * person + (1 - SMOOTH) * prev
        a = cv2.GaussianBlur(smoothstep(prev), (0, 0), max(1.0, w / 700))[..., None]
        back = cv2.GaussianBlur(frame, (0, 0), max(w, h) / 60).astype(np.float32) if scene is None else scene
        out = frame.astype(np.float32) * a + back * (1 - a)
        ff.stdin.write(np.clip(out, 0, 255).astype(np.uint8).tobytes())
        i += 1
    cap.release()
    ff.stdin.close()
    ff.wait()
    return i


def main():
    src, bg_arg, out = pathlib.Path(sys.argv[1]), sys.argv[2], pathlib.Path(sys.argv[3])
    out.mkdir(parents=True, exist_ok=True)
    for clip in sorted(src.glob("*.mp4")):
        opts = mp.tasks.vision.ImageSegmenterOptions(base_options=mp.tasks.BaseOptions(model_asset_path=model()),
                                                     running_mode=mp.tasks.vision.RunningMode.VIDEO, output_confidence_masks=True,
                                                     output_category_mask=False)
        with mp.tasks.vision.ImageSegmenter.create_from_options(opts) as seg:  # one per clip: timestamps restart
            n = clip_on_scene(clip, out / clip.name, bg_arg, seg)
        print(f"{clip.name}: {n} frames", flush=True)
    for audio in [*src.glob("*.mp3"), *src.glob("*.wav")]:
        shutil.copy2(audio, out / audio.name)


if __name__ == "__main__":
    main()

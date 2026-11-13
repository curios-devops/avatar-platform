"""EchoMimicV3 preview with the authors' own settings (infer_preview.py: Flow sampler, 25 steps, text CFG 4, audio CFG 2.9,
dynamic CFG, negative prompt for hands, 113-frame windows with 8 frames of overlap, 768x768 area). Only the paths, the
input and the prompt are ours.  Run inside /workspace/em with its venv:
    python /workspace/run_em_preview.py <portrait.png> <audio.wav> <out_dir>
"""
import os, shutil, sys, time
sys.path.insert(0, os.getcwd())
import infer_preview as ip

PROMPT = ("A young man sits at his desk in a bright home office and talks to the camera like a friendly tech creator. As the "
          "video progresses, he speaks with natural, expressive hand gestures above the desk and light head and shoulder "
          "movement, consistent with an engaged speaking posture; when he pauses he listens calmly with his hands resting "
          "on the desk. Don't blink too often. Preserve background integrity matching the reference image's spatial "
          "configuration, lighting conditions, and color temperature.")
img, wav, out = sys.argv[1:4]
base = "/workspace/em_data"
for d in ("imgs", "audios", "prompts"):
    os.makedirs(f"{base}/{d}", exist_ok=True)
shutil.copy(img, f"{base}/imgs/jin.png"); shutil.copy(wav, f"{base}/audios/jin.wav")
open(f"{base}/prompts/jin.txt", "w").write(PROMPT)
W = "/workspace/models"
orig = ip.Config.__init__


def init(self):
    orig(self)
    self.model_name = f"{W}/em/Wan2.1-Fun-V1.1-1.3B-InP"
    self.transformer_path = f"{W}/em/preview/transformer/diffusion_pytorch_model.safetensors"
    self.wav2vec_model_dir = f"{W}/wav2vec2-base-960h"
    self.base_dir, self.test_name_list, self.save_path = base + "/", ["jin"], out
    # 24 GB cards: the README's own advice, shorter windows (113 -> 81 frames) keep the 768 px area
    self.partial_video_length = int(os.environ.get("EM_PARTIAL", 113))
    side = int(os.environ.get("EM_SIDE", 768)); self.sample_size = [side, side]


ip.Config.__init__ = init
t = time.time(); ip.main(); print(f"EM_PREVIEW_SECONDS {time.time() - t:.1f}", flush=True)

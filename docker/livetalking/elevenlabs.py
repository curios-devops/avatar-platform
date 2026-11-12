"""ElevenLabs streaming TTS for LiveTalking: PCM 16 kHz chunks go to the lip-sync as they arrive (low first-word latency)."""
import os
import time

import numpy as np
import requests

from utils.logger import logger
from .base_tts import BaseTTS, State
from registry import register


@register("tts", "elevenlabs")
class ElevenLabsTTS(BaseTTS):
    def txt_to_audio(self, msg):
        text, textevent = msg
        voice = textevent.get("tts", {}).get("voice") or self.opt.REF_FILE or "SDVJaMLoJa7wc3s2sn7d"
        t0 = time.time()
        res = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_16000",
            headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "content-type": "application/json"},
            json={"text": text, "model_id": os.environ.get("EL_MODEL", "eleven_v4_turbo"),
                  "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "speed": 1.05}},
            stream=True, timeout=30)
        if not res.ok:
            logger.error("elevenlabs %s %s", res.status_code, res.text[:200])
            return
        buf = b""
        first = True
        idx = 0
        for part in res.iter_content(chunk_size=self.chunk * 2):
            if self.state != State.RUNNING:
                break
            buf += part
            while len(buf) >= self.chunk * 2:
                frame = np.frombuffer(buf[: self.chunk * 2], dtype=np.int16).astype(np.float32) / 32768.0
                buf = buf[self.chunk * 2:]
                event = {}
                if first:
                    logger.info(f"LATENCY elevenlabs first audio {time.time() - t0:.3f}s")
                    event = {"status": "start", "text": text}
                    first = False
                event.update(**textevent)
                self.parent.put_audio_frame(frame, event)
                idx += 1
        if self.state == State.RUNNING:
            self.parent.put_audio_frame(np.zeros(self.chunk, np.float32), {"status": "end", "text": text, **textevent})
        logger.info(f"elevenlabs done {time.time() - t0:.3f}s, {idx * 0.02:.2f}s of audio")

"""Body states for MuseTalk + LiveTalking (round 2). Run from LiveTalking's root (/opt/lt) on a meya-livetalking pod.

  listening   while the being is silent, LiveTalking's own custom silent video plays (audiotype 1): the listening clip,
              lips closed, no lip sync needed. Configured from MEYA_CUSTOM_CONFIG when the offer brings none.
  explaining  while it talks, MuseTalk paints the mouth on the avatar video. The avatar is built from the explaining
  emphasis    clip followed by the emphasis clip; MEYA_SEGMENTS='{"explain":[0,250],"emphasis":[250,500]}' names the
              frame ranges, and the ping-pong loop stays inside the chosen one.
  choice      the MEYA bridge reads each answer's text (agent_response) and picks the segment: lists and strong
              statements -> emphasis (its clip counts on fingers), the rest -> explaining. A new choice restarts the
              segment from its first frame (all clips start from the portrait's pose).
Also: a 0.2 s cross-fade between listening and talking, and no "LiveTalking" text drawn on every frame.
"""
from pathlib import Path

p = Path("avatars/base_avatar.py"); s = p.read_text()
if "seg_index" not in s:
    s = s.replace("        self.custom_audiotype = 0 # 0: normal, 1: sinlence, >1: custom audio\n",
                  "        self.custom_audiotype = 0 # 0: normal, 1: sinlence, >1: custom audio\n"
                  "        import json as _json, os as _os\n"
                  "        self.body_segments = _json.loads(_os.environ.get('MEYA_SEGMENTS') or 'null')\n"
                  "        self.body_segment = 'explain'\n", 1)
    s = s.replace("    def get_avatar_length(self):",
                  "    def seg_index(self, length, k):\n"
                  "        seg = self.body_segments.get(self.body_segment) if self.body_segments else None\n"
                  "        if not seg:\n"
                  "            return mirror_index(length, k)\n"
                  "        return seg[0] + mirror_index(seg[1] - seg[0], k)\n\n"
                  "    def get_avatar_length(self):", 1)
    old = "                t = time.perf_counter()\n\n                pred = self.inference_batch(index, audiofeat_batch)"
    assert old in s
    s = s.replace(old, "                if self.body_segment != getattr(self, '_last_segment', None):\n"
                       "                    index = 0; self._last_segment = self.body_segment\n"
                       "                    logger.info(f'body segment {self.body_segment}')\n" + old, 1)
    old = "                    self.res_frame_queue.put((res_frame, audio_frames[i*2:i*2+2], mirror_index(length, index)))"
    assert old in s
    s = s.replace(old, "                    self.res_frame_queue.put((res_frame, audio_frames[i*2:i*2+2], self.seg_index(length, index)))", 1)
    s = s.replace("        enable_transition = False  # 设置为False禁用过渡效果，True启用", "        enable_transition = True  # MEYA: soft cut between listening and talking", 1)
    s = s.replace("            _transition_duration = 0.1  # 过渡时间", "            _transition_duration = 0.2  # 过渡时间", 1)
    s = s.replace('            cv2.putText(combine_frame, "LiveTalking", (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128,128,128), 1)\n', "", 1)
    p.write_text(s)

p = Path("avatars/musetalk_avatar.py"); s = p.read_text()
old = "            idx = mirror_index(length, index + i)\n            latent = self.input_latent_list_cycle[idx]"
if old in s:
    p.write_text(s.replace(old, "            idx = self.seg_index(length, index + i)\n            latent = self.input_latent_list_cycle[idx]", 1))

p = Path("app.py"); s = p.read_text()
old = "    custom_config=params.get('custom_config','') #动作编排配置"
if old in s and "MEYA_CUSTOM_CONFIG" not in s:
    p.write_text(s.replace(old, "    custom_config=params.get('custom_config','') or os.environ.get('MEYA_CUSTOM_CONFIG','') #动作编排配置", 1))

p = Path("el_bridge.py"); s = p.read_text()
if "segment_for" not in s:
    s = s.replace("CHUNK = 320  # 20 ms at 16 kHz",
                  "CHUNK = 320  # 20 ms at 16 kHz\n\n"
                  "import re as _re\n"
                  "_EMPH = _re.compile(r'\\b(primero|segundo|tercero|uno|dos|tres|ojo|importante|clave|lo mejor|incre[ií]ble|s[ií] o s[ií]|'\n"
                  "                    r'first|second|third|important|key|amazing)\\b', _re.I)\n\n\n"
                  "def segment_for(text: str) -> str:\n"
                  "    \"\"\"Which body clip goes with this answer: lists and strong statements -> emphasis, the rest -> explaining.\"\"\"\n"
                  "    hits = len(_EMPH.findall(text)) + max(0, text.count('!') - 1)\n"
                  "    return 'emphasis' if hits >= 2 else 'explain'\n", 1)
    old = '        elif kind == "agent_response":\n'
    assert old in s
    s = s.replace(old, old + '            text = m["agent_response_event"]["agent_response"]\n'
                             '            self.avatar.body_segment = segment_for(text)\n'
                             '            logger.info(f"bridge: body {self.avatar.body_segment} for: {text[:60]}")\n', 1)
    p.write_text(s)
print("patched", all(x in Path(f).read_text() for x, f in (("seg_index", "avatars/base_avatar.py"), ("seg_index", "avatars/musetalk_avatar.py"),
                                                           ("MEYA_CUSTOM_CONFIG", "app.py"), ("segment_for", "el_bridge.py"))))

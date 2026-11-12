"""Patches LiveTalking (run from its root): MuseTalk paste-back near the frame edge, and the MEYA agent bridge."""
from pathlib import Path

p = Path("avatars/musetalk/myutil.py"); s = p.read_text()
old = '''    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
'''
new = '''    x, y, x1, y1 = face_box
    x_s, y_s, x_e, y_e = crop_box
    # The mask's crop box can stick out of the frame (negative x when the face nears the edge): clip box and mask.
    H, W = body.shape[:2]
    mh, mw = mask_array.shape[:2]
    mask_array = mask_array[max(0, -y_s):mh - max(0, y_e - H), max(0, -x_s):mw - max(0, x_e - W)]
    x_s, y_s, x_e, y_e = max(0, x_s), max(0, y_s), min(W, x_e), min(H, y_e)
    # The face box can stick out of the crop box too: keep the overlap.
    fx0, fy0 = max(0, x_s - x), max(0, y_s - y)
    fx1, fy1 = face.shape[1] - max(0, x1 - x_e), face.shape[0] - max(0, y1 - y_e)
    face = face[fy0:fy1, fx0:fx1]
    x, y, x1, y1 = max(x, x_s), max(y, y_s), min(x1, x_e), min(y1, y_e)
'''
if "clip box and mask" not in s:
    assert old in s; p.write_text(s.replace(old, new, 1))

p = Path("server/rtc_manager.py"); s = p.read_text()
if "el_bridge" not in s:
    s = s.replace("async def _create_pc_and_answer(self, avatar_session, sessionid, offer):",
                  "async def _create_pc_and_answer(self, avatar_session, sessionid, offer, params=None):")
    s = s.replace("        self.pcs.add(pc)\n", "        self.pcs.add(pc)\n        if params and params.get('agent'):\n            from el_bridge import attach\n            attach(pc, avatar_session, params['agent'])\n", 1)
    s = s.replace("            session_manager.get_session(sessionid), sessionid, offer\n        )", "            session_manager.get_session(sessionid), sessionid, offer, params\n        )", 1)
    p.write_text(s)
print("patched", "el_bridge" in Path("server/rtc_manager.py").read_text())

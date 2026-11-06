"""Capybara for the web: low-poly retopology (v2.0 Smart with baked texture, 30 credits; v1.0 cannot bake), quadruped rig (25), walk (10).

    python tripo/capybara_chain.py <text-to-model task id> <out dir>
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tripo  # noqa: E402

src, out = sys.argv[1], Path(sys.argv[2])
low = tripo.run("/mesh/decimate", {"input": src, "model": "v2.0", "face_limit": 20000, "bake": True}, out, "lowpoly")
rig = tripo.run("/animations/rig", {"input": low["task_id"], "model": "v2.5-20260210",
                                     "rig_type": "quadruped", "out_format": "glb"}, out, "rig")
tripo.run("/animations/retarget", {"input": rig["task_id"],
                                   "animation": "preset:quadruped:walk", "out_format": "glb"}, out, "walk")
print("balance", tripo.balance())

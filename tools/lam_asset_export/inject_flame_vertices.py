"""Blender-free LAM skin.glb vertex injection.

Overwrites the base-mesh POSITION block of a template skin.glb with a new
avatar's FLAME vertices (same topology/order), keeping the skeleton, skin
weights and all 51 ARKit morph-target deltas from the template. This is the
only per-avatar step the LAM export needs Blender for today (Blender otherwise
just does FBX->GLB format conversion + a fixed vertex_order.json).

Usage (round-trip self-test): inject_flame_vertices.py in.glb out.glb
  -> re-injects the template's own vertices (identity), proving the read/write
     path is lossless.
Real use: pass a (20018,3) float32 array of FLAME vertices.
"""
import json, struct, sys
import numpy as np


def load_glb(path):
    with open(path, "rb") as f:
        magic, ver, total = struct.unpack("<III", f.read(12))
        assert magic == 0x46546C67
        chunks = []
        while f.tell() < total:
            clen, ctype = struct.unpack("<II", f.read(8))
            chunks.append((ctype, f.read(clen)))
    gltf = json.loads(chunks[0][1])
    bin_blob = bytearray(chunks[1][1])
    return gltf, bin_blob


def save_glb(path, gltf, bin_blob):
    json_bytes = json.dumps(gltf, separators=(",", ":")).encode()
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b" " * json_pad
    bin_pad = (4 - len(bin_blob) % 4) % 4
    bin_blob = bytes(bin_blob) + b"\x00" * bin_pad
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A)); f.write(json_bytes)
        f.write(struct.pack("<II", len(bin_blob), 0x004E4942)); f.write(bin_blob)


def inject(gltf, bin_blob, verts):
    # POSITION of mesh 0 / primitive 0
    acc_i = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    acc = gltf["accessors"][acc_i]
    assert acc["type"] == "VEC3" and acc["componentType"] == 5126
    n = acc["count"]
    assert verts.shape == (n, 3), f"expected ({n},3), got {verts.shape}"
    bv = gltf["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    data = verts.astype("<f4").tobytes()
    assert len(data) == n * 12
    bin_blob[off:off + len(data)] = data
    # glTF requires correct POSITION min/max
    acc["min"] = verts.min(0).tolist()
    acc["max"] = verts.max(0).tolist()
    return acc_i, n


def read_positions(gltf, bin_blob):
    acc_i = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]
    acc = gltf["accessors"][acc_i]
    bv = gltf["bufferViews"][acc["bufferView"]]
    off = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    n = acc["count"]
    return np.frombuffer(bytes(bin_blob[off:off + n * 12]), "<f4").reshape(n, 3)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    gltf, blob = load_glb(src)
    verts = read_positions(gltf, blob)          # round-trip: its own verts
    print("read POSITION:", verts.shape, "bbox", verts.min(0).round(3), verts.max(0).round(3))
    inject(gltf, blob, verts)
    save_glb(dst, gltf, blob)
    # verify by reloading
    g2, b2 = load_glb(dst)
    v2 = read_positions(g2, b2)
    print("round-trip max abs diff:", float(np.abs(v2 - verts).max()))
    print("morph targets preserved:", len(g2["meshes"][0]["primitives"][0].get("targets", [])))
    print("skins preserved:", len(g2.get("skins", [])), " nodes:", len(g2.get("nodes", [])))

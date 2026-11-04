"""Bakes an Anny body (NAVER, Apache-2.0) plus MakeHuman CC0 proxies into one skinned glTF.

The output is a GLB the three.js creator loads as is:
  - one skin with Anny's 104-bone rig, posed in its rest (T) pose for the requested shape;
  - the body, eyes, teeth, tongue, brows, lashes, hair and clothes as skinned meshes that share it;
  - the 52 ARKit facial actions as morph targets on every mesh they move (lip sync, blinks, emotions);
  - textures are not embedded: each material names its files in `extras` and the client loads them
    from the asset route, so a skin change costs no re-bake.

Coordinates: Anny is Z-up with the front at -Y, in meters. glTF is Y-up with the front at +Z,
so every point and matrix goes through R below, and the feet are moved to y = 0.
"""
from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
import torch

ASSETS = Path(__file__).parent / "assets_src"
SYSTEM = ASSETS / "makehuman_system_assets_cc0"
R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)


@lru_cache(maxsize=1)
def models():
    import anny

    kwargs = dict(phenotypes="all", local_changes="default", facial_actions="all")
    full = anny.Anny(topology="makehuman", **kwargs).to(dtype=torch.float32)  # every hm08 vertex, helpers included
    body = anny.Anny(topology="anny", **kwargs).to(dtype=torch.float32)  # clean triangulated body + UVs
    return full, body


# --------------------------------------------------------------------------------------------- assets


@dataclass
class Proxy:
    """A MakeHuman .mhclo: each vertex is a weighted triangle of base-mesh vertices plus a scaled offset."""

    name: str
    kind: str
    refs: np.ndarray  # (n, 3) base vertex indices
    weights: np.ndarray  # (n, 3)
    offsets: np.ndarray  # (n, 3) in MakeHuman axes, before scaling
    scales: dict[str, tuple[int, int, float]]
    positions_uv: tuple[np.ndarray, np.ndarray, np.ndarray]  # (faces as vertex idx, faces as uv idx, uvs)
    delete_verts: np.ndarray
    material: dict = field(default_factory=dict)
    z_depth: int = 50


def _parse_obj(path: Path):
    uvs, faces_v, faces_t = [], [], []
    for line in path.read_text(errors="ignore").splitlines():
        if line.startswith("vt "):
            u, v = line.split()[1:3]
            uvs.append((float(u), float(v)))
        elif line.startswith("f "):
            corners = [c.split("/") for c in line.split()[1:]]
            vi = [int(c[0]) - 1 for c in corners]
            ti = [int(c[1]) - 1 if len(c) > 1 and c[1] else int(c[0]) - 1 for c in corners]
            for k in range(1, len(vi) - 1):  # fan-triangulate quads
                faces_v.append((vi[0], vi[k], vi[k + 1]))
                faces_t.append((ti[0], ti[k], ti[k + 1]))
    return np.array(faces_v, np.int64), np.array(faces_t, np.int64), np.array(uvs, np.float64)


def _parse_mhmat(path: Path) -> dict:
    mat: dict = {}
    if not path.exists():
        return mat
    for line in path.read_text(errors="ignore").splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or line.startswith("#"):
            continue
        key, value = parts
        if key in ("diffuseTexture", "normalmapTexture", "aomapTexture", "specularmapTexture", "transparencymapTexture"):
            mat[key] = str((path.parent / value.strip()).resolve().relative_to(ASSETS.resolve()))
        elif key in ("diffuseColor",):
            mat[key] = [float(x) for x in value.split()]
        elif key in ("transparent", "backfaceCull", "alphaToCoverage"):
            mat[key] = value.strip() == "True"
        elif key in ("opacity", "shininess"):
            mat[key] = float(value)
    return mat


@lru_cache(maxsize=None)
def load_proxy(mhclo: str) -> Proxy:
    path = ASSETS / mhclo
    refs, weights, offsets, deletes = [], [], [], []
    scales: dict[str, tuple[int, int, float]] = {}
    obj_file = material = None
    z_depth, section = 50, None

    def add_deletes(nums: list[str]):
        i = 0
        while i < len(nums):
            if i + 2 < len(nums) and nums[i + 1] == "-":
                deletes.extend(range(int(nums[i]), int(nums[i + 2]) + 1))
                i += 3
            else:
                deletes.append(int(nums[i]))
                i += 1

    for raw in path.read_text(errors="ignore").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if section == "delete" and parts[0][0].isdigit():
            add_deletes(parts)
            continue
        if section == "verts" and parts[0][0].isdigit():
            if len(parts) == 1:
                refs.append((int(parts[0]),) * 3)
                weights.append((1.0, 0.0, 0.0))
                offsets.append((0.0, 0.0, 0.0))
            else:
                refs.append(tuple(int(p) for p in parts[:3]))
                weights.append(tuple(float(p) for p in parts[3:6]))
                offsets.append(tuple(float(p) for p in parts[6:9]))
            continue
        # some files put other keys (material, weights) between "verts 0" and the vertex rows
        key = parts[0]
        if key == "verts":
            section = "verts"
        elif key in ("x_scale", "y_scale", "z_scale"):
            scales[key[0]] = (int(parts[1]), int(parts[2]), float(parts[3]))
        elif key == "obj_file":
            obj_file = parts[1]
        elif key == "material":
            material = line.split(None, 1)[1]
        elif key == "z_depth":
            z_depth = int(parts[1])
        elif key == "delete_verts":
            section = "delete"
            add_deletes(parts[1:])
    faces_v, faces_t, uvs = _parse_obj(path.parent / obj_file)
    kind = mhclo.split("/")[1] if "/" in mhclo else "clothes"
    return Proxy(
        name=path.stem,
        kind=kind,
        refs=np.array(refs, np.int64),
        weights=np.array(weights, np.float64),
        offsets=np.array(offsets, np.float64),
        scales=scales,
        positions_uv=(faces_v, faces_t, uvs),
        delete_verts=np.array(sorted(set(deletes)), np.int64),
        material=_parse_mhmat(path.parent / material) if material else {},
        z_depth=z_depth,
    )


def fit_proxy(proxy: Proxy, base_mh: np.ndarray) -> np.ndarray:
    """Proxy vertex positions for base vertices given in MakeHuman axes (batch, n, 3)."""
    tri = base_mh[:, proxy.refs]  # (b, n, 3, 3)
    pos = (tri * proxy.weights[None, :, :, None]).sum(axis=2)
    scale = np.ones((base_mh.shape[0], 3))
    for axis, k in (("x", 0), ("y", 1), ("z", 2)):
        if axis in proxy.scales:
            a, b, s = proxy.scales[axis]
            scale[:, k] = np.abs(base_mh[:, a, k] - base_mh[:, b, k]) / s
    return pos + proxy.offsets[None] * scale[:, None, :]


# --------------------------------------------------------------------------------------------- bake


@dataclass
class Shape:
    phenotype: dict[str, float] = field(default_factory=dict)
    local: dict[str, float] = field(default_factory=dict)

    def key(self) -> str:
        return hashlib.sha1(json.dumps([self.phenotype, self.local], sort_keys=True).encode()).hexdigest()[:16]


def _run(full, shape: Shape, facial: torch.Tensor):
    b = facial.shape[0]
    ph = {k: torch.full((b,), float(shape.phenotype.get(k, 0.5))) for k in full.phenotype_labels}
    lc = {k: torch.full((b,), float(v)) for k, v in shape.local.items() if k in full.local_change_labels}
    with torch.no_grad():
        out = full(phenotype_kwargs=ph, local_changes_kwargs=lc or None, facial_actions=facial)
    return out["rest_vertices"].numpy().astype(np.float64), out["rest_bone_poses"][0].numpy().astype(np.float64)


def _top4(indices: np.ndarray, weights: np.ndarray):
    order = np.argsort(-weights, axis=1)[:, :4]
    j = np.take_along_axis(indices, order, 1)
    w = np.take_along_axis(weights, order, 1)
    w = w / np.clip(w.sum(1, keepdims=True), 1e-8, None)
    return j.astype(np.uint16), w.astype(np.float32)


def _blend_weights(vbi: np.ndarray, vbw: np.ndarray, refs: np.ndarray, rw: np.ndarray, bones: int):
    """Skin weights of proxy vertices: the barycentric mix of their three base vertices' weights."""
    dense = np.zeros((refs.shape[0], bones))
    for k in range(3):
        idx, w = vbi[refs[:, k]], vbw[refs[:, k]] * rw[:, k : k + 1]
        np.add.at(dense, (np.repeat(np.arange(refs.shape[0]), idx.shape[1]), idx.ravel()), w.ravel())
    order = np.argsort(-dense, axis=1)[:, :4]
    w = np.take_along_axis(dense, order, 1)
    w = w / np.clip(w.sum(1, keepdims=True), 1e-8, None)
    return order.astype(np.uint16), w.astype(np.float32)


def _split_uv(faces_v: np.ndarray, faces_t: np.ndarray):
    """glTF needs one UV per vertex: duplicate vertices along UV seams."""
    pairs = np.stack([faces_v.ravel(), faces_t.ravel()], 1)
    uniq, inverse = np.unique(pairs, axis=0, return_inverse=True)
    return uniq[:, 0], uniq[:, 1], inverse.reshape(faces_v.shape)


def _normals(pos: np.ndarray, faces: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos)
    fn = np.cross(pos[faces[:, 1]] - pos[faces[:, 0]], pos[faces[:, 2]] - pos[faces[:, 0]])
    for k in range(3):
        np.add.at(n, faces[:, k], fn)
    return n / np.clip(np.linalg.norm(n, axis=1, keepdims=True), 1e-12, None)


def bake(shape: Shape, proxies: list[str], *, facial_morphs: bool = True) -> bytes:
    full, body = models()
    labels = list(full.facial_action_labels)
    facial = torch.zeros(1 + len(labels), len(labels))
    facial[1:] = torch.eye(len(labels))
    verts, bone_world = _run(full, shape, facial if facial_morphs else facial[:1])

    to_gltf = lambda p: p @ R.T  # noqa: E731
    floor = to_gltf(verts[0])[:, 1].min()
    shift = np.array([0.0, -floor, 0.0])
    world = np.repeat(np.eye(4)[None], bone_world.shape[0], 0)
    world[:, :3, :3] = R @ bone_world[:, :3, :3] @ R.T
    world[:, :3, 3] = to_gltf(bone_world[:, :3, 3]) + shift

    vbi = full.vertex_bone_indices.numpy()
    vbw = full.vertex_bone_weights.numpy().astype(np.float64)
    bones = full.bone_count
    mh_verts = verts @ R.T @ np.diag([1, 1, 1])  # MakeHuman axes == glTF axes (x right, y up, z front)
    gl_verts = mh_verts + shift

    meshes = []
    # body: Anny's clean topology, minus faces the clothes ask to hide
    bmvi = body.base_mesh_vertex_indices.numpy()
    faces = body.faces.numpy().astype(np.int64)
    if faces.shape[1] == 4:
        faces = np.concatenate([faces[:, [0, 1, 2]], faces[:, [0, 2, 3]]])
    faces_t = body.face_texture_coordinate_indices.numpy().astype(np.int64)
    hidden = np.zeros(len(full.template_vertices), bool)
    loaded = [load_proxy(p) for p in proxies]
    for p in loaded:
        hidden[p.delete_verts[p.delete_verts < len(hidden)]] = True
    # hm08 vertices from 13380 on are helpers; the Anny topology keeps the eyeball helpers, which would
    # render as skin over the eyes (the eye proxy draws the real ones)
    # The base mesh also carries low-poly eyeballs, skinned to the eye bones: drop them too.
    eye_bones = [list(full.bone_labels).index(b) for b in ("eye.L", "eye.R")]
    eye_w = np.where(np.isin(vbi, eye_bones), vbw, 0).sum(1)
    keep = ~hidden[bmvi[faces]].any(1) & (bmvi[faces] < 13380).all(1) & ~(eye_w[bmvi[faces]] > 0.5).all(1)
    v_idx, t_idx, tri = _split_uv(faces[keep], faces_t[keep])
    src = bmvi[v_idx]
    uv = body.texture_coordinates.numpy()[t_idx]
    j, w = _top4(vbi[src], vbw[src])
    meshes.append(
        dict(name="body", kind="body", pos=gl_verts[0, src], uv=uv, tri=tri, joints=j, weights=w,
             morphs=gl_verts[1:, src] - gl_verts[0:1, src], material={"name": "skin"}, z=0)
    )
    for p in loaded:
        pv = fit_proxy(p, gl_verts)  # (b, n, 3); proxy offsets are already in these axes
        fv, ft, uvs = p.positions_uv
        v_idx, t_idx, tri = _split_uv(fv, ft)
        j, w = _blend_weights(vbi, vbw, p.refs[v_idx], p.weights[v_idx], bones)
        meshes.append(
            dict(name=p.name, kind=p.kind, pos=pv[0, v_idx], uv=uvs[t_idx], tri=tri, joints=j, weights=w,
                 morphs=pv[1:, v_idx] - pv[0:1, v_idx], material=p.material, z=p.z_depth)
        )
    return _write_glb(meshes, world, full, labels if facial_morphs else [], shape)


# --------------------------------------------------------------------------------------------- glTF


def _write_glb(meshes, world, full, morph_names, shape: Shape) -> bytes:
    import pygltflib as g

    blob = bytearray()
    views, accessors = [], []

    def add(arr: np.ndarray, comp: int, typ: str, target=None, minmax=False) -> int:
        nonlocal blob
        while len(blob) % 4:
            blob += b"\0"
        data = np.ascontiguousarray(arr).tobytes()
        views.append(g.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data), target=target))
        blob += data
        acc = g.Accessor(bufferView=len(views) - 1, componentType=comp, count=len(arr), type=typ)
        if minmax:
            acc.min = arr.min(0).tolist()
            acc.max = arr.max(0).tolist()
        accessors.append(acc)
        return len(accessors) - 1

    def add_sparse(delta: np.ndarray) -> int:
        nonlocal blob
        moved = np.nonzero(np.abs(delta).max(1) > 1e-6)[0].astype(np.uint32)
        acc = g.Accessor(componentType=g.FLOAT, count=len(delta), type=g.VEC3,
                         min=(delta.min(0) if len(moved) else np.zeros(3)).tolist(),
                         max=(delta.max(0) if len(moved) else np.zeros(3)).tolist())
        if len(moved):
            for arr in (moved, delta[moved].astype(np.float32)):
                while len(blob) % 4:
                    blob += b"\0"
                data = np.ascontiguousarray(arr).tobytes()
                views.append(g.BufferView(buffer=0, byteOffset=len(blob), byteLength=len(data)))
                blob += data
            acc.sparse = g.Sparse(count=len(moved),
                                  indices=g.AccessorSparseIndices(bufferView=len(views) - 2, componentType=g.UNSIGNED_INT),
                                  values=g.AccessorSparseValues(bufferView=len(views) - 1))
        accessors.append(acc)
        return len(accessors) - 1

    nodes, parents = [], list(full.bone_parents)
    labels = list(full.bone_labels)
    for i, label in enumerate(labels):
        local = world[i] if parents[i] < 0 else np.linalg.inv(world[parents[i]]) @ world[i]
        rot = local[:3, :3]
        u, _, vt = np.linalg.svd(rot)
        rot = u @ vt
        quat = _quat(rot)
        nodes.append(g.Node(name=label, translation=local[:3, 3].tolist(), rotation=quat.tolist()))
    for i, p in enumerate(parents):
        if p >= 0:
            nodes[p].children = (nodes[p].children or []) + [i]
    ibm = np.stack([np.linalg.inv(m) for m in world]).astype(np.float32).transpose(0, 2, 1)  # column-major
    skin = g.Skin(joints=list(range(len(labels))), skeleton=0, inverseBindMatrices=add(ibm.reshape(-1, 16), g.FLOAT, g.MAT4))

    gl_meshes, materials = [], []
    for m in meshes:
        pos = m["pos"].astype(np.float32)
        tri = m["tri"].astype(np.uint32)
        attrs = g.Attributes(
            POSITION=add(pos, g.FLOAT, g.VEC3, g.ARRAY_BUFFER, minmax=True),
            NORMAL=add(_normals(m["pos"], m["tri"]).astype(np.float32), g.FLOAT, g.VEC3, g.ARRAY_BUFFER),
            TEXCOORD_0=add(np.stack([m["uv"][:, 0], 1 - m["uv"][:, 1]], 1).astype(np.float32), g.FLOAT, g.VEC2, g.ARRAY_BUFFER),
            JOINTS_0=add(m["joints"], g.UNSIGNED_SHORT, g.VEC4, g.ARRAY_BUFFER),
            WEIGHTS_0=add(m["weights"], g.FLOAT, g.VEC4, g.ARRAY_BUFFER),
        )
        targets, names = [], []
        for k, name in enumerate(morph_names):
            delta = m["morphs"][k]
            if np.abs(delta).max() > 1e-6:
                targets.append({"POSITION": add_sparse(delta.astype(np.float32))})
                names.append(name)
        mat = dict(m["material"])
        materials.append(g.Material(name=mat.get("name", m["name"]), extras={**mat, "kind": m["kind"], "zDepth": m["z"]},
                                    doubleSided=m["kind"] in ("hair", "eyebrows", "eyelashes")))
        prim = g.Primitive(attributes=attrs, indices=add(tri.ravel(), g.UNSIGNED_INT, g.SCALAR, g.ELEMENT_ARRAY_BUFFER),
                           material=len(materials) - 1, targets=targets or None)
        gl_meshes.append(g.Mesh(name=m["name"], primitives=[prim], extras={"targetNames": names} if names else None,
                                weights=[0.0] * len(names) if names else None))
        nodes.append(g.Node(name=m["name"], mesh=len(gl_meshes) - 1, skin=0))
    root = len(nodes)
    nodes.append(g.Node(name="human", children=[0] + list(range(len(labels), root))))
    gltf = g.GLTF2(
        asset=g.Asset(generator="avatar-platform human baker (Anny Apache-2.0 + MakeHuman CC0)"),
        scene=0, scenes=[g.Scene(nodes=[root])], nodes=nodes, meshes=gl_meshes, skins=[skin],
        materials=materials, accessors=accessors, bufferViews=views,
        buffers=[g.Buffer(byteLength=len(blob))],
        extras={"shape": {"phenotype": shape.phenotype, "local": shape.local}, "license": "Anny Apache-2.0; MakeHuman assets CC0"},
    )
    gltf.set_binary_blob(bytes(blob))
    return b"".join(gltf.save_to_bytes())


def _quat(m: np.ndarray) -> np.ndarray:
    """Rotation matrix to glTF quaternion (x, y, z, w)."""
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    return q / np.linalg.norm(q)


if __name__ == "__main__":
    import sys
    import time

    t = time.time()
    proxies = sys.argv[2:] or [
        "makehuman_system_assets_cc0/eyes/high-poly/high-poly.mhclo",
        "makehuman_system_assets_cc0/eyebrows/eyebrow001/eyebrow001.mhclo",
        "makehuman_system_assets_cc0/eyelashes/eyelashes01/eyelashes01.mhclo",
        "makehuman_system_assets_cc0/teeth/teeth_base/teeth_base.mhclo",
        "makehuman_system_assets_cc0/tongue/tongue01/tongue01.mhclo",
        "makehuman_system_assets_cc0/hair/short02/short02.mhclo",
        "makehuman_system_assets_cc0/clothes/male_casualsuit01/male_casualsuit01.mhclo",
        "makehuman_system_assets_cc0/clothes/shoes01/shoes01.mhclo",
    ]
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "out/human.glb")
    out.parent.mkdir(parents=True, exist_ok=True)
    models()
    print(f"models {time.time() - t:.1f}s")
    t = time.time()
    data = bake(Shape(phenotype={"gender": 1.0, "age": 0.5, "muscle": 0.6}), proxies)
    out.write_bytes(data)
    print(f"bake {time.time() - t:.2f}s -> {out} {len(data) / 1e6:.1f} MB")

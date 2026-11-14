"""Animation writing without the game files: a tiny trimesh scene plus a fake clip."""
import json
import os
import struct
import sys
import zlib

import numpy as np
import trimesh

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import anim_glb, caf  # noqa: E402


def _json(glb):
    length = struct.unpack_from("<I", glb, 12)[0]
    return json.loads(glb[20:20 + length])


def _scene():
    s = trimesh.Scene()
    m = np.eye(4)
    m[:3, 3] = [0, 0, 1]
    s.graph.update(frame_from=s.graph.base_frame, frame_to="Arm", matrix=m)
    s.add_geometry(trimesh.creation.box((0.1, 0.1, 0.5)), node_name="solid|steel|0", geom_name="solid|steel|0",
                   parent_node_name="Arm")
    return s.export(file_type="glb")


def test_add_animations():
    info = caf.ClipInfo(0, 30, 1, 0, 30)
    track = caf.Track(rot_t=np.array([0, 30], np.float32),
                      rot=np.array([[0, 0, 0, 1], [0, 0, -0.7071, -0.7071]], np.float32))   # second key flipped
    glb = anim_glb.add_animations(_scene(), [("swing", caf.Clip(info, {zlib.crc32(b"Arm"): track}),
                                              {zlib.crc32(b"Arm"): "Arm"})])
    js = _json(glb)
    arm = next(i for i, n in enumerate(js["nodes"]) if n.get("name") == "Arm")
    assert "matrix" not in js["nodes"][arm] and js["nodes"][arm]["translation"] == [0, 0, 1]
    (anim,) = js["animations"]
    assert anim["name"] == "swing"
    assert [c["target"] for c in anim["channels"]] == [{"node": arm, "path": "rotation"}]
    acc = js["accessors"][anim["samplers"][0]["input"]]
    assert acc["min"] == [0.0] and acc["max"] == [1.0]
    # trimesh can read the result back (valid buffers)
    assert len(trimesh.load(trimesh.util.wrap_as_stream(glb), file_type="glb").geometry) == 1


def test_no_matching_track_adds_nothing():
    clip = caf.Clip(caf.ClipInfo(0, 30, 1, 0, 30), {123: caf.Track(rot_t=np.zeros(1), rot=np.array([[0, 0, 0, 1.0]]))})
    js = _json(anim_glb.add_animations(_scene(), [("x", clip, {})]))
    assert "animations" not in js


def test_same_name_sources_merge():
    """One clip played on two instances (hull + landing gear leg) becomes one glTF animation."""
    s = trimesh.Scene()
    for name in ("A", "leg/A"):
        s.graph.update(frame_from=s.graph.base_frame, frame_to=name, matrix=np.eye(4))
        s.add_geometry(trimesh.creation.box((0.1, 0.1, 0.1)), node_name=f"solid|m|{name}", geom_name=f"g{name}",
                       parent_node_name=name)
    track = caf.Track(pos_t=np.array([0, 10], np.float32), pos=np.array([[0, 0, 0], [0, 0, 1]], np.float32))
    clip = caf.Clip(caf.ClipInfo(0, 30, 1, 0, 10), {zlib.crc32(b"A"): track})
    js = _json(anim_glb.add_animations(s.export(file_type="glb"), [
        ("extend", clip, {zlib.crc32(b"A"): "A"}), ("extend", clip, {zlib.crc32(b"A"): "leg/A"})]))
    (anim,) = js["animations"]
    names = {js["nodes"][c["target"]["node"]]["name"] for c in anim["channels"]}
    assert names == {"A", "leg/A"}

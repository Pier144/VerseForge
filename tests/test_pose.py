"""Still exports in the pose the viewer shows (export.posed)."""
import os
import sys
from types import SimpleNamespace

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import export, materials, model, rig  # noqa: E402

MAT = materials.Material("m", "", "solid", (0.5, 0.5, 0.5))
TRI = np.array([[0.0, 0, 0], [1, 0, 0], [0, 1, 0]])


def _model():
    hull = rig.Bone("hull", -1, np.eye(4), np.eye(4))
    leg_w = np.eye(4)
    leg_w[:3, 3] = (0, 0, -1)
    leg = rig.Bone("gear leg/a.1", 0, leg_w.copy(), leg_w)
    foot_w = np.eye(4)
    foot_w[:3, 3] = (0, 0, -2)
    foot = rig.Bone("foot", 1, np.linalg.inv(leg_w) @ foot_w, foot_w)   # never animated: follows the leg
    parts = [model.Part("body", MAT, TRI.copy(), np.array([[0, 1, 2]]), "x", node="hull"),
             model.Part("leg", MAT, TRI + (0, 0, -1), np.array([[0, 1, 2]]), "x", node="gear leg/a.1"),
             model.Part("foot", MAT, TRI + (0, 0, -2), np.array([[0, 1, 2]]), "x", node="foot")]
    m = model.Model("ship.cga", parts=parts, skeleton=[hull, leg, foot])
    sources = [("deploy", SimpleNamespace(tracks={7: None}), {7: "gear leg/a.1"})]
    return m, sources


def _column_major(m):
    return [float(x) for x in m.T.reshape(-1)]


def test_node_key_matches_three_js():
    assert export.node_key("gear leg/a.1") == "gear_lega1"
    assert export.node_key("a[0]:b") == "a0b"


def test_pose_moves_the_node_and_what_hangs_from_it():
    m, sources = _model()
    posed_w = np.eye(4)
    posed_w[:3, 3] = (0, 0, -1.5)                       # leg lowered by half a metre
    out = export.posed(m, sources, {"gear_lega1": _column_major(posed_w), "hull": _column_major(np.eye(4))})
    assert out is not m
    assert np.allclose(out.parts[0].vertices, m.parts[0].vertices)
    assert np.allclose(out.parts[1].vertices, m.parts[1].vertices + (0, 0, -0.5))
    assert np.allclose(out.parts[2].vertices, m.parts[2].vertices + (0, 0, -0.5))
    assert np.allclose(m.parts[1].vertices, TRI + (0, 0, -1))       # the cached model is untouched


def test_rotation_is_read_column_by_column():
    m, sources = _model()
    w = m.skeleton[1].world.copy()
    w[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]      # quarter turn about Z, about the leg's origin
    out = export.posed(m, sources, {"gear_lega1": _column_major(w)})
    assert np.allclose(out.parts[1].vertices, [[0, 0, -1], [0, 1, -1], [-1, 0, -1]])


def test_rest_pose_or_no_pose_returns_the_same_model():
    m, sources = _model()
    rest = {export.node_key(b.name): _column_major(b.world) for b in m.skeleton}
    assert export.posed(m, sources, rest) is m
    assert export.posed(m, sources, {}) is m
    assert export.posed(m, [], rest) is m
    assert export.posed(m, sources, {"gear_lega1": [1.0] * 5}) is m

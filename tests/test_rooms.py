"""Rooms of an interior: volumes (containers.room_of), how the GLB keeps them apart (export), and the real thing
on the Perseus (needs Data.p4k)."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from sc_explorer import assembly, containers, entities, export, materials, model  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
needs_game = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")
PERSEUS = "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga"


def _cube(lo, hi):
    """Closed box as 12 outward triangles."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    c = np.array([[x0, y0, z0], [x1, y0, z0], [x1, y1, z0], [x0, y1, z0],
                  [x0, y0, z1], [x1, y0, z1], [x1, y1, z1], [x0, y1, z1]], np.float64)
    f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
         (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    return c[np.array(f)]


def _rooms():
    big = containers.Room("a", "Room_RN_bunks", "", [(np.eye(4), "shape", ([(0, 0), (10, 0), (10, 6), (0, 6)], 3.0), 180.0)])
    shift = np.eye(4)
    shift[:3, 3] = (-2, -2, 0)                      # the toilet's box is centred on (2, 2, 1.5)
    small = containers.Room("b", "Room_RN_toilet", "", [(shift, "box", ((-1, -1, -1.5), (1, 1, 1.5)), 12.0)])
    mesh = containers.Room("c", "Room_RN_mess", "@vehicle_room_messhall", [(np.eye(4), "mesh", _cube((20, 0, 0), (26, 4, 3)), 72.0)])
    return [big, small, mesh]


def test_point_in_room_volumes():
    rooms = _rooms()
    assert containers.room_of(rooms, (8, 5, 1)) == 0            # outline pulled up
    assert containers.room_of(rooms, (2, 2, 1)) == 1            # inside both: the smaller room wins
    assert containers.room_of(rooms, (23, 2, 1.5)) == 2         # closed mesh
    assert containers.room_of(rooms, (27, 2, 1.5)) == -1        # just outside the mesh
    assert containers.room_of(rooms, (15, 3, 1)) == -1          # between rooms
    assert containers.room_of(rooms, (8, 5, 3.2)) == 0          # a ceiling sits on the edge of the volume
    assert containers.room_of(rooms, (8, 5, 4.0)) == -1


def test_room_centre():
    rooms = _rooms()
    assert np.allclose(rooms[0].centre(), (5, 3, 1.5))
    assert np.allclose(rooms[1].centre(), (2, 2, 0))
    assert np.allclose(rooms[2].centre(), (23, 2, 1.5))


def _part(kind, room, n=2, name="m"):
    mat = materials.Material(name, "", kind, (0.5, 0.5, 0.5))
    v = np.zeros((3 * n, 3))
    f = np.arange(3 * n).reshape(-1, 3)
    return model.Part("p", mat, v, f, "x", room=room)


def test_solids_split_by_room_and_see_through_pieces_keep_runs():
    solid = [_part("solid", 0), _part("solid", 1), _part("solid", 1), _part("solid", -1)]
    glass = [_part("glass", 1, 2, "g"), _part("glass", -1, 1, "g"), _part("glass", 0, 3, "g"), _part("glass", 1, 4, "g")]
    out = export.merged_by_material(solid + glass, rooms=True)
    by = {(m.kind, r if not isinstance(r, list) else "runs"): (len(f), r) for m, v, f, uv, r in out}
    assert by[("solid", 0)][0] == 2 and by[("solid", 1)][0] == 4 and by[("solid", -1)][0] == 2
    faces, runs = by[("glass", "runs")]
    assert faces == 10 and runs == [[-1, 0, 1], [0, 1, 3], [1, 4, 6]]
    # without rooms nothing changes for the callers that never asked
    assert len(export.merged_by_material(solid + glass)) == 2


def test_models_without_rooms_keep_their_names():
    out = export.merged_by_material([_part("solid", -1), _part("glass", -1, 2, "g")], rooms=True)
    assert [r for *_, r in out] == [-1, -1]
    mat = materials.Material("Hull", "", "solid", (1, 1, 1))
    assert export._node_name(mat, 7, -1) == "solid|Hull|7"
    assert export._node_name(mat, 7, 3) == "solid|Hull|7|R3"
    assert export._node_name(mat, 7, [[-1, 0, 4], [2, 4, 10]]) == "solid|Hull|7|Mrxs0n4_r2s4n10"


@pytest.fixture(scope="module")
def archive():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    return a


@needs_game
def test_perseus_rooms(archive):
    rooms = containers.rooms(archive, "ObjectContainers/Ships/RSI/Perseus/rsi_perseus_habs.socpak")
    by = {r.name: r for r in rooms}
    assert {"Room_RN_habs_bunks", "Room_RN_habs_mess", "Room_RN_habs_engineering"} <= set(by)
    assert by["Room_RN_habs_mess"].label == "@vehicle_room_messhall"
    assert {v[1] for v in by["Room_RN_habs_mess"].volumes} == {"mesh"}          # closed meshes
    assert {v[1] for v in by["Room_RN_habs_bunks"].volumes} == {"shape"}        # the doorway box is not its extent
    assert {v[1] for v in by["Room_RN_habs_bunks_toilet"].volumes} == {"box"}


@needs_game
def test_perseus_interior_parts_know_their_room(archive):
    dcb = next(n for n in archive.names if n.lower().endswith(".dcb"))
    index = entities.build(archive.read(dcb), entities.archive_reader(archive))
    base = model.load_model(archive, PERSEUS)
    m = assembly.load_interior(archive, base, entities.vehicle_for(index, PERSEUS), entities.classes_of(index))
    inner = [p for p in m.parts if p.name.startswith(assembly.INTERIOR_PREFIX)]
    assert len(m.rooms) >= 15 and all(r["parts"] > 0 for r in m.rooms)
    assert sum(p.room >= 0 for p in inner) > 0.9 * len(inner)
    assert all(p.room == -1 for p in m.parts if not p.name.startswith(assembly.INTERIOR_PREFIX))
    assert all(-1 <= p.room < len(m.rooms) for p in inner)

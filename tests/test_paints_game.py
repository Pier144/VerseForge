"""Instant paints on the real Perseus (needs Data.p4k): every paint passes the swap check, and an interior reused
from another paint matches one built from scratch."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import assembly, entities, model, paints, variants  # noqa: E402
from sc_explorer.p4k import P4kArchive  # noqa: E402
from sc_explorer.server import CACHE_DIR, load_config  # noqa: E402

P4K = load_config()["p4k_path"]
pytestmark = pytest.mark.skipif(not os.path.isfile(P4K), reason="Data.p4k not found")
PERSEUS = "Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga"


@pytest.fixture(scope="module")
def game():
    a = P4kArchive(P4K, CACHE_DIR)
    a.load()
    dcb = next(n for n in a.names if n.lower().endswith(".dcb"))
    data = a.read(dcb)
    vs = variants.build(data, {})[PERSEUS.lower()]
    index = entities.build(data, entities.archive_reader(a))
    return a, vs, index


def test_perseus_stock_paint_is_marked(game):
    _, vs, _ = game
    assert vs[0]["stock"] and not any(v["stock"] for v in vs[1:]) and len(vs) >= 10


def test_every_perseus_paint_can_be_swapped(game):
    a, vs, index = game
    base = model.load_model(a, PERSEUS, entities.adb_for(index, PERSEUS))
    paint = lambda v: model.with_variant(base, a, v["material"], v["palette"])
    ref = paint(vs[0])
    groups = paints.group_keys(ref)
    bad = [v["label"] for v in vs[1:] if not paints.check(ref, paint(v), groups)]
    assert not bad


def test_every_perseus_paint_can_be_swapped_on_the_full_ship(game):
    a, vs, index = game
    base = assembly.load_full(a, PERSEUS, entities.vehicle_for(index, PERSEUS), entities.adb_for(index, PERSEUS))
    paint = lambda v: model.with_variant(base, a, v["material"], v["palette"])
    ref = paint(vs[0])
    groups = paints.group_keys(ref)
    assert not [v["label"] for v in vs[1:] if not paints.check(ref, paint(v), groups)]


def test_reused_interior_matches_a_fresh_one(game):
    a, vs, index = game
    base = model.load_model(a, PERSEUS, entities.adb_for(index, PERSEUS))
    hull_a = model.with_variant(base, a, vs[0]["material"], vs[0]["palette"])
    hull_b = model.with_variant(base, a, vs[5]["material"], vs[5]["palette"])
    veh, classes = entities.vehicle_for(index, PERSEUS), entities.classes_of(index)
    fresh = assembly.load_interior(a, hull_b, veh, classes)
    reused = assembly.repaint_interior(assembly.load_interior(a, hull_a, veh, classes), hull_b, len(hull_a.parts))
    assert len(fresh.parts) == len(reused.parts) and len(fresh.rooms) == len(reused.rooms)
    for p, q in zip(fresh.parts, reused.parts):
        assert repr(p.material) == repr(q.material) and np.array_equal(p.vertices, q.vertices) and p.room == q.room

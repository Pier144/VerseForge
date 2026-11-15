"""In-memory model cache with a memory budget (no game files needed)."""
import os
import sys
import threading
import time
from dataclasses import replace

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer import materials, model  # noqa: E402
from sc_explorer.modelcache import PART_OVERHEAD, ModelCache, model_bytes  # noqa: E402

MB = 2 ** 20
MAT = materials.Material("m", "", "solid", (1, 1, 1))


def _model(mb):
    """A model with one part whose vertices take `mb` MB."""
    v = np.zeros((mb * MB // 12, 3), np.float32)
    return model.Model("x", parts=[model.Part("p", MAT, v, np.zeros((0, 3), np.uint32), "x")])


def test_shared_arrays_are_counted_once():
    a = _model(2)
    variant = replace(a, parts=[replace(p, material=MAT) for p in a.parts], cache={})   # same arrays, new parts
    one = model_bytes([a])
    assert 2 * MB <= one < 2 * MB + 4096
    assert model_bytes([a, variant]) == one + PART_OVERHEAD
    view = replace(a.parts[0], vertices=a.parts[0].vertices[:10])                       # a view: its base counts
    assert model_bytes([model.Model("v", parts=[view]), a]) == one + PART_OVERHEAD
    a.cache["glb"] = b"x" * MB
    assert model_bytes([a]) == one + MB


def test_least_recently_used_go_first_beyond_the_budget():
    c = ModelCache(budget_mb=5)
    c.put("a", _model(2))
    c.put("b", _model(2))
    assert c.get("a") is not None                 # a is now the most recent
    c.put("c", _model(2))                         # 6 MB > 5: b goes
    assert c.keys() == ["a", "c"] and c.bytes <= 5 * MB
    big = c.put("d", _model(8))                   # bigger than the budget alone: it stays, the others go
    assert c.keys() == ["d"] and c.get("d") is big


def test_a_model_that_grows_is_counted_on_trim():
    c = ModelCache(budget_mb=5)
    c.put("a", _model(2))
    b = c.put("b", _model(1))
    b.cache[("glb", True)] = b"x" * (3 * MB)      # its GLB got cached afterwards
    c.trim()
    assert c.keys() == ["b"]


def test_one_build_for_requests_at_the_same_time():
    c = ModelCache()
    calls, out = [], []

    def build():
        calls.append(1)
        time.sleep(0.2)
        return _model(1)
    threads = [threading.Thread(target=lambda: out.append(c.get_or_build("k", build))) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(calls) == 1 and len(out) == 4 and all(m is out[0] for m in out)


def test_a_failed_build_is_not_cached():
    c = ModelCache()

    def bad():
        raise ValueError("broken")
    with pytest.raises(ValueError):
        c.get_or_build("k", bad)
    assert "k" not in c
    assert c.get_or_build("k", lambda: _model(1)) is c.get("k")

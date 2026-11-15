"""Built models kept in memory, least recently used dropped first beyond a memory budget (not a fixed count).

A model's weight is estimated from its geometry arrays (vertices, faces, UVs, bone indices) plus what its own cache
holds (encoded GLBs, decoded animation clips). Models share arrays: a paint variant keeps the parts of the default
paint, an interior keeps the hull's parts and every copy of a room keeps the same faces and UVs. So the total is
counted over all cached models together, each array once, and dropping a model that shares everything with another
frees nothing (the estimate says so too)."""
import os
import threading
from collections import OrderedDict

import numpy as np

DEFAULT_BUDGET_MB = int(os.environ.get("VERSEFORGE_MODEL_MB") or 1536)   # env: benchmarks of other budgets
PART_OVERHEAD = 1024        # Python objects of one part and its material, roughly (bytes)
_ARRAYS = ("vertices", "faces", "uvs", "uvs2", "vbones")


def _root(a):
    """The object that owns an array's memory (a view counts its base once, not once per view)."""
    while isinstance(a, np.ndarray) and a.base is not None:
        a = a.base
    return a


def _nbytes(r):
    return r.nbytes if isinstance(r, np.ndarray) else memoryview(r).nbytes


def _add(obj, seen):
    """Bytes of `obj` not counted yet (numpy arrays, bytes); containers are walked (animation clips, decks)."""
    stack, total = [obj], 0
    while stack:
        o = stack.pop()
        if isinstance(o, np.ndarray):
            r = _root(o)
            if id(r) not in seen:
                seen[id(r)] = r          # keeps the object alive while counting, so ids stay unique
                total += _nbytes(r)
        elif isinstance(o, (bytes, bytearray, memoryview)):
            if id(o) not in seen:
                seen[id(o)] = o
                total += len(o)
        elif isinstance(o, dict):
            stack.extend(o.values())
        elif isinstance(o, (list, tuple, set)):
            stack.extend(o)
        elif hasattr(o, "__dict__") and not isinstance(o, type):
            if id(o) not in seen:
                seen[id(o)] = o
                stack.extend(vars(o).values())
    return total


def model_bytes(models):
    """Estimated memory of several models together, shared arrays counted once."""
    seen, total = {}, 0
    for m in models:
        for p in list(m.parts):
            if id(p) in seen:
                continue
            seen[id(p)] = p
            total += PART_OVERHEAD
            for name in _ARRAYS:
                a = getattr(p, name, None)
                if a is not None:
                    r = _root(a)
                    if id(r) not in seen:
                        seen[id(r)] = r
                        total += _nbytes(r)
        total += _add(list(m.cache.values()), seen)
    return total


class ModelCache:
    """key -> Model, LRU within `budget_mb` (the most recent model always stays, whatever its size)."""

    def __init__(self, budget_mb=DEFAULT_BUDGET_MB):
        self.budget = int(budget_mb * 2 ** 20)
        self.bytes = 0
        self._items = OrderedDict()
        self._lock = threading.RLock()
        self._building = {}         # key -> [Event, model]: the build under way (other requests wait for it)

    def __len__(self):
        return len(self._items)

    def __contains__(self, key):
        return key in self._items

    def get(self, key):
        """The cached model (now the most recent) or None."""
        with self._lock:
            m = self._items.get(key)
            if m is not None:
                self._items.move_to_end(key)
            return m

    def put(self, key, m):
        with self._lock:
            self._items[key] = m
            self._items.move_to_end(key)
            self.trim()
        return m

    def get_or_build(self, key, build):
        """The cached model, else build() it once: requests that ask for the same model meanwhile (the viewer asks
        for its description and its GLB at the same time) wait for that build instead of making a second copy."""
        while True:
            m = self.get(key)
            if m is not None:
                return m
            with self._lock:
                slot = self._building.get(key)
                mine = slot is None
                if mine:
                    slot = self._building[key] = [threading.Event(), None]
            if not mine:
                slot[0].wait()
                if slot[1] is not None:
                    return slot[1]
                continue                # that build failed: try (and fail, with its error) here
            try:
                slot[1] = self.put(key, build())
                return slot[1]
            finally:
                with self._lock:
                    self._building.pop(key, None)
                slot[0].set()

    def trim(self):
        """Recount (a model grows when its GLB or clips get cached) and drop the oldest models beyond the budget."""
        with self._lock:
            self.bytes = model_bytes(self._items.values())
            while self.bytes > self.budget and len(self._items) > 1:
                self._items.popitem(last=False)
                self.bytes = model_bytes(self._items.values())
            return self.bytes

    def clear(self):
        with self._lock:
            self._items.clear()
            self.bytes = 0

    def keys(self):
        with self._lock:
            return list(self._items)

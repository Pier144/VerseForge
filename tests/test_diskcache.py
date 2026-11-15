"""Disk cache of built models and textures (no game files needed)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sc_explorer.diskcache import PREFIX, DiskCache  # noqa: E402


def _fake_p4k(tmp_path, size):
    p = tmp_path / "Data.p4k"
    p.write_bytes(b"x" * size)
    return str(p)


def test_put_get_and_versions(tmp_path):
    root = tmp_path / "cache"
    root.mkdir()
    c = DiskCache(str(root))
    c.bind("1.0.0", _fake_p4k(tmp_path, 10))
    assert c.get("glb", ("a", 1), "glb") is None
    c.put("glb", ("a", 1), "glb", b"model")
    assert c.get("glb", ("a", 1), "glb") == b"model" and c.size == 5
    # a new game (or program) version starts from an empty folder and removes the old one
    c2 = DiskCache(str(root))
    c2.bind("1.0.0", _fake_p4k(tmp_path, 11))
    assert c2.get("glb", ("a", 1), "glb") is None
    assert len([d for d in os.listdir(root) if d.startswith(PREFIX)]) == 1


def test_disabled_and_clear(tmp_path):
    c = DiskCache(str(tmp_path))
    c.bind("1.0.0", _fake_p4k(tmp_path, 10))
    c.enabled = False
    c.put("tex", "k", "png", b"data")
    assert c.get("tex", "k", "png") is None and c.size == 0
    c.enabled = True
    c.put("tex", "k", "png", b"data")
    c.clear()
    assert c.get("tex", "k", "png") is None and c.size == 0


def test_least_recently_used_files_go_first(tmp_path):
    c = DiskCache(str(tmp_path), limit=130)
    c.bind("1.0.0", _fake_p4k(tmp_path, 10))
    for i in range(3):
        c.put("tex", i, "jpg", b"x" * 40)
        p = c._path("tex", i, "jpg")
        os.utime(p, (1000 + i, 1000 + i))           # 0 oldest, 2 newest
    os.utime(c._path("tex", 0, "jpg"), (5000, 5000))  # 0 used again: now the newest
    c.put("tex", 3, "jpg", b"x" * 40)                # 160 > 130: oldest go until <= 110 bytes
    assert c.get("tex", 0, "jpg") is not None and c.get("tex", 3, "jpg") is not None
    assert c.get("tex", 1, "jpg") is None and c.get("tex", 2, "jpg") is None and c.size <= 110

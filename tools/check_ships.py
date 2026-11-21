"""Open every ship and vehicle the way the viewer does and check what comes back.

    set VERSEFORGE_URL=http://127.0.0.1:8798        (a running app, best started with --no-disk-cache)
    python tools/check_ships.py out_dir [name ...]  (no names: every ship, and the ground vehicles the game names)

For each one, as a full ship and (when it has one) with its interior:
  - /api/model/info answers, is strict JSON (no Infinity / NaN) and has triangles;
  - /api/model/glb (the viewer's lite file) is a well-formed GLB: strict JSON, every buffer view inside the buffer,
    every float accessor finite, every node matrix finite, at least one drawn mesh;
  - the warnings of the model (ports left empty, parts that failed, interior pieces missing);
  - drawn meshes that lie wholly beyond the rest of the ship, and interiors bigger than the ship (a part in the
    wrong place).
Writes out_dir/results.json after every ship (a rerun skips what is done) and out_dir/REPORT.md at the end.
"""
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import numpy as np

BASE = os.environ.get("VERSEFORGE_URL", "http://127.0.0.1:8798").rstrip("/")
OUT = sys.argv[1]
NAMES = [n.lower() for n in sys.argv[2:]]
COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
DTYPES = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}


def get(url, timeout=1800):
    return urllib.request.urlopen(BASE + url, timeout=timeout).read()


def strict(text):
    def bad(name):
        raise ValueError(f"{name} in JSON")
    return json.loads(text, parse_constant=bad)


def _local(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=np.float64).reshape(4, 4).T
    m = np.eye(4)
    if "rotation" in node:
        x, y, z, w = node["rotation"]
        m[:3, :3] = [[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]]
    if "scale" in node:
        m[:3, :3] = m[:3, :3] * np.array(node["scale"], dtype=np.float64)
    if "translation" in node:
        m[:3, 3] = node["translation"]
    return m


def check_glb(data):
    """(facts, problems) of a GLB."""
    problems = []
    if len(data) < 20 or data[:4] != b"glTF":
        return {}, ["not a GLB"]
    total = struct.unpack_from("<I", data, 8)[0]
    if total != len(data):
        problems.append(f"length in the header {total}, file {len(data)}")
    jlen, jtype = struct.unpack_from("<II", data, 12)
    if jtype != 0x4E4F534A:
        return {}, ["first chunk is not JSON"]
    try:
        js = strict(data[20:20 + jlen].decode("utf-8"))
    except ValueError as e:
        return {}, [f"GLB JSON: {e}"]
    p = 20 + jlen
    blen = struct.unpack_from("<I", data, p)[0] if p + 8 <= len(data) else 0
    buf = memoryview(data)[p + 8:p + 8 + blen]
    views, accs = js.get("bufferViews", []), js.get("accessors", [])
    for i, v in enumerate(views):
        if v.get("byteOffset", 0) + v["byteLength"] > blen:
            problems.append(f"bufferView {i} runs past the buffer")

    def read(i):
        a = accs[i]
        v = views[a["bufferView"]]
        n = a["count"] * COMPONENTS[a["type"]]
        return np.frombuffer(buf, DTYPES[a["componentType"]], n, v.get("byteOffset", 0) + a.get("byteOffset", 0))

    bad_acc = 0
    for i, a in enumerate(accs):
        if a["componentType"] != 5126 or "bufferView" not in a:
            continue
        try:
            if not np.isfinite(read(i)).all():
                bad_acc += 1
        except (ValueError, KeyError) as e:
            problems.append(f"accessor {i}: {e}")
    if bad_acc:
        problems.append(f"{bad_acc} accessors with infinite or NaN values")

    nodes = js.get("nodes", [])
    world = [None] * len(nodes)
    stack = [(r, np.eye(4)) for s in js.get("scenes", []) for r in s.get("nodes", [])]
    while stack:
        i, parent = stack.pop()
        world[i] = parent @ _local(nodes[i])
        stack += [(c, world[i]) for c in nodes[i].get("children", [])]
    if any(w is not None and not np.isfinite(w).all() for w in world):
        problems.append("node matrix with infinite or NaN values")

    boxes, tris, drawn = [], 0, 0
    for i, n in enumerate(nodes):
        if "mesh" not in n or world[i] is None:
            continue
        mesh = js["meshes"][n["mesh"]]
        name = mesh.get("name") or n.get("name") or ""
        kind = name.split("|", 1)[0]
        for prim in mesh.get("primitives", []):
            pos = accs[prim["attributes"]["POSITION"]]
            t = (accs[prim["indices"]]["count"] if "indices" in prim else pos["count"]) // 3
            tris += t
            if kind == "hidden" or "min" not in pos:
                continue
            drawn += 1
            lo, hi = np.array(pos["min"]), np.array(pos["max"])
            corners = np.array([[x, y, z, 1.0] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])])
            w = (corners @ world[i].T)[:, :3]
            boxes.append((name, t, w.min(axis=0), w.max(axis=0)))
    if not drawn:
        problems.append("no drawn mesh")

    stray, size = [], None
    if len(boxes) > 1:
        # a mesh is stray when it lies wholly beyond everything else the ship is made of, by more than 2 m (wing tip
        # lights sit at the edge of the wing, not beyond it)
        los, his = np.array([b[2] for b in boxes]), np.array([b[3] for b in boxes])
        for k, (name, t, blo, bhi) in enumerate(boxes):
            rest = np.arange(len(boxes)) != k
            lo, hi = los[rest].min(axis=0), his[rest].max(axis=0)
            gap = float(max((lo - bhi).max(), (blo - hi).max()))
            if gap > 2.0:
                stray.append({"mesh": name, "triangles": int(t), "metres_out": round(gap, 1)})
    if boxes:
        alo, ahi = np.min([b[2] for b in boxes], axis=0), np.max([b[3] for b in boxes], axis=0)
        size = [round(float(x), 1) for x in ahi - alo]
    stray.sort(key=lambda s: -s["metres_out"])
    return {"bytes": len(data), "meshes": drawn, "triangles": int(tris), "size_m": size, "stray": stray[:12],
            "stray_n": len(stray)}, problems


def check(item, interior):
    row = {"name": item["name"], "path": item["path"], "interior": interior, "problems": []}
    q = urllib.parse.urlencode({"path": item["path"], "full": "true", "interior": "true" if interior else "false"})
    t = time.time()
    info = None
    try:
        info = strict(get("/api/model/info?" + q).decode("utf-8"))
        row["warnings"] = info.get("warnings", [])
        row["parts"] = info["stats"].get("parts")
        row["info_triangles"] = info["stats"].get("triangles")
        row["full"], row["has_interior"] = info.get("full"), info.get("can_interior")
        if not info["stats"].get("triangles"):
            row["problems"].append("info: no triangles")
    except urllib.error.HTTPError as e:
        row["problems"].append(f"info: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}")
    except Exception as e:
        row["problems"].append(f"info: {e}")
    try:
        facts, problems = check_glb(get("/api/model/glb?" + q + "&tex=true&lite=true"))
        row.update(facts)
        row["problems"] += problems
    except urllib.error.HTTPError as e:
        row["problems"].append(f"glb: HTTP {e.code} {e.read()[:300].decode('utf-8', 'replace')}")
    except Exception as e:
        row["problems"].append(f"glb: {e}")
    row["seconds"] = round(time.time() - t, 1)
    return row, info


def report(rows):
    bad = [r for r in rows if r["problems"]]
    warn = [r for r in rows if not r["problems"] and r.get("warnings")]
    stray = [r for r in rows if not r["problems"] and r.get("stray_n")]
    # an interior that makes the ship bigger than the ship itself holds something far from it
    full = {r["path"]: r.get("size_m") for r in rows if not r["interior"]}
    beyond = []
    for r in rows:
        if r["interior"] and r.get("size_m") and full.get(r["path"]):
            extra = [round(b - a, 1) for a, b in zip(full[r["path"]], r["size_m"])]
            if max(extra) > 2.0:
                beyond.append((r, extra))
    mode = lambda r: "with interior" if r["interior"] else "full ship"
    out = ["# Ship check", "", f"{len({r['path'] for r in rows})} ships and vehicles, {len(rows)} loads "
           f"(full ship, and with the interior where there is one).", "",
           f"- do not open or come back broken: **{len(bad)}**", f"- open, with warnings from the model: {len(warn)}",
           f"- open, with meshes far from the bulk of the ship (to look at): {len(stray)}", ""]
    out += ["## Broken", ""] + ([f"- **{r['name']}** ({mode(r)}): " + "; ".join(r["problems"]) for r in bad] or ["None."])
    out += ["", "## Warnings", ""] + ([f"- **{r['name']}** ({mode(r)}): " + " / ".join(r["warnings"]) for r in warn] or ["None."])
    out += ["", "## Meshes far from the ship", ""]
    for r in stray:
        out.append(f"- **{r['name']}** ({mode(r)}), {r['stray_n']} meshes, size {r.get('size_m')} m: " +
                   ", ".join(f"`{s['mesh']}` {s['metres_out']} m" for s in r["stray"][:4]))
    if not stray:
        out.append("None.")
    out += ["", "## Interiors that reach beyond the ship", ""]
    out += [f"- **{r['name']}**: {extra} m more than the full ship (width, height, length)" for r, extra in beyond] or ["None."]
    out += ["", "## All", "", "| Ship | Mode | Parts | Triangles | Meshes | MB | s | Result |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        res = "BROKEN" if r["problems"] else "warnings" if r.get("warnings") else "ok"
        out.append(f"| {r['name']} | {mode(r)} | {r.get('parts', '')} | {r.get('triangles', '')} | {r.get('meshes', '')} | "
                   f"{round(r.get('bytes', 0) / 1048576, 1)} | {r['seconds']} | {res} |")
    open(os.path.join(OUT, "REPORT.md"), "w", encoding="utf-8").write("\n".join(out) + "\n")


def main():
    sys.stdout.reconfigure(errors="replace")              # names like San'tok.yāi on a cp1252 console
    os.makedirs(OUT, exist_ok=True)
    for _ in range(600):
        try:
            if json.loads(get("/api/status", 10))["ready"]:
                break
        except OSError:
            pass
        time.sleep(1)
    items = json.loads(get("/api/search?cat=ships&limit=2000"))["items"]
    items += [it for it in json.loads(get("/api/search?cat=vehicles&sub=ground&limit=2000"))["items"] if it.get("game_name")]
    if NAMES:
        items = [it for it in items if it["name"].lower() in NAMES]
    path = os.path.join(OUT, "results.json")
    rows = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else []
    done = {(r["path"], r["interior"]) for r in rows}
    done |= {(r["path"], True) for r in rows if not r["interior"] and not r.get("has_interior") and not r["problems"]}
    print(len(items), "to check,", len(done), "loads already done", flush=True)
    for n, it in enumerate(items):
        for interior in (False, True):
            if (it["path"], interior) in done:
                continue
            row, info = check(it, interior)
            if interior and not row.get("has_interior") and not row["problems"]:
                continue                                  # no interior: the same file as the full ship
            rows.append(row)
            json.dump(rows, open(path, "w", encoding="utf-8"), indent=1)
            print(f"[{n + 1}/{len(items)}]", it["name"], "interior" if interior else "full", row["seconds"], "s",
                  "BROKEN: " + "; ".join(row["problems"]) if row["problems"] else "ok",
                  f"warnings {len(row.get('warnings', []))} stray {row.get('stray_n', 0)}", flush=True)
            if not interior and info is not None and not info.get("can_interior"):
                break
    report(rows)
    print("done:", sum(1 for r in rows if r["problems"]), "broken of", len(rows), flush=True)


main()

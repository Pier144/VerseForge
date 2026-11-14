"""Which animations belong to a model, and what they mean.

The game links them in three steps: <model>.chrparams (AnimationList: base folder, optional .dba track database,
named clips or wildcards) -> the clips (.caf files or .dba entries) -> the Mannequin .adb of the entity (group +
action -> clip, with playback speed; -1 = backwards). Without an .adb, labels come from the clip names."""
import fnmatch
import re
import zlib
from dataclasses import dataclass

from . import caf, cryxml, dba


@dataclass
class AnimRef:
    id: str            # "group/action", unique in the model
    label: str         # action label ("Open")
    group: str         # group label ("Canopy")
    clip: str          # clip name in the .chrparams; also the glTF animation name
    source: str        # .caf path (Data-relative), or the entry key inside `dba`
    dba: str | None
    speed: float
    duration: float
    pose: bool
    targets: frozenset = frozenset()   # CRC32 of the bone/node names the clip moves
    reverse_keys: bool = False         # decode the clip backwards (used to make a "retract" out of an "extend")


@dataclass
class AnimSet:
    """Animations of one object instance inside a model: the object itself ("" prefix) or an assembled component."""
    prefix: str
    refs: list
    targets: dict        # CRC32 of the bone/node name in the object's own files -> node name in the model


_DIRS = {}          # id(archive) -> {folder (lowercase): [.caf paths]}


def _data_path(p):
    p = (p or "").replace("\\", "/").strip("/")
    return p[5:] if p.lower().startswith("data/") else p


def _caf_dirs(archive):
    key = id(archive)
    if key not in _DIRS:
        d = {}
        for n in archive.names:
            if n[-4:].lower() == ".caf":
                p = _data_path(n)
                d.setdefault(p.rsplit("/", 1)[0].lower(), []).append(p)
        _DIRS.clear()
        _DIRS[key] = d
    return _DIRS[key]


def chrparams_for(archive, model_path):
    p = _data_path(model_path)
    ext = p.rsplit(".", 1)[-1].lower()
    if ext == "cdf":
        try:
            m = cryxml.parse(archive.read(p)).find("Model")
        except Exception:
            return None
        if m is None or not m.get("File"):
            return None
        p, ext = _data_path(m.get("File")), "chr"
    if ext not in ("chr", "cga"):
        return None
    cp = p.rsplit(".", 1)[0] + ".chrparams"
    return cp if archive.exists(cp) else None


def _animation_list(archive, cp, seen=None):
    """(.dba path | None, [(name, full path)], [(folder, wildcard pattern)]) of a .chrparams, following $Include.
    #filepath may appear several times: each one applies to the entries after it."""
    seen = seen or set()
    seen.add(cp.lower())
    folder, db, named, wild = "", None, [], []
    root = cryxml.parse(archive.read(cp))
    for a in root.iter("Animation"):
        name, path = a.get("name") or "", _data_path(a.get("path"))
        if name == "#filepath":
            folder = path
        elif name == "$TracksDatabase":
            db = db or path
        elif name == "$Include":
            if path and path.lower() not in seen and archive.exists(path):
                d2, n2, w2 = _animation_list(archive, path, seen)
                db, named, wild = db or d2, named + n2, wild + w2
        elif name.startswith(("$", "#")) or not path:
            continue
        else:
            full = path if not folder or path.lower().startswith(folder.lower() + "/") else f"{folder}/{path}"
            if "*" in name or "*" in path:
                wild.append((folder, path))
            else:
                named.append((name, full))
    return db, named, wild


def _wild_match(rel, pat):
    return fnmatch.fnmatch(rel, pat) or (pat.startswith("*/") and fnmatch.fnmatch(rel, pat[2:]))


def _clips(archive, cp):
    """{clip name lowercase: (name, source, dba path | None, ClipInfo, track hashes)} for a .chrparams."""
    db, named, wild = _animation_list(archive, cp)
    entries, db_data = {}, b""
    if db and archive.exists(db):
        try:
            db_data = archive.read(db)
            entries = {n: (info, off) for n, info, off in dba.entries(db_data)}
        except Exception:
            entries = {}
    out = {}

    def add(name, path):
        key = path.lower()
        try:
            if key in entries:
                info, off = entries[key]
                out.setdefault(name.lower(), (name, key, db, info, caf.block_hashes(db_data, off)))
            elif archive.exists(path):
                data = archive.read(path)
                info, hashes = caf.header(data), caf.hashes(data)
                out.setdefault(name.lower(), (name, path, None, info, hashes))
        except Exception:        # unreadable clip: left out, the others stay
            pass

    for name, p in named:
        add(name, p)
    for folder, pat in wild:
        fl = folder.lower()
        pat = pat.lower()
        files = {}
        for d, paths in _caf_dirs(archive).items():
            if d == fl or d.startswith(fl + "/"):
                for p in paths:
                    files[p.lower()] = p
        for key in entries:
            if key.startswith(fl + "/"):
                files.setdefault(key, key)
        for low, p in sorted(files.items()):
            if _wild_match(low[len(fl) + 1:] if fl else low, pat):
                add(p.rsplit("/", 1)[-1][:-4], p)
    return out


def _adb_fragments(archive, adb_path):
    """[(group, action, clip name, speed)] of every fragment of a Mannequin database, in file order. A group/action
    often has several fragments for different scopes (Polaris: the legs' landing_gear_deploy first, then the hull's
    Landing_Deploy): the caller keeps the first one whose clip the model has."""
    if not adb_path or not archive.exists(adb_path):
        return []
    root = cryxml.parse(archive.read(adb_path))
    fl = root.find("FragmentList")
    out = []
    for group in (fl if fl is not None else []):
        for frag in group.findall("Fragment"):
            action = frag.get("FragTags") or "Default"
            anim = next((a for layer in frag.findall("AnimLayer") for a in layer.findall("Animation") if a.get("name")),
                        None)
            if anim is None:
                continue
            try:
                speed = float(anim.get("speed") or 1.0) or 1.0
            except ValueError:
                speed = 1.0
            out.append((group.tag, action, anim.get("name"), speed))
    return out


def _key(s):
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _title(s):
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)          # NoScopeAttached -> No Scope Attached
    return " ".join(w[:1].upper() + w[1:] for w in re.split(r"[_\s]+", s) if w)


def _name_rule(name, stem_tokens, pose):
    tokens = [t for t in name.lower().split("_") if t]
    while len(tokens) > 1 and tokens[0] in stem_tokens:
        tokens.pop(0)
    while len(tokens) > 1 and tokens[-1].isdigit():
        tokens.pop()
    if pose:
        if len(tokens) > 1 and tokens[-1] == "pose":
            tokens.pop()
        return "Poses", _title("_".join(tokens))
    if len(tokens) == 1:
        return _title(tokens[0]), "Play"
    return _title("_".join(tokens[:-1])), _title(tokens[-1])


def find(archive, model_path, adb_path=None, names=None):
    """Playable actions of a model (empty when the game links no animations to it). Never decodes the tracks.
    names: bone/node names of the model; clips that move none of them (shared databases) are left out."""
    cp = chrparams_for(archive, model_path)
    if not cp:
        return []
    # additive clips are offsets to add on top of a pose, not poses: the flag is not always set inside .dba files,
    # so the game's "_add" naming convention counts too
    clips = {k: v for k, v in _clips(archive, cp).items() if not v[3].additive and not k.endswith("_add")}
    if names is not None:
        wanted = {zlib.crc32(n.encode()) for n in names}
        clips = {k: v for k, v in clips.items() if wanted & set(v[4])}
    refs, ids, used = [], set(), set()

    def push(group, action, c, speed):
        name, source, db, info, hashes = c
        rid = f"{_key(group)}/{_key(action)}"
        if rid in ids:
            return
        ids.add(rid)
        used.add(name.lower())
        refs.append(AnimRef(rid, _title(action), _title(group), name, source, db, speed, round(info.duration, 4),
                            info.pose, frozenset(hashes) - {caf.ROOT_HASH}))

    played = set()          # (group, clip, speed): an action that only repeats another one is not offered twice
    for group, action, clip, speed in _adb_fragments(archive, adb_path):
        c = clips.get(clip.lower())
        same = (_key(group), clip.lower(), speed)
        if c and same not in played and f"{_key(group)}/{_key(action)}" not in ids:
            played.add(same)
            push(group, action, c, speed)
    stem = _data_path(model_path).rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
    stem_tokens = set(stem.split("_"))
    rest = []
    for low, c in clips.items():
        if low in used:
            continue
        group, action = _name_rule(c[0], stem_tokens, c[3].pose)
        rest.append((c[3].pose, group, action, c))
    for _, group, action, c in sorted(rest, key=lambda r: r[:3]):
        push(group, action, c, 1.0)
    return refs


def sources(archive, model):
    """[(clip name, caf.Clip, {name hash: model node name})] for every animated instance of a model, + warnings."""
    out, warnings = [], []
    for s in model.anim_sets:
        clips, warns = load_clips(archive, s.refs)
        warnings += warns
        out += [(name, clip, s.targets) for name, clip in clips.items()]
    return out, warnings


def load_clips(archive, refs):
    """Decode the clips the actions use -> ({clip name: caf.Clip}, [warning tuples])."""
    clips, warnings, dbs = {}, [], {}
    for r in refs:
        if r.clip in clips:
            continue
        try:
            if r.dba:
                if r.dba not in dbs:
                    dbs[r.dba] = archive.read(r.dba)
                clips[r.clip] = dba.read(dbs[r.dba], r.source)
            else:
                clips[r.clip] = caf.read(archive.read(r.source))
            if r.reverse_keys:
                clips[r.clip] = caf.reversed_clip(clips[r.clip])
        except Exception as e:      # one broken clip never hides the others
            warnings.append(("warn_anim_error", {"clip": r.clip, "error": str(e)}))
    return clips, warnings

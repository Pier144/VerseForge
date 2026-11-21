"""Game values of the DataCore entities: what a weapon, a ship or a component is worth in play.

build() reads them once for every entity (EntityClassDefinition) that has any:
- weapons (personal and ship guns): fire rate, damage per shot and by type, DPS, magazine, projectile speed, range;
- missiles: damage, speed, lock time and range;
- ships and vehicles: hull health, mass, size, crew, role, and from the factory loadout the flight speeds and
  turn rates (flight controller), shields, guns, missiles, cargo and the quantum drive;
- components: shield generators, quantum drives, coolers, thrusters;
- armour: damage resistances and temperatures.

The answer is plain JSON: {"version", "records": {lower-case record name: entry}, "geo": {geometry: [record names]}},
an entry being {"record", "name" (global.ini key), "kind", "geo", "groups": [[group id, [[stat id, value], ...]]]}.
A text value that starts with "@" is a key of the game's texts. Labels and units are in i18n.STATS and UNITS.

Property names are looked up without regard to case and a value that is not there is left out: a patch that
renames a field loses that row, not the rest (coverage() tells which rows nothing fills any more).

raw() gives everything the game has on one entity, as nested dicts, with the records it points to."""
import csv
import io
import math
import re

from . import cryxml, entities
from .datacore import CLASS, REFERENCE, STRONG, View

VERSION = 1
DAMAGE = ("physical", "energy", "distortion", "thermal", "biochemical", "stun")
SCU_M3 = 1.953125               # one Standard Cargo Unit is a 1.25 m cube

# stat id -> unit ("" for counts and texts); the order is the one of the tables
UNITS = {
    "type": "", "size": "", "grade": "", "manufacturer": "", "mass": "kg", "health": "HP",
    "role": "", "career": "", "crew": "", "length": "m", "width": "m", "height": "m", "hull_hp": "HP",
    "scm_speed": "m/s", "max_speed": "m/s", "boost_speed": "m/s", "boost_speed_back": "m/s",
    "pitch": "°/s", "yaw": "°/s", "roll": "°/s",
    "shield_hp": "HP", "shield_regen": "HP/s", "shields": "", "regen_delay_damaged": "s", "regen_delay_down": "s",
    "weapons": "", "weapons_dps": "", "missiles": "", "cargo": "SCU",
    "quantum_speed": "km/s", "spool_time": "s", "cooldown": "s", "quantum_fuel_rate": "",
    "fire_mode": "", "fire_rate": "rpm", "pellets": "", "alpha": "", "dps": "",
    **{f"dmg_{d}": "" for d in DAMAGE},
    "magazine": "", "ammo_speed": "m/s", "range": "m", "explosion_damage": "", "explosion_radius": "m",
    "capacitor": "", "capacitor_regen": "/s", "other_modes": "",
    "speed": "m/s", "lock_time": "s", "lock_range": "m", "tracking": "",
    "cooling_rate": "", "thrust": "N",
    **{f"res_{d}": "%" for d in DAMAGE},
    "temp_min": "°C", "temp_max": "°C",
}
GROUPS = ("general", "vehicle", "flight", "loadout", "weapon", "missile", "shield", "quantum", "cooler", "thruster",
          "armor")
# kind -> the stats a record of that kind is expected to have (coverage)
KINDS = ("ship", "vehicle", "weapon", "ship_weapon", "missile", "shield", "quantum_drive", "cooler", "thruster",
         "armor")


# ---------------------------------------------------------------------------------------------- reading DataCore
def _names(v):
    """{lower-case property name: its real name} of a view's struct."""
    key = ("lower", v.si)
    cache = v.dc._props_cache
    if key not in cache:
        cache[key] = {n.lower(): n for n in v.dc.layout(v.si)}
    return cache[key]


def _child(v, name):
    """A property of a view, whatever the case of its name; records it refers to come back as views."""
    real = _names(v).get(name.lower())
    if real is None:
        return None
    try:
        val = v[real]
    except Exception:               # a pointer out of the file: as if it was not there
        return None
    if v.dc.layout(v.si)[real][1] == REFERENCE:
        def record(r):
            return v.dc.record_view(r) if isinstance(r, int) and not isinstance(r, bool) else None
        return [record(r) for r in val] if isinstance(val, list) else record(val)
    return val


def _get(v, path, default=None):
    """v.a.b.c for "a.b.c"; "a|b" tries one name then the other; a list on the way means its first entry."""
    for seg in path.split("."):
        if isinstance(v, list):
            v = next((x for x in v if isinstance(x, View)), None)
        if not isinstance(v, View):
            return default
        for name in seg.split("|"):
            got = _child(v, name)
            if got is not None:
                break
        else:
            return default
        v = got
    return v


def _num(v, path=None):
    x = _get(v, path) if path else v
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    x = float(x)
    return x if math.isfinite(x) else None


def _text(v, path):
    x = _get(v, path)
    return x.strip() if isinstance(x, str) else ""


def _comp(comps, *types):
    return next((c for c in comps if c.type in types), None)


def _components(view):
    got = _child(view, "Components") if isinstance(view, View) else None
    return [c for c in got if isinstance(c, View)] if isinstance(got, list) else []


def _damage(v):
    """{damage type: amount} of a DamageInfo (DamagePhysical, DamageEnergy…), without the zeros."""
    if isinstance(v, list):
        v = next((x for x in v if isinstance(x, View)), None)
    if not isinstance(v, View):
        return {}
    out = {}
    for low in _names(v):
        if low.startswith("damage") and low[6:] in DAMAGE:
            x = _num(v, low)
            if x:
                out[low[6:]] = x
    if not out and "damageinfo" in _names(v):
        return _damage(_child(v, "DamageInfo"))
    return out


def _round(x, digits=2):
    if x is None:
        return None
    x = round(float(x), digits)
    return int(x) if x == int(x) else x


def _rows(pairs):
    """The rows that have a value: what the game leaves at zero or empty is not a value."""
    return [[k, v] for k, v in pairs if v not in (None, "", 0)]


# ---------------------------------------------------------------------------------------------- weapons
def _modes(action, depth=0):
    """Fire modes of a weapon action: [{"mode", "rate" (shots per minute), "pellets"}] or [{"mode": "beam", "beam":
    damage per second}]. Actions that only hold others (charged, sequences, conditions) give theirs."""
    if not isinstance(action, View) or depth > 3:
        return []
    t = action.type.lower()
    if "weaponaction" in t:
        if "beam" in t:
            beam = _damage(_get(action, "damagePerSecond"))
            return [{"mode": "beam", "beam": beam}] if beam else []
        rate = _num(action, "fireRate")
        if rate:
            mode = next((m for m in ("burst", "rapid", "charged") if m in t), "single")
            return [{"mode": mode, "rate": rate, "pellets": max(1, int(_num(action, "launchParams.pelletCount") or 1)),
                     "shots": int(_num(action, "shotCount") or 0)}]
    out = []
    for name, (_, typ, _conv, _idx) in action.dc.layout(action.si).items():
        if typ not in (STRONG, CLASS):
            continue
        val = _child(action, name)
        for sub in val if isinstance(val, list) else [val]:
            for m in _modes(sub, depth + 1):
                if "charged" in t and m["mode"] != "beam":
                    m["mode"] = "charged"
                if m not in out:
                    out.append(m)
    return out


def _ammo(idx, comps, weapon):
    """(AmmoParams view, rounds) of a weapon: the factory magazine's, its own ammo container's (energy weapons),
    or the ammo record the weapon names."""
    def container(cs):
        c = _comp(cs, "SAmmoContainerComponentParams")
        if c is None:
            return None, 0
        return _get(c, "ammoParamsRecord"), int(_num(c, "maxAmmoCount") or 0)
    found = (None, 0)
    for e in idx.entries(comps):
        try:
            if e is None or "magazine" not in (e["itemPortName"] or "").lower():
                continue
            ri = idx.by_name.get((e["entityClassName"] or "").lower())
        except (KeyError, TypeError):
            continue
        if ri is not None:
            found = container(idx.info(ri)[2])
            if found[0] is not None or found[1]:
                break
    if found[0] is None and not found[1]:
        found = container(comps)
    ammo, rounds = found
    if ammo is None:
        rec = _get(weapon, "ammoContainerRecord")
        if isinstance(rec, View):
            if "components" in _names(rec):
                ammo, n = container(_components(rec))
                rounds = rounds or n
            else:
                ammo = rec
    return ammo, rounds


def _weapon(idx, comps):
    """Rows of a weapon, [] when it fires nothing that does damage (tractor beams, scanners)."""
    weapon = _comp(comps, "SCItemWeaponComponentParams")
    if weapon is None:
        return []
    modes = []
    for a in _get(weapon, "fireActions", []) or []:
        for m in _modes(a):
            if m not in modes:
                modes.append(m)
    ammo, rounds = _ammo(idx, comps, weapon)
    speed, life = _num(ammo, "speed"), _num(ammo, "lifetime")
    shell = _get(ammo, "projectileParams")
    hit = _damage(_get(shell, "damage"))
    blast_at = _get(shell, "detonationParams.explosionParams")
    blast = _damage(_get(blast_at, "damage"))
    per_shot = dict(hit)
    for k, x in blast.items():
        per_shot[k] = per_shot.get(k, 0.0) + x
    rows = []
    first = modes[0] if modes else None
    if first and first["mode"] == "beam":
        per_shot = first["beam"]
        rows += [["fire_mode", "beam"], ["dps", _round(sum(per_shot.values()), 1)]]
    elif first:
        alpha = sum(per_shot.values()) * first["pellets"]
        rows += [["fire_mode", first["mode"]], ["fire_rate", _round(first["rate"], 1)],
                 ["pellets", first["pellets"] if first["pellets"] > 1 else None],
                 ["alpha", _round(alpha, 2)], ["dps", _round(alpha * first["rate"] / 60.0, 1)]]
    elif not per_shot:
        return []
    else:
        rows += [["alpha", _round(sum(per_shot.values()), 2)]]
    rows += [[f"dmg_{d}", _round(per_shot.get(d), 2)] for d in DAMAGE]
    rows += [["magazine", rounds], ["ammo_speed", _round(speed, 1)],
             ["range", _round(speed * life, 0) if speed and life else None],
             ["explosion_damage", _round(sum(blast.values()), 2) if blast else None],
             ["explosion_radius", _round(_num(blast_at, "maxRadius"), 2) if blast else None]]
    regen = _get(weapon, "weaponRegenConsumerParams")
    rows += [["capacitor", _round(_num(regen, "maxAmmoLoad"), 0)],
             ["capacitor_regen", _round(_num(regen, "maxRegenPerSec"), 2)]]
    others = [f"{m['mode']} {_round(m['rate'], 0)} rpm" if m["mode"] != "beam" else "beam" for m in modes[1:]]
    rows.append(["other_modes", " · ".join(dict.fromkeys(others))])
    return _rows(rows)


def _missile(comps):
    m = _comp(comps, "SCItemMissileParams", "SCItemBombParams")
    if m is None:
        return []
    blast = _damage(_get(m, "explosionParams.damage"))
    return _rows([["explosion_damage", _round(sum(blast.values()), 1)]]
                 + [[f"dmg_{d}", _round(blast.get(d), 1)] for d in DAMAGE]
                 + [["explosion_radius", _round(_num(m, "explosionParams.maxRadius"), 1)],
                    ["speed", _round(_num(m, "GCSParams.linearSpeed"), 1)],
                    ["lock_time", _round(_num(m, "targetingParams.lockTime"), 2)],
                    ["lock_range", _round(_num(m, "targetingParams.lockRangeMax"), 0)],
                    ["tracking", _text(m, "targetingParams.trackingSignalType")]])


# ---------------------------------------------------------------------------------------------- items
def _maker(record):
    """A manufacturer's name key ("@manufacturer_NameBEHR"), or its code when the game gives it no name."""
    name = _text(record, "Localization.Name")
    return _text(record, "Code") if not name or name.lower().startswith("@loc_") else name


def _general(comps):
    att = _get(_comp(comps, "SAttachableComponentParams"), "AttachDef")
    typ, sub = _text(att, "Type"), _text(att, "SubType")
    if sub and sub.lower() not in ("undefined", "unknown", typ.lower()):
        typ = f"{typ} / {sub}" if typ else sub
    size, grade = _num(att, "Size"), _num(att, "Grade")
    return _rows([["type", typ], ["size", int(size) if size else None], ["grade", int(grade) if grade else None],
                  ["manufacturer", _maker(_get(att, "Manufacturer"))],
                  ["mass", _round(_num(_comp(comps, "SEntityPhysicsControllerParams"), "PhysType.Mass"), 2)],
                  ["health", _round(_num(_comp(comps, "SHealthComponentParams"), "Health"), 0)]])


def _shield(comps):
    s = _comp(comps, "SCItemShieldGeneratorParams")
    return _rows([["shield_hp", _round(_num(s, "MaxShieldHealth"), 0)], ["shield_regen", _round(_num(s, "MaxShieldRegen"), 1)],
                  ["regen_delay_damaged", _round(_num(s, "DamagedRegenDelay"), 2)],
                  ["regen_delay_down", _round(_num(s, "DownedRegenDelay"), 2)]]) if s is not None else []


def _quantum(comps):
    q = _comp(comps, "SCItemQuantumDriveParams")
    if q is None:
        return []
    speed = _num(q, "params.driveSpeed")
    return _rows([["quantum_speed", _round(speed / 1000.0, 0) if speed else None],
                  ["spool_time", _round(_num(q, "params.spoolUpTime"), 2)],
                  ["cooldown", _round(_num(q, "params.cooldownTime"), 2)],
                  ["quantum_fuel_rate", _round(_num(q, "quantumFuelRequirement"), 5)]])


def _cooler(comps):
    return _rows([["cooling_rate", _round(_num(_comp(comps, "SCItemCoolerParams"), "CoolingRate"), 0)]])


def _thruster(comps):
    return _rows([["thrust", _round(_num(_comp(comps, "SCItemThrusterParams"), "thrustCapacity"), 0)]])


def _armor(comps):
    suit = _comp(comps, "SCItemSuitArmorParams")
    rows = []
    if suit is not None:
        res = _get(suit, "damageResistance")
        inner = _get(res, "damageResistance")
        res = inner if isinstance(inner, View) else res
        for d in DAMAGE:
            mult = _num(res, f"{d}Resistance.Multiplier")
            rows.append([f"res_{d}", _round((1.0 - mult) * 100.0, 1) if mult is not None and mult != 1.0 else None])
    temp = _get(_comp(comps, "SCItemClothingParams"), "TemperatureResistance")
    rows += [["temp_min", _round(_num(temp, "MinResistance"), 0)], ["temp_max", _round(_num(temp, "MaxResistance"), 0)]]
    return _rows(rows)


# ---------------------------------------------------------------------------------------------- ships and vehicles
def vehicle_parts_totals(xml_bytes):
    """(health, mass) summed over the parts of a vehicle implementation XML (<Part damageMax=… mass=…>)."""
    hp = mass = 0.0
    for part in cryxml.parse(xml_bytes).iter("Part"):
        for attr in ("damageMax", "damagemax"):
            try:
                hp += float(part.get(attr) or 0)
            except ValueError:
                pass
        try:
            mass += float(part.get("mass") or 0)
        except ValueError:
            pass
    return hp, mass


def _walk(idx, entries, depth=0):
    """Every item of a factory loadout, the ones without a model too (flight controller, shields…): (record,
    components)."""
    for e in entries or []:
        try:
            if e is None:
                continue
            ri = idx.by_name.get((e["entityClassName"] or "").lower()) if e["entityClassName"] else None
            if ri is None:
                ref = e["entityClassReference"]
                ri = ref if isinstance(ref, int) and not isinstance(ref, bool) else None
            if ri is None:
                continue
            comps = idx.info(ri)[2]
            nested = e["loadout"]
            sub = nested["entries"] if nested is not None and nested.has("entries") else None
        except (KeyError, TypeError):
            continue
        yield ri, comps
        if depth + 1 < entities.MAX_DEPTH:
            yield from _walk(idx, sub if sub else idx.entries(comps), depth + 1)


def _cargo_scu(comps):
    box = _get(_comp(comps, "SCItemInventoryContainerComponentParams"), "containerParams")
    dims = [_num(box, f"interiorDimensions.{k}") for k in "xyz"]
    return math.floor(dims[0] * dims[1] * dims[2] / SCU_M3 + 1e-6) if all(dims) else 0


def _vehicle(idx, comps, read, entry_of):
    """(vehicle rows, flight rows, loadout rows) of a ship or ground vehicle."""
    v = _comp(comps, "VehicleComponentParams")
    box = [_num(v, f"maxBoundingBoxSize.{k}") for k in "xyz"]
    hp = _num(_comp(comps, "SHealthComponentParams"), "Health")
    mass = _num(_comp(comps, "SEntityPhysicsControllerParams"), "PhysType.Mass")
    path = entities._vehicle_definition(comps)
    if path and read is not None and not (hp and mass):
        try:
            xml = read(path)
            parts_hp, parts_mass = vehicle_parts_totals(xml) if xml else (0, 0)
            hp, mass = hp or parts_hp, mass or parts_mass
        except Exception:           # a broken XML: those two rows are missing
            pass
    crew = _num(v, "crewSize")
    vehicle = _rows([["manufacturer", _maker(_get(v, "manufacturer"))],
                     ["role", _text(v, "vehicleRole")], ["career", _text(v, "vehicleCareer")],
                     ["crew", int(crew) if crew else None],
                     ["length", _round(box[1], 1)], ["width", _round(box[0], 1)], ["height", _round(box[2], 1)],
                     ["hull_hp", _round(hp, 0)], ["mass", _round(mass, 0)]])
    flight, shields, guns, dps, missiles, cargo, quantum = [], [0.0, 0.0, 0], {}, 0.0, 0, 0, None
    for ri, cs in _walk(idx, idx.entries(comps)):
        ifcs = _comp(cs, "IFCSParams")
        if ifcs is not None and not flight:
            flight = _rows([["scm_speed", _round(_num(ifcs, "scmSpeed"), 0)], ["max_speed", _round(_num(ifcs, "maxSpeed"), 0)],
                            ["boost_speed", _round(_num(ifcs, "boostSpeedForward"), 0)],
                            ["boost_speed_back", _round(_num(ifcs, "boostSpeedBackward"), 0)],
                            ["pitch", _round(_num(ifcs, "maxAngularVelocity.x"), 1)],
                            ["yaw", _round(_num(ifcs, "maxAngularVelocity.z"), 1)],
                            ["roll", _round(_num(ifcs, "maxAngularVelocity.y"), 1)]])
        s = _comp(cs, "SCItemShieldGeneratorParams")
        if s is not None:
            shields = [shields[0] + (_num(s, "MaxShieldHealth") or 0), shields[1] + (_num(s, "MaxShieldRegen") or 0),
                       shields[2] + 1]
        typ = _text(_comp(cs, "SAttachableComponentParams"), "AttachDef.Type").lower()
        size = int(_num(_comp(cs, "SAttachableComponentParams"), "AttachDef.Size") or 0)
        if typ == "weapongun":
            got = dict(next((rows for g, rows in entry_of(ri)["groups"] if g == "weapon"), []))
            if got:
                guns[size] = guns.get(size, 0) + 1
                dps += got.get("dps") or 0
        elif typ == "missile":
            missiles += 1
        elif typ in ("cargogrid", "cargo"):
            cargo += _cargo_scu(cs)
        if quantum is None and _comp(cs, "SCItemQuantumDriveParams") is not None:
            quantum = dict(_quantum(cs)).get("quantum_speed")
    loadout = _rows([["shield_hp", _round(shields[0], 0)], ["shield_regen", _round(shields[1], 1)],
                     ["shields", shields[2] if shields[2] > 1 else None],
                     ["weapons", ", ".join(f"{n}× S{s}" for s, n in sorted(guns.items(), reverse=True))],
                     ["weapons_dps", _round(dps, 0)], ["missiles", missiles], ["cargo", cargo],
                     ["quantum_speed", quantum]])
    return vehicle, flight, loadout


# ---------------------------------------------------------------------------------------------- the index
def _kind(comps, groups, geo):
    have = {g for g, _ in groups}
    if "vehicle" in have:
        return "vehicle" if "/vehicles/" in f"/{geo}" else "ship"
    typ = _text(_comp(comps, "SAttachableComponentParams"), "AttachDef.Type").lower()
    if "weapon" in have:
        return "weapon" if typ == "weaponpersonal" else "ship_weapon"
    for group, kind in (("missile", "missile"), ("shield", "shield"), ("quantum", "quantum_drive"),
                        ("cooler", "cooler"), ("thruster", "thruster"), ("armor", "armor")):
        if group in have:
            return kind
    return ""


def build(idx, read=None):
    """idx: entities.open_index(); read(path) -> bytes or None, for the vehicle implementation XMLs."""
    dc = idx.dc
    done = {}

    def entry_of(ri):
        if ri in done:
            return done[ri]
        done[ri] = entry = {"record": dc.record_name(ri).split(".", 1)[-1], "name": "", "kind": "", "geo": "",
                            "groups": []}
        try:
            geo, _adb, comps = idx.info(ri)
            entry["geo"] = entities._norm(geo)
            groups = []
            if _comp(comps, "VehicleComponentParams") is not None:
                entry["name"] = entities._vehicle_name(comps)
                groups += zip(("vehicle", "flight", "loadout"), _vehicle(idx, comps, read, entry_of))
            else:
                entry["name"] = entities._item_name(comps)
                groups += [("weapon", _weapon(idx, comps)), ("missile", _missile(comps)), ("shield", _shield(comps)),
                           ("quantum", _quantum(comps)), ("cooler", _cooler(comps)), ("thruster", _thruster(comps)),
                           ("armor", _armor(comps))]
            groups = [[g, rows] for g, rows in groups if rows]
            if groups:
                # a ship's own rows already say what it is and who makes it
                general = [] if groups[0][0] == "vehicle" else _general(comps)
                groups = ([["general", general]] if general else []) + groups
                entry["kind"] = _kind(comps, groups, entry["geo"])
            entry["groups"] = groups if entry["kind"] else []
        except Exception:                   # one odd record does not stop the others
            entry["groups"] = []
        return entry

    records, geo = {}, {}
    for ri in dc.records_of("EntityClassDefinition"):
        entry = entry_of(ri)
        if not entry["groups"]:
            continue
        records[entry["record"].lower()] = entry
        if entry["geo"]:
            geo.setdefault(entry["geo"], []).append(entry["record"])
    for path, names in geo.items():
        stem = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        names.sort(key=lambda n: (not n.lower().endswith(stem), len(n), n))
    return {"version": VERSION, "records": records, "geo": geo}


def for_path(index, path):
    """The entries that share a model, the one named like the file first."""
    index = index or {}
    names = index.get("geo", {}).get(entities._norm(path), [])
    return [index["records"][n.lower()] for n in names if n.lower() in index.get("records", {})]


def of_kind(index, kind):
    return sorted((e for e in (index or {}).get("records", {}).values() if e["kind"] == kind),
                  key=lambda e: e["record"].lower())


def flat(entry):
    """{stat id: value} of an entry; the first group that has a stat gives it."""
    out = {}
    for _g, rows in entry["groups"]:
        for k, v in rows:
            out.setdefault(k, v)
    return out


def table(entries, label=lambda stat: stat, text=lambda stat, value: value, name=lambda entry: entry["record"]):
    """The entries as the lines of a table, one each, under a line of headings: a column for every stat one of
    them has. label(stat) -> heading, text(stat, value) -> the value as shown, name(entry) -> its name in game."""
    rows = [(e, flat(e)) for e in entries]
    cols = [k for k in UNITS if any(k in f for _, f in rows)]
    head = ["Record", "Name"] + [label(k) + (f" ({UNITS[k]})" if UNITS[k] else "") for k in cols]
    return [head] + [[e["record"], name(e)] + [text(k, f[k]) if k in f else "" for k in cols] for e, f in rows]


def csv_bytes(lines):
    """A table as a CSV file; the byte order mark makes spreadsheets read the accents and the "×" right."""
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerows(lines)
    return out.getvalue().encode("utf-8-sig")


def coverage(index):
    """{kind: {"records": n, "stats": {stat id: how many records have it}}}: a stat that no record of any kind has
    means the game renamed what it was read from."""
    out = {k: {"records": 0, "stats": {}} for k in KINDS}
    for e in (index or {}).get("records", {}).values():
        c = out.setdefault(e["kind"], {"records": 0, "stats": {}})
        c["records"] += 1
        for k in flat(e):
            c["stats"][k] = c["stats"].get(k, 0) + 1
    return out


def missing(index):
    """Stat ids that no record has."""
    seen = {k for c in coverage(index).values() for k in c["stats"]}
    return [k for k in UNITS if k not in seen]


# ---------------------------------------------------------------------------------------------- everything, raw
def find_record(dc, name):
    """Record index of an entity by its name ("ANVL_Hornet_F7C", any case), or None."""
    want = name.lower()
    for ri in dc.records_of("EntityClassDefinition"):
        if dc.record_name(ri).split(".", 1)[-1].lower() == want:
            return ri
    return None


def raw(dc, ri, depth=8, follow=2, budget=60000):
    """Everything DataCore has on a record, as nested dicts. The records it refers to (ammunition, manufacturer,
    damage tables…) are read in their place, `follow` levels deep; other entities are only named."""
    left = [budget]
    entity = dc.struct_index.get("EntityClassDefinition")

    def expand(node, level):
        if isinstance(node, list):
            return [expand(x, level) for x in node]
        if not isinstance(node, dict):
            return node
        left[0] -= 1
        ref = node.get("_record")
        if "_ref" in node and isinstance(ref, int):
            name = dc.record_name(ref)
            if level >= follow or left[0] <= 0 or int(dc.records[ref]["struct"]) == entity:
                return {"_ref": name}
            return {"_ref": name, **expand(dc.record(ref, depth), level + 1)}
        if "_weak" in node:
            return {"_weak": node["_weak"][0]}
        return {k: expand(x, level) for k, x in node.items() if k != "_record"}
    return expand(dc.record(ri, depth), 0)


def schema(dc, text):
    """{struct name: [property names]} of the structs whose name, or one of whose properties, holds `text`."""
    want = text.lower()
    out = {}
    for name, si in dc.struct_index.items():
        props = [p[0] for p in dc.struct_props(si)]
        if want in name.lower() or any(want in p.lower() for p in props):
            out[name] = props
    return out


def slug(text):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", text).strip("_") or "values"

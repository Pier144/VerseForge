"""Writes a small DataCore file (Game2.dcb, format v8) from Python dicts, for tests that need one without the game.

    b = Dcb({"Gun": {"fireRate": "f32", "ammo": "ref", "modes": "[strong]", "box": "class:Vec3"}, "Vec3": {...}})
    b.record("EntityClassDefinition.MyGun", {"_type": "Gun", "fireRate": 300.0, "ammo": "AmmoParams.Bullet"})
    data = b.build()

Property types: f32 i32 bool str enum locale, class:<Struct> (inline), strong (pointer to any struct), ref (a
record, by its full name), and their arrays: [f32] [strong] [class:<Struct>] [ref]… A property left out is zero,
empty or null."""
import struct
import uuid

from sc_explorer import datacore as dcmod

_TYPES = {"f32": dcmod.F32, "i32": dcmod.I32, "bool": dcmod.BOOL, "str": dcmod.STRING, "enum": dcmod.ENUM,
          "locale": dcmod.LOCALE, "strong": dcmod.STRONG, "ref": dcmod.REFERENCE}


def _guid(name):
    return uuid.uuid5(uuid.NAMESPACE_URL, name.lower()).bytes_le


class Dcb:
    def __init__(self, structs):
        self.names = list(structs)
        self.props = {}                                     # struct -> [(name, type, array?, target struct or None)]
        for sname, props in structs.items():
            out = []
            for pname, spec in props.items():
                array = spec.startswith("[")
                spec = spec.strip("[]")
                if spec.startswith("class:"):
                    out.append((pname, dcmod.CLASS, array, spec[6:]))
                else:
                    out.append((pname, _TYPES[spec], array, None))
            self.props[sname] = out
        self.blocks = {n: [] for n in self.names}           # struct -> its instances, as bytes
        self.pools = {typ: [] for typ, _ in dcmod._POOLS}
        self.text, self.text_at = bytearray(), {}
        self.blob, self.blob_at = bytearray(), {}
        self.records = []

    # ------------------------------------------------------------------ strings
    def _str(self, s, table, at):
        if s not in at:
            at[s] = len(table)
            table += s.encode("utf-8") + b"\0"
        return at[s]

    def _text(self, s):
        return self._str(s or "", self.text, self.text_at)

    def _name(self, s):
        return self._str(s, self.blob, self.blob_at)

    # ------------------------------------------------------------------ values
    def size(self, sname):
        total = 0
        for _, typ, array, target in self.props[sname]:
            total += 8 if array else (self.size(target) if typ == dcmod.CLASS else dcmod._INLINE[typ])
        return total

    def add(self, obj):
        """An instance in its struct's block: (struct index, instance index)."""
        sname = obj["_type"]
        block = self.blocks[sname]
        block.append(None)                                  # its place is taken before its children are written
        at = len(block) - 1
        block[at] = self._encode(obj)
        return self.names.index(sname), at

    def _scalar(self, typ, value):
        if typ in dcmod._SCALAR:
            return struct.pack(dcmod._SCALAR[typ], value or 0)
        if typ in (dcmod.STRING, dcmod.ENUM, dcmod.LOCALE):
            return struct.pack("<i", self._text(value))
        if typ == dcmod.STRONG:
            return struct.pack("<ii", *(self.add(value) if value else (-1, -1)))
        if typ == dcmod.REFERENCE:
            return b"\0\0\0\0" + (_guid(value) if value else bytes(16))
        raise ValueError(typ)

    def _encode(self, obj):
        out = b""
        for pname, typ, array, target in self.props[obj["_type"]]:
            value = obj.get(pname)
            if not array:
                out += self._encode({"_type": target, **(value or {})}) if typ == dcmod.CLASS else self._scalar(typ, value)
                continue
            items = value or []
            if typ == dcmod.CLASS:
                block = self.blocks[target]
                first = len(block)
                block.extend([None] * len(items))           # an array's instances sit side by side
                for k, item in enumerate(items):
                    block[first + k] = self._encode({"_type": target, **item})
            else:
                packed = [self._scalar(typ, item) for item in items]   # children first: they may use the pool too
                first = len(self.pools[typ])
                self.pools[typ].extend(packed)
            out += struct.pack("<ii", len(items), first)
        return out

    def record(self, name, obj, file=""):
        """name: "<Struct>.<record name>", as the game writes it."""
        si, at = self.add(obj)
        self.records.append((self._name(name), self._text(file), si, _guid(name), at))

    # ------------------------------------------------------------------ the file
    def build(self):
        structs, props = b"", b""
        for sname in self.names:
            mine = self.props[sname]
            structs += struct.pack("<iiHHI", self._name(sname), -1, len(mine), len(props) // 12, self.size(sname))
            for pname, typ, array, target in mine:
                props += struct.pack("<iHHHH", self._name(pname), self.names.index(target) if target else 0, typ,
                                     1 if array else 0, 0)
        used = [n for n in self.names if self.blocks[n]]
        maps = b"".join(struct.pack("<Ii", len(self.blocks[n]), self.names.index(n)) for n in used)
        records = b"".join(struct.pack("<iiii16sHH", name, file, 0, si, guid, at, 0)
                           for name, file, si, guid, at in self.records)
        pools = b"".join(b"".join(self.pools[typ]) for typ, _ in dcmod._POOLS)
        counts = [len(self.pools[typ]) for typ in dcmod._POOL_COUNT_ORDER]
        header = struct.pack("<30i", 0, 8, 0, 0, len(self.names), len(props) // 12, 0, len(used), len(self.records),
                             *counts, 0, len(self.text), len(self.blob))
        data = b"".join(b"".join(self.blocks[n]) for n in used)
        return header + structs + props + maps + records + pools + bytes(self.text) + bytes(self.blob) + data

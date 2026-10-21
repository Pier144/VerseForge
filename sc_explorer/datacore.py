"""Minimal reader for Star Citizen's DataCore (Data/Game2.dcb, format v8): records -> nested dicts on demand."""
import struct
import uuid

import numpy as np

# property data types
BOOL, I8, I16, I32, I64, U8, U16, U32, U64 = 1, 2, 3, 4, 5, 6, 7, 8, 9
STRING, F32, F64, LOCALE, GUID, ENUM = 10, 11, 12, 13, 14, 15
CLASS, STRONG, WEAK, REFERENCE = 0x10, 0x110, 0x210, 0x310

_SCALAR = {BOOL: "<?", I8: "<b", I16: "<h", I32: "<i", I64: "<q", U8: "<B", U16: "<H", U32: "<I", U64: "<Q",
           F32: "<f", F64: "<d"}
_INLINE = {BOOL: 1, I8: 1, I16: 2, I32: 4, I64: 8, U8: 1, U16: 2, U32: 4, U64: 8, STRING: 4, F32: 4, F64: 8,
           LOCALE: 4, GUID: 16, ENUM: 4, STRONG: 8, WEAK: 8, REFERENCE: 20}
# order of the value pools that array properties index into
_POOLS = [(I8, 1), (I16, 2), (I32, 4), (I64, 8), (U8, 1), (U16, 2), (U32, 4), (U64, 8), (BOOL, 1), (F32, 4),
          (F64, 8), (GUID, 16), (STRING, 4), (LOCALE, 4), (ENUM, 4), (STRONG, 8), (WEAK, 8), (REFERENCE, 20)]
_POOL_COUNT_ORDER = [BOOL, I8, I16, I32, I64, U8, U16, U32, U64, F32, F64, GUID, STRING, LOCALE, ENUM, STRONG, WEAK,
                     REFERENCE]


def _guid(b):
    return str(uuid.UUID(bytes_le=bytes(b)))


class DataCore:
    def __init__(self, data: bytes):
        self.d = d = data
        h = struct.unpack_from("<30i", d, 0)
        if h[1] < 6:
            raise ValueError(f"DataCore version {h[1]} not supported")
        n_struct, n_prop, n_enum, n_map, n_rec = h[4:9]
        counts = dict(zip(_POOL_COUNT_ORDER, h[9:27]))
        n_enum_opt, l_text, l_blob = h[27:30]
        o = 120
        self.structs = np.frombuffer(d, np.dtype([("name", "<i4"), ("parent", "<i4"), ("nattr", "<u2"),
                                                  ("first", "<u2"), ("size", "<u4")]), n_struct, o)
        o += 16 * n_struct
        self.props = np.frombuffer(d, np.dtype([("name", "<i4"), ("index", "<u2"), ("type", "<u2"),
                                                ("conv", "<u2"), ("pad", "<u2")]), n_prop, o)
        o += 12 * n_prop
        o += 8 * n_enum
        maps = np.frombuffer(d, np.dtype([("count", "<u4"), ("struct", "<i4")]), n_map, o)
        o += 8 * n_map
        rec_size = 36 if h[1] >= 8 else 32          # v8 added a third string offset to each record
        fields = [("name", "<i4"), ("file", "<i4")] + ([("tag", "<i4")] if rec_size == 36 else []) + [
            ("struct", "<i4"), ("guid", "V16"), ("instance", "<u2"), ("other", "<u2")]
        self.records = np.frombuffer(d, np.dtype(fields), n_rec, o)
        o += rec_size * n_rec
        self.pool = {}
        for typ, size in _POOLS:
            self.pool[typ] = o
            o += size * counts[typ]
        o += 4 * n_enum_opt
        self.text, self.blob = o, o + l_text
        o += l_text + l_blob
        self.block = {}
        for m in maps:
            self.block[int(m["struct"])] = o
            o += int(m["count"]) * int(self.structs[m["struct"]]["size"])
        self._props_cache = {}
        self.struct_index = {self.blob_str(s["name"]): i for i, s in enumerate(self.structs)}
        self._by_guid = None

    # ------------------------------------------------------------------ strings
    def _cstr(self, off):
        return self.d[off:self.d.index(b"\0", off)].decode("utf-8", "replace")

    def text_str(self, off):
        return self._cstr(self.text + off) if off >= 0 else ""

    def blob_str(self, off):
        return self._cstr(self.blob + off) if off >= 0 else ""

    # ------------------------------------------------------------------ structure
    def struct_props(self, si):
        if si not in self._props_cache:
            chain, s = [], si
            while s >= 0:
                chain.append(s)
                s = int(self.structs[s]["parent"])
            props = []
            for s in reversed(chain):
                st = self.structs[s]
                props += [self.props[i] for i in range(st["first"], st["first"] + st["nattr"])]
            self._props_cache[chain[0]] = [(self.blob_str(p["name"]), int(p["type"]), int(p["conv"]), int(p["index"]))
                                           for p in props]
        return self._props_cache[si]

    def struct_name(self, si):
        return self.blob_str(self.structs[si]["name"])

    def record_name(self, ri):
        return self.blob_str(self.records[ri]["name"])

    def record_file(self, ri):
        return self.text_str(self.records[ri]["file"])

    def records_of(self, struct_name):
        si = self.struct_index.get(struct_name)
        return [] if si is None else np.nonzero(self.records["struct"] == si)[0].tolist()

    def record_by_guid(self, guid):
        if self._by_guid is None:
            self._by_guid = {_guid(r["guid"].tobytes()): i for i, r in enumerate(self.records)}
        return self._by_guid.get(guid)

    # ------------------------------------------------------------------ values
    def _value(self, typ, off, si, depth):
        d = self.d
        if typ in _SCALAR:
            return struct.unpack_from(_SCALAR[typ], d, off)[0]
        if typ in (STRING, LOCALE, ENUM):
            return self.text_str(struct.unpack_from("<i", d, off)[0])
        if typ == GUID:
            return _guid(d[off:off + 16])
        if typ == CLASS:
            return self.instance(si, None, depth - 1, off)
        if typ in (STRONG, WEAK):
            s, i = struct.unpack_from("<ii", d, off)
            if s < 0 or i < 0:
                return None
            return self.instance(s, i, depth - 1) if typ == STRONG else {"_weak": (self.struct_name(s), i)}
        if typ == REFERENCE:
            g = _guid(d[off + 4:off + 20])
            if g == "00000000-0000-0000-0000-000000000000":
                return None
            ri = self.record_by_guid(g)
            return {"_ref": self.record_file(ri) if ri is not None else g, "_record": ri}
        return None

    def instance(self, si, index, depth=6, off=None):
        """Struct instance as a dict (pointers followed up to `depth` levels)."""
        if off is None:
            off = self.block[si] + index * int(self.structs[si]["size"])
        out = {"_type": self.struct_name(si)}
        if depth < 0:
            return out
        for name, typ, conv, idx in self.struct_props(si):
            if conv == 0:
                out[name] = self._value(typ, off, idx, depth)
                off += int(self.structs[idx]["size"]) if typ == CLASS else _INLINE[typ]
            else:
                count, first = struct.unpack_from("<ii", self.d, off)
                off += 8
                if typ == CLASS:
                    size = int(self.structs[idx]["size"])
                    out[name] = [self.instance(idx, first + k, depth - 1) for k in range(count)] if depth > 0 else []
                else:
                    size = _INLINE[typ]
                    base = self.pool[typ]
                    out[name] = [self._value(typ, base + (first + k) * size, idx, depth) for k in range(count)]
        return out

    def record(self, ri, depth=6):
        r = self.records[ri]
        out = self.instance(int(r["struct"]), int(r["instance"]), depth)
        out["_name"] = self.record_name(ri)
        out["_file"] = self.record_file(ri)
        return out

    # ------------------------------------------------------------------ lazy access (fast scans)
    def layout(self, si):
        """name -> (offset in instance, type, conversion, struct/enum index), cached per struct."""
        key = ("layout", si)
        if key not in self._props_cache:
            off, out = 0, {}
            for name, typ, conv, idx in self.struct_props(si):
                out[name] = (off, typ, conv, idx)
                off += 8 if conv else (int(self.structs[idx]["size"]) if typ == CLASS else _INLINE[typ])
            self._props_cache[key] = out
        return self._props_cache[key]

    def view(self, si, index):
        return View(self, si, self.block[si] + index * int(self.structs[si]["size"]))

    def record_view(self, ri):
        r = self.records[ri]
        return self.view(int(r["struct"]), int(r["instance"]))


class View:
    """Lazy struct instance: v["Prop"] reads just that property (nested classes/pointers come back as Views)."""
    __slots__ = ("dc", "si", "off")

    def __init__(self, dc, si, off):
        self.dc, self.si, self.off = dc, si, off

    @property
    def type(self):
        return self.dc.struct_name(self.si)

    def has(self, name):
        return name in self.dc.layout(self.si)

    def _one(self, typ, off, idx):
        dc = self.dc
        if typ == CLASS:
            return View(dc, idx, off)
        if typ in (STRONG, WEAK):
            s, i = struct.unpack_from("<ii", dc.d, off)
            return dc.view(s, i) if s >= 0 and i >= 0 and s in dc.block else None
        if typ == REFERENCE:
            g = _guid(dc.d[off + 4:off + 20])
            return dc.record_by_guid(g) if g != "00000000-0000-0000-0000-000000000000" else None
        return dc._value(typ, off, idx, 0)

    def __getitem__(self, name):
        off, typ, conv, idx = self.dc.layout(self.si)[name]
        off += self.off
        if conv == 0:
            return self._one(typ, off, idx)
        count, first = struct.unpack_from("<ii", self.dc.d, off)
        if typ == CLASS:
            return [self.dc.view(idx, first + k) for k in range(count)]
        size, base = _INLINE[typ], self.dc.pool[typ]
        return [self._one(typ, base + (first + k) * size, idx) for k in range(count)]

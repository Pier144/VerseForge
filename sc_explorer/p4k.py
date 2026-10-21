"""Reader for Star Citizen's Data.p4k archive (ZIP64 with zstd compression and AES-CBC encrypted entries)."""
import os
import pickle
import struct
import threading

import numpy as np
import zstandard
from Crypto.Cipher import AES

P4K_KEY = bytes.fromhex("5E7A2002302EEB1A3BB617C30FDE1E47")
CACHE_VERSION = 2


class P4kArchive:
    def __init__(self, path, cache_dir):
        self.path = path
        self.cache_dir = cache_dir
        self._lock = threading.Lock()
        self._fh = None
        self.names = []          # original names, e.g. "Data\\Objects\\..."
        self.lookup = {}         # lowercase forward-slash path -> entry index
        self.method = self.csize = self.usize = self.offset = None

    # ------------------------------------------------------------------ index
    def _cache_file(self):
        st = os.stat(self.path)
        return os.path.join(self.cache_dir, f"p4k_index_v{CACHE_VERSION}_{st.st_size}_{int(st.st_mtime)}.pkl")

    def load(self, progress=None):
        os.makedirs(self.cache_dir, exist_ok=True)
        cache = self._cache_file()
        if os.path.exists(cache):
            with open(cache, "rb") as f:
                self.names, self.method, self.csize, self.usize, self.offset = pickle.load(f)
        else:
            self._read_central_directory(progress)
            for old in os.listdir(self.cache_dir):
                if old.startswith("p4k_index_"):
                    try:
                        os.remove(os.path.join(self.cache_dir, old))
                    except OSError:
                        pass
            with open(cache, "wb") as f:
                pickle.dump((self.names, self.method, self.csize, self.usize, self.offset), f, protocol=5)
        self.lookup = {self.norm(n): i for i, n in enumerate(self.names)}
        self._fh = open(self.path, "rb")

    @staticmethod
    def norm(name):
        name = name.replace("\\", "/").lower()
        return name[5:] if name.startswith("data/") else name

    def _read_central_directory(self, progress):
        size = os.path.getsize(self.path)
        with open(self.path, "rb") as f:
            f.seek(size - 65536)
            tail = f.read()
            i = tail.rfind(b"PK\x06\x06")
            if i < 0:
                raise ValueError("Data.p4k: ZIP64 end of central directory not found")
            count, cd_size, cd_off = struct.unpack_from("<QQQ", tail, i + 32)
            f.seek(cd_off)
            cd = f.read(cd_size)
        names = []
        method = np.zeros(count, np.uint16)
        csize = np.zeros(count, np.uint64)
        usize = np.zeros(count, np.uint64)
        offset = np.zeros(count, np.uint64)
        p, k = 0, 0
        unpack = struct.unpack_from
        while p < len(cd) and cd[p:p + 4] == b"PK\x01\x02":
            meth = unpack("<H", cd, p + 10)[0]
            cs, us = unpack("<II", cd, p + 20)
            nl, el, cl = unpack("<HHH", cd, p + 28)
            off = unpack("<I", cd, p + 42)[0]
            names.append(cd[p + 46:p + 46 + nl].decode("utf-8", "replace"))
            q, end = p + 46 + nl, p + 46 + nl + el
            while q + 4 <= end:
                hid, hl = unpack("<HH", cd, q)
                if hid == 1:
                    r = q + 4
                    if us == 0xFFFFFFFF:
                        us = unpack("<Q", cd, r)[0]; r += 8
                    if cs == 0xFFFFFFFF:
                        cs = unpack("<Q", cd, r)[0]; r += 8
                    if off == 0xFFFFFFFF:
                        off = unpack("<Q", cd, r)[0]
                    break
                q += 4 + hl
            method[k], csize[k], usize[k], offset[k] = meth, cs, us, off
            k += 1
            p = end + cl
            if progress and k % 50000 == 0:
                progress(k / count)
        self.names = names
        self.method, self.csize, self.usize, self.offset = method[:k], csize[:k], usize[:k], offset[:k]

    # ------------------------------------------------------------------ access
    def exists(self, path):
        return self.norm(path) in self.lookup

    def size(self, path):
        return int(self.usize[self.lookup[self.norm(path)]])

    def read(self, path):
        i = self.lookup.get(self.norm(path))
        if i is None:
            raise FileNotFoundError(path)
        return self.read_index(i)

    def read_index(self, i):
        with self._lock:
            self._fh.seek(int(self.offset[i]))
            header = self._fh.read(30)
            nl, el = struct.unpack_from("<HH", header, 26)
            self._fh.seek(int(self.offset[i]) + 30 + nl + el)
            data = self._fh.read(int(self.csize[i]))
        if self.method[i] == 0:
            return data
        if data[:4] != b"\x28\xb5\x2f\xfd":
            data = AES.new(P4K_KEY, AES.MODE_CBC, b"\0" * 16).decrypt(data + b"\0" * ((-len(data)) % 16))
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=int(self.usize[i]))

"""Disk cache of what the viewer asks for again and again: built model files (GLB), model descriptions (info) and
game textures. A model opened once opens again without being rebuilt from Data.p4k.

One folder per program version and game version (`disk_<app version>_<p4k size>_<p4k time>`): when either changes the
old folder is deleted. Files are evicted, least recently used first, beyond `limit` bytes. Writes go through a temp
file, so a crash never leaves half a file behind."""
import hashlib
import os
import shutil
import threading

FORMAT = 4                          # bump when cached content changes shape within the same app version
                                    # 2: viewer GLBs merged further (export.to_glb merge)
DEFAULT_LIMIT = 10 * 1024 ** 3      # 10 GB
PREFIX = "disk_"


class DiskCache:
    def __init__(self, root, limit=DEFAULT_LIMIT):
        self.root = root
        self.limit = limit
        self.enabled = True
        self.dir = None
        self.size = 0
        self._lock = threading.Lock()

    def bind(self, app_version, p4k_path):
        """Use the folder of this program + game version; folders of other versions are removed."""
        try:
            st = os.stat(p4k_path)
        except OSError:
            self.dir = None
            return
        name = f"{PREFIX}{app_version}_f{FORMAT}_{st.st_size}_{int(st.st_mtime)}"
        with self._lock:
            self.dir = os.path.join(self.root, name)
            os.makedirs(self.dir, exist_ok=True)
            for old in os.listdir(self.root):
                if old.startswith(PREFIX) and old != name:
                    shutil.rmtree(os.path.join(self.root, old), ignore_errors=True)
            self.size = self._scan()

    def _scan(self):
        total = 0
        for dp, _, files in os.walk(self.dir):
            for f in files:
                try:
                    total += os.path.getsize(os.path.join(dp, f))
                except OSError:
                    pass
        return total

    def _path(self, kind, key, ext):
        h = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()
        return os.path.join(self.dir, kind, h[:2], f"{h}.{ext}")

    def get(self, kind, key, ext):
        """Cached bytes or None."""
        if not self.enabled or not self.dir:
            return None
        p = self._path(kind, key, ext)
        try:
            with open(p, "rb") as f:
                data = f.read()
            os.utime(p)                 # recently used: evicted last
            return data
        except OSError:
            return None

    def put(self, kind, key, ext, data):
        """Store bytes; True when they are on disk now (False: cache off, or the write failed)."""
        if not self.enabled or not self.dir or not data:
            return False
        p = self._path(kind, key, ext)
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            tmp = f"{p}.{threading.get_ident()}.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            old = os.path.getsize(p) if os.path.exists(p) else 0
            os.replace(tmp, p)
        except OSError:
            return False
        with self._lock:
            self.size += len(data) - old
            over = self.size > self.limit
        if over:
            self._evict()
        return os.path.exists(p)        # an eviction may have taken it already

    def _evict(self):
        """Remove the least recently used files down to 85 % of the limit."""
        with self._lock:
            files = []
            for dp, _, names in os.walk(self.dir):
                for f in names:
                    fp = os.path.join(dp, f)
                    try:
                        s = os.stat(fp)
                        files.append((s.st_mtime, s.st_size, fp))
                    except OSError:
                        pass
            files.sort()
            total = sum(f[1] for f in files)
            for _, size, fp in files:
                if total <= self.limit * 0.85:
                    break
                try:
                    os.remove(fp)
                    total -= size
                except OSError:
                    pass
            self.size = total

    def clear(self):
        """Delete everything cached (the folder stays, empty)."""
        with self._lock:
            if self.dir:
                shutil.rmtree(self.dir, ignore_errors=True)
                os.makedirs(self.dir, exist_ok=True)
            self.size = 0

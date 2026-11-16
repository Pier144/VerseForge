"""Watertight, filled STL for 3D printing.

Game meshes are open shells made of overlapping pieces. Pipeline (same one used for the P4-AR cosplay print):
  1. Blender (background): solidify every surface and voxel-remesh -> one closed shell
  2. Python: voxelise the shell, close small openings, fill the hollow interior with an inset core, union.
"""
import glob
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import trimesh

from . import i18n, paths

BLENDER_SCRIPT = r'''
import bpy, sys
a = sys.argv[sys.argv.index("--") + 1:]
src, dst, vox, thick, target = a[0], a[1], float(a[2]), float(a[3]), int(a[4])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.wm.stl_import(filepath=src)
ob = bpy.context.selected_objects[0]; bpy.context.view_layer.objects.active = ob
bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.005); bpy.ops.object.mode_set(mode="OBJECT")
m = ob.modifiers.new("sol", "SOLIDIFY"); m.thickness = thick; m.offset = -1; m.use_rim = True
r = ob.modifiers.new("rem", "REMESH"); r.mode = "VOXEL"; r.voxel_size = vox; r.adaptivity = 0
bpy.ops.object.modifier_apply(modifier="sol"); bpy.ops.object.modifier_apply(modifier="rem")
n = len(ob.data.polygons)
if n > target:
    d = ob.modifiers.new("dec", "DECIMATE"); d.ratio = target / n; bpy.ops.object.modifier_apply(modifier="dec")
bpy.ops.wm.stl_export(filepath=dst)
'''

BLENDER_CANDIDATES = [
    r"C:\Program Files\Blender Foundation",
    r"C:\Program Files",
    r"D:\Program Files",
]
# Linux: distro package, snap, flatpak (its exported launcher), Steam, and the official .tar.xz unpacked somewhere
BLENDER_LINUX = [
    "/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
    "/var/lib/flatpak/exports/bin/org.blender.Blender", "~/.local/share/flatpak/exports/bin/org.blender.Blender",
    "~/.steam/steam/steamapps/common/Blender/blender", "~/.local/share/Steam/steamapps/common/Blender/blender",
    "/opt/blender*/blender", "~/blender*/blender", "~/Applications/blender*/blender", "~/.local/opt/blender*/blender",
    "~/Downloads/blender*/blender", "~/Applications/[Bb]lender*.AppImage",
]


def _find_blender_linux():
    for pattern in BLENDER_LINUX:
        for cand in sorted(glob.glob(os.path.expanduser(pattern)), reverse=True):   # newest version first
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


BLENDER_EXE = "blender.exe" if sys.platform == "win32" else "blender"
UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def from_setting(configured):
    """The Blender path typed in the settings: the program itself, its folder, or a folder of Blender versions
    (newest first). Quotes and spaces around it are ignored (Windows "Copy as path" adds quotes)."""
    path = os.path.expanduser((configured or "").strip().strip('"\'').strip())
    if not path:
        return None
    if os.path.isfile(path):
        return path
    if os.path.isdir(path):
        inside = [os.path.join(path, BLENDER_EXE)]
        inside += sorted(glob.glob(os.path.join(glob.escape(path), "*", BLENDER_EXE)), reverse=True)
        return next((c for c in inside if os.path.isfile(c)), None)
    return None


def _installed_programs():
    """Windows "installed programs" list: (name, version, folder) for every entry (Blender's installer, Steam…)."""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    for hive, view in ((winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY), (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
                       (winreg.HKEY_CURRENT_USER, 0)):
        try:
            root = winreg.OpenKey(hive, UNINSTALL_KEY, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                try:
                    with winreg.OpenKey(root, winreg.EnumKey(root, i), 0, winreg.KEY_READ | view) as entry:
                        values = {}
                        for name in ("DisplayName", "DisplayVersion", "InstallLocation"):
                            try:
                                values[name] = str(winreg.QueryValueEx(entry, name)[0])
                            except OSError:
                                values[name] = ""
                except OSError:
                    continue
                out.append((values["DisplayName"], values["DisplayVersion"], values["InstallLocation"]))
    return out


def pick_installed(entries):
    """Newest Blender among the installed programs whose folder really holds blender.exe."""
    from .updates import parse_version
    found = []
    for name, version, folder in entries:
        if "blender" in (name or "").lower() and folder:
            exe = os.path.join(folder.strip().strip('"'), BLENDER_EXE)
            if os.path.isfile(exe):
                found.append((parse_version(version) or (), os.path.normpath(exe)))
    return max(found)[1] if found else None


def find_blender(configured=None):
    exe = from_setting(configured) or shutil.which("blender")
    if exe:
        return exe
    if sys.platform != "win32":
        return _find_blender_linux()
    exe = pick_installed(_installed_programs())   # any drive or folder, e.g. D:\Programmi\Blender 4.4
    if exe:
        return exe
    for root in BLENDER_CANDIDATES:
        if not os.path.isdir(root):
            continue
        for d in sorted(os.listdir(root), reverse=True):
            for cand in (os.path.join(root, d, "blender.exe"), os.path.join(root, d, d, "blender.exe")):
                if "blender" in d.lower() and os.path.isfile(cand):
                    return cand
            sub = os.path.join(root, d)
            if "blender" in d.lower() and os.path.isdir(sub):
                for dd in sorted(os.listdir(sub), reverse=True):
                    cand = os.path.join(sub, dd, "blender.exe")
                    if os.path.isfile(cand):
                        return cand
    return None


def _fill_interior(shell, h, r=4.0, e=0.6):
    """Fill cavities of a closed shell (mm) while leaving its outer surface untouched."""
    from scipy import ndimage
    from skimage import measure
    import manifold3d as mf

    lo, hi = shell.bounds[0] - 2 * r, shell.bounds[1] + 2 * r
    xs, ys, zs = (np.arange(lo[i], hi[i], h) for i in range(3))
    if len(xs) * len(ys) * len(zs) > 250_000_000:
        raise MemoryError()   # no text: too many voxels at this resolution
    Y, Z = np.meshgrid(ys, zs, indexing="ij")
    origins = np.column_stack([np.full(Y.size, lo[0] - 1), Y.ravel(), Z.ravel()])
    locs, ray, _ = shell.ray.intersects_location(origins, np.tile([1.0, 0, 0], (len(origins), 1)), multiple_hits=True)
    mask = np.zeros((len(xs), len(ys), len(zs)), bool)
    order = np.lexsort((locs[:, 0], ray)); ray, hx = ray[order], locs[order, 0]
    starts = np.searchsorted(ray, np.arange(len(origins))); ends = np.searchsorted(ray, np.arange(len(origins)), "right")
    for k in np.nonzero(ends - starts)[0]:
        x = hx[starts[k]:ends[k]]
        x = x[:len(x) // 2 * 2]
        iy, iz = divmod(k, len(zs))
        for a, b in zip(x[0::2], x[1::2]):
            mask[np.searchsorted(xs, a):np.searchsorted(xs, b), iy, iz] = True
    dil = ndimage.distance_transform_edt(~mask, sampling=h) <= r
    filled = ndimage.binary_fill_holes(ndimage.distance_transform_edt(dil, sampling=h) > r)
    del dil
    ext = ndimage.binary_dilation(~filled, ndimage.generate_binary_structure(3, 1), int(np.ceil((r + 1) / h)), mask=~mask)
    # iso-surface of the distance field, not of a 0/1 mask: a mask gives a staircase that pokes through the
    # smooth outer skin on every slanted face. The inset is at least one cell so the core stays under the skin.
    e = max(e, h)
    dist = ndimage.distance_transform_edt(~ext, sampling=h).astype(np.float32)
    del ext
    if dist.max() <= e:
        return shell
    v, f, _, _ = measure.marching_cubes(np.pad(dist, 1), e, spacing=(h, h, h))
    core_mesh = trimesh.Trimesh(v - h + lo, f)
    core_mesh.merge_vertices()
    if core_mesh.volume < 0:          # marching cubes winding depends on the gradient direction
        core_mesh.invert()
    res = _drop_small(_to_manifold(shell) + _to_manifold(core_mesh))
    # the union is only worth it when it stays closed; otherwise keep the (already closed) shell
    if shell.is_watertight and not res.is_watertight:
        return shell
    return res


def _to_manifold(t):
    import manifold3d as mf
    return mf.Manifold(mf.Mesh(vert_properties=np.asarray(t.vertices, np.float32), tri_verts=np.asarray(t.faces, np.uint32)))


def _drop_small(m, min_volume=50.0):
    """Remove fragments and internal voids (manifold3d: fast even on millions of triangles)."""
    import manifold3d as mf
    keep = [c for c in m.decompose() if c.volume() > min_volume] or [m]
    m = mf.Manifold.batch_boolean(keep, mf.OpType.Add) if len(keep) > 1 else keep[0]
    g = m.to_mesh()
    return trimesh.Trimesh(g.vert_properties[:, :3], g.tri_verts, process=False)


def make_printable(stl_mm: bytes, blender, voxel_mm=None, fill=True, progress=lambda msg, frac: None):
    mesh = trimesh.load(trimesh.util.wrap_as_stream(stl_mm), file_type="stl")
    size = float(max(mesh.extents))
    voxel = voxel_mm or float(np.clip(size / 1600.0, 0.2, 2.0))
    progress(("print_solidify", {"voxel": f"{voxel:.2f}"}), 0.1)
    # Linux: not /tmp, which a flatpak Blender does not share with the rest of the system
    tmp_root = None if sys.platform == "win32" else paths.cache_dir()
    if tmp_root:
        os.makedirs(tmp_root, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="print-", dir=tmp_root) as tmp:
        src, dst, script = (os.path.join(tmp, n) for n in ("in.stl", "out.stl", "solid.py"))
        open(src, "wb").write(stl_mm)
        open(script, "w").write(BLENDER_SCRIPT)
        proc = subprocess.run([blender, "-b", "--factory-startup", "-P", script, "--", src, dst, str(voxel),
                               str(max(0.8, voxel * 3)), "2000000"], capture_output=True, text=True, timeout=3600,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), env=paths.child_env())
        if not os.path.exists(dst):
            raise i18n.LocalizedError("blender_no_output", log=proc.stdout[-800:] + proc.stderr[-800:])
        shell = trimesh.load(dst)
    if shell.is_watertight:
        shell = _drop_small(_to_manifold(shell))
    if fill:
        progress(("print_fill",), 0.6)
        try:
            shell = _fill_interior(shell, max(0.5, voxel * 2))
        except MemoryError as e:
            progress(("print_fill_skipped", {"error": str(e)}) if str(e) else ("print_fill_too_big",), 0.9)
    if shell.volume < 0:
        shell.invert()
    if not shell.is_watertight:
        shell.merge_vertices()
        trimesh.repair.fill_holes(shell)
        trimesh.repair.fix_normals(shell)
    progress(("print_write",), 0.95)
    return shell.export(file_type="stl"), {"voxel_mm": voxel, "watertight": bool(shell.is_watertight),
                                           "volume_cm3": round(float(shell.volume) / 1000, 1),
                                           "size_mm": [round(float(x), 1) for x in shell.extents]}

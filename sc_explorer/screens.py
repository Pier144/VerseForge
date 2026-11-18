"""The game's own MFD graphics for the ship screens.

The game draws its dashboard screens live (the materials only say $RenderToTexture), so no ship has a finished picture
to show. What the files do hold are the pieces the game builds the MFDs from: backgrounds, the power triangle, frames.
Aegis, Anvil, Argo and Drake have their own set, Origin has its own backdrop, every other maker uses the generic set.
The viewer draws its pages (status, power, radar, target) on these pieces: see web/screen.js."""
import re

BASE = "ui/textures/i_interactivescreens/mfd/"
GENERIC = {
    "name": "generic",
    "bg": "pu generic/pu_mfd_generic_4x3_background_1.dds",
    "tri_fill": "pu generic/pu_mfd_generic_power_dist_triangle_inner_fill_1.dds",
    "tri_frame": "pu generic/pu_mfd_generic_power_dist_triangle_outer_frame_1.dds",
    "panel": "pu generic/pu_mfd_generic_container_big_1.dds",
    "accent": None,                 # the screen's own colour (paint accent or the holo cyan)
}
KITS = {
    "aegs": {"bg": "aegs/aegs_mfd_4x3_background.dds",
             "tri_fill": "aegs/aegs_mfd_power_dist_triangle_inner_fill_1.dds",
             "tri_frame": "aegs/aegs_mfd_power_dist_triangle_outer_frame_1.dds",
             "panel": "aegs/aegs_mfd_container_big_1.dds", "accent": "#63e6e2"},
    "anvl": {"bg": "anvl/anvl_mfd_4x3_background.dds", "accent": "#3fe8c5"},
    "argo": {"bg": "argo/mfd_argo_4x3_panel_background.dds",
             "tri_fill": "argo/argo_mfd_power_dist_triangle_inner_fill_1.dds",
             "tri_frame": "argo/argo_mfd_power_dist_triangle_outer_frame_1.dds",
             "panel": "argo/argo_mfd_container_big_1.dds", "accent": "#f08a3c"},
    "drak": {"bg": "drak/drake_mfd_4x3_background_1.dds",
             "tri_fill": "drak/drak_mfd_power_dist_triangle_inner_fill_1.dds",
             "tri_frame": "drak/drak_mfd_power_dist_triangle_outer_frame_1.dds",
             "panel": "drak/drak_mfd_container_big_1.dds", "accent": "#f2a23c"},
    "orig": {"bg": "pu generic/origin_mfd_4x3_backdrop_1.dds", "accent": "#e8eef2"},
}
OWN_SET = ("aegs", "anvl", "argo", "drak")      # makers with a full set of their own


def maker_code(path):
    """Manufacturer folder of a ship or vehicle path (objects/spaceships/ships/aegs/...), or ""."""
    m = re.search(r"/(?:ships|ground|vehicles)/([a-z0-9]+)/", path.lower().replace("\\", "/"))
    return m.group(1) if m else ""


def kit_for(archive, path):
    """Which pieces the viewer draws the screens of this model with: {name, own, accent, bg, tri_fill, tri_frame,
    panel} (texture paths, missing pieces filled from the generic set, None when the game files lack them)."""
    code = maker_code(path)
    own = KITS.get(code, {})
    kit = {"name": code if own else "generic", "own": code in OWN_SET, "accent": own.get("accent")}
    for k in ("bg", "tri_fill", "tri_frame", "panel"):
        for src in (own.get(k), GENERIC[k]):
            p = BASE + src if src else None
            if p and (archive is None or archive.exists(p)):
                kit[k] = p
                break
        else:
            kit[k] = None
    return kit

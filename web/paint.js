// Instant paint switching (docs/superpowers/specs/2026-11-18-vernici-istantanee-design.md).
// The server gives every paint of a model the same geometry, its parts grouped by paint group: the "g<n>" field of
// the GLB material names (sc_explorer/paints.py). A paint is then a table of one material per group.
import * as THREE from "three";

// the paint group written in a GLB material name ("solid|hull|1a2b3c4d|g12", "screen|mfd|g3|rtt"), or null
export function groupOf(material) {
  const f = (material?.name || "").split("|").find((x) => /^g\d+$/.test(x));
  return f ? Number(f.slice(1)) : null;
}

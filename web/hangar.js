// "Hangar" image-based lighting: a dark, slightly blue-grey hall lit by long ceiling strips and a few wall panels,
// like the game's hangars. Glossy paints show crisp strip highlights over dark reflections instead of the washed-out
// look of a white photo studio. Rendered once into a PMREM environment map.
import * as THREE from "three";

function emissive(rgb, power) {
  const m = new THREE.MeshBasicMaterial({ side: THREE.DoubleSide });
  m.color.setRGB(rgb[0] * power, rgb[1] * power, rgb[2] * power);
  return m;
}

export class HangarEnvironment extends THREE.Scene {
  constructor() {
    super();
    const box = new THREE.BoxGeometry();
    box.deleteAttribute("uv");
    const plane = new THREE.PlaneGeometry();

    // hall: walls dark blue-grey, floor a little lighter (bounce light from below, as on a hangar deck)
    const walls = new THREE.Mesh(box, emissive([0.055, 0.062, 0.075], 1));
    walls.material.side = THREE.BackSide;
    walls.scale.set(60, 26, 60);
    walls.position.y = 9;
    this.add(walls);
    const floor = new THREE.Mesh(plane, emissive([0.10, 0.10, 0.105], 1));
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -3.9;
    floor.scale.set(58, 58, 1);
    this.add(floor);

    // ceiling: parallel strip lights (cool white)
    const strip = emissive([0.92, 0.96, 1.0], 9);
    for (let i = -2; i <= 2; i++) {
      const s = new THREE.Mesh(plane, strip);
      s.rotation.x = Math.PI / 2;
      s.position.set(i * 7, 21.5, 0);
      s.scale.set(0.9, 40, 1);
      this.add(s);
    }
    // a big soft key panel high on one side (warm) and a cooler fill on the other
    const key = new THREE.Mesh(plane, emissive([1.0, 0.95, 0.88], 4.5));
    key.position.set(-29.5, 12, -6);
    key.rotation.y = Math.PI / 2;
    key.scale.set(22, 8, 1);
    this.add(key);
    const fill = new THREE.Mesh(plane, emissive([0.75, 0.85, 1.0], 1.6));
    fill.position.set(29.5, 8, 8);
    fill.rotation.y = -Math.PI / 2;
    fill.scale.set(18, 6, 1);
    this.add(fill);
    // thin horizontal light bands along the far walls (the bright lines that run across glossy hulls in game)
    const band = emissive([0.85, 0.92, 1.0], 6);
    for (const z of [-29.5, 29.5]) {
      const b = new THREE.Mesh(plane, band);
      b.position.set(0, 4.5, z);
      b.rotation.y = z > 0 ? Math.PI : 0;
      b.scale.set(48, 0.35, 1);
      this.add(b);
    }
    // a few dark structures (gantries) break the reflections up
    const dark = emissive([0.02, 0.022, 0.026], 1);
    for (const [x, z, sx, sz] of [[-12, -14, 3, 10], [14, 12, 4, 6], [6, -20, 10, 2]]) {
      const g = new THREE.Mesh(box, dark);
      g.position.set(x, 3, z);
      g.scale.set(sx, 14, sz);
      this.add(g);
    }
  }
}

export function hangarTexture(renderer) {
  const pmrem = new THREE.PMREMGenerator(renderer);
  const tex = pmrem.fromScene(new HangarEnvironment(), 0.02).texture;
  pmrem.dispose();
  return tex;
}

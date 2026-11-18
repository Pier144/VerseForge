// Fewer draw calls for big models: pieces that share a material are drawn together (THREE.BatchedMesh).
//
// The server already merges the pieces that never move. What is left on a big ship is ~2000 small meshes hanging
// under animated nodes (doors, gear, turrets...), each one a draw call: on the Perseus with everything on, 7 of the
// 9 ms of a frame were three.js walking through 2400 calls on the CPU while the GPU was nearly idle. A batch keeps
// every piece's own transform in a small texture, so the pieces still move with the animations, but one material is
// one call. Each piece's place in the scene tree is taken by an empty node with the same name and transform (the
// animations move that), and `sync()` copies the nodes' transforms to the batches after the pose changed.
import * as THREE from "three";

const MIN_PIECES = 2;            // a batch of one piece gains nothing
const SKIP_KINDS = new Set(["glass", "screen", "hidden"]);   // glass has its tint layer, screens are drawn on, proxies are never shown

const kindOf = (o) => ((o.name || o.parent?.name || "").split("|")[0] || "solid");
// mesh names are "kind|material|number": the first two parts are what the layer and material switches look at
const labelOf = (o) => (o.name || o.parent?.name || "").split("|").slice(0, 2).join("|");
const _m = new THREE.Matrix4(), _inv = new THREE.Matrix4(), _box = new THREE.Box3();

function layout(g) {
  const names = Object.keys(g.attributes).sort();
  return names.map((n) => { const a = g.attributes[n]; return `${n}:${a.itemSize}:${a.array.constructor.name}:${a.normalized ? 1 : 0}`; }).join(",")
    + (g.index ? "+i" : "");
}

function batchable(o) {
  if (!o.isMesh || o.isSkinnedMesh || o.isBatchedMesh || o.isInstancedMesh || o.userData.glass) return false;
  if (SKIP_KINDS.has(kindOf(o)) || Array.isArray(o.material)) return false;
  const g = o.geometry, m = o.material;
  if (!g.attributes.position || g.groups.length > 1 || Object.keys(g.morphAttributes || {}).length) return false;
  if (Object.values(g.attributes).some((a) => a.isInterleavedBufferAttribute || a.isInstancedBufferAttribute)) return false;
  // See-through pieces (decals, overlays) are drawn far-to-near, one by one, mixed with each other whatever their
  // material: in a batch that order would change and overlapping decals would come out differently (Reclaimer).
  if (m.transparent) return false;
  return true;
}

// BatchedMesh draws a list of index ranges, one per piece. With `wireframe` three.js swaps in an index of lines
// (a-b, b-c, c-a for every triangle: twice as long, in the same order), so the ranges must be converted, or the
// wireframe comes out as scrambled lines. `hook` is the material's per-frame hook (POM decals: light direction).
class Batch extends THREE.BatchedMesh {
  onBeforeRender(renderer, scene, camera, geometry, material, group) {
    if (this.hook && scene) this.hook(camera);
    super.onBeforeRender(renderer, scene, camera, geometry, material, group);
    if (material.wireframe) this.toWireRanges(geometry);
  }

  onBeforeShadow(renderer, object, camera, shadowCamera, geometry, depthMaterial) {
    super.onBeforeRender(renderer, null, shadowCamera, geometry, depthMaterial);
    if (depthMaterial.wireframe) this.toWireRanges(geometry);
  }

  toWireRanges(geometry) {
    const index = geometry.index;
    if (!index) return;                       // not indexed: three.js has no line index for it either
    if (this.wireBytes === undefined) {       // three.js picks 32-bit line indices when any index is >= 65535
      let max = 0;
      for (let i = 0, a = index.array, l = a.length; i < l; i++) if (a[i] > max) max = a[i];
      this.wireBytes = max >= 65535 ? 4 : 2;
    }
    const k = 2 * this.wireBytes / index.array.BYTES_PER_ELEMENT;
    const starts = this._multiDrawStarts, counts = this._multiDrawCounts;
    for (let i = 0, l = this._multiDrawCount; i < l; i++) { starts[i] *= k; counts[i] *= 2; }
  }
}

export class Batches {
  constructor() {
    this.list = [];              // the BatchedMesh objects
    this.nodes = [];             // [node, batch, id] for every piece
    this.root = null;
  }

  get active() { return this.list.length > 0; }

  // Replace the batchable meshes under `root` by batches (children of `root`). `pause` is awaited now and then so
  // the page keeps breathing. Returns { pieces, batches }.
  async build(root, pause) {
    this.root = root;
    root.updateMatrixWorld(true);
    _inv.copy(root.matrixWorld).invert();
    const groups = new Map();
    root.traverse((o) => {
      if (!batchable(o)) return;
      if (_m.multiplyMatrices(_inv, o.matrixWorld).determinant() < 0) return;   // mirrored: needs its own winding
      const key = [labelOf(o), o.material.uuid, layout(o.geometry), o.renderOrder, o.castShadow, o.receiveShadow].join("#");
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(o);
    });
    let pieces = 0, slice = performance.now();
    for (const meshes of groups.values()) {
      if (meshes.length < MIN_PIECES) continue;
      let verts = 0, idx = 0;
      for (const o of meshes) { verts += o.geometry.attributes.position.count; idx += o.geometry.index ? o.geometry.index.count : 0; }
      const first = meshes[0];
      const batch = new Batch(meshes.length, verts, Math.max(idx, 1), first.material);
      batch.name = labelOf(first);
      batch.renderOrder = first.renderOrder;
      batch.castShadow = first.castShadow;
      batch.receiveShadow = first.receiveShadow;
      batch.sortObjects = false;                                // opaque only: the depth buffer sorts, no CPU sort needed
      batch.hook = first.material.userData?.beforeRender || null;
      const disposable = new Set();
      for (const o of meshes) {
        const id = batch.addGeometry(o.geometry);
        batch.setMatrixAt(id, _m.multiplyMatrices(_inv, o.matrixWorld));
        // an empty node takes the mesh's place: same name and transform (animations may target it), same children
        const node = new THREE.Object3D();
        node.name = o.name;
        node.position.copy(o.position); node.quaternion.copy(o.quaternion); node.scale.copy(o.scale);
        node.matrix.copy(o.matrix); node.matrixWorld.copy(o.matrixWorld);
        node.matrixAutoUpdate = o.matrixAutoUpdate;
        node.userData = o.userData;
        while (o.children.length) node.add(o.children[0]);
        const parent = o.parent;
        parent.add(node);
        parent.remove(o);
        this.nodes.push([node, batch, id]);
        disposable.add(o.geometry);
        pieces++;
        if (performance.now() - slice > 12) { await pause(); slice = performance.now(); }
      }
      for (const g of disposable) g.dispose();                  // never sent to the GPU: only the batch's copy is
      root.add(batch);
      this.list.push(batch);
    }
    return { pieces, batches: this.list.length };
  }

  // the pose changed (an animation moved): copy every node's transform to its batch
  sync() {
    if (!this.active) return;
    this.root.updateMatrixWorld(true);
    _inv.copy(this.root.matrixWorld).invert();
    for (const [node, batch, id] of this.nodes) batch.setMatrixAt(id, _m.multiplyMatrices(_inv, node.matrixWorld));
    for (const b of this.list) { b.boundingBox = null; b.boundingSphere = null; }
  }

  // pieces lying wholly above the section plane (world height y) are not drawn; y = Infinity shows them all.
  // hidden(node): pieces to leave out whatever their height (the rooms that are not being shown)
  cullAbove(y, hidden = null) {
    for (const [node, batch, id] of this.nodes) {
      let off = hidden ? hidden(node) : false;
      if (!off && y !== Infinity) {
        batch.getMatrixAt(id, _m);
        off = batch.getBoundingBoxAt(id, _box).applyMatrix4(_m).applyMatrix4(batch.matrixWorld).min.y > y;
      }
      if (batch.getVisibleAt(id) === off) batch.setVisibleAt(id, !off);
    }
  }

  // world box around the pieces `pick(node)` chooses, added to `target`
  boxOf(pick, target) {
    for (const [node, batch, id] of this.nodes) {
      if (!pick(node)) continue;
      batch.getMatrixAt(id, _m);
      target.union(batch.getBoundingBoxAt(id, _box).applyMatrix4(_m).applyMatrix4(batch.matrixWorld));
    }
    return target;
  }

  dispose() {
    for (const b of this.list) b.dispose();
    this.list.length = this.nodes.length = 0;
    this.root = null;
  }
}

// Smooth vertex normals straight from the typed arrays: the same result as BufferGeometry.computeVertexNormals()
// (area-weighted face normals summed per vertex, then normalized), without its per-vertex Vector3 calls.
// The viewer GLB comes without normals (a third of the file): they are computed on every load, about 3x faster here
// with the identical result. Also reads interleaved or quantized positions (a uniform scale keeps the directions).
import * as THREE from "three";

export function vertexNormals(geometry) {
  const pos = geometry.attributes.position, index = geometry.index;
  if (!pos || !index || pos.itemSize !== 3) { geometry.computeVertexNormals(); return; }
  const src = pos.isInterleavedBufferAttribute ? pos.data.array : pos.array;
  const stride = pos.isInterleavedBufferAttribute ? pos.data.stride : 3;
  const off = pos.isInterleavedBufferAttribute ? pos.offset : 0;
  const idx = index.array, n = new Float32Array(pos.count * 3);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t], b = idx[t + 1], c = idx[t + 2];
    const ia = a * stride + off, ib = b * stride + off, ic = c * stride + off;
    const bx = src[ib], by = src[ib + 1], bz = src[ib + 2];
    const ux = src[ic] - bx, uy = src[ic + 1] - by, uz = src[ic + 2] - bz;     // C - B
    const vx = src[ia] - bx, vy = src[ia + 1] - by, vz = src[ia + 2] - bz;     // A - B
    const x = uy * vz - uz * vy, y = uz * vx - ux * vz, z = ux * vy - uy * vx;
    n[a * 3] += x; n[a * 3 + 1] += y; n[a * 3 + 2] += z;
    n[b * 3] += x; n[b * 3 + 1] += y; n[b * 3 + 2] += z;
    n[c * 3] += x; n[c * 3 + 1] += y; n[c * 3 + 2] += z;
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]);
    if (l > 0) { n[i] /= l; n[i + 1] /= l; n[i + 2] /= l; }
  }
  geometry.setAttribute("normal", new THREE.BufferAttribute(n, 3));
}

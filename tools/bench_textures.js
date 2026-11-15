// Browser benchmark of the game-look textures (progressive vs full size straight away). Paste into the viewer's
// console (or run it through an automation tool), then e.g.
//
//   await __bench("Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga", true)    // progressive
//   await __bench("Objects/Spaceships/Ships/RSI/perseus/exterior/rsi_perseus.cga", false)   // old behaviour
//
// Fair cold runs: start the server with --no-disk-cache and restart it before every run. Every run adds a fresh
// cache-busting value to the texture URLs (GameLook.bust), so the browser's HTTP cache is never used. Frames are
// driven with __verseforge.tick() (requestAnimationFrame stops while the page is hidden). Interior is switched on.
//
// tLowDrawn / tFullDrawn: ms from load start until the model is drawn with every texture small / at full size
// texStart: ms until the first texture request (before it: model build + GLB download, the same in both modes)
// firstFrame: the first frame with the textures (GPU upload); maxFrame: longest frame after it
// peakGpuMB: image memory of the textures in use (width x height x 4 bytes x 4/3 for mipmaps), sampled every 250 ms
window.__bench = async function (path, progressive) {
  const vf = __verseforge;
  window.dispatchEvent(new Event("resize"));
  vf.state().interior = true;
  const GL = vf.look.constructor;
  GL.progressive = progressive;
  GL.bust = String(Date.now());
  performance.setResourceTimingBufferSize(20000);
  performance.clearResourceTimings();
  const texSet = () => {
    const out = new Set();
    vf.scene.traverse((o) => {
      if (!o.isMesh) return;
      for (const m of [].concat(o.material)) {
        const refs = [m.map, m.normalMap, m.roughnessMap, m.specularColorMap, m.emissiveMap, m.userData?.detailNormal,
          ...[m.uniforms, m.userData?.gameUniforms].flatMap((u) => (u ? Object.values(u).map((v) => v?.value) : []))];
        for (const r of refs) if (r && r.isTexture && r.image) out.add(r.source);
      }
    });
    return out;
  };
  const imageMB = () => { let b = 0; for (const s of texSet()) b += s.data.width * s.data.height * 4 * 4 / 3; return b / 1048576; };
  let peakN = 0, peakMB = 0, maxFrame = 0, frames = 0;
  const pump = setInterval(() => {
    const a = performance.now(); vf.tick(); const d = performance.now() - a;
    if (vf.stats.frames !== frames) { frames = vf.stats.frames; maxFrame = Math.max(maxFrame, d); }
    peakN = Math.max(peakN, vf.renderer.info.memory.textures);
  }, 16);
  const memSample = setInterval(() => { peakMB = Math.max(peakMB, imageMB()); }, 250);
  const t0 = performance.now();
  await vf.load({ path, name: path.split("/").pop() });
  const tLow = performance.now() - t0;
  vf.invalidate(50);
  const a = performance.now(); vf.tick(); const firstFrame = performance.now() - a;
  maxFrame = 0;
  const tLowDrawn = performance.now() - t0;
  await vf.look.full;
  const tFull = performance.now() - t0;
  vf.invalidate(50); vf.tick();
  const tFullDrawn = performance.now() - t0;
  await new Promise((r) => setTimeout(r, 300));
  clearInterval(pump); clearInterval(memSample);
  const res = performance.getEntriesByType("resource").filter((e) => e.name.includes("/api/texture"));
  const small = res.filter((e) => e.name.includes("size=256"));
  const big = res.filter((e) => !e.name.includes("size=256"));
  const sum = (l) => +(l.reduce((s, e) => s + (e.encodedBodySize || e.transferSize || 0), 0) / 1048576).toFixed(1);
  const span = (l) => (l.length ? Math.round(Math.max(...l.map((e) => e.responseEnd)) - Math.min(...l.map((e) => e.startTime))) : 0);
  return {
    progressive, tLow: Math.round(tLow), tLowDrawn: Math.round(tLowDrawn), tFull: Math.round(tFull), tFullDrawn: Math.round(tFullDrawn),
    texStart: Math.round(Math.min(...res.map((e) => e.startTime)) - t0),
    firstFrame: Math.round(firstFrame), maxFrame: Math.round(maxFrame),
    requests: res.length, MB: sum(res), smallMB: sum(small), smallSpan: span(small), bigSpan: span(big),
    peakTexCount: peakN, peakGpuMB: Math.round(peakMB), endGpuMB: Math.round(imageMB()),
  };
};

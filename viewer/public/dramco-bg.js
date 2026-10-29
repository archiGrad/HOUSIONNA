/* DRAMCO background: a monochrome ASCII field behind the page.
   One website = one look: the variation (pattern, character set, cell size, speed, density) comes from a seed.
   Use the SAME seed on every page of a website, and a different one for every new website:
   <canvas id="dramco-bg" data-seed="sensor-lab"></canvas>  -> always the same look for that website
   <canvas id="dramco-bg"></canvas>                         -> no seed: the domain name is the seed
   <canvas id="dramco-bg" data-seed="random"></canvas>      -> a new look on every load (demos only)
   Cheap by design: window-sized canvas, pre-drawn glyph tiles, empty cells skipped, ~25 fps,
   paused in background tabs, a still frame with prefers-reduced-motion. No dependencies. */
(function () {
  const canvas = document.getElementById('dramco-bg');
  if (!canvas || !canvas.getContext) return;
  const ctx = canvas.getContext('2d');

  // --- seeded randomness: the same seed gives the same variation
  const seedText = canvas.dataset.seed === 'random' ? String(Math.random()) : (canvas.dataset.seed || location.hostname || 'dramco');
  let h = 2166136261;
  for (let i = 0; i < seedText.length; i++) h = Math.imul(h ^ seedText.charCodeAt(i), 16777619);
  const rand = () => { h = (h + 0x6d2b79f5) | 0; let t = Math.imul(h ^ (h >>> 15), 1 | h); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  const pick = (a) => a[Math.floor(rand() * a.length)];
  const between = (a, b) => a + rand() * (b - a);

  // --- the variation for this website
  const CHARSETS = [' .:-=+*#', ' .:;+=xX#', ' .-~=+*', ' .oO0@', ' ._-=#', ' .,:;|/'];
  const v = {
    chars: pick(CHARSETS),
    cell: Math.round(between(14, 22)),           // px per character
    mode: pick(['waves', 'rings', 'bands', 'blobs']),
    speed: between(0.5, 1.3),
    scale: between(380, 720),                    // size of the shapes, in px
    angle: between(0, Math.PI),                  // direction of bands / waves
    gap: between(0.0, 0.22),                     // how much stays black between the shapes
    light: between(0.16, 0.26),                  // brightest character opacity (white on black)
    centers: Array.from({ length: 6 }, () => [rand(), rand(), between(0.6, 1.4)]),
  };
  const levels = 10;
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  let W = 0, H = 0, dpr = 1, cols = 0, rows = 0, atlas = null, tile = 0;
  const build = () => {
    W = innerWidth; H = innerHeight; dpr = Math.min(devicePixelRatio || 1, 1.5);
    const cell = W < 600 ? Math.max(13, v.cell - 3) : v.cell;
    cols = Math.ceil(W / cell) + 1; rows = Math.ceil(H / cell) + 2;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    tile = Math.round(cell * dpr);
    atlas = document.createElement('canvas');
    atlas.width = tile * levels; atlas.height = tile;
    const a = atlas.getContext('2d');
    a.textAlign = 'center'; a.textBaseline = 'middle';
    a.font = `600 ${Math.round(tile * 0.8)}px ui-monospace, SFMono-Regular, Consolas, monospace`;
    for (let k = 1; k <= levels; k++) {
      const f = k / levels;
      a.fillStyle = `rgba(255, 255, 255, ${(0.06 + v.light * f).toFixed(3)})`;
      a.fillText(v.chars[Math.min(v.chars.length - 1, 1 + Math.floor(f * (v.chars.length - 1.01)))], (k - 0.5) * tile, tile / 2);
    }
    canvas._cell = cell;
  };

  // --- the four kinds of shapes; each returns roughly -1..1 for a page position (x, y) at time t
  const ca = Math.cos(v.angle), sa = Math.sin(v.angle);
  const field = (x, y, t) => {
    const u = x / v.scale, w = y / v.scale, ts = t * v.speed;
    if (v.mode === 'waves') {
      const p = u * ca + w * sa, q = -u * sa + w * ca;
      return (Math.sin(p * 5 + ts * 0.6 + Math.sin(q * 2 + ts * 0.3) * 1.5) + 0.7 * Math.sin(q * 4 - ts * 0.4 + p * 2)) / 1.7;
    }
    if (v.mode === 'bands') {
      const p = u * ca + w * sa;
      return Math.sin(p * 7 + ts * 0.5) * 0.7 + Math.sin(p * 2.3 - ts * 0.2 + w) * 0.3;
    }
    if (v.mode === 'rings') {
      // ripples spreading from three points
      let s = 0;
      for (const [cx, cy, k] of v.centers.slice(0, 3)) s += Math.sin((Math.hypot(x - cx * W, y - cy * H * 1.6) / v.scale) * 9 * k - ts * 1.2);
      return s / 3;
    }
    // blobs: six soft islands drifting around a little, repeated down the page every screen
    const span = H, yy = ((y % span) + span) % span;
    let s = -0.55;
    v.centers.forEach(([cx, cy, k], i) => {
      const bx = cx * W + Math.sin(ts * 0.21 * k + i) * 0.3 * v.scale, by = cy * span + Math.cos(ts * 0.17 * k + i * 2) * 0.3 * v.scale;
      s += 0.75 / (1 + (((x - bx) ** 2 + (yy - by) ** 2) / (v.scale * v.scale)) * 5);
    });
    return Math.tanh(s * 1.5);   // keeps overlapping blobs within -1..1 like the other shapes
  };

  // --- make sure every variation is clearly visible, at every moment: measure how much of the screen is lit at
  // several points in time and, if the emptiest moment shows too little (some seeds park the shapes mostly off
  // screen), open up the black gap just enough.
  const lit = (t) => {
    let n = 0;
    for (let gy = 0; gy < 24; gy++) for (let gx = 0; gx < 40; gx++) {
      if ((field((gx + 0.5) / 40 * W, (gy + 0.5) / 24 * H, t) - v.gap) / (1 - v.gap) > 0) n++;
    }
    return n / 960;
  };
  const range = () => { const a = [0, 3, 6, 10, 15, 21, 28, 36].map(lit); return [Math.min(...a), Math.max(...a)]; };
  const tune = () => {
    // find the largest black gap for which even the emptiest moment still lights ~24% of the screen
    let lo = -1.6, hi = 0.85;
    for (let i = 0; i < 14; i++) {
      const mid = (lo + hi) / 2;
      v.gap = mid;
      if (range()[0] >= 0.24) lo = mid; else hi = mid;
    }
    v.gap = lo;
  };

  const draw = (now) => {
    const t = reduced ? 20 : now / 1000, sy = scrollY, cell = canvas._cell, step = cell * dpr;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const offY = -(sy % cell) * dpr, firstRow = Math.floor(sy / cell);
    for (let j = 0; j < rows; j++) {
      const pageY = (firstRow + j) * cell;
      for (let i = 0; i < cols; i++) {
        const s = (field(i * cell, pageY, t) - v.gap) / (1 - v.gap);
        if (s <= 0) continue;                                    // empty: the black between the shapes
        const k = Math.min(levels, Math.max(1, Math.ceil(s * levels)));
        ctx.drawImage(atlas, (k - 1) * tile, 0, tile, tile, i * step, offY + j * step, tile, tile);
      }
    }
  };

  build();
  tune();
  let last = 0, lastScroll = -1, raf = 0;
  const loop = (now) => {
    raf = requestAnimationFrame(loop);
    if (scrollY === lastScroll && (reduced || now - last < 40)) return;   // ~25 fps, every frame while scrolling
    last = now; lastScroll = scrollY; draw(now);
  };
  const run = () => { cancelAnimationFrame(raf); if (!document.hidden) raf = requestAnimationFrame(loop); };
  let rt = 0;
  addEventListener('resize', () => { clearTimeout(rt); rt = setTimeout(() => { build(); tune(); lastScroll = -1; }, 150); });
  document.addEventListener('visibilitychange', run);
  run();
})();

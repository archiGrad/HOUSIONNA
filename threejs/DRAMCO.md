# DRAMCO web style

How every DRAMCO web page looks: dark, calm, a white DRAMCO logo, bold wide headlines, and a quiet animated ASCII background that is a little different on every website. Follow this file and pages built by different people (or by an AI assistant) will look like they belong together.

**In one line:** near-black background, white and grey interface, colour only where it carries information (charts, data, partner logos), the white DRAMCO logo, Archivo for type, and the ASCII background below.

---

## 1. Rules at a glance

| Do | Don't |
|---|---|
| Near-black backgrounds (`#0a0a0b`), dark grey surfaces | White or light page backgrounds |
| A monochrome interface: white headlines and logo, warm grey body text, white as the only button colour | Colour on interface chrome: buttons, links, headings, nav, borders |
| Colour in charts and data, from the data palette (section 2), with one fixed colour per thing across the whole site | Grey-only charts that are hard to read, or the same series changing colour between charts |
| Partner and funder logos in their own colours (section 3) | Recolouring, outlining, stretching or shadowing any logo |
| The white DRAMCO logo on dark | The DRAMCO logo in colour or on a light background |
| Big, wide, uppercase headlines (Archivo 900, 125% width) | Many font families or decorative fonts |
| Thin 1 px grey lines to separate things | Heavy borders, drop shadows, decorative gradients |
| The ASCII background, with **one seed per website** (every page of a site shares it) | Using the same seed for two different websites, or a different seed per page |
| Respect `prefers-reduced-motion` | Motion that cannot be turned off |

The idea: the interface stays black, white and grey so the page feels like DRAMCO; colour appears only where it means something, so the eye goes straight to it.

---

## 2. Colours

Paste this at the top of your stylesheet and only use these tokens.

```css
:root {
  /* interface: monochrome */
  --bg:        #0a0a0b;   /* page background: on <html>, see section 5 */
  --surface:   #111113;   /* bands: header, hero, footer */
  --card:      #18181b;   /* cards and panels */
  --card-glass: rgba(24, 24, 27, 0.78); /* cards that let the background show through a little */
  --line:      #2a2a2e;   /* 1 px separators, chart gridlines */
  --line-strong: #3a3a40;
  --text:      #f2f1ec;   /* headlines, important text (warm white) */
  --muted:     #a3a29c;   /* body copy, labels, axis text (7:1 on --bg) */
  --faint:     #6e6d68;   /* captions, disabled */
  --ink:       #0b0b0c;   /* text on a white button */
  --plate:     #f2f1ec;   /* light plate behind partner logos made for white backgrounds */

  /* data: for charts, legends, keys and data tables only */
  --data-1:    #56b4e9;   /* sky blue */
  --data-2:    #e69f00;   /* orange */
  --data-3:    #2fbf9a;   /* bluish green */
  --data-4:    #cc79a7;   /* reddish purple */
  --data-5:    #f0e442;   /* yellow */
  --data-6:    #e3693b;   /* vermillion */

  /* status: only when meaning requires it, always next to text */
  --ok:        #5fbf8a;
  --warn:      #e6b450;
  --error:     #f07167;
}
```

- **Interface tokens** (`--bg` to `--plate`) are for everything that is not data. `--text` and `--muted` pass WCAG AA on every background above. Never put `--faint` on anything important.
- **Data tokens** are a colour-blind-safe set (based on Okabe–Ito, brightened for a dark background). Each one reaches at least 5:1 against `--card`. Use them in this order, and keep the mapping fixed across the whole website: if *amplifiers* are `--data-3` in one chart, they are `--data-3` in every chart, legend, table key and summary bar.
- **Status tokens** are for form errors, success and warning messages. Keep them small (an icon, a left border, a word) and always pair them with text.

---

## 3. Logos

### DRAMCO

Two versions, both **white on transparent**, embedded at the end of this file (Appendix) so this document is self-contained. Save them as files in your project:

| File | What | Use |
|---|---|---|
| `dramco-mark-white.png` (160 × 160) | the round wave mark | header, favicon-size spots, next to a page title |
| `dramco-logo-white.png` (320 × 430) | mark + "DRAMCO" word mark, stacked | footer, title slides, splash screens |

- Only on dark backgrounds (`--bg`, `--surface`, `--card`).
- Header: the mark at 32–40 px high, next to the site name in white.
- Footer: the stacked logo, 90–120 px high, on the left of the footer content.
- Clear space around the logo: at least a quarter of its height on every side.
- Always with `alt="DRAMCO"`.

```html
<a class="brand" href="/">
  <img src="dramco-mark-white.png" alt="DRAMCO" width="36" height="36">
  <span class="brand__name">Page name</span>
</a>
```

### Partners, funders and institutions

Logos of KU Leuven, project partners, funders and so on are shown **in their own colours**, exactly as their owners supply them.

- Put them together in one row (usually in the footer, next to or below the DRAMCO block), all at the **same height** (36–44 px) with the same gap between them.
- Check the file first. Most partner logos are transparent PNGs: they go straight onto the dark background, with no plate, even when their text is dark. Only a logo whose white background is part of the image itself (no transparency) goes on a light plate: `background: var(--plate)`, padding of a quarter of the logo height, no border, no rounded corners beyond 2 px.
- A solid coloured tile (for example a square with its own background) is used as is, without a plate.
- Use the organisation's name as `alt` text, and link to its website.
- Never recolour a partner logo to white or grey to "fit in"; never put it on a busy part of the ASCII background without a band or card behind it.

```html
<div class="partners">
  <a href="https://www.kuleuven.be/"><img src="kuleuven.png" alt="KU Leuven" height="40"></a>
  <a href="https://example.org/"><img src="partner.png" alt="Partner name" height="40"></a>
  <a class="plate" href="https://example.org/"><img src="white-background-partner.jpg" alt="Partner name" height="40"></a>
</div>
```

```css
.partners { display: flex; flex-wrap: wrap; align-items: center; gap: 1rem 1.5rem; }
.partners img { display: block; height: 40px; width: auto; }
.partners .plate { background: var(--plate); padding: 10px 12px; border-radius: 2px; }
.partners .plate img { height: 30px; }   /* plate + logo together are as high as the other logos */
```

---

## 4. Typography

One family: **Archivo** (variable, with a width axis). Load it from Google Fonts or self-host it.

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@100..125,400..900&display=swap" rel="stylesheet">
```

```css
body { font-family: "Archivo", ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; font-size: 1rem; line-height: 1.55; color: var(--muted); }
h1, .display { color: var(--text); font-weight: 900; font-stretch: 125%; text-transform: uppercase; letter-spacing: -0.035em; line-height: 0.9;
               font-size: clamp(2.6rem, 1.6rem + 4vw, 5.2rem); margin: 0; }
h2 { color: var(--text); font-weight: 800; font-stretch: 112%; letter-spacing: -0.02em; line-height: 1.05; font-size: clamp(1.5rem, 1.2rem + 1vw, 2.1rem); }
h3 { color: var(--text); font-weight: 750; font-size: 1.15rem; }
.eyebrow { color: var(--text); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.16em; text-transform: uppercase;
           display: inline-flex; align-items: center; gap: 0.6rem; }
.eyebrow::before { content: ""; width: 1.4rem; height: 2px; background: currentColor; }   /* a short dash, never a dot */
.num { font-variant-numeric: tabular-nums; }
```

Pattern for a page head: eyebrow (small caps with a dash) → big uppercase headline → one or two lines of muted text.

---

## 5. Page skeleton

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0a0a0b">
  <title>Page title · DRAMCO</title>
  <!-- Archivo (section 4) + your stylesheet -->
</head>
<body>
  <canvas id="dramco-bg" data-seed="my-site-name" aria-hidden="true"></canvas>   <!-- the SAME seed on every page of this website -->

  <header class="site-header"> <!-- logo mark + nav --> </header>
  <main>
    <section class="page-head">
      <p class="eyebrow">Section label</p>
      <h1>Big headline</h1>
      <p>One or two lines that say what this page is.</p>
    </section>
    <!-- content -->
  </main>
  <footer class="site-footer"> <!-- stacked logo left, links right, partner logos (section 3) --> </footer>

  <script src="dramco-bg.js" defer></script>
</body>
</html>
```

```css
html { background: var(--bg); }            /* the page colour lives on <html> ...                       */
body { margin: 0; background: transparent; } /* ... and <body> stays transparent, or it hides the background */
#dramco-bg { position: fixed; inset: 0; width: 100%; height: 100%; z-index: -1; pointer-events: none; display: block; }

.site-header { position: sticky; top: 0; z-index: 10; background: rgba(10, 10, 11, 0.88); border-bottom: 1px solid var(--line); }
/* header: logo left, nav right; the nav wraps onto a second line on narrow screens instead of overflowing */
.site-header .wrap { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 0.4rem 1.5rem; min-height: 4rem; padding-block: 0.4rem; }
.brand { display: flex; align-items: center; gap: 0.7rem; color: var(--text); text-decoration: none; font-weight: 800; }
.nav { display: flex; flex-wrap: wrap; gap: 0.3rem 1.5rem; }
.nav a { color: var(--muted); text-decoration: none; font-size: 0.9rem; }
.nav a:hover, .nav a[aria-current="page"] { color: var(--text); }
.page-head, .site-footer { background: rgba(10, 10, 11, 0.45); }  /* let the background show faintly through bands */
.card { background: var(--card-glass); border: 1px solid var(--line); padding: 1.5rem; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 0 clamp(1rem, 4vw, 2.5rem); }
hr, .divider { border: 0; border-top: 1px solid var(--line); }
```

**Buttons** (white is the interface's only "accent"):

```css
.btn { display: inline-flex; align-items: center; gap: 0.5rem; min-height: 2.9rem; padding: 0 1.4rem; border: 1px solid var(--text);
       font: 800 0.8rem/1 "Archivo", sans-serif; letter-spacing: 0.14em; text-transform: uppercase; text-decoration: none; cursor: pointer; }
.btn--primary { background: var(--text); color: var(--ink); }
.btn--primary:hover { background: #ffffff; }
.btn--ghost { background: transparent; color: var(--text); border-color: var(--line-strong); }
.btn--ghost:hover { border-color: var(--text); }
:focus-visible { outline: 2px solid var(--text); outline-offset: 3px; }
```

Form controls follow the same idea: dark fields with a 1 px `--line-strong` border that turns `--text` on focus, square corners, sliders with a thin white track and a square white thumb, and toggles that fill white when selected.

**Footer:** the stacked logo on the left, the same height as the text block next to it; links in `--muted` on the right; partner logos in one row (section 3); no extra bottom bar.

---

## 6. Charts and data

Charts are where colour belongs. The page around them stays monochrome, which is exactly what makes the data stand out.

- **One colour per thing, everywhere.** Assign each category a data token once (for example digital `--data-1`, analog `--data-2`, amplifiers `--data-3`) and reuse it in every chart, legend, summary bar and table key on the site.
- **Order:** use `--data-1`, `--data-2`, `--data-3`… in that order; keep to six series at most. Need more? Group the small ones as "other" in `--muted`.
- **Two parts of the same thing** (for example a fixed and a variable part): the same colour, solid for the first and a lighter version (the colour at about 40% opacity, or diagonal hatching in that colour) for the second. Explain it once in the legend.
- **Never colour alone:** pair colour with a second cue where series could be confused: direct labels on bars or line ends, different marker shapes, solid versus dashed lines.
- **Chart chrome is monochrome:** gridlines `--line`, axes `--line-strong`, axis text and units `--muted`, value labels `--text`. No chart backgrounds; the chart sits on a card.
- **Highlight, don't shout:** mark the reader's current selection with a thin dashed `--text` line or a filled marker, not with a new colour.
- **Numbers:** tabular figures (`.num`), units in the axis title or after the value, and the underlying values available as a table for screen readers and copying.

```css
.chart text   { fill: var(--muted); font: 500 11px "Archivo", sans-serif; }
.chart .grid  { stroke: var(--line); }
.chart .axis  { stroke: var(--line-strong); }
.chart .value { fill: var(--text); font-weight: 700; }
.key          { display: inline-block; width: 10px; height: 10px; }   /* legend swatch: background = the series colour */
```

---

## 7. The ASCII background

A field of grey characters drifting slowly behind the page, with black empty areas between the shapes. **One website = one look. A new website = a different look.**

The look is chosen by a *seed*: a name that picks one of four shape families (flowing waves, straight bands, spreading rings, drifting blobs), a character set, the character size, the scale of the shapes, their direction, speed, how much stays black and how bright the brightest characters are. The same seed always gives exactly the same background.

### How to use the seed

- **One seed per website, the same on every page.** Choose a name once, for example the project or site name, and put it on the canvas of every page:

  ```html
  <canvas id="dramco-bg" data-seed="sensor-lab" aria-hidden="true"></canvas>
  ```

  All pages of that site then share the same background layout, so the site feels consistent while it scrolls from page to page.
- **A new website gets a new seed.** Pick another name (`data-seed="open-day-2027"`) and you get a different pattern. Never reuse a seed from another site.
- **Don't like the look?** Just change the name until you do. Any text works; there is no list to choose from. A quick way to preview: change the seed, reload.
- **Forgot the seed?** Without `data-seed` the website's domain name is used, so every page of the site still shares one look and each different domain gets its own. (On `localhost` all projects would look the same, so set a seed while developing.)
- `data-seed="random"` gives a new look on every load. Use it only for demos and experiments, not for real sites.

### Rules that don't change

- Always white characters at low opacity on black: the background never uses colour, even on pages with colourful charts.
- The pattern is anchored to the page: it scrolls with the content.
- It checks itself: on start it measures how much of the screen is lit at several moments and, if a seed would give an almost empty (or an overfull) background at any point, it adjusts the black gap, so every site shows a clear but quiet pattern.

Built to stay cheap: one window-sized canvas, characters pre-drawn once into a tile strip (one `drawImage` per visible cell, no `fillText` per frame), empty cells skipped, about 25 frames per second (every frame while scrolling), paused in background tabs, a single still frame with `prefers-reduced-motion`. No libraries. If a page is very heavy, it can also be moved into a Web Worker with `canvas.transferControlToOffscreen()`.

Save this as `dramco-bg.js`:

```js
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
```

Keep it subtle: if a page needs more calm (long reading, forms, dense charts), lower `light` or raise `gap` in the variation block rather than removing the background.

---

## 8. Starting a new website: checklist

1. Copy this file's CSS (sections 2, 3, 4, 5, 6), the two DRAMCO logo files (appendix) and `dramco-bg.js` (section 7) into the project.
2. Choose a **site seed** (a name nobody else has used) and put it in `data-seed` on the canvas of **every** page.
3. Build the pages from the skeleton in section 5 (header with the logo mark, page head, content, footer with the stacked logo and partner logos).
4. If the site has charts, write down which data colour belongs to which category, once, and stick to it.
5. Check: dark only, white DRAMCO logo, monochrome interface, colour only in data and partner logos, same background on all pages, readable at 320 px wide.

## 9. Accessibility and performance checklist

- Text on the background: always on `--bg`, a band or a card, never directly over bright parts of the pattern.
- Headings in order (one `h1`), real buttons and links, visible focus.
- Charts: colour plus a second cue (labels, markers, line style), a text alternative, and the numbers available as a table.
- Everything readable and usable without JavaScript; the background is decoration (`aria-hidden="true"`).
- `prefers-reduced-motion: reduce`: no animation (the background script already handles it).
- No horizontal scrolling at 320 px wide (wrap wide tables in a scroll container).
- Images: logos as PNG (or SVG), photos compressed (WebP/JPEG), sizes set with `width` / `height`.

---

## Appendix: DRAMCO logo files (white, transparent PNG)

To save them: open the data URL in a browser and "Save image as", or decode the base64 part.

**`dramco-mark-white.png`** (160 × 160):

```text
data:image/png;base64,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
```

**`dramco-logo-white.png`** (320 × 430):

```text
data:image/png;base64,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
```

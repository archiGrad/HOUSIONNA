# HOUSIONNA viewer

The three.js web app that shows HOUSIONNA runs: scene geometry, propagation paths, radio maps and link metrics, per transmitter and across the runs of a batch.

```powershell
npm.cmd install
npm.cmd run build      # writes dist/
```

It runs in two ways:

- **Locally**, served with the HOUSIONNA importer and simulation API by `../toolkit` (see its README).
- **As a read-only website**: `python run.py publish` in `../toolkit` copies `dist/` together with the published runs into a static site (GitHub Pages: https://archigrad.io/HOUSIONNA/).

Source: `src/main.js` (the app), `src/rf-inputs.js` (RF parameter checks), `src/dramco.css` (style).

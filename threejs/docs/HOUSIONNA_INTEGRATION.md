# HOUSIONNA integration boundary

This integration keeps the two repositories independent. HOUSIONNA owns Houdini geometry and device authoring, Sionna RT solving, and its raw run format. `src/integrations/housionna.py` is the only component that reads that format. The Three.js app receives the project's normalized viewer scene format.

## Import a completed run

Run from `sionna-cea-poc`:

```powershell
python run.py import-housionna ..\houdini_files\sionna\data\20261007_200100Z
```

The command validates the folder, writes a normalized import under `outputs/integrations/housionna/<run>/viewer_import.json`, and rebuilds `outputs/digital_twin/viewer_scene.json`. Starting the local viewer then opens the imported run as its featured scenario. Each HOUSIONNA transmitter is a separate scenario choice so the existing viewer can inspect one transmitter's paths, link metrics, and radio map at a time.

No HOUSIONNA files are changed or copied into this repository. The adapter reads its scene meshes and serializes their geometry into the normalized viewer asset. Provenance records the resolved source run folder and input artifact names.

## HOUSIONNA run folder

The Houdini node script embedded in `houdini_files/SIONNA_HOUDINI_pipeline.hipnc` was inspected alongside `sionna_run.py`, the README, and the run at `20261007_200100Z`.

The export button creates a timestamped directory containing:

| Artifact | Written by | Purpose |
|---|---|---|
| `meshes/<name>.ply` | Houdini export | One ASCII PLY mesh per primitive `name`; triangle faces, zero-based vertex indices. |
| `<hip>_scene.xml` | Houdini export | Mitsuba/Sionna scene, mesh references, and ITU radio-material definitions. |
| `<hip>_txrx.json` | Houdini export | Named TX and RX devices and their positions/orientations. |
| `<hip>_log.txt` | Houdini export | Export/validation messages. |

The solve button subsequently writes `<hip>_settings.json` and, on success, `<hip>_result.json`. Preview can add `<hip>_dump.json` and `<hip>_previz.bgeo.sc`. Houdini's result import adds `<hip>_paths.bgeo.sc` and `<hip>_links.bgeo.sc`. Radio-map work uses `<hip>_measure.json`, `<hip>_radiomap.json`, and `<hip>_radiomap.bgeo.sc`. The last three families are workflow outputs, not files created by the export button itself. The successful `20261007_200100Z` folder contains all of these JSON/BGeo outputs plus `meshes/measure_ground.ply`.

## Source schemas

The file prefix is the Houdini scene name (`test1` in the inspected run). The XML shape `id` is `mesh-<name>`, its filename is `meshes/<name>.ply`, and path interaction object names use `<name>` without the `mesh-` prefix. Material IDs come from the ITU type plus thickness/scattering values, for example `concrete_t0p2_s0`; the XML stores the ITU type, slab thickness in metres, and scattering coefficient. The optional `_dump.json` enriches these materials with relative permittivity and conductivity.

### TX/RX JSON

```json
{
  "tx": [{
    "name": "tx_0",
    "position": [0.0, 0.0, 1.0],
    "orientation": [0.0, 0.0, 0.0],
    "velocity": [0.0, 0.0, 0.0],
    "power_dbm": 30.0
  }],
  "rx": [{
    "name": "rx_0",
    "position": [1.0, 0.0, 1.0],
    "orientation": [0.0, 0.0, 0.0],
    "velocity": [0.0, 0.0, 0.0]
  }]
}
```

`power_dbm` is optional in the exporter. If it is absent, the adapter preserves it as `null`; it does not guess which Sionna default was applied. The exporter writes position and velocity components through `to_sionna(v) = (v[0], -v[2], v[1])`. Orientation is written as the supplied three-component vector.

### Settings JSON

The observed keys are `frequency` (Hz), `max_depth`, `samples`, the booleans `los`, `specular_reflection`, `diffuse_reflection`, `refraction`, and `diffraction`, `bandwidth` (Hz), `cfr_points`, and `radiomap_samples`. `sionna_run.py` sets the scene frequency from this file and uses the settings for path and radio-map solvers.

### Result JSON

Top-level keys are `sionna_rt`, `variant`, `settings`, `cfr_frequencies`, `paths`, and `links`.

- A path has `tx`, `rx`, `vertices`, `interactions`, `objects`, `primitives`, complex coefficient components `a_re`/`a_im`, `gain_db`, delay `tau` (seconds), departure/arrival angles, and `doppler`. `vertices` contains TX, each interaction point, then RX. The three interaction arrays align by hop. Interaction values are bit flags: `1` specular reflection, `2` diffuse reflection, `4` refraction, `8` diffraction. `gain_db` is `20 log10(|a|)`; it is an amplitude/coefficient magnitude in dB.
- A link has `tx`, `rx`, the two endpoint `vertices`, `num_paths`, `gain_db_coherent`, `gain_db_incoherent`, `delay_spread` (seconds), and optionally `cfr_db`. `cfr_db` indexes `cfr_frequencies` (Hz). A zero-amplitude dB value is JSON `null` in the solver output.

### Radio-map JSON

Top-level keys are `sionna_rt`, `settings`, `tx` (ordered transmitter names), and `maps`. Each map has a `name`, `vertices`, `faces`, and `path_gain_db`. In the inspected run `path_gain_db` is `[measurement triangle][transmitter]`; columns use the `tx` array order and rows use the map's face order. It is not a rectangular raster. Values are `10 log10(path_gain)` in dB, with `-999` used for non-finite/missing cells. This is path gain, not RSS or received power. `_measure.json` is the ordered list of measurement mesh names; each name has a matching `meshes/<name>.ply`.

## Coordinates, units, and names

HOUSIONNA writes scene vertices and device positions in the Sionna frame, in metres. Its Houdini-to-Sionna position transform is `(x, -z, y)`, which produces X/Y horizontal and Z up. This matches the existing viewer's metres/Z-up frame, so the adapter applies no second coordinate transform. Path vertices and radio-map vertices are already in the same Sionna frame. Delay is seconds, frequency/bandwidth are Hz, device power is dBm, and orientation values are radians.

The adapter uses each PLY filename stem as the viewer object ID/name, retains the XML shape ID and source mesh path in object metadata, and keeps the XML material ID as the viewer material key. The ITU type, thickness, scattering coefficient, and any optional dump permittivity/conductivity remain attached to that material/object. Path interaction object names are preserved verbatim.

## Normalized viewer data

The existing viewer already supports selectable scene scenarios, one transmitter and multiple receivers per scenario, interaction polylines, per-receiver path metrics, and rectangular radio-map grids. Its native scenes describe generated geometry with bounds and material categories. It did not previously render arbitrary imported triangle meshes or per-triangle measurement maps; this milestone adds those two internal viewer capabilities.

The adapter emits the same scenario fields used by `digital_twin_data.py`: geometry, one `transmitter`, `receivers`, `paths`, `receiver_metrics`, `radio_map`, solver settings, and material metadata. It adds references to shared geometry/map assets at the top level rather than repeating the mesh arrays for each transmitter. The viewer resolves these references before rendering.

- Geometry is represented as `geometry.objects[]` with `mesh_format: "indexed_triangles"`, metre coordinates in `vertices`, zero-based `faces`, `bounds_m`, category, material key, and source metadata. The Three.js renderer builds a `BufferGeometry` from this normalized shape.
- HOUSIONNA paths are converted to the viewer's `interaction_vertices_m`, `interaction_types`, `interaction_type_ids`, `interacted_objects`, coefficient magnitude, delay, path length, and LOS fields. Each exported TX/RX endpoint is checked against the corresponding device position using `housionna.path_endpoint_tolerance_m` in `config/housionna.yaml` (default 0.001 m). The measured maximum endpoint error and configured tolerance are recorded in provenance. `-999` and non-finite result values become JSON `null`; missing radio-map triangles are not drawn.
- Each result link is retained in `scenario.links` and summarized into the existing per-RX metrics. This carries coherent/incoherent link gain, delay spread, and CFR samples/frequencies while the current inspector shows the coherent gain and delay spread.
- Each transmitter gets one selectable scenario with only its paths, links, and radio-map column. Radio-map triangles share their measurement mesh asset and retain face order.
- Every imported scenario has `source_type: "housionna"` and provenance containing the source folder, source file names, Sionna version/variant, import time, and coordinate convention.

The adapter requires scene XML, TX/RX JSON, settings JSON, result JSON, and every referenced scene PLY. Radio maps are optional; if present, `_measure.json`, each measurement PLY, and correctly dimensioned `path_gain_db` values are required. Current export writes ASCII PLY 1.0 triangles; the adapter rejects unsupported/binary PLY rather than silently misreading it.

## Live Sionna reruns on imported geometry

The interactive solver reads the original `<hip>_scene.xml`, source PLY references, TX/RX JSON, and settings from the configured HOUSIONNA run. It does not use the normalized Three.js meshes as solver geometry. `rt.load_scene(xml, merge_shapes=False)` loads the original Mitsuba shapes and their XML-defined ITU materials. One selected TX and one to eight selected original RXs are added to that scene. The interactive antenna configuration matches the source runner: 1x1 isotropic arrays with V polarization. Coordinates pass through unchanged: XYZ metres, Z up.

Houdini remains responsible for changes to geometry, device layouts, object names, or RF materials. Sionna can be rerun without Houdini when the user changes frequency, TX position/orientation, receiver subset, path sample count, maximum depth, or LOS/reflection/refraction/diffraction flags. The UI preserves unusual exported source poses for inspection, warns for below-floor and likely geometry overlap, and provides **Reset TX position**. It does not auto-correct a source position.

Path jobs run one at a time in an isolated Python child process. This avoids sharing Dr.Jit/Mitsuba objects between the HTTP server and a worker thread. The local server remains responsive and reports queued, preparing, running, exporting, completed, or failed states with elapsed time. It does not invent percentage progress. A worker log and full traceback are retained below `outputs/live/.housionna-jobs/<job-id>/`; concise errors are returned to the viewer. User input never supplies a filesystem path or executable command. The server binds to `127.0.0.1`.

The path request is JSON with `source_run_id`, normalized `import_id`, `transmitter`, `receiver_ids`, `frequency_hz`, `tx_position`, `tx_orientation`, `samples_per_src`, `seed`, and `solver`. Frequency is bounded to 100 MHz–6 GHz, depth to 1–5, path samples to 1–2,000,000, and each position axis to the scene bounds plus `max(1 m, 25% of that axis span)`. Device IDs are checked against the selected export. The UI uses the original settings as defaults and a fixed seed 42 for repeatability. The worker loads only the selected source devices.

Each path run gets a new `outputs/live/housionna-reruns/<job-id>/` folder containing `config.json`, `metadata.json`, raw HOUSIONNA-shaped `paths.json`/`links.json`, normalized `viewer_result.json`, `comparison.json`, and `result.json`. Metadata includes source file hashes, XML/material provenance, TX/RX pose, frequency, antenna, solver flags, samples, seed, deterministic mode, Sionna version/variant, runtime, and baseline comparison. Original data remains under `outputs/integrations/housionna/`; the HOUSIONNA source tree is never written.

The separate radio-map endpoint can run immediately, independently of paths. It loads the original measurement PLY named by `_measure.json`, adds only the selected TX, and calls `RadioMapSolver` with `measurement_surface`. Values remain in source face order. Quality presets are Low: 100,000, Medium: 500,000, High: 2,000,000 samples/TX. Their exact counts are recorded in each map's config and metadata. The viewer sends only per-face values because it already has the source triangles loaded. Zero/non-finite path gains become JSON `null`; imported `-999` sentinels are also missing values. This retains triangular measurement data without inventing a raster grid.

The viewer keeps session snapshots of the original imported result and the latest Sionna result. Its result selector switches between them without refetching the large viewer document. A changed path input hides stale path lines and shows **RF RESULTS OUT OF DATE — RERUN REQUIRED**. A recalculated map is labeled with its quality and sample count. The map selector can show the selected result or `rerun − original`; difference mode is enabled only after a rerun map exists, its carrier frequency matches the original, and source mesh identity, triangle coordinates, indices, and ordering match. It subtracts only cells where both values are finite and present. Changing TX pose is a supported comparison; a frequency mismatch disables difference mode. A path rerun alone does not imply that the original map matches a moved TX or changed frequency.

### Live simulation API

| Method and route | Purpose |
| --- | --- |
| `POST /api/housionna/simulate` | Validate a request and start one isolated path job; returns 202 and a job ID. |
| `POST /api/housionna/radio-map` | Start a selected-TX map job on the original triangular measurement mesh. |
| `GET /api/housionna/simulations/<job-id>/status` | Poll actual job stage, message, and elapsed time. |
| `GET /api/housionna/simulations/<job-id>` | Fetch normalized paths/metrics and comparison, or face values and map metadata. |
| `GET /api/housionna/simulations/latest?source_run_id=…&import_id=…&transmitter=…` | Find the newest saved path and map run IDs for this imported transmitter. |

Both HOUSIONNA job types share a server gate with the existing native `/api/simulate` route, so only one Sionna calculation runs at a time across the viewer. A concurrent submission receives HTTP 409. Invalid scene, TX/RX, frequency, coordinate, solver, or sample requests are rejected before starting a process. The existing native experiment remains available.

### Verified reruns

On 2026-10-08, source run `20261007_200100Z` was loaded from original XML and PLY on local Sionna RT 2.2.0 / Mitsuba `llvm_ad_mono_polarized`. A `tx_0` baseline using three receivers returned 10 paths (4/3/3 per RX). Compared with the source CUDA result, path counts and LOS matched; strongest-path magnitudes differed by less than 0.00003 dB; the maximum matched delay error was 0.0000036 ns; and the maximum interaction-vertex difference was 0.000016 m. Coherent/incoherent link gains differed by less than 0.00015 dB in this sample. This is close numerical agreement, not bitwise identity: the source uses CUDA and `PathSolver()` default `deterministic=False`; local interactive reruns use LLVM, seed 42, and deterministic mode.

A controlled deterministic experiment changed only `tx_0` from `[-1.146370,-4.866590,1.371567]` m to `[-0.646370,-4.366590,1.371567]` m, with 3.5 GHz, the same three RXs, one million samples, depth 3, and identical material/scene data. Both cases returned 4/3/3 paths. Strongest-path gain changed +6.426 dB (`rx_0`), +5.807 dB (`rx_1`), and -2.333 dB (`rx_2`); coherent aggregate link gain changed +11.120, +4.364, and -9.772 dB. The two calculations together took 7.797 seconds in the saved experiment metadata.

The standalone feasibility commands can be repeated from PowerShell:

```powershell
.\.venv\Scripts\python.exe run.py housionna-rerun --run-id 20261007_200100Z --transmitter tx_0 --receivers rx_0 rx_1 rx_2
.\.venv\Scripts\python.exe run.py housionna-position-test --run-id 20261007_200100Z --transmitter tx_0 --receivers rx_0 rx_1 rx_2 --offset 0.5 0.5 0
```

Earlier HTTP path runs recorded 3.218–6.546 seconds inside the simulation function; process startup adds to wall-clock wait. An end-to-end HTTP smoke took about nine seconds. A low radio map used 100,000 samples over all 19,602 triangles of `measure_ground.ply`; a checked output had about 13,500 missing values. A triangle-aligned comparison against the source map had 6,119 jointly valid cells, 1.695 dB mean absolute difference, and 3.022 dB RMS difference. This low-sample map is visibly sparse and those deltas are sample-sensitive; they are not a calibrated accuracy claim. Earlier recorded map-function time was 2.375–2.750 seconds, including scene setup and conversion, rather than pure solver time. New exclusive solver timings are documented in [PERFORMANCE_RELIABILITY.md](PERFORMANCE_RELIABILITY.md). These historical timings were recorded before the 2026-10-09 MX450 driver update and used CPU/LLVM. A later matched CPU/GPU check is in that report. A seed is passed to `RadioMapSolver`, but bitwise repeatability across runs/backends is not claimed.

## Live run discovery and import

`config/housionna.yaml` selects the export directory. A relative value is resolved from the `sionna-cea-poc` project root; an absolute path is also accepted in this local config. `HOUSIONNA_RUNS_DIRECTORY` can override it for the current process. The API never accepts a caller-supplied filesystem path: import requests name a child run folder discovered under this configured directory. Folder names with traversal syntax and symlinks that point outside the configured root are rejected. The viewer server continues to bind to `127.0.0.1`.

Discovery checks for the four required solve artifacts (`*_scene.xml`, `*_txrx.json`, `*_settings.json`, and `*_result.json`) and validates the source JSON, XML references, PLY geometry, path/link references, and optional radio-map artifacts. Folders are listed as valid, incomplete, or invalid; only valid completed exports are eligible for **Import latest**. Timestamp-shaped folder names sort by their UTC timestamp; other names use folder modification time. Import runs on a background thread and reports actual stages through the UI.

The viewer API is:

| Method and route | Purpose |
| --- | --- |
| `GET /api/housionna/runs` | List discovered exports and validation status. |
| `POST /api/housionna/import-latest` | Import the newest valid export. |
| `POST /api/housionna/import` | Import `{"run_id":"<discovered folder name>"}`. |
| `GET /api/housionna/imports` | List normalized import revisions. |
| `GET /api/housionna/imports/<import-id>` | Read public import metadata (source paths are omitted). |
| `GET /api/housionna/jobs/<32-hex-id>` | Poll import stage and final status. |
| `POST /api/housionna/compare` | Compare two import IDs and one transmitter. |
| `POST /api/housionna/simulate` | Run paths for selected imported TX/RXs against original XML/PLY. |
| `POST /api/housionna/radio-map` | Recalculate the selected TX on original measurement triangles. |
| `GET /api/housionna/simulations/<job-id>/status` | Poll isolated Sionna job stage and elapsed time. |
| `GET /api/housionna/simulations/<job-id>` | Read normalized results, comparison, or triangular map values. |
| `GET /api/housionna/simulations/latest?source_run_id=…&import_id=…&transmitter=…` | Resolve the latest completed saved path and radio-map run IDs after a viewer/server restart. |

The viewer calls the latest-results route when an imported transmitter is selected. It restores normalized paths and receiver metrics from the saved run, then attaches compatible triangular values to the already-loaded mesh. Saved maps are restored only when source run, import revision, TX, frequency, TX position, and face count match the selected path result. This lookup reads the CEA project's saved output folders and works after restarting the viewer server; no Sionna calculation is started during restoration. Import IDs include a SHA-256 fingerprint of source JSON/XML and PLY files. Unchanged inputs reuse the normalized import. Changed inputs receive a new output folder and keep prior revisions intact. Normalized documents include the original run folder name and local source location, input filenames and individual hashes, adapter version, import time, scene name, TX/RX/mesh/path/map counts, frequency, solver settings, and Sionna version/variant. The API omits absolute source paths.

## Viewer controls

Choose **Scene source → Built-in demo** to use the existing vertical-farm, CEA, and canopy scenes. Choose **Scene source → HOUSIONNA** to select a normalized run revision and then a transmitter. Each transmitter's paths, links, receiver metrics, and radio-map column remain in its own viewer scenario. Switching run or TX replaces the entire geometry and result layers, preserves the camera when the old view still frames the new bounds, and otherwise fits the new scene. The page fetches the normalized viewer document again after import; no browser reload is required.

Imported geometry defaults to a matte, neutral **Solid** display. **Wireframe**, **Transparent**, and deterministic **Object colors** modes are viewer-only styles; the legend associates displayed colors with the original mesh and material names, while the inspector continues to show the unmodified RF material metadata. Device markers default to **Selected TX + associated RXs**; **All TXs and RXs in this run** shows every exported device without duplicating the shared RX. Labels can show selected devices, all displayed devices, or none. **Show measurement mesh** draws the exact triangular surface independently of its path-gain colors. The path filter offers the strongest, top five, or all paths for the selected RX. Camera presets include isometric, top, front, side, fit scene, selected object, selected TX, and selected RX. Coordinate axes, origin, and the scene bounds can be toggled separately; the imported default hides diagnostic overlays and the scene boundary.

Exported mesh names, XML shape IDs, PLY paths, and RF material keys remain attached to clickable geometry. The inspector shows dimensions, triangle count, RF material, original mesh, source run, and revision. HOUSIONNA exports contain no Three.js crop instances; imported scenes show only exported geometry. Measurement maps are batched into one `BufferGeometry` per surface, with one face color per source triangle. Null/missing measurements are omitted from rendering. The legend uses the valid path-gain dB range for the selected transmitter.

HOUSIONNA source runs remain read-only, while their imported TX markers can be dragged and their on-demand Sionna controls are enabled. Built-in demo simulation remains available by changing the scene source selector. Dragging changes X/Y; numeric controls edit X/Y/Z/yaw. Results run only when the user starts a job.

For a first import from Windows PowerShell, run `npm.cmd --prefix frontend run build` and then `.\.venv\Scripts\python.exe run.py view`. In the viewer choose **Scene source ? HOUSIONNA ? Import latest Houdini run**. Choose a transmitter, edit its pose/frequency or solver fields, select receivers, and press **RUN SIONNA RT**. The original result remains selectable under **Displayed RF result**. Inspect new receiver metrics and paths; after the path job completes, choose a map quality and press **RECALCULATE RADIO MAP** to update the original triangle overlay for that TX. Use **Reset TX position** to restore its exported pose. The result panel shows runtime and comparison deltas.

## Coordinate diagnostic

**Performance refinement:** radio-map calculation now runs independently of paths;
the selected TX's map can be calculated immediately. Saved maps restore their own
inputs after refresh. Paths and RX metrics remain associated with their calculation
and become stale when those inputs differ. Null faces are represented by transparent
RGBA colours in stable triangle buffers. The Sionna yaw control edits orientation
component 0 (alpha about Z); pitch and roll are retained. See
[PERFORMANCE_RELIABILITY.md](PERFORMANCE_RELIABILITY.md) for the current cache,
worker/status contract, runtime measurements and native Windows limitations.

The inspected Houdini exporter transforms positions and mesh vertices with `(x, y, z) -> (x, -z, y)` before writing the Sionna scene/device data. The adapter has verified that the sample TX/RX, path vertices, PLY vertices, and measurement mesh are already in this resulting frame and passes their coordinates through unchanged. All are metres, X/Y horizontal, Z up. The Three.js app explicitly sets `camera.up` to `(0, 0, 1)`, and its vector helper maps source `[x,y,z]` directly to Three.js `Vector3(x,y,z)`; no second axis conversion is applied. Orientation vectors are retained in radians; the marker uses the exported yaw about Z.

The 3D viewport adds a world-axis marker at `[0,0,0]`, a separate origin marker, a bounds outline from the imported scene bounds, and an XY reference grid at the scene's lower Z bound. These coordinate diagnostics and the scene boundary have independent visibility controls. Propagation paths are drawn from the selected TX to each RX through the exported interaction vertices. Triangle winding is retained from the source faces, and the mesh material is double-sided for display.

## Run comparison rules

The comparison endpoint checks frequency, exact normalized scene geometry (including vertex/face ordering), TX pose/orientation/power, RX names/poses/orientations/velocities, material definitions, and solver settings. It reports compatibility before showing deltas. Receiver-matched rows report path counts, strongest-path delay deltas, coherent and incoherent link-gain deltas, and delay-spread deltas.

The import-to-import comparison endpoint reports radio-map cell statistics only if the selected TX exists in both imports, frequency and TX configuration match, each measurement surface has the same name, exact vertex coordinates, exact triangle indices/winding/order, and value count, and both compared cell values are finite. Missing cells are excluded. The live Sionna viewer also has a rerun-minus-original difference layer; it applies the same frequency, metric, and triangle-alignment checks before rendering.

## Reproduce and test

From the project root in Windows PowerShell:

```powershell
npm.cmd --prefix frontend run build
.\.venv\Scripts\python.exe run.py view
```

Use the viewer controls to import latest, select a prior imported run and TX, enable **Radio map** and **Show returned paths**, click source meshes, and compare two imports. The command-line adapter remains available for scripted imports:

```powershell
.\.venv\Scripts\python.exe run.py import-housionna ..\houdini_files\sionna\data\20261007_200100Z
```

Automated integration tests live under `tests/` and use the actual `20261007_200100Z` export if it is present locally. They make temporary copies only for corrupt/incomplete-input cases; HOUSIONNA source files are not changed.

Run the suite with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Measured import and payload size

On the local Python 3.12.10 environment, a cold normalization of `20261007_200100Z` took 3.72 seconds and wrote a 6,109,536-byte normalized import (5.83 MiB). At that point, the viewer scene was 7,020,271 bytes (6.69 MiB), with a duplicate legacy copy of the same RF content suppressed from the scene while both import files remained under `outputs/`. A second valid run, `20261007_195457Z`, was also imported; its normalized import is 20,863,321 bytes and contains 1,999,404 radio-map values. The current viewer scene with both imports and built-in scenarios is 30,125,043 bytes (28.73 MiB), with 126 scenarios. Discovery of all nine local export folders took 6.33 seconds cold and 0.40 seconds with the in-process validation cache (six valid, two invalid, one incomplete). The 19,602 map triangles render as one batched `BufferGeometry` per surface rather than individual Three.js mesh objects. These are local command and file-size measurements, not browser load-time or frame-rate measurements.

The inspected sample contains 15 transmitters, 5 receivers, 530 paths across all transmitters, and a 19,602-triangle measurement surface. Browser automation is not available in this workspace, so successful data validation and a frontend build do not establish that WebGL rendering has been visually checked. Confirm the imported TX selection/drag and reset, numeric edits and stale indicator, live path refresh, original/latest selector, low-map overlay, triangle difference selector, and camera preservation in a local browser as the remaining visual QA step.

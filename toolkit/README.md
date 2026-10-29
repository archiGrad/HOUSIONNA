# HOUSIONNA toolkit

The Python side of HOUSIONNA: it imports the runs that `houdini_files/` exports and Sionna RT solves, serves them to the three.js viewer in `../viewer/`, publishes the read-only website, and evaluates the applications. All commands run from this folder through `run.py`.

| Folder | Contents |
|---|---|
| `src/housionna/` | import of Houdini/Sionna runs and batches (`importer.py`), the viewer API, simulation jobs, caching |
| `src/server/` | local viewer server, viewer payloads, `publish` for the website |
| `src/engine/` | application engine: link margins, RF power transfer, harvesters, maps, placement, case study |
| `src/demos/` | the early stand-alone demos below (room, CEA greenhouse, vertical farm, canopy physics) |
| `config/`, `data/devices/` | application profiles and measured device data |
| `scripts/`, `tests/` | reference cases, material table, figures; unit tests (`python -m unittest discover -s tests`) |
| `outputs/` | the built-in demo farm (in git) and local results (ignored) |

The viewer is built with `npm.cmd --prefix ../viewer install` and `npm.cmd --prefix ../viewer run build` into `../viewer/dist/`.

## Early demos

This started as a small, runnable Sionna RT starter project. It checks a built-in Sionna scene, creates a simple room from OBJ surfaces, records paths/CIR and a planar path-gain map, and measures the effect of moving one panel.

The model uses **x/y as horizontal axes and z as up**, with meters for positions. The 2.4 GHz setting is provisional. The room's dielectric values are teaching placeholders, not measured or literature-validated values. The output is a simulation sanity check, not a validated propagation prediction.

## What is included

- `basic`: the official Sionna `floor_wall` scene with one transmitter and three receivers.
- `room`: a 10 m × 6 m × 3 m room, generic concrete-like surfaces, one movable panel, one transmitter and three receivers.
- `compare`: repeats the room run after moving only the panel by 1.8 m and saves a radio-map difference.
- `cea`: generates empty, narrow-canopy, and wide-canopy greenhouse scenarios with separate material categories and a comparison figure.
- `canopy-physics`: runs the transparent/weak-loss/current material study, solver-sensitivity repeats, and an isolated Sionna slab transmission check.
- `digital twin`: a local Three.js 3D viewer that reads generated scene geometry and saved Sionna paths/maps and is the only viewer (the 2D dashboard was removed).
- CSV/JSON path and CIR output, raw linear path-gain arrays, cell-center coordinates, metadata, and PNG geometry/channel/map visualizations.

The radio-map array is **path gain** (linear power ratio), not received power or RSS. The PNG converts it to `10 log10(path_gain)` for display. The CIR stores the complex baseband path coefficients and delays; it does not apply the transmitter power to create RSS.

This is a solver and export smoke check, not a calibrated result: the maps are coarse and use modest ray counts, the example plane includes cells close to the transmitter, and the room's materials are placeholders. Do not use these values for quantitative site claims.

## Local environment

This project uses Python 3.12.10, Sionna RT 2.2.0, Mitsuba 3.9.1, Dr.Jit 1.5.0, and LLVM 18.1.8. The pinned NumPy 2.5.3 and SciPy 1.18.1 packages declare Python 3.12 or newer, so Python 3.11 cannot satisfy this lock. The local runtime and environment live under `.runtime/` and `.venv/` and are ignored by Git. Official downloads: [Python 3.12.10](https://www.python.org/downloads/release/python-31210/) and [LLVM 18.1.8](https://github.com/llvm/llvm-project/releases/tag/llvmorg-18.1.8).

From PowerShell in this folder, the installed environment can be used directly:

```powershell
.\.venv\Scripts\python.exe run.py basic
.\.venv\Scripts\python.exe run.py room
.\.venv\Scripts\python.exe run.py compare
```

## Open the interactive viewer

In the VS Code terminal, run:

```powershell
.\.venv\Scripts\python.exe run.py view
```

It opens the 3D digital twin at `http://127.0.0.1:8765/` (see [Three-dimensional digital twin](#three-dimensional-digital-twin)). Keep the terminal open while viewing; press **Ctrl+C** there when finished. The page is served only from `127.0.0.1`. It loads the Archivo font from Google Fonts; everything else is local. The older 2D dashboard was removed; the `basic`, `room` and `compare` runs still write their PNG figures under `outputs/`.

To create the environment on another Windows x64 machine, install Python 3.12, extract the LLVM 18.1.8 Windows x64 release so that `.runtime\llvm-18.1.8\bin\LLVM-C.dll` exists, then run:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The existing `.venv` was repaired in place after its `pyvenv.cfg` pointed to a removed checkout path; the original file is retained as `.venv\pyvenv.cfg.before-repair.txt`. At first setup, the GeForce MX450 driver was too old for Dr.Jit's CUDA backend, so the viewer used LLVM on CPU. After the driver update, Windows reports driver 617.14 / CUDA 13.4 and automatic backend selection chooses `cuda_ad_mono_polarized`; a Low Sionna radio-map run has been confirmed on the GPU. See the current GPU check below.

## CEA demo

The CEA milestone adds a small, procedural greenhouse to the existing Sionna RT pipeline. It has a floor, simple glazing-like envelope, a few metal-like supports and roof rails, and three longitudinal rectangular canopy proxies. These are artificial software-test dimensions and geometry; they are **not KU Leuven greenhouse dimensions** and do not represent a surveyed greenhouse.

Run all three scenarios and create the comparison outputs:

```powershell
.\.venv\Scripts\python.exe run.py cea
```

To regenerate one scenario at a time:

```powershell
.\.venv\Scripts\python.exe run.py cea-empty
.\.venv\Scripts\python.exe run.py cea-narrow
.\.venv\Scripts\python.exe run.py cea-wide
```

The one-scenario commands refresh only that scenario's folder. Run `run.py cea` after changing shared settings or scenario overrides to regenerate all three cases and the comparison together.

Then open the viewer with `run.py view`, choose **Scene source → Built-in demo**, and pick the narrow or wide greenhouse case in the scenario selector. Each case shows the greenhouse geometry, its path-gain map, and paths for the three representative receivers; **Difference map** shows the case minus the empty greenhouse. The side-by-side comparison of all maps is `outputs/cea/comparison/radio_map_comparison.png`. The receiver grid is used for the radio-map coverage; paths are computed only for the three selected receiver points.

CEA output is under `outputs/cea/empty/`, `outputs/cea/narrow/`, `outputs/cea/wide/`, and `outputs/cea/comparison/`. Scenario folders contain the scene image, generated named OBJ assets, `scene_manifest.json`, config snapshot, metadata, path/CIR exports, and radio-map arrays/images. The comparison folder contains `summary.csv`, `representative_receivers.csv`, difference arrays, `comparison.json`, and `radio_map_comparison.png`.

Edit `config/cea_demo.yaml` to change greenhouse length/width/height, canopy row count/length/height/spacing/bottom height, TX position/orientation, representative RX positions, radio-map grid bounds/resolution, frequency, and solver settings. The three scenario overrides live under `scenarios`: empty disables canopy, narrow enables 0.6 m rows, and wide enables 1.2 m rows. The comparison holds all other settings fixed. A changed row count must still fit across the greenhouse. `frequency_hz` is 2.4 GHz only as a provisional software-demo value.

Every custom material value is marked **DEMO PLACEHOLDER**. In particular, the canopy is modeled as a solid lossy rectangular block, not a physically validated plant model. Plant water content is not calibrated; leaves and stems are absent; scattering/refraction behavior has not been validated; and no measurement validation has been performed. The geometry, dimensions, and dielectric values are artificial, and no conclusions about real greenhouse coverage should be drawn. Future work should compare this proxy with more detailed vegetation representations after the geometry-to-Sionna handoff is established.

The geometry/result handoff now reads HOUSIONNA's exported meshes, device data, settings, paths, links, and radio maps through a normalized adapter. See `docs/HOUSIONNA_INTEGRATION.md` for the verified interface and local import workflow. Detailed plant modeling can follow as a separate geometry milestone.

## Vertical-farm / wardrobe demo

The featured 3D scene is now a compact, semi-open indoor rack with three vertically stacked growing levels. All cabinet, shelf, support, tray, grow-light, RF-zone, device, and receiver-grid coordinates are generated from `config/vertical_farm.yaml`. Its 1.25 m x 0.65 m x 2.10 m envelope is an artificial software-demo placeholder, not a measured farm or equipment specification. Shelf levels, depth/width, panel and tray thicknesses, front opening, lights, TX/RX positions, grid resolution, and visual planting density are configurable there.

Run the three deterministic Sionna RT cases:

```powershell
.\.venv\Scripts\python.exe run.py vertical-farm
```

The controlled cases are **Empty rack**, **RF plant proxy** (one canopy zone per shelf), and **Dense canopy proxy** (the same zone, with a denser, higher-loss placeholder material standing in for a fuller crop). The shell, rack, shelf levels, non-canopy materials, TX/RX points, radio-map grid, solver settings, seed, and decorative plant layout are held fixed. Proxy versus empty shows the effect of adding a canopy; dense versus proxy shows the effect of canopy density alone. In the empty control, detailed plants start hidden; enable **Detailed visual plants** to show the same decorative crop while the RF-zone layer remains empty. Paths, radio maps, scene manifests, config snapshots, metadata, and difference maps are written under `outputs/vertical_farm/`.

**Map planes.** With `receiver_grid.map_planes: air_gaps` (the default), each shelf level gets one radio-map plane midway through the free air above its canopy, below the shelf, supports and grow light overhead. This is where a sensor could sit; the planes never cut through a canopy block, and the runner checks this against the generated geometry. The `primary_level` plane (level 2) is the one shown in the 3D viewer; every plane is saved as `radio_map_level<N>.npy` and used in the zone report.

**Zone report.** `outputs/vertical_farm/comparison/comparison.json` has a `zone_report` with, per plane and per zone (in front of the rack, over the canopy, beside the canopy inside the rack, outside), the median change against the empty rack over cells that receive signal in both maps, and the coverage share at `analysis.receiver_sensitivity_dbm` (a placeholder). The older floored `stats` are kept, but they are dominated by cells without signal and should not be read as the canopy effect.

**Sampling.** The default sample counts are kept low so runs stay quick on a laptop GPU, but they are too noisy for quantitative comparison: a sampling study on the DGX Spark (Oct 2026, `scripts/vertical_farm_convergence.py`) found single cells varying by tens of dB between seeds at 1x. For results to report, run `run.py vertical-farm --profile spark`, which raises the map samples 10000x and averages 8 seeds (defined under `run_profiles` in `config/vertical_farm.yaml`).

Detailed leafy plants are generated in the Three.js frontend from the separately exported `visual_plants` layout and use instanced stems, crowns, and curved leaves. They are **visual-only** and never enter the Sionna scene. The named `rf_plant_zone` boxes are separate coarse RF objects, exported as OBJ and passed to Sionna by the vertical-farm runner. In the viewer, use **Detailed visual plants** and **RF plant zones** as independent layer toggles; clicking a plant shelf, tray, or RF zone shows its level and RF/visual status in the inspector.

Open the viewer after generating the farm outputs:

```powershell
npm.cmd --prefix ../viewer run build
.\.venv\Scripts\python.exe run.py view
```

With **Scene source → Built-in demo** the viewer opens on **Vertical farm · RF plant proxy**. Start with **Isometric**, then try **Front elevation**, **Shelf close-up**, and **TX view**. Use the scenario selector to compare the empty, one-zone, and two-zone-per-level models. Switch on **Radio map**, then use **Map level** to move between the three air-gap planes; the map sits at the solved plane height, so the height slider is locked for these cases. **Difference map** shows the selected level minus the empty rack, and the panel under the legend shows that level's zone report (median change and coverage per zone).

These dimensions and RF material properties are placeholders. Each proxy is a solid box, not a detailed leaf/stem or volumetric crop model; plant water content, dielectric properties, scattering, and equipment materials are not calibrated. No measurement validation is included, so the RF output is an implementation experiment and should not be read as a real farm coverage prediction.

## Interactive simulation

The Three.js viewer sends on-demand jobs for both the built-in scenes and imported HOUSIONNA geometry. The scene remains interactive while a Sionna worker process runs. Editing a TX, frequency, selected RX set, sample count, or solver setting marks its path result stale and hides stale path lines. Releasing a dragged TX never starts a calculation. `Ctrl+Enter` starts the built-in scene calculation when focus is outside a text/select control.

The browser calls `GET /api/status`, `GET /api/history`, `POST /api/simulate`, and `GET /api/simulation/<run-id>` on the same local viewer server. Runs are serialized: one Sionna job can run at a time. The API accepts the three configured farm cases (`farm_empty`, `farm_proxy`, `farm_dense`), 100 MHz–6 GHz, the configured default RX set, path depth 1–5, and LOW/MEDIUM/HIGH map presets. The 433 MHz, 868 MHz, 2.4 GHz, and 5 GHz entries are editable frequency presets, not validated bands or study recommendations. HIGH uses a 0.10 m map grid and more samples, so it can take longer.

Build and start the integrated viewer from this project folder:

```powershell
npm.cmd --prefix ../viewer run build
.\.venv\Scripts\python.exe run.py view
```

For a built-in scene, use the **On-demand Sionna RT** panel as before. For an imported HOUSIONNA run, select its TX, edit frequency and pose, choose one to eight receivers, set path samples and solver options, then press **RUN SIONNA RT**. Dragging the active TX changes X/Y; use the numeric fields for Z/yaw. **Reset TX position** restores the original exported pose. The viewer warns about floor and possible mesh-bound overlap but keeps source placements unchanged until you move them.

Each new run is saved in its own `outputs/live/<run-id>/` folder with `config.json`, `metadata.json`, `paths.json`, `radio_map.npy`, `radio_map.json`, `viewer_data.json`, and `receiver_metrics.json`. The map files contain path gain; the viewer's dB colors are only the documented `10 log10(max(path_gain, 1e-15))` display transform, not RSS. Exact successful request hashes reuse saved results; different TX/settings get a new folder and leave previous runs intact. The frontend exchanges run IDs and JSON payloads only, not local filesystem paths, so the same API contract can later sit on a DGX Spark. The Sionna loader keeps the bundled LLVM DLL setup on Windows and allows native Dr.Jit/Mitsuba backend selection on Linux. The Spark environment itself is set up and verified (see [Running on the DGX Spark](#running-on-the-dgx-spark)); sending these on-demand jobs to it from the viewer is not configured yet.

## Canopy physics sanity study

Run the narrow-canopy control experiment and its one-factor diagnostics:

```powershell
.\.venv\Scripts\python.exe run.py canopy-physics
```

The four core cases are empty, a free-space-matched transparent control, an arbitrary weak-loss placeholder, and the existing current canopy material. They use the same 0.6 m canopy geometry, greenhouse shell/structure, frequency, TX, RX, radio-map grid, and solver settings. The command also runs diagnostics that change only one current-case factor at a time: refraction off, lower permittivity, lower conductivity, or thinner Sionna material slab.

In the viewer (`run.py view`, **Scene source → Built-in demo**), pick the empty, transparent, weak-loss or current case in the scenario selector; **Difference map** shows each case minus empty, and choosing RX_A, RX_B or RX_C updates the path summary. The overlaid CIR plot and the four-map comparison are saved as `outputs/canopy_physics/comparison/cir_comparison.png` and `radio_map_comparison.png`. This study moves RX_C to `[10.0, 5.0, 1.5]` m for all cases: the prior RX_C position was inside the closed canopy box, so it was not a valid far-side receiver.

Results are written under `outputs/canopy_physics/`: per-case maps, path/CIR exports, direct Sionna interaction/object sequences, material/solver metadata, and config snapshots; plus `comparison/summary.csv`, `representative_receivers.csv`, difference arrays, figures, `analysis.json`, and a generated `report.md`. Diagnostics are under `diagnostics/`.

The transparent control uses epsilon_r=1 and conductivity=0, matched to free space; it is a solver control, not vegetation. Weak-loss uses epsilon_r=2 and conductivity=0.01 S/m, also an arbitrary placeholder. The current values are epsilon_r=8, conductivity=0.25 S/m, and Sionna RadioMaterial thickness=0.8 m; scattering coefficient and XPD are 0. The current solver enables refraction, so transmission is permitted, but this finite-sample experiment found no RX_C path traversing the current canopy at the chosen settings. No material here is validated.

The canopy meshes are closed boxes. Sionna's material thickness models a plane slab at each intersected surface; this does not make a closed box a validated volumetric plant model. The study is useful for identifying implementation sensitivity and explaining this demo's behavior, not for predicting crop or greenhouse attenuation. See `outputs/canopy_physics/report.md` for measured results and the run-specific conclusion.

The expanded diagnosis, including direct TX/RX-to-canopy intersections, exact transparent-control map statistics, sensitivity reruns, isolated slab results, assumptions, and the recommended next representation, is saved in `CANOPY_PHYSICS_FINDINGS.md`. These results use software-demo inputs. No material value or measurement is taken from the papers.

## Three-dimensional digital twin

Generate all data used by the viewer, build its local JavaScript bundle, and open it:

```powershell
.\.venv\Scripts\python.exe run.py all
.\.venv\Scripts\python.exe run.py cea
.\.venv\Scripts\python.exe run.py canopy-physics
.\.venv\Scripts\python.exe run.py vertical-farm
npm.cmd --prefix ../viewer install
npm.cmd --prefix ../viewer run build
.\.venv\Scripts\python.exe run.py view
```

The simulation commands run Sionna and create the saved geometry, paths, and radio maps. Run `vertical-farm` to generate the featured vertical-farm scenes; it does not rerun the older demos. The last two frontend commands are needed after a fresh checkout or when changing the Three.js UI; Three.js and Vite are installed locally and the browser does not load a CDN. Keep the `run.py view` terminal open while using the page and press **Ctrl+C** there to stop it. The server binds to `127.0.0.1` only.

With vertical-farm outputs present the viewer opens on the RF plant-proxy rack; otherwise it falls back to the current-canopy scene. The scenario selector holds the empty/proxy/dense vertical-farm cases and the legacy empty, transparent, weak-loss, current, narrow, and wide cases. **Layers** and **Inspector** open or close the side panels; drag a panel's inner edge (the thin grip next to the 3D scene) to resize it, drag it past the edge to close it, or flick it open again. The inspector reports the selected TX/RX, geometry, map, or returned path. The camera selector has isometric, front, side, top, shelf close-up, fit, and TX views. Enable **Show returned paths** to draw exported Sionna path vertices; use the receiver and display selectors to inspect one, five, or all saved paths. Map opacity, map level or height, labels, diagnostics, and capture controls are in the same view. The interface follows the DRAMCO web style (`DRAMCO.md`): dark only, monochrome controls, colour reserved for data.

Detailed vertical-farm plants are instanced Three.js geometry only and remain excluded from Sionna. Sionna uses the configured enclosure, rack/tray/equipment objects, and separate `rf_plant_zone` boxes shown by **RF plant zones**; the drawn plants stay within those boxes. Legacy greenhouse scenarios continue to use their configured shell, frame, and rectangular canopy proxies. The report and inspector label these different meanings. The viewer visualizes saved runs and does not run new RF calculations when a scenario is selected. None of the current inputs or outputs are literature data or greenhouse measurements.

## Public website (read-only)

`python run.py publish` writes the viewer and the current results to `outputs/site/` (ignored by git). Build the viewer first with `npm --prefix ../viewer run build`. The folder is a plain static site, with no Python server needed: upload its contents, including `.htaccess`, to any web host (one.com, GitHub Pages, a university server), at the root or in a subfolder. It is the same viewer, marked `data-site="static"`. It reads `data/viewer_scene.json` and one `data/runs/<import>.json` per HOUSIONNA run, shows a research-demo note, and hides the import, rerun, compare and simulation controls. `--batch <id>` (repeatable) publishes only those batches, and `--no-single-runs` leaves out runs that are not part of a batch. Numbers are written with six significant digits, which makes run files about a third smaller. Publishing refuses to write data that contains a local file path, and leaves out source maps. The `.htaccess` turns on compression on Apache hosts, so a 12 MB run downloads as about 1.5 MB. To update the site, publish again and re-upload the folder.

**GitHub Pages.** The site is served from the `gh-pages` branch at https://archigrad.github.io/HOUSIONNA/ (Settings → Pages → Deploy from a branch → `gh-pages`, `/ (root)`; set once by a repository admin). The branch holds only the latest site, as a single commit, so its history does not grow. A `.nojekyll` file makes Pages serve the files as they are. Pages allows 1 GB per site and 100 MB per file; one batch with radio maps is about 350 MB, so publish one or two batches with `--no-single-runs`. To publish, from `toolkit/` (wait for "Published … to …" before the second step):

```powershell
.\.venv\Scripts\python.exe run.py publish --batch <batch id> --no-single-runs
Set-Location outputs\site
if (Test-Path .housionna-site) { git init -b gh-pages; git add -A; git commit -m "Publish viewer"; git push --force https://github.com/archiGrad/HOUSIONNA.git gh-pages } else { "Not in the site folder: nothing done" }
Set-Location ..\..
```

The `Test-Path` check matters: if the publish failed and `outputs\site` does not exist, `git add -A` would otherwise run in the main repository.

The next publish deletes the folder, including this temporary repository, and the force push replaces the previous site.

## Running on the DGX Spark

The vertical-farm study runs on the lab's NVIDIA DGX Spark (GB10, ARM64, CUDA). The pinned `requirements.txt` installs there unchanged (sionna-rt 2.2.0, Mitsuba 3.9.1 and Dr.Jit 1.5.0 have ARM64 Linux wheels), and Mitsuba's `cuda_ad_*` variants are available. No LLVM setup is needed on Linux. Over SSH (VPN required), from a checkout of this repository:

```bash
cd HOUSIONNA/toolkit
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -c "import mitsuba as mi; print(mi.variants())"   # should list cuda_ad_mono_polarized
SIONNA_RT_BACKEND=cuda python run.py basic                # fails loudly if the GPU backend does not work
python run.py vertical-farm --profile spark
```

Run long jobs inside `tmux` so they survive a dropped connection, and copy results back to the workstation with `scp -r <user>@<spark-host>:~/HOUSIONNA/toolkit/outputs/vertical_farm toolkit/outputs/` before opening the viewer locally. The viewer itself stays on the workstation. `scripts/vertical_farm_convergence.py` repeats the farm study across sample counts and seeds (`--diffraction`, `--diffuse` and `--canopy-scattering` test other physics settings); with diffuse scattering on, its per-run `paths.json` files reach about 1 GB each at 10000x samples, so delete them once `summary.json` is written. Sending jobs to the Spark directly from Houdini or the viewer is not set up yet.

## HOUSIONNA runs and live Sionna

The viewer can import completed Houdini/Sionna exports without rerunning Sionna. Configure the source folder in `config/housionna.yaml` (relative paths resolve from this project directory); the default points to the sibling HOUSIONNA checkout. A different folder containing valid run exports can be set there or with the `HOUSIONNA_RUNS_DIRECTORY` environment variable.

Build and open the existing viewer:

```powershell
npm.cmd --prefix ../viewer run build
.\.venv\Scripts\python.exe run.py view
```

In the viewer choose **Scene source → HOUSIONNA**, then **Import latest Houdini run**, or **Import all new runs** for a batch (each run is imported once, then the scene data is rebuilt once). **← Older / Newer →** steps through imported runs in export order and lists what changed since the previous run; **Across runs of this scene** charts a value (median map, mean link gain, reached cells, path count) along run order or any quantity that varies across the series. The scene file lists each imported run as a small cached summary (`viewer_summary.json` next to its import); the viewer fetches a run's full data from `/api/housionna/imports/<id>/viewer` when it is selected and keeps at most four runs loaded. Batch exports from Houdini (`houdini_files/sionna/batches/<batch>/wiNNN/`, next to `batch.json` and `status.json`; set `housionna.batches_directory` to use another folder) are discovered alongside the plain runs, with one run per work item named `<batch>.wiNNN`. On import, the run's `<hip>_meta.json` adds the wedged `TOPS_*` values, the batch ID and the Houdini version and commit. Only the `.hipnc` file name is kept, never its local path. For a batch run, the chart becomes **Across this batch**: the x axis can be any `TOPS_` value that varies in the batch (default: the one in `wedgeattribs`), the other varying values become filters set to the current run's values, and a line shows how many of the batch's work items are imported. The run list groups runs by batch, and **← Older / Newer →** steps within the current batch. The first time discovery sees a new batch, it validates every work item once, which takes about a minute for 280. The results are saved in `outputs/integrations/housionna/discovery_cache.json`, so later page loads and server restarts take under a second. Previously imported runs and transmitters can be selected without reloading the page. **Reload selected** revalidates the current export. The **Displayed RF result** selector switches between original HOUSIONNA output and the latest Sionna rerun. The comparison summary reports per-RX path counts and coherent-gain deltas.

The live path API reloads the original Mitsuba XML and its referenced source PLY files in an isolated worker process. Houdini is needed only when geometry, devices, or materials change. Changing frequency, TX pose, selected RXs, samples, or supported solver switches runs Sionna against the existing export. Every run is saved separately under `outputs/live/housionna-reruns/<run-id>/`; the source HOUSIONNA folder is read-only to this application.

Select **RECALCULATE RADIO MAP** to calculate only the selected TX on the source triangular measurement surface. A prior path run is not required; **RUN SIONNA RT** updates paths and RX metrics separately. The map quality tiers remain Low: 100,000 samples/TX, Medium: 500,000, and High: 2,000,000. Results contain face values and provenance; the viewer reuses its loaded triangle geometry and colour buffers. New maps are saved under `outputs/live/housionna-maps/<run-id>/`; null values remain missing/unestimated measurements. The legend records the map's frequency, TX pose, depth and valid triangles. **Rerun − original difference** requires matching frequency, quantity and verified triangle alignment and uses jointly valid values only.

The local API is `POST /api/housionna/simulate`, `POST /api/housionna/radio-map`, `GET /api/housionna/simulations/<job-id>/status`, `GET /api/housionna/simulations/<job-id>`, and `GET /api/housionna/simulations/latest?source_run_id=…&import_id=…&transmitter=…`. The viewer restores saved paths and the latest map independently after a viewer or server restart without rerunning Sionna. Each map displays its own inputs; differing path inputs remain stale. It accepts one to eight RXs, 100 MHz to 6 GHz, path depth 1 to 5, and at most 2,000,000 path samples per source. A single isolated worker runs at a time; failures retain a private traceback under `outputs/live/.housionna-jobs/`. The viewer server binds to `127.0.0.1`.

Earlier workstation reruns used `llvm_ad_mono_polarized` (CPU). A path worker run on `20261007_200100Z`, `tx_0` and `rx_0`–`rx_2` completed in 3.218–6.546 seconds of recorded Sionna run time; the Low map over 19,602 source triangles took 2.375–2.750 seconds. Those measurements predate the GPU driver update. Worker startup adds to browser wait. The local API uses JSON IDs and is suitable for CPU or GPU Python environments; remote deployment and tunnel forwarding are not configured here.

For this local sample, the baseline `tx_0` rerun reproduced 4/4, 3/3, and 3/3 paths for `rx_0`, `rx_1`, and `rx_2`; all three LOS values stayed false. Strongest-path gain changed by less than 0.00003 dB, matched delays by at most 0.0000036 ns, and interaction vertices by at most 0.000016 m. The separate deterministic position experiment moved TX by `[+0.5,+0.5,0]` m. Path counts stayed 4/3/3; strongest-path gain changed +6.426 dB, +5.807 dB, and -2.333 dB across the three RXs. Coherent aggregate link-gain deltas were +11.120 dB, +4.364 dB, and -9.772 dB. These are solver outputs for the exported sample, not calibrated coverage predictions. The original HOUSIONNA run uses the CUDA variant and its `PathSolver()` default nondeterministic mode; the local reruns use LLVM, fixed seed 42, and deterministic mode in the interactive worker, so the close baseline is a numerical check rather than a claim of bitwise identity.

See [docs/HOUSIONNA_INTEGRATION.md](docs/HOUSIONNA_INTEGRATION.md) for the export schema, coordinate convention, configuration, API, comparison rules, and limitations.

See [docs/HOUSIONNA_VISUAL_VALIDATION.md](docs/HOUSIONNA_VISUAL_VALIDATION.md) for the source-mesh inspection, rendering root cause, geometry/data comparisons, and viewer changes for run `20261007_195457Z`.

### Performance, cache and diagnostics

Exact RF requests can load saved results without launching Sionna. Keys include source hashes, TX pose/orientation/power, frequency, materials/measurement geometry, antenna, solver, sampling, seed and runtime. Path keys also include RX selection. The UI identifies cache hits and distinguishes total wait from historical solver time. **Calculation diagnostics** contains timing stages and failure details. Worker limits and bounded retry prevent a crashed calculation from remaining "running" indefinitely; previous results are retained. Refresh reconnects to an active job on the same server and restores completed results.

The idle Three.js scene renders on change. Radio-map updates reuse buffers; camera/layer changes do not run RF calculations. TX yaw uses Sionna's Z-axis angle, the first component of `[alpha,beta,gamma]`.

On the controlled 162-triangle CPU test, a fresh Low request took 2.73 s; exact reuse took 0.03 s in the backend. The 19,602-triangle/102-TX dataset completed Low/Medium/High tests for one selected TX. Native Windows RT startup can still vary or fail, so these timings do not guarantee uncached browser latency. After the MX450 driver update, a matched Low run selected `cuda_ad_mono_polarized` automatically and completed in 7.33 s wall time (0.66 s solver); its map agreed with the CPU run over all 50 valid cells (maximum absolute difference 1.44e-5 dB). A separate fresh browser-triggered worker hit the 120 s startup limit, so that Windows issue remains intermittent. The first GPU run does **not** establish a speedup. The MX450 has 2 GB VRAM, shared with other applications. `SIONNA_RT_BACKEND` accepts `auto`, `llvm`, or `cuda`.

See [docs/PERFORMANCE_RELIABILITY.md](docs/PERFORMANCE_RELIABILITY.md) for measured before/after results, browser evidence, sampling statistics, cache rules, diagnostics, timeouts and remaining limitations. Tests: `.\.venv\Scripts\python.exe -m unittest discover -s tests -v` and `node scripts/test_rf_inputs.mjs`.

## Application engine and reference cases

These commands work on imported HOUSIONNA runs (use **Import all** in the viewer first). Application profiles are in `config/applications.yaml`. Values marked EXAMPLE there, such as the BLE and LoRa sensitivities, are placeholders until measured device data replaces them.

The harvester is one of the named entries in the `harvesters` section; `apps` and `maps` take `--harvester <name>` and then add the name to their output folder or file names. The default `cappelle2025_chain` is the measured complete device (`data/devices/cappelle2025/`). The `rectifier_bound_915`, `_868` and `_2450` entries are upper bounds: the AEM30940 kit rectifiers alone at their best load voltage, from the AMBIENT-6G dataset (`python scripts/import_ambient6g.py`, see `data/devices/ambient6g/`).

- `python run.py apps --batch <batch>` (or `--import <id>`, or no option for every run) computes the following and writes them to `outputs/applications/<scope>/`:
  - received power, link margin, best server, coverage and the worst case over a batch;
  - for RF wireless power transfer with a total power budget: the incident power for four strategies (best single TX; equal split without phase alignment; equal split in phase without channel knowledge; coherent maximum-ratio transmission), the harvested DC power and the shortest sustainable reporting interval.
- `python run.py placement --run <run>` treats every transmitter of a run as a candidate position. For each number of transmitters k it finds the subset that is best for the worst receiver, exhaustively for up to 16 candidates and greedy beyond. Output goes to `outputs/placement/<run>/`.
- `python run.py maps --run <run> [--placement-k K | --tx NAME ...]` computes the same metrics per triangle of the radio-map surface and reports the share of the area where a node can run. Maps carry no phase, so coherent MRT appears there as its local average P Σ g_i. Output goes to `outputs/applications/maps/<run>/`.
- `python scripts/material_table.py` evaluates every material of `houdini_files/sionna/materials.json` with the exporter's own models at 868 MHz, 915 MHz, 2.437 GHz, 3.5 GHz and 5.18 GHz and writes the loss of one surface crossing to `outputs/validation/material_losses.csv`.
- `python scripts/harvester_figure.py` plots the efficiency of the harvester models against incident power (`outputs/validation/harvester_models.pdf`).
- `python scripts/reference_cases.py` compares Sionna RT against analytical cases and writes `outputs/validation/`:
  - free space;
  - a single slab (ITU-R P.2040);
  - a closed block, whose thickness Sionna applies at every surface it crosses;
  - thin objects, where paths with a segment shorter than 1 cm are discarded (`MIN_SEGMENT_LENGTH` in Sionna RT 2.2).

Coherent quantities use h = Σ a_k exp(-j2π f_c τ_k). The exported coefficients are Sionna's `Paths.a`, which do not include the propagation phase; `Paths.cir()` returns them with the phase applied.

## Output layout

Each run writes under `outputs/`:

- `scene.png`: room geometry and radio-device positions.
- `cir.csv`, `paths.json`, `cir.png`: valid path delays and complex CIR coefficient magnitudes.
- `radio_map.npy`: raw linear path gain, with axes `[transmitter, y_cell, x_cell]`.
- `radio_map_cell_centers.npy`: cell-center coordinates in world coordinates.
- `radio_map_db.npy`, `radio_map.png`: display-only dB conversion.
- `radio_map_metadata.json`, `metadata.json`: grid, units, solver, scene, coordinate, and software details.
- `comparison/radio_map_delta_db.npy` and `radio_map_comparison.png`: moved minus baseline path-gain map.

The small checks in `src/demos/poc.py` assert that the solver produced valid paths, a finite nonempty path-gain map, three receivers, and matching comparison grids.

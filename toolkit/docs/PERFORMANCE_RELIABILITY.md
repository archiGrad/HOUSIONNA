# Radio-map performance and reliability

## Scope and evidence

This refinement changes only `sionna-cea-poc`. HOUSIONNA exports and the repository
remain unchanged. There is no Git metadata in this workspace, so the pre-edit
sources, tests, documentation, bundle and failed job record were preserved in
`outputs/performance_refinement/20261008_110959Z/baseline.zip`, with SHA256 hashes
in `baseline_manifest.json`. Scientific outputs were retained.

CPU measurements below use Windows, Sionna RT 2.2.0, Mitsuba 3.9.1 and Dr.Jit
1.5.0. Browser passes use an isolated local Chrome profile and SwiftShader; these
are software-rendered checks, not a GPU rendering benchmark.

## MX450 CUDA check (2026-10-09)

After the driver update, `nvidia-smi` reported an MX450, driver 617.14 and CUDA
UMD 13.4. The earlier 457.20 driver was incompatible with this Dr.Jit CUDA backend.
The MX450's Turing compute capability 7.5 meets Dr.Jit's current minimum; its CUDA
backend also requires driver R535 or newer. NVIDIA's 560.70 release lists MX450
notebooks and advises checking the laptop OEM's certified driver. Sources:
[Dr.Jit requirements](https://drjit.readthedocs.io/en/stable/changelog.html),
[NVIDIA supported products and notebook guidance](https://www.nvidia.com/Download/driverResults.aspx/230094/en-us/%EF%BF%BC%EF%BF%BCtheres/).

Both `SIONNA_RT_BACKEND=auto` and `cuda` selected `cuda_ad_mono_polarized` in the
project environment. A Dr.Jit CUDA JIT smoke returned 30. More importantly, an
actual Low Sionna radio-map worker completed and recorded CUDA variant
`cuda_ad_mono_polarized`, driver 13040 (CUDA 13.4), Low quality and 100,000 samples
per TX. Job `0cae6a5db8af4130b1198036ce775f3a` took 7.33 s wall time; worker profile
records 0.66 s in the solver, 3.72 s in RT initialization, and 5.42 s total in the
simulation function. Fifty of 162 measurement triangles were valid.

Compared with the saved CPU Low result using identical source, TX, seed and solver
settings, both runs had the same missing mask and 50 valid cells. Maximum absolute
cell difference was `1.44e-5 dB`, RMSE `2.52e-6 dB`. This validates that the GPU
calculation ran and agrees numerically on this small case. It does **not** show a
speedup: the prior CPU wall time was 2.73 s, while this first GPU worker took 7.33 s,
in part because GPU/RT initialization and kernel compilation are costly. Larger
maps may benefit, but have not yet been benchmarked on the MX450. It has 2 GB VRAM;
other applications were already using about 860 MiB during the check, so memory
pressure may constrain large/high-sample jobs. Start with Low and monitor GPU memory.

An additional automated viewer check requested a new, uncached TX pose. That worker
hit the 120-second safety limit and was terminated; its log remained empty. The
saved CUDA calculation is complete and readable. CUDA execution is verified, while
fresh browser-triggered worker startup remains intermittent on this Windows host;
the driver update did not fix that separate startup reliability issue.

## Why the button kept loading

The reported job `21c8eee8fdea48dabdee03864c9c592d` stopped with a native LLVM
`Failed to materialize symbols` error. The supervisor recorded a failure in memory,
then status polling loaded an older `running` file and overwrote that failure.
The UI could therefore poll forever after the worker had exited. Its status was
recovered, preserving the original record in the baseline archive.

Other measured costs were repeated normalized-import reads, RT/library startup,
uncompressed scene transfer, complete scene reconstruction after a map result,
and continuous rendering of an idle scene. Under the software browser, continuous
rendering coincided with very large API/startup delays. Rendering on change brought
a successful initial load from about 10.6 s to 1.6 s in one measured pass.
This comparison is environment-specific and does not establish a hardware GPU speedup.

Windows verification also exposed transient `PermissionError` during atomic
status-file replacement while another process held a read handle. Writes now use
unique temporary files and bounded retry; readers always see a complete record.

## Changes

- Terminal failures cannot regress to `running`. Status writes survive transient
  Windows handle locks. Failed/partial jobs are excluded from latest-result and
  exact-cache lookup. The supervisor saves execution provenance before publishing
  completion, avoiding a status/result race.
- One selected TX per map; path calculation is independent. A map run updates
  map values, pose and its own metadata. Old paths/RX metrics retain their original
  inputs and are marked stale when necessary.
- Serial, isolated RT processes are retained. Native LLVM symbol failures and
  Windows access-violation/heap-corruption exits get at most one fresh-process
  retry, only before an output folder exists. Seed and RF settings remain identical.
  Persistent scene/Dr.Jit objects are not shared across Python threads or processes.
  The observed native failures do not justify a persistent-worker correctness claim.
- Worker time limits: paths 180 s, Low 120 s, Medium 300 s, High 600 s, configured
  in `config/housionna.yaml`. Termination targets the tracked process and its owned
  descendants, including the real Python child of a Windows venv launcher.
  Process teardown can add a few seconds to a limit.
- Bounded normalized-import reuse (two documents), catalog summaries (16),
  validation summaries (128), job records (32), latest viewer snapshots (12),
  and compressed static assets (four). Disk results are never evicted.
- The worker receives only its selected TX's normalized record and required
  measurement geometry, rather than rereading all 102 TX maps.
- Source hashes are checked at submission and before/after map calculation.
  A changed export requires reimport; its result cannot enter the old RF cache.
- A lightweight RT loader avoids importing plotting libraries. `SIONNA_RT_BACKEND`
  supports `auto`, `llvm`, or `cuda`. Auto selects LLVM on Windows when the detected
  CUDA driver is known to be incompatible; Dr.Jit may still print its driver warning.
- Compact JSON and gzip replace unnecessary transfer overhead. Initial scene
  loading still includes all saved TX data; subsequent RF results contain selected
  values/metadata and reference already loaded meshes. A separate binary protocol
  was not needed for these measured payloads.
- Measurement overlays use one mesh per surface with stable position buffers and
  dynamic RGBA colours. Missing values have zero alpha. Changes to values/TX/difference
  display reuse buffers; no normal computation or full scene rebuild is needed.
  Geometry resources are disposed when switching to different assets.
- TX switching updates the inspector/diagnostics as well as the scene. Detached
  CSS2D marker labels are removed during disposal. Delayed initial result restoration
  cannot overwrite a result already installed by a user calculation.
- An idle scene no longer renders continuously. Camera damping, pulse animation,
  interaction, resize and scene updates still request frames.
- Fetches time out after 20 s. Polling reports actual stages and worker elapsed
  time. Frame waits are bounded so background tabs cannot strand disabled controls.
  Refresh reconnects to an active job on the same server, or loads saved results.
- The UI shows total time, historical solver time, cache hit, actual samples,
  valid/total triangles, frequency, TX position and depth. Detailed client/worker
  timings and errors are available under **Calculation diagnostics**.
- TX yaw now edits Sionna's first angle, alpha about Z. The installed SDK's
  `utils/geometry.py::rotation_matrix` defines orientation as rotations about
  `(Z,Y,X)`. Exported orientation vectors are preserved; this fixes the editable
  yaw control and marker rather than rewriting HOUSIONNA data.

## Timings and their definitions

`profile.json` and `metadata.json.profile.stages_seconds` record source JSON,
selected import JSON, source checks, RT initialization, scene XML/PLY/material
loading, devices/arrays, measurement PLY, triangle alignment, solver (including
`dr.eval`/`dr.sync_thread`), extraction, normalization, comparison, serialization,
file writes, process startup and Python imports. XML scene geometry and material
construction happen together inside `rt.load_scene`; separate exclusive timings
for those internal operations would be misleading.

`execution.json.worker_wall_seconds` includes process lifetime and retries;
function totals are narrower. Previous `duration_seconds` values included scene
setup and conversion and must not be described as pure solver time.
HTTP `Server-Timing` reports backend/serialization work. Client timings split
preparation, submission roundtrip, waiting, response headers/download, JSON parse,
visualization update, and click-to-frame duration. Browser frame confirmation falls
back after 250 ms in a suspended tab; such a background measurement is not proof
of an actually visible frame. Network and backend durations overlap and should
not be added as independent measurements.

Raw evidence is under `outputs/performance_refinement/20261008_110959Z/`:
`baseline_runs.json`, `benchmark-after.json`, `benchmark-final.json`,
`benchmark-cpu-selection.json`, `benchmark-large.json`, `benchmark-large-retry.json`,
and browser reports/screenshots. HTTP and client records are also saved as JSONL
under `outputs/performance_refinement/`.

### Backend measurements

The equivalent small-scene request uses `20261007_194013Z`, `tx_0`, position
`[-3.32,-3.327,1.532]`, 3.5 GHz, depth 3, LOS/specular/refraction enabled,
100k map samples, seed 42, and 162 measurement triangles.
"Fresh" means a fresh process; OS and Dr.Jit disk caches were not cleared.

| Case | Before, seconds | After, seconds | Actual solver, after |
| --- | ---: | ---: | ---: |
| Fresh Low, equivalent inputs | 4.347 | 2.735 | 0.027 |
| Exact repeated Low | 3.395, recalculated | 0.030, cached | no new solver |
| Low, TX moved +0.2 m in X | not measured | 2.488 | 0.035 |
| Medium, seeds 42 / 43 | not measured | 2.505 / 2.460 | 0.082 / 0.072 |
| High, seeds 42 / 43 | not measured | 3.155 / 2.844 | 0.353 / 0.259 |

Small-scene fresh Low initialization was 1.811 s; process startup 0.126 s,
Python imports 0.335 s, selected-import read 0.010 s, scene loading 0.034 s,
measurement loading 0.004 s, serialization 0.0002 s and main file writes 0.004 s.
Startup dominates this request. These individual runs are measurements, not a
statistically controlled speedup study.

The 102-TX export `20261007_195457Z` has 19,602 measurement triangles per TX.
Only `tx_0` was recalculated:

| Case | Full backend wall, seconds | Solver, seconds | Valid triangles |
| --- | ---: | ---: | ---: |
| Fresh Low, seed 42 | 10.887 | 0.150 | 3,413 |
| Low, moved TX | 6.103 | 0.106 | 3,533 |
| Exact cached Low | 0.186 | no new solver | 3,413 |
| Medium, seed 42 / 43 | 5.119 / 5.396 | 0.146 / 0.136 | 4,549 / 4,553 |
| High, seed 42 / 43 | 5.364 / 5.160 | 0.653 / 0.410 | 4,717 / 4,734 |

An earlier large-scene series had native heap-corruption exits; the subsequent
series completed all eight requests. Native Windows failures remain a limitation.

### Browser measurements and limits

A successful software-browser pass loaded the full combined scene in 1.577 s and
showed a cached map in 2.345 s (27.1 ms update, 0.3 ms JSON parse). A later pass
measured 0.392 s from the application's click handler to its completion frame,
2.1 ms map update and 0.2 ms parse; the automation's click/wait duration was 0.670 s.
Those cache hits used their historical solver metadata and did not start a new solver.
The combined scene transferred about 5 MB compressed; a selected small map result
was about 3.3 KB including headers in that pass. Geometry was not retransmitted.

Three round trips between imported runs plus selection in the 102-TX export took
0.219, 1.276 and 1.839 s. JavaScript heap at the end was 37.4 MB used / 52.0 MB
allocated. This is a snapshot after three switches, not a leak-proofing claim.
Camera and map-layer changes produced no RF POST requests.

Fresh native workers under the browser also showed large startup variance:
one completed in 57.9 s (21.4 s Python imports and 31.7 s RT initialization);
another reached the safety limit. Therefore **2.7 s is not a guarantee of an
uncached browser calculation**. The root cause of every Windows startup stall has
not been established. Native failures, timeouts and transient file locks were
exercised, with earlier maps retained and controls recovered. Final browser-release
artifacts include an automation-protocol timeout and should not be counted as a
successful regression. `browser-verified` completed the scene-switching/recovery
pass: its modified-TX worker reached 120 s and was terminated in 120.9 s; the UI
retained the previous map, recovered its controls, and restored completed data on
refresh. Its single console error records that actual worker timeout. Its cached
click also took 11.0 s inside the app (9.8 s submission roundtrip), showing host
variability affects API work as well as native startup.

`browser-visual` passed with zero JavaScript/console errors, tested cached maps,
difference display, completed refresh, 102-TX selection, and all three built-in farm
scenes. No inspection action submitted RF work. The app measured 1.613 s cached
click-to-frame, 3.7 ms map update, and 0.4 ms parsing; the automation measured 2.442 s.
Heap after both imported and built-in scene changes was 61.2 MB used / 128.7 MB
allocated. A final pass additionally asserts selected-TX inspector and marker
consistency after the visual audit found and fixed stale labels.

`browser-visual-final` passed those assertions with zero JavaScript/console errors:
the 102-TX run showed exactly the selected `tx_101` marker and matching inspector,
completed refresh and difference display worked, and saved empty/proxy/dense farm
scenes rendered. The app's cached click-to-frame was 0.908 s (18.3 ms map update,
0.2 ms parse); automation measured 1.246 s. Initial scene load was 4.590 s. Heap
after the full inspection sequence was 32.6 MB used / 109.3 MB allocated. These
snapshots demonstrate cleanup behavior, not a long-duration memory stability test.

Regression checks passed: 31 Python tests (43.0 s), six frontend RF assertions,
and the production frontend build. The build retains Vite's warning about the
approximately 698 KB bundled JavaScript chunk; gzip is about 179 KB. The 2D and 3D
pages both return HTTP 200. Saved built-in farm scenes were rendered in the browser;
their native solver was not freshly rerun during this refinement.
The final focused performance suite also passed independently: 19 tests in 1.85 s.
Active-job refresh reconnection is implemented but was not exercised as a separate
real-worker browser case; completed-result refresh and worker-timeout recovery were.

## Scientific checks and sampling

No sample preset, interaction flag, depth, source geometry, material, coordinate
conversion, quantity or random seed was reduced to improve speed. Low / Medium /
High remain **100k / 500k / 2M samples per selected TX**. Source measurement vertices
and exact face indices are checked against the imported asset; a difference map
requires matching quantity, frequency and geometry/order. Comparisons use jointly
valid cells only. Null is missing/unestimated data, not a physical -999 dB value
or proof of zero coverage. RF values remain double precision; Float32/RGBA buffers
are display resources only.

Equivalent pre/post Low output had the same missing mask and 50 jointly valid
triangles, RMS difference `1.07e-7 dB`, maximum difference `3.20e-7 dB`.
This is numerical agreement for one controlled request, not measurement validation.

For the 19,602-triangle scene at seed 42, Low-to-Medium RMS difference was 5.952 dB
over 3,400 jointly valid cells, median absolute difference 1.990 dB and 99th
percentile 25.983 dB. Medium-to-High RMS was 1.696 dB over 4,512 cells, median 0.660 dB,
99th percentile 5.008 dB, maximum 30.202 dB. Missing fractions were 82.6%, 76.8%,
75.9% respectively. Seed-to-seed RMS was 0.497 / 0.275 / 0.489 dB for Low/Medium/High;
their missing masks also differed. Two seeds and these tail differences do not
establish convergence, even where means are close. Original HOUSIONNA data are
comparison data, not ground truth. Medium is a useful additional numerical check;
High still needs more seeds and inspection of weak cells for research conclusions.

Path coefficient magnitude, coherent/incoherent link gain, map power-ratio gain
and received power/RSS retain their separate labels. Maps use
`10 log10(path_gain)`; RSS additionally requires appropriate TX/antenna assumptions.
Vegetation RF proxy values remain explicitly uncalibrated placeholders.

## Run, diagnose, repeat

From the project directory in PowerShell:

```powershell
npm.cmd --prefix ../viewer run build
.\.venv\Scripts\python.exe run.py view
```

Choose **Scene source: HOUSIONNA**, an imported run and TX. Edit RF fields, select
Low/Medium/High under **Solver and map settings**, and press **RECALCULATE RADIO MAP**.
No prior path run is required. **RUN SIONNA RT** calculates paths/RX metrics separately.
Repeat an identical request to see **Loaded cached simulation**. Changing pose,
orientation, frequency, materials/source bytes, solver, samples, seed or runtime
changes the RF cache key. RX selection and path sampling are excluded from map
keys because they do not affect the selected-TX map. Path keys include them.

The new cache identifies exact RF requests plus full source hashes, fixed antenna
configuration, TX power, package/LLVM/CUDA-driver identity and backend preference.
Older outputs remain readable but are not declared exact cache hits without the
new execution record. Different seeds create distinct records. Cached solver times
describe the original calculation, not the cache lookup.

Inspect **Calculation diagnostics** or
`GET /api/housionna/simulations/<job-id>/diagnostics`. Private logs/specs/status are
under `outputs/live/.housionna-jobs/<job-id>/`; results under
`outputs/live/housionna-maps/<job-id>/` and `housionna-reruns/<job-id>/`.
An HTTP timeout does not cancel a worker: refresh reconnects on the same running
server. After a server restart, completed results are restored; active orphan
workers are not reattached by the new server. Keep the terminal running during a job.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node scripts/test_rf_inputs.mjs
.\.venv\Scripts\python.exe scripts/benchmark_housionna.py --force-recompute --timeout 60
# Supply another saved request.json with --request to benchmark another imported scene.
node scripts/browser_check.mjs http://127.0.0.1:8765/digital-twin/ outputs/performance_refinement/manual-browser regression
```

The browser script uses installed Chrome and a disposable system-temp profile,
never the user's signed-in profile. It needs permission for Chrome renderer/GPU
processes when run in a restricted execution environment. It records exceptions,
network sizes, screenshots and heap metrics. Saved reports distinguish real native
worker failure recovery from a successful numerical calculation.

For future GPU work, create an environment appropriate to the remote host,
install supported pinned RT/Mitsuba/Dr.Jit packages and a compatible NVIDIA driver,
check `mi.variant()` reports CUDA, rerun controlled seed/geometry checks, and forward
only the local viewer port through the authenticated tunnel. Set
`SIONNA_RT_BACKEND=cuda` only in that compatible environment. This task did not
deploy DGX Spark, move source files, or measure GPU speedups.

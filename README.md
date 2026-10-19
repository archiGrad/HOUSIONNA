# Houdini to Sionna RT

Run [Sionna RT](https://nvlabs.github.io/sionna/rt/) radio propagation simulations from a Houdini scene, compute them on the Techtile Spark GPU server, and bring the results back into Houdini as geometry with attributes.

Houdini is the procedural generator: geometry, materials and devices are built with nodes, so one network can produce an unlimited number of scene variations, and each variation can be simulated and inspected within seconds.

![Paths and radio map in Houdini](docs/prev.png)
![Paths and radio map in Houdini](docs/2preview.png)

## What it is

A set of Python functions called from buttons on one Houdini node, plus a solver script that runs in a separate Python environment, either on the same machine or on a remote GPU server over SSH. Houdini handles geometry, device placement and visualisation. Sionna RT handles the physics on the GPU.

| Button | Function | Does |
|---|---|---|
| check_spark_health | `on_check` | Reports the compute target: reachable, Sionna version, Mitsuba variant, GPU, other GPU users |
| validate_geometry | `on_validate` | Checks the scene: triangles only, names and materials set, sane units, devices present |
| export_to_files | `on_export` | Writes meshes, scene XML, materials and devices into a new timestamped run folder on this machine |
| previz_sionna_scene | `on_previz` | Copies the run folder to the target, has Sionna load it, and shows in Houdini what Sionna actually holds |
| copy_to_spark_and_solve | `on_solve` | Copies the run folder to the target, computes paths between every TX and RX and a radio map on every measurement surface, copies the results back |
| import_sionna_results | `on_import` | Loads paths, per-link results and radio maps into File SOPs |
| run | `on_run` | Validate, export, solve and import in one press; stops at the first step that fails |
| batch_export | `on_batch_export` | Exports every TOP work item from `batch_start` to `batch_end` into one batch folder |
| batch_solve | `on_batch_solve` | Sends the batch to the target and starts it there in the background; returns immediately |
| batch_status | `on_batch_status` | Progress of the running batch: solved, failed, current work item, time left |
| batch_fetch | `on_batch_fetch` | Copies the finished results of the batch back and converts them for the `sionna_batch_*` File SOPs, which show the result of the work item selected in the TOP network |

Export never contacts the server; previz, solve and the batch buttons except export do. The first six buttons are for testing one scene step by step; run does the same in one press.

## Folder structure

```
.
├── .venv/                      local Sionna RT environment (not committed)
├── requirements.txt
├── docs/preview.png
└── houdini_files/
    ├── <scene>.hip
    └── sionna/
        ├── sionna_sop.py       functions called by the buttons on the Houdini node
        ├── sionna_run.py       solver script, run by the target's Python
        ├── materials.json      custom material library
        ├── log.txt             log over all runs, same text as the terminal output
        ├── previz.bgeo.sc      latest results, read by File SOPs
        ├── paths.bgeo.sc
        ├── links.bgeo.sc
        ├── radiomap.bgeo.sc
        └── data/
            └── <YYYYMMDD_HHMMSSZ>/
                ├── scene.bgeo.sc         the input geometry as exported, with all attributes; stays on this machine
                ├── meshes/<name>.ply     binary PLY, one per object name
                ├── sionna_run.py         copy of the solver used for this run
                ├── <hip>_meta.json       git commit, uncommitted changes flag, Houdini version
                ├── <hip>_scene.xml
                ├── <hip>_materials.json  resolved permittivity and conductivity per object
                ├── <hip>_txrx.json
                ├── <hip>_measure.json
                ├── <hip>_settings.json
                ├── <hip>_dump.json
                ├── <hip>_result.npz      paths and links
                ├── <hip>_radiomap.npz
                ├── <hip>_log.txt         validate and export messages of this run
                ├── solver.log            full solver output of the last solve or previz
                ├── <hip>_previz.bgeo.sc
                └── paths.bgeo.sc, links.bgeo.sc, radiomap.bgeo.sc
        └── batches/
            └── <YYYYMMDD_HHMMSSZ>/
                ├── batch.json            TOP node, range, git commit, export status per work item
                ├── queue.json            work items sent with the last batch solve
                ├── status.json           progress, written by the solver
                ├── batch.log             solver output of all batch solves
                └── wi<index>/            one run folder per work item, as above, plus
                    ├── done.json         settings it was solved with
                    └── failed.json       error, if the solve failed
```

Every export creates a new run folder. Previz, solve and import always work on the latest one.

On a remote target the folders are mirrored to:

```
<remote_root>/
├── venv/
├── runs/<hip>/<stamp>/
└── batches/<hip>/<stamp>/
```

## Setup

Requires Houdini, and on the machine that computes: an NVIDIA GPU and Python 3.10 or later. Sionna RT is only needed on that machine, your own PC (local target) or a server (remote target).

```bash
python -m venv .venv
source .venv/bin/activate          # Linux; on Windows (Git Bash): .venv/Scripts/activate
pip install -r requirements.txt    # sionna-rt==2.2.0
```

In Houdini:

1. Add a Null SOP at the end of the scene network.
2. Add one Button parm per function, with this Python callback (change only the function name):

```python
exec(open(hou.expandString('$HIP/sionna/sionna_sop.py')).read()); on_validate()
```

The code is read from `sionna/sionna_sop.py` on every press, so the file in git is the only copy.

Start Houdini from a terminal. All feedback is printed there and appended to `sionna/log.txt`; there are no pop-ups.

## Compute target

A string parm `target` on the Null selects where the solver runs:

- `local` (or empty): the venv on this machine, at `$HIP/../.venv/bin/python3` (Windows: `$HIP/../.venv/Scripts/python.exe`). Override with a string parm `python_exe`.
- an SSH host alias, e.g. `spark`: a remote server. Override the remote folder with a string parm `remote_root` (default `~/Documents/HyROPA`).

To pick the target per machine, set the parm to `$SIONNA_TARGET` and define it in each machine's `houdini.env`, e.g. `SIONNA_TARGET = spark`.

**The Spark is only reachable through the VPN.** Start it before check, previz or solve, and keep that terminal open:

```bash
sudo openvpn --config <client>.ovpn
```

Without the VPN every remote action fails after about 10 s with `T001 ... Connection timed out`. Never commit the `.ovpn` file: it contains the VPN certificate and key.

Remote setup, once per server:

1. An alias in `~/.ssh/config`:
   ```
   Host spark
       HostName 192.108.2.65
       User dramco_spark
       IdentityFile ~/.ssh/<your key>
   ```
2. Key login, since Houdini cannot type a password: `ssh-copy-id -i ~/.ssh/<your key>.pub spark`. Never commit a private key.
3. On the server, a venv at `<remote_root>/venv` with `requirements.txt` installed. Without it, every remote action fails with `T002`.
4. `rsync` on both machines.

Each remote run checks that the server and venv exist and reads the GPU status, mirrors the run folder (without `.bgeo.sc` files) to the server, runs the solver there, and copies the results back. The solver refuses to run on a machine without a CUDA variant (`T003`).

## Batches

For many scene variations from a TOP network (e.g. a Wedge TOP), next to the Null:

1. Set the int parms `batch_start` and `batch_end` to a range of work item indices (both included; without the parms, all work items).
2. **batch_export**: for each work item in the range, selects it in the TOP network, so the SOP network cooks that variation, then validates and exports it to `batches/<stamp>/wi<index>/`. The wedge attributes of the work item are stored in its `<hip>_meta.json`. A work item that fails validation or does not cook is recorded in `batch.json` and skipped; the others continue. The selection is restored afterwards.
3. **batch_solve**: writes the current settings into every exported work item, sends the batch folder and starts one solver process on the target, which solves all work items one after the other in one Sionna session. The button returns at once; Houdini stays usable and the job keeps running if Houdini or the laptop is closed.
4. **batch_status**: prints progress while it runs.
5. **batch_fetch**: copies the results back, converts every new or changed result to `.bgeo.sc` in its `wi<index>` folder, and creates four File SOPs next to the Null: `sionna_batch_scene` (the geometry as exported for that work item), `sionna_batch_paths`, `sionna_batch_links`, `sionna_batch_radiomap`. Can be pressed while the batch is still running; press it again later for the rest.
6. Click a work item in the TOP network: the SOP network cooks that variation and the `sionna_batch_*` File SOPs load its exported geometry and results. `sionna_batch_scene` is what was simulated, also after the network has been changed since the export. Their file path is

   ```
   $HIP/sionna/batches/`chs("../<null>/batch")`/wi`padzero(3, @pdg_index)`/radiomap.bgeo.sc
   ```

   With no work item selected, or for a work item without result (failed, not solved or not fetched yet), they load nothing instead of giving an error.

The TOP node is the one with the display flag inside `../topnet1`; another can be set with a string parm `top_node`: a TOP network (its display node is used) or a TOP node, absolute or relative to the Null.

Add a string parm `batch` to the Null. Batch export writes the new batch name into it, and all batch buttons and the `sionna_batch_*` File SOPs use that batch. To go back to an older batch, type its folder name. Without the parm the buttons use the latest batch, and the File SOPs find nothing (`W009`).

Fetch makes the local batch folder a copy of the remote one: a result that no longer exists on the target (work item solved again and failed, or being solved) is removed locally too, with its `.bgeo.sc` files.

Pressing batch_solve again resumes: work items already solved with the same settings are skipped, failed ones are tried again. After a settings change all work items are solved again. A batch cannot be started twice at the same time (`B004`). A failed work item does not stop the batch; its error is in `failed.json`, `batch_status` and `batch.log`.

To stop a running batch: `ssh spark`, then `kill <pid>` with the pid printed by batch_solve (also in `batch.pid` in the remote batch folder).

## Scene: supported attributes

Everything Sionna receives comes from the attributes below. Any other attribute (`Cd`, `N`, `uv`, groups) is ignored.

### Geometry (primitive attributes, triangles only)

| Attribute | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Object name. One mesh and one Sionna object per value. Letters, digits, `_` and `-` only. |
| `material` | string | yes | An ITU material, a name from `materials.json`, or `measure` for a radio map surface |
| `thickness` | float | no | Slab thickness in metres used for reflection and transmission. 0 or absent: library default, else 0.1. Not the mesh thickness. |
| `scattering_coefficient` | float | no | 0 to 1. Share of reflected energy that is scattered diffusely. Only has an effect with `diffuse_reflection` on. 0 or absent: library default, else 0. |

All primitives with the same `name` must have the same material attributes (`V006`). Every surface is a slab of the given thickness, so a closed box is a hollow shell: a ray through it crosses two slabs.

### Devices (point attributes on loose points)

| Attribute | Type | Required | Meaning |
|---|---|---|---|
| `P` | vector | yes | Position |
| `role` | string | yes | `tx` or `rx` |
| `name` | string | yes | Unique name, carried through to all results |
| `orientation` | vector | no | Yaw, pitch, roll in radians, Sionna convention. No effect with the current isotropic antennas. |
| `velocity` | vector | no | m/s. Exported, but not yet passed to Sionna: no effect. |
| `power_dbm` | float | no | TX power. Passed to Sionna, but no current output depends on it: all results are path gain. |

### Measurement surfaces (radio maps)

Any triangulated mesh with `material = "measure"` and its own `name`. Each triangle is one cell of the radio map. Measurement surfaces are not part of the scene: they neither block nor reflect. Keep them off other surfaces, e.g. 1.5 m above a floor.

Solve computes paths when there is at least one RX, and a radio map when there is at least one measurement surface. Without either, validation fails (`V107`).

### Not settable per primitive

`xpd_coefficient`, and the model inputs `moisture`, `temperature_c` and `ionic_conductivity`, exist only per entry in `materials.json`. A moisture gradient over a canopy currently needs separate library entries (`leaf_70`, `leaf_90`, ...).

## Materials

### ITU materials (built into Sionna)

Permittivity and conductivity follow ITU-R P.2040: `er = a * f^b`, `sigma = c * f^d` with f in GHz. **Each material is only defined in the listed frequency range; outside it Sionna stops with an error.** Validation does not check this yet. Coefficients for the range that covers 0.1 to 10 GHz, from Sionna's `itu.py`:

| Material | Range (GHz) | a | b | c | d | 433 MHz | 868 MHz | 2.4 GHz | 3.5 GHz | 5 GHz |
|---|---|---|---|---|---|---|---|---|---|---|
| `vacuum` | 0.001–100 | 1.0 | 0 | 0 | 0 | yes | yes | yes | yes | yes |
| `wood` | 0.001–100 | 1.99 | 0 | 0.0047 | 1.0718 | yes | yes | yes | yes | yes |
| `glass` | 0.1–100 | 6.31 | 0 | 0.0036 | 1.3394 | yes | yes | yes | yes | yes |
| `concrete` | 1–100 | 5.24 | 0 | 0.0462 | 0.7822 | no | no | yes | yes | yes |
| `brick` | 1–40 | 3.91 | 0 | 0.0238 | 0.16 | no | no | yes | yes | yes |
| `plasterboard` | 1–100 | 2.73 | 0 | 0.0085 | 0.9395 | no | no | yes | yes | yes |
| `ceiling_board` | 1–100 | 1.48 | 0 | 0.0011 | 1.0750 | no | no | yes | yes | yes |
| `chipboard` | 1–100 | 2.58 | 0 | 0.0217 | 0.7800 | no | no | yes | yes | yes |
| `plywood` | 1–40 | 2.71 | 0 | 0.33 | 0 | no | no | yes | yes | yes |
| `marble` | 1–60 | 7.074 | 0 | 0.0055 | 0.9262 | no | no | yes | yes | yes |
| `vinyl_tile` | 1–40 | 3.62 | 0 | 0.0051 | 0.8422 | no | no | yes | yes | yes |
| `carpet_tile` | 1–40 | 2.08 | 0 | 0.0009 | 0.8200 | no | no | yes | yes | yes |
| `asphalt_concrete` | 1–40 | 4.83 | 0 | 0.0108 | 1.3969 | no | no | yes | yes | yes |
| `metal` | 1–100 | 1.0 | 0 | 1e7 | 0 | no | no | yes | yes | yes |
| `very_dry_ground` | 1–10 | 3.0 | 0 | 0.00015 | 2.52 | no | no | yes | yes | yes |
| `medium_dry_ground` | 1–10 | 15 | -0.1 | 0.035 | 1.63 | no | no | yes | yes | yes |
| `wet_ground` | 1–10 | 30 | -0.4 | 0.15 | 1.30 | no | no | yes | yes | yes |
| `floorboard` | 50–100 | 3.66 | 0 | 0.0044 | 1.3515 | no | no | no | no | no |
| `clear_acrylic` | 110–330 | 2.58 | 0 | 0.0001 | 1.6524 | no | no | no | no | no |

At 433 and 868 MHz only `vacuum`, `wood` and `glass` are usable. `vacuum` is in Sionna but not yet accepted by validation (`V007`).

### Library materials (`materials.json`)

| Kind | Fields | Permittivity and conductivity |
|---|---|---|
| `fixed` | `relative_permittivity` plus one of `conductivity`, `loss_tangent`, `loss_factor` | constant permittivity; loss converted to conductivity at the run frequency |
| `water` | `temperature_c`, `ionic_conductivity` | Debye model (Liebe, Hufford, Manabe 1991) plus ionic conductivity |
| `vegetation` | `moisture` (gravimetric, 0 to 1) | dual-dispersion model (Ulaby and El-Rayes 1987) |

Every entry also has a default `thickness`, a `source` and a `status`. Values are resolved at export for the current `frequency` and written to `<hip>_materials.json`. Changing the frequency requires a new export (`S008`). A material whose status is not `confirmed` raises warning `W005`.

Current entries:

| Material | Kind | Status |
|---|---|---|
| `polycarbonate` | fixed | permittivity from datasheets at 1 MHz only; no GHz value |
| `polyethylene_film` | fixed | permittivity confirmed, loss assumed zero |
| `polypropylene` | fixed | permittivity confirmed, loss assumed zero |
| `pvc` | fixed | permittivity confirmed, loss assumed zero |
| `water` | water | model equations match Liebe et al. 1991; not yet marked confirmed |
| `nutrient_solution` | water | as water; ionic conductivity from an assumed EC of 2.5 mS/cm |
| `leaf`, `stem` | vegetation | coefficients not yet checked against the paper |
| `fruit` | fixed | strawberry values used for tomato |
| `rockwool_wet` | fixed | placeholder, must be measured |

A value becomes `confirmed` only when it comes from a measurement or a source that states it for the frequency range in use, with the reference in `source`. Ways to get there, in order of strength:

1. Measure it: dielectric probe or free-space measurement with a VNA, or fit it from channel measurements (CELSA T3; Sionna is differentiable for this).
2. Peer-reviewed values at the right frequency: ITU-R P.2040 and P.527, Ulaby and El-Rayes 1987, Peng et al. 2013 (tomato), manufacturer data at GHz frequencies.
3. Datasheet values at 1 MHz (plastics) are not enough for 433 MHz to 5 GHz.

## Settings

Defaults, each overridable by a parm of the same name on the Null:

| Parm | Default | Meaning |
|---|---|---|
| `frequency` | 3.5e9 | Carrier frequency in Hz. Sets the wavelength and all material values. Changing it requires a new export. |
| `max_depth` | 3 | Maximum number of interactions per path (reflections, transmissions, scattering). Higher finds more paths and is slower. Passing through a closed box costs 2. |
| `samples` | 1000000 | Rays launched per TX when searching for paths. More rays miss fewer paths. |
| `max_paths_per_tx` | 100000 | Upper limit on paths kept per TX. Limits GPU memory. |
| `los` | on | Include the direct path |
| `specular_reflection` | on | Mirror-like reflections |
| `refraction` | on | Transmission through surfaces |
| `diffuse_reflection` | off | Diffuse scattering. Needs `scattering_coefficient` > 0 on materials. |
| `diffraction` | off | First-order edge diffraction (Sionna supports first order only) |
| `bandwidth` | 100e6 | Width in Hz of the per-link frequency response `cfr_db`, centred on `frequency` |
| `cfr_points` | 256 | Number of frequencies in `cfr_db`. 0 skips the frequency response; it is the largest part of the paths result. |
| `radiomap_samples` | 10000000 | Rays per TX for the radio map. More rays give less noise per cell. `radiomap_samples` × number of TX must stay below 4.29e9 (Sionna limit), otherwise solve stops with `S010`. |
| `target` | local | Where the solver runs: `local` or an SSH alias |
| `remote_root` | ~/Documents/HyROPA | Folder on the remote target that holds `venv/` and `runs/` |
| `timeout` | 1800 | Seconds before a previz or solve is aborted |
| `python_exe` | `$HIP/../.venv/bin/python3` | Python for the local target |
| `batch_start`, `batch_end` | all | Range of work item indices for batch export |
| `top_node` | display node in `../topnet1` | TOP node whose work items are exported |
| `batch` | set by batch export | Batch folder name used by the batch buttons and the `sionna_batch_*` File SOPs |

## Terminal output

Every message, including all error and warning codes, is printed to the terminal and appended to `sionna/log.txt` with a timestamp. Each button ends with a line such as `solve passed (0 errors, 1 warning)` or `export FAILED (2 errors, 0 warnings)`.

| Button | Prints |
|---|---|
| check | target, Sionna version, Mitsuba variant, GPU and its load |
| validate | objects, triangles and object count per material, radio map surfaces, devices, frequency and wavelength, scene size |
| export | run folder, every file written with its size, permittivity and conductivity per material at the run frequency, git commit |
| previz | files sent and received, Sionna's own progress, what Sionna loaded |
| solve | files sent and received, Sionna's progress per step with timings, number of paths and radio map cells |
| import | gain range of the paths, number of line-of-sight paths, radio map signal range, cells without signal, time taken |
| run | the output of validate, export, solve and import, then the total time |
| batch export | one line per work item: status, primitive count, warning and error codes, time |
| batch solve | work items queued, files sent, pid of the started job |
| batch status | running, finished or stopped; solved, skipped and failed counts; current work item; seconds per work item and time left; errors of failed work items; last lines of `batch.log` |
| batch fetch | files received and removed, work items converted to bgeo with time, number of results |

## Results

**`sionna_paths`**: one polyline per propagation path, from TX through every interaction point to RX.
Prim: `tx`, `rx`, `gain_db`, `tau` (delay, s), `a_re`, `a_im` (complex amplitude), `bounces`, `theta_t`, `phi_t` (departure angles, rad), `theta_r`, `phi_r` (arrival angles, rad), `doppler` (Hz). Angles are in Sionna's frame (z up).
Point: `interaction` (1 specular, 2 diffuse, 4 refraction, 8 diffraction), `object` (name of the object hit), `primitive` (triangle index hit).

**`sionna_links`**: one line per TX/RX pair, summarising all its paths.
Prim: `num_paths`, `gain_db_coherent` (paths added with phase: the value at exactly that position), `gain_db_incoherent` (powers added: the local average), `delay_spread` (RMS, s), `cfr_db` (array: gain per frequency). Detail: `cfr_frequencies`.

**`sionna_radiomap`**: the measurement triangles.
Prim: `path_gain_db` (array, one entry per TX, in the order of detail `tx`), `path_gain_db_max` (strongest TX), `best_tx`, `best_tx_name`, `name`. Detail: `tx`.
The radio map adds powers without phase and averages over each cell, so it shows the local average, not small-scale fading.

Missing values are stored as -999.

Solve writes the results as compressed NumPy files (float32), about 10 times smaller than JSON and read without parsing. Import turns them into the geometry above. They can also be read directly, e.g. for analysis over a batch:

```python
import numpy as np
d = np.load("wi015/<hip>_result.npz")
d["link_gain_db_incoherent"]   # [rx, tx], order of d["rx"] and d["tx"]
```

| File | Arrays |
|---|---|
| `_result.npz` | `tx`, `rx` (names), `tx_position`, `rx_position`, `object_names`, `cfr_frequencies`, `info` (JSON: Sionna version, settings). Per path, in rx, tx order: `path_tx`, `path_rx` (indices), `path_interactions`, `path_objects` (index into `object_names`, -1 none), `path_primitives`, `path_vertices` ([path, depth] and [path, depth, 3], unused depths 0), `path_gain_db`, `path_tau`, `path_a_re`, `path_a_im`, `path_theta_t`, `path_phi_t`, `path_theta_r`, `path_phi_r`, `path_doppler`. Per link [rx, tx]: `link_num_paths`, `link_gain_db_coherent`, `link_gain_db_incoherent`, `link_delay_spread`, `link_cfr_db` ([rx, tx, frequency]) |
| `_radiomap.npz` | `tx`, `map_names`, `vertices`, `faces` (all surfaces together), `cell_map` (surface index per cell), `path_gain_db` ([cell, tx]), `info` |

Positions are in Sionna axes (z up).

## Messages

Codes starting with N are information, W warnings (do not block), all others are errors (stop the button).

| Code | Message | Meaning / what to do |
|---|---|---|
| N001 | scene size | Bounding box of the geometry in Sionna axes. Check units and orientation. |
| N002 | exported to | Run folder written |
| N003 | sionna dump written | Previz succeeded |
| N004 | paths, result written | Solve found paths |
| N005 | imported paths, links | Import succeeded |
| N006 | radio map cells | Radio map computed or imported |
| N008 | target status | Result of check |
| N009 | batch exported | Number of work items exported and failed |
| N010 | batch started | The job runs on the target; follow it with batch status |
| N011 | batch results | Work items with a result, failed, and not solved (yet) |
| W001 | scene diagonal outside 1 m to 50 km | Probably wrong units |
| W002 | object smaller than one wavelength | Ray tracing is not valid for it; results for that object are unreliable |
| W003 | device far from the geometry | Device probably misplaced or in other units |
| W004 | no rx point | Only the radio map is computed |
| W005 | material not confirmed | Library value not verified; results depend on it |
| W006 | GPU in use by other processes | Runs slower; large jobs may run out of memory |
| W008 | node exists but is not a File SOP | A node next to the Null already has the name `sionna_previz`, `sionna_paths`, `sionna_links`, `sionna_radiomap` or `sionna_batch_scene`, `_paths`, `_links`, `_radiomap`. The result file is written but not loaded; rename that node. |
| W009 | no `batch` parm on the Null | Add a string parm `batch`; the `sionna_batch_*` File SOPs read the batch name from it |
| V001 | no primitives | Nothing to export; add geometry or a measurement surface |
| V002 | missing prim attribute | Add `name` and `material` |
| V003 | not a triangle | Triangulate (Divide SOP) |
| V004 | zero area | Remove degenerate triangles (Clean SOP) |
| V005 | invalid name | Only letters, digits, `_`, `-` |
| V006 | material attributes differ within a name | Same `name` must have one material, thickness and scattering |
| V007 | unknown material | Not an ITU name and not in `materials.json` |
| V008 | thickness < 0 | Fix the attribute |
| V009 | scattering_coefficient outside 0 to 1 | Fix the attribute |
| V010 | empty name | Every primitive needs a `name` |
| V011 | material resolves to invalid values | Library entry gives permittivity < 1 or negative conductivity |
| V101 | missing point attribute | Add `role` and `name` to device points |
| V102 | no tx point | At least one TX is required |
| V103 | device with empty name | Name every device |
| V104 | duplicate device name | Device names must be unique |
| V105 | tx and rx at same position | Zero distance is undefined |
| V106 | loose point without valid role | A point that is not a device; remove it or set `role` |
| V107 | nothing to compute | Add an RX or a measurement surface |
| E001 | cannot create output directory | Check permissions and disk space |
| E002 | cannot write file | Check permissions and disk space |
| E003 | hip file is not saved | Save the hip file first; run folders live next to it |
| S001 | python executable not found | Local venv missing; check `python_exe` |
| S002 | solver script not found | `sionna/sionna_run.py` missing |
| S003 | solver exited with an error | Last line of the solver output; full output in `solver.log`. A missing Sionna installation in the venv also ends here (`No module named 'sionna'`). |
| S004 | solver timed out | Increase `timeout` or reduce the job |
| S005 | solver produced no result file | Solver ended without writing results |
| S006 | no exported run found | Export first |
| S008 | frequency changed since export | Export again |
| S009 | program not found | `ssh`, `rsync` or `nvidia-smi` missing on this machine |
| S010 | radio map exceeds the ray limit | `radiomap_samples` × number of TX is above Sionna's 4.29e9 rays per radio map. Lower `radiomap_samples` to the value shown. Checked before anything is sent. |
| T001 | target unreachable | VPN off, wrong SSH alias, or key not installed. The SSH reason is shown. |
| T002 | no python on target | No venv at `<remote_root>/venv` |
| T003 | no GPU on target | Sionna would run on the CPU; refused |
| T004 | file transfer failed | rsync error; reason shown |
| I001 | result file not found | Solve first |
| I002 | result file unreadable | Damaged file; solve again. Runs solved before the switch to `.npz` give `I001`; solve them again. |
| B001 | TOP node not found | No `../topnet1`, no node with the display flag in it, or a wrong `top_node` |
| B002 | no work items in range | Check `batch_start` and `batch_end` against the work item indices |
| B003 | no batch found | Batch export first, or check the `batch` parm |
| B004 | batch already running | Wait for it, or stop it on the target |
| B007 | nothing to solve | Every work item failed at export or at the checks before sending (`S008`, `S010`) |
| B008 | input did not cook | The SOP network gave an error for this work item; it is skipped |

## Tests

Analytic cases with known answers. Each should get its own hip file in `tests/`. Positions are given in Sionna coordinates (z up) with y = 0, so in Houdini a Sionna point (x, 0, z) is (x, z, 0). Frequency 3.5 GHz (wavelength 8.565 cm) unless stated. Expected values are computed independently: free-space loss with Friis, the wall with the exact plane-wave slab formula, concrete parameters from the ITU table above.

**A. Free space.** TX (0, 0, 2), RX (10, 0, 2). No geometry; a measurement plane 20 × 20 m at z = 0, centred under the TX, about 0.25 m cells.
- one path, `bounces` 0, `gain_db` −63.33 dB, `tau` 33.36 ns
- radio map: every cell equals free-space loss to the TX, e.g. −49.35 dB directly below it (2 m), −66.43 dB in the far corners (14.28 m). Compute `diff_db` per cell (see below): expect values scattered around 0 dB, the scatter shrinking as `radiomap_samples` grows. A systematic offset means an error.

**B. Ground reflection.** As A, with a `metal` plane 40 × 40 m at z = 0 (`thickness` 0.01) and the measurement plane moved to z = 1.
- two paths: line of sight −63.33 dB at 33.36 ns, and one specular reflection off the plane at (5, 0, 0), about −63.97 dB at 35.93 ns
- `gain_db_incoherent` of the link about −60.63 dB

**C. Wall transmission.** TX (0, 0, 2), RX (6, 0, 2). A `concrete` wall in the plane x = 3, 10 m wide (y −5 to 5), 4 m high (z 0 to 4), `thickness` 0.2. No floor.
- one path with `interaction` 4 (refraction), `gain_db` about −77.91 dB: −58.89 dB free space minus 19.02 dB through 0.2 m concrete (σ 0.123 S/m)

**D. Frequency scaling.** Test A at 2.4 GHz: the path is 3.28 dB stronger, −60.05 dB.

**E. Pipeline failures.** Expected codes: VPN off → `T001`; `remote_root` pointing to a folder without venv → `T002`; frequency changed after export → `S008`; open polygon or quad → `V003`; no RX and no measurement surface → `V107`.

**F. Canopy representations (study, not pass/fail).** A TX and RX with a canopy block between them, depth 0 to several metres, at 433 MHz, 868 MHz, 2.4 GHz and 5 GHz. Compare three representations (closed shell, stacked internal sheets, stochastic small triangles) against ITU-R P.833 and published greenhouse measurements. Expected: loss grows with depth; which representation gets the slope right is the question.

Radio map check per cell (Primitive Wrangle on `sionna_radiomap`, scene with TX points in the second input; set the wavelength for other frequencies):

```c
int tx = findattribval(1, "point", "name", s@best_tx_name);
if (tx >= 0) {
    float d = distance(@P, point(1, "P", tx));
    f@friis_db = 20 * log10(0.08565 / (4 * PI * d));
    f@diff_db = f@path_gain_db_max - f@friis_db;
}
```

## Current limitations

- **One isotropic, vertically polarised antenna per device.** Every TX and RX is an ideal antenna radiating equally in all directions. Real antennas (dipoles, patches, arrays for wireless power transfer) have directional gain and their own polarisation. Sionna supports antenna patterns and arrays; the plugin does not expose them yet. Needed for the polarisation and multi-antenna parts of CELSA.
- **ITU materials have frequency limits.** Below 1 GHz most of them are undefined and Sionna stops with an error (see the table). Sub-GHz scenes need library materials.
- **Library values are mostly unverified** (see Materials).
- **No volumetric media.** Materials live on surfaces, so canopies must be built from surfaces; see test F.
- **Houdini is blocked while previz, solve or run is busy.** Batch solve runs in the background.
- **Radio maps grow with cells × TX**: 4 bytes per value, so 100,000 cells and 100 TX is 40 MB before compression.
- **Validation does not check** whether a device sits inside an object or below a floor, or whether ITU materials are defined at the run frequency.
- **Remote targets need `ssh` and `rsync`** on your machine (standard on Linux and macOS, not on Windows).
- Developed against Sionna RT 2.2.0.

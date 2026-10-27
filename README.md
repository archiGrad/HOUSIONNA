# Houdini to Sionna RT

Run [Sionna RT](https://nvlabs.github.io/sionna/rt/) radio propagation simulations from a Houdini scene, compute them on the Techtile Spark GPU server, and bring the results back into Houdini as geometry with attributes.

Houdini is the procedural generator: geometry, materials and devices are built with nodes, so one network can produce an unlimited number of scene variations, and each variation can be simulated and inspected within seconds.

![Paths and radio map in Houdini](docs/preview.png)

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
| batch_clear | `on_clear("session")` | Deletes the batches of the current `batch_name` on the target, after confirmation |
| clear_all | `on_clear("all")` | Deletes all runs and batches of this hip file on the target, after confirmation |

Export never contacts the server; previz, solve and the batch buttons except export do. The first six buttons are for testing one scene step by step; run does the same in one press.

## Folder structure

```
.
├── venv/                       local Sionna RT environment (not committed)
├── requirements.txt
├── docs/                       preview image, presentations (see Update #1)
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
            └── [<batch_name>_]<YYYYMMDD_HHMMSSZ>/
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

Requires Houdini, and on the machine that computes: Python 3.11 or later and Sionna RT. Sionna RT 2.2.0 installs on Python 3.10 but fails on import there (`cannot import name 'Self' from 'typing'`). Sionna RT is only needed on that machine, your own PC (local target) or a server (remote target). An NVIDIA GPU is optional: without one, Sionna runs on the CPU (see Compute target).

```bash
python -m venv venv
source venv/bin/activate           # Linux; on Windows (Git Bash): venv/Scripts/activate
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

Validate and export read the geometry in bulk. To get which points belong to which triangle, they create a temporary Attribute Wrangle `sionna_scan` next to the node that feeds the Null, cook it and delete it again. This adds no undo steps, but marks the hip file as changed.

## Compute target

A string parm `target` on the Null selects where the solver runs:

- `local` (or empty): the venv on this machine, at `$HIP/../venv/bin/python3` (Windows: `$HIP/../venv/Scripts/python.exe`). Override with a string parm `python_exe`.
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

Each remote run checks that the server and venv exist and reads the GPU status, mirrors the run folder (without `.bgeo.sc` files) to the server, runs the solver there, and copies the results back.

### GPU or CPU

A Toggle parm `use_gpu` on the Null (default on) selects the device, on every target:

- on: Sionna runs on the GPU (CUDA). Without a usable GPU, check, solve and batch solve stop with `T003`.
- off: Sionna runs on the CPU (LLVM), locally or on the Spark. Same results, but much slower: use small tests (few TX, `samples` 1e5, `radiomap_samples` 1e6). Needs the LLVM library, version 17 or newer, on that machine; if check reports the CPU as not available (`T005`), install it (Ubuntu: `sudo apt install llvm`). Check shows the LLVM version and warns (`W013`) below 17.

Check prints what the target has and what is selected:

```
[sionna check] target local: sionna 2.2.0
[sionna check]   gpu: not available (jit_init_thread_state(): the CUDA backend hasn't been initialized)
[sionna check]   cpu: <cpu model>, 4 threads, available, LLVM 20.1.8
[sionna check]   selected: cpu (use_gpu off)
[sionna check] N008 target 'local': sionna 2.2.0, runs on the cpu
```

## Batches

For many scene variations from a TOP network (e.g. a Wedge TOP), next to the Null:

1. Set the int parms `batch_start` and `batch_end` to a range of work item indices (both included; without the parms, all work items).
2. **batch_export**: for each work item in the range, selects it in the TOP network, so the SOP network cooks that variation, then validates and exports it to `batches/<batch_name>_<stamp>/wi<index>/` (see Batch names). The wedge attributes of the work item are stored in its `<hip>_meta.json`. A work item that fails validation or does not cook is recorded in `batch.json` and skipped; the others continue. The selection is restored afterwards.
3. **batch_solve**: writes the current settings into every exported work item, sends the batch folder and starts one solver process on the target, which solves all work items one after the other in one Sionna session. The button returns at once; Houdini stays usable and the job keeps running if Houdini or the laptop is closed. Houdini then checks the batch every 15 s in the background and prints a `[sionna watch]` line when work items are solved or fail, and one when the batch is finished or has stopped. It only prints; fetch is up to you. Watching ends with the batch, after 4 failed checks in a row (e.g. VPN down), or when Houdini closes; the job itself is not affected.
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

### Batch names

A string parm `batch_name` on the Null groups batches into sessions, e.g. `plants_on` and `plants_off`. Batch export names the folder `<batch_name>_<YYYYMMDD_HHMMSSZ>`, or only the timestamp when `batch_name` is empty. Letters, digits, `_` and `-` only (`B009`).

### Clearing

Both buttons work on the selected `target` only: local deletes folders on this machine, a remote target deletes them on that machine, never both. When the remote target is not reachable they stop with `T001`.

- **batch_clear**: all batches of this hip file with the current `batch_name`, any timestamp. With `batch_name` empty: the batches without a name.
- **clear_all**: all single runs (`data/`, or `runs/<hip>/` remotely) and all batches of this hip file. Folders of other hip files in the same `sionna/` folder are kept.

The folders and their size are listed in the terminal and in a dialog; nothing is deleted until you press Delete. A batch that is still running is kept (`W014`). File SOPs that pointed at deleted results load nothing.

## Scene: supported attributes

Everything Sionna receives comes from the attributes below. Any other attribute (`Cd`, `N`, `uv`, groups) is ignored.

### Geometry (primitive attributes, triangles only)

| Attribute | Type | Required | Meaning |
|---|---|---|---|
| `name` | string | yes | Object name. One mesh and one Sionna object per value. Letters, digits, `_` and `-` only. |
| `material` | string | yes | An ITU material, a name from `materials.json`, or `measure` for a radio map surface |
| `thickness` | float | no | Slab thickness in metres used for reflection and transmission. 0 or absent: library default, else 0.1. Not the mesh thickness. |
| `scattering_coefficient` | float | no | 0 to 1. Share of reflected energy that is scattered diffusely. Only has an effect with `diffuse_reflection` on. 0 or absent: library default, else 0. |
| `moisture` | float | no | Percent water, only for vegetation materials (`leaf`, `stem`: % of fresh mass, living leaves 70 to 90) and soil materials (`soil_*`: % of volume, 0 to 50). 0 or absent: library default. Ignored on other materials (`W011`); outside 0 to 100 is an error (`V012`). |

All primitives with the same `name` must have the same material attributes (`V006`). `moisture` may vary: it is rounded to whole percent and each value becomes its own Sionna object, named `<name>_m<percent>` (e.g. `leaves_m80`); that is the name in the results and in `object` of `sionna_paths`. Every surface is a slab of the given thickness, so a closed box is a hollow shell: a ray through it crosses two slabs.

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

`xpd_coefficient`, and the model inputs `temperature_c`, `ionic_conductivity` and the soil texture (`sand`, `clay`, `silt`, densities), exist only per entry in `materials.json`.

## Materials

Every material name is looked up in `sionna/materials.json`. Values are computed at export for the run `frequency` and written to `<hip>_materials.json`, so changing the frequency requires a new export (`S008`). Every entry has a `source` and a `status`; a status other than `confirmed` gives warning `W005`. Entries with a measured frequency range give `W010` when the run frequency lies outside it: the values are then extrapolated and the solve still runs.

### Kinds

| Kind | Fields | Model |
|---|---|---|
| `itu` | `ranges_ghz`: `[lo, hi, a, b, c, d]` per range | ITU-R P.2040-3: `er = a * f^b`, `sigma = c * f^d`, f in GHz. Outside every range the nearest range is used (`W010`) |
| `cole_cole` | `eps_inf`, `eps_s`, `sigma_s`, `tau`, `alpha` | Cole-Cole fit to measurements |
| `soil` | `sand`, `clay`, `silt` (%), `specific_gravity`, `bulk_density`, `moisture` (% volume), `temperature_c` | ITU-R P.527-6 section 5.2 |
| `conductor` | `conductivity` | metal: permittivity 1, conductivity constant over frequency |
| `fixed` | `relative_permittivity` plus one of `conductivity`, `loss_tangent`, `loss_factor` | constant permittivity; loss converted at the run frequency |
| `water` | `temperature_c`, `ionic_conductivity` | Debye model (Liebe, Hufford, Manabe 1991, same equations as ITU-R P.527-6) plus ionic conductivity |
| `vegetation` | `moisture` (% of fresh mass) | dual-dispersion model (Ulaby and El-Rayes 1987) |

### Entries

**Building materials in situ (kind `itu`, ITU-R P.2040-3 Table 3, coefficients as in Sionna's `itu.py`, status confirmed).** Inside their range the values are identical to Sionna's built-in ITU materials (checked); outside it they are extrapolated instead of stopping the solve:

| Material | Measured range (GHz) | At 868/915 MHz |
|---|---|---|
| `vacuum`, `wood` | 0.001–100 | in range |
| `glass` | 0.1–100 | in range |
| `concrete`, `plasterboard`, `ceiling_board`, `chipboard` | 1–100 | extrapolated, `W010` |
| `brick`, `plywood`, `vinyl_tile`, `carpet_tile`, `asphalt_concrete` | 1–40 | extrapolated, `W010` |
| `marble` | 1–60 | extrapolated, `W010` |
| `very_dry_ground`, `medium_dry_ground`, `wet_ground` | 1–10 | extrapolated, `W010`; below 1 GHz prefer `soil_*` |
| `floorboard` | 50–100 | far outside, avoid |
| `clear_acrylic` | 110–330 | far outside, use `pmma` |

**Lab samples, air-dried (kind `cole_cole`, Zhekov, Franek, Pedersen 2020, IEEE Antennas Propag. Mag. 62(1), Table II, measured 0.2–67 GHz):** `pmma`, `polypropylene`, `ptfe`, `polystyrene` (solid, not foam), `pine_dry`, `hardboard_dry`, `plywood_dry`, `mdf_dry`, `chipboard_dry`, `wood_cement_board_dry`, `gypsum_dry`, `plasterboard_dry` (confirmed); `brick_red_dry`, `brick_yellow_dry`, `concrete_dry` (small gravel), `concrete_coarse_dry` (large gravel) give `W005`, because the paper reports a less reliable fit for brick and concrete.

**Metals (kind `conductor`, no frequency limit, confirmed):** `metal` (1e7 S/m, as ITU), `steel` (6.99e6, carbon steel), `stainless_steel` (1.45e6), `aluminium` (3.5e7), `zinc` (1.69e7, galvanised coating), `copper` (5.96e7). Any of them acts as a near-perfect reflector at these frequencies.

**Soils (kind `soil`, ITU-R P.527-6 section 5.2 with the textures of its Table 2, confirmed):** `soil_sandy_loam`, `soil_loam`, `soil_silty_loam`, `soil_silty_clay`. Default moisture 20 %, set per primitive with `moisture`. Range 0.3–18 GHz, the measurements the model is built on (Peplinski et al. 1995, Dobson et al. 1985). The implementation reproduces the reference values of MathWorks `earthSurfacePermittivity` (P.527-6) exactly. Example `soil_loam` at 868 MHz: er 4.1 / 11.2 / 20.9 and sigma 0.02 / 0.06 / 0.10 S/m at 5 / 20 / 35 % moisture.

**Greenhouse materials:**

| Material | Kind | Status |
|---|---|---|
| `water` | water | confirmed (equations checked against ITU-R P.527-6) |
| `nutrient_solution` | water | `W005`: ionic conductivity from an assumed EC of 2.5 mS/cm |
| `leaf`, `stem` | vegetation | `W005`: coefficients not yet checked against the paper; valid 0.2–20 GHz |
| `fruit` | fixed | `W005`: strawberry values used for tomato |
| `polycarbonate` | fixed | `W005`: permittivity from datasheets at 1 MHz only |
| `polyethylene_film`, `pvc` | fixed | `W005`: permittivity confirmed, loss assumed zero |
| `rockwool_wet` | fixed | `W005`: placeholder, must be measured |

### In situ versus lab values

The two sources disagree most for concrete and brick: the lab samples were dried, real walls hold water. Loss through a 23 cm concrete wall at normal incidence, computed with Sionna (CPU), against the 3GPP TR 38.901 formula for real walls (5 + 4 f dB):

| Material | 868 MHz | 2.4 GHz | 5 GHz |
|---|---|---|---|
| `concrete` (ITU, in situ) | 8.0 dB | 16.5 dB | 28.2 dB |
| `concrete_dry` (lab) | 1.8 dB | 1.5 dB | 2.6 dB |
| `concrete_coarse_dry` (lab) | 1.9 dB | 2.7 dB | 4.3 dB |
| 3GPP TR 38.901 | 8.5 dB | 14.6 dB | 25.0 dB |

The ITU values match real walls within 0.5 to 3 dB, also when extrapolated to 868 MHz. Use the ITU names for real buildings; the `_dry` entries describe very dry material and are a lower bound on loss.

### When a value is confirmed

A value becomes `confirmed` only when it comes from a measurement or a source that states it for the frequency range in use, with the reference in `source`. Ways to get there, in order of strength:

1. Measure it: dielectric probe or free-space measurement with a VNA, or fit it from channel measurements (CELSA T3; Sionna is differentiable for this).
2. Peer-reviewed values at the right frequency: ITU-R P.2040 and P.527, Zhekov et al. 2020, Ulaby and El-Rayes 1987, Peng et al. 2013 (tomato), manufacturer data at GHz frequencies.
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
| `quality`, `band` | none | Menus that set a group of parms at once, see Presets |
| `use_gpu` | on | Toggle. On: run on the GPU (CUDA). Off: run on the CPU (LLVM), locally or on the Spark |
| `python_exe` | `$HIP/../venv/bin/python3` | Python for the local target |
| `batch_start`, `batch_end` | all | Range of work item indices for batch export |
| `top_node` | display node in `../topnet1` | TOP node whose work items are exported |
| `batch` | set by batch export | Batch folder name used by the batch buttons and the `sionna_batch_*` File SOPs |
| `batch_name` | empty | Session name in front of the batch timestamp; also selects what batch_clear deletes |

### Presets

`PRESETS` at the top of `sionna_sop.py` holds two independent sets of named parm values, each with its own menu on the Null:

- `quality`: target, `use_gpu`, ray and depth settings, interaction toggles, `timeout`.
- `band`: `frequency` and `bandwidth`.

Neither sets the other's parms, so any quality can be combined with any band. Parms that are not on the Null are listed (`W012`) and left alone. Edit the dict to change or add presets; the menus follow it.

| Quality | For |
|---|---|
| `laptop_test` | Small tests on the laptop CPU (`target` local, `use_gpu` off) |
| `spark_quick` | Fast check on the Spark |
| `spark_standard` | Normal single runs |
| `dense_canopy` | Paths through plants: `max_depth` 8, more rays |
| `batch` | Many variations: no frequency response, fewer radio map rays |
| `final` | Highest accuracy, diffraction on |

| Band | `frequency` | `bandwidth` |
|---|---|---|
| `lora_868` | 868 MHz | 125 kHz |
| `lora_915` | 915 MHz | 125 kHz |
| `wifi_2g4` | 2.437 GHz (channel 6) | 20 MHz |
| `wifi_5g` | 5.18 GHz (channel 36) | 20 MHz |

Setup on the Null: two String parms, `quality` and `band`. On the Menu tab of each: "Use Menu", Menu Script, Python:

```python
g = {}
exec(open(hou.expandString('$HIP/sionna/sionna_sop.py')).read(), g)
return g["preset_menu"]("quality")
```

and as callback script (Python), so a choice is applied immediately:

```python
exec(open(hou.expandString('$HIP/sionna/sionna_sop.py')).read()); on_preset("quality")
```

For `band`, replace `"quality"` with `"band"` in both.

## Terminal output

Every message, including all error and warning codes, is printed to the terminal and appended to `sionna/log.txt` with a timestamp. Each button ends with a line such as `solve passed (0 errors, 1 warning) after 21.4 s` or `export FAILED (2 errors, 0 warnings) after 0.3 s`; the time counts from the button press.

| Button | Prints |
|---|---|
| check | target, Sionna version, GPU (name, load) and CPU (model, threads) with their availability, selected device |
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
| watch | work items solved or failed since the last check, then finished or stopped with totals |
| clear | folders found with size (running ones marked), then the number deleted |

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
| N008 | target status | Result of check: Sionna version and the device it will run on |
| N009 | batch exported | Number of work items exported and failed |
| N010 | batch started | The job runs on the target; follow it with batch status |
| N011 | batch results | Work items with a result, failed, and not solved (yet) |
| N012 | cleared | Number and size of the deleted folders |
| N013 | nothing to clear | No runs or batches of this hip file (and `batch_name`) on the target |
| W001 | scene diagonal outside 1 m to 50 km | Probably wrong units |
| W002 | object smaller than one wavelength | Ray tracing is not valid for it; results for that object are unreliable |
| W003 | device far from the geometry | Device probably misplaced or in other units |
| W004 | no rx point | Only the radio map is computed |
| W005 | material not confirmed | Library value not verified; results depend on it |
| W006 | GPU in use by other processes | Runs slower; large jobs may run out of memory |
| W010 | material outside its measured range | The run frequency lies outside the range the material was measured for; values are extrapolated. Below 1 GHz this applies to most ITU materials; see Materials |
| W011 | moisture set on a material that does not use it | `moisture` only affects vegetation and soil materials |
| W008 | node exists but is not a File SOP | A node next to the Null already has the name `sionna_previz`, `sionna_paths`, `sionna_links`, `sionna_radiomap` or `sionna_batch_scene`, `_paths`, `_links`, `_radiomap`. The result file is written but not loaded; rename that node. |
| W014 | running batch not cleared | Clear again after it finished, or stop it first |
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
| V012 | moisture outside 0 to 100 | Fix the `moisture` attribute (percent) |
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
| S011 | python on target failed | Check could not import Sionna; the last lines of the error are printed above it. On Python 3.10: `cannot import name 'Self'`, use Python 3.11 or later |
| S004 | solver timed out | Increase `timeout` or reduce the job |
| S005 | solver produced no result file | Solver ended without writing results |
| S006 | no exported run found | Export first |
| S008 | frequency changed since export | Export again |
| S009 | program not found | `ssh`, `rsync` or `nvidia-smi` missing on this machine |
| S010 | radio map exceeds the ray limit | `radiomap_samples` × number of TX is above Sionna's 4.29e9 rays per radio map. Lower `radiomap_samples` to the value shown. Checked before anything is sent. |
| T001 | target unreachable | VPN off, wrong SSH alias, or key not installed. The SSH reason is shown. |
| T002 | no python on target | No venv at `<remote_root>/venv` |
| T003 | no GPU on target | `use_gpu` is on but the target has no usable GPU. Switch `use_gpu` off to run on the CPU |
| T005 | no CPU backend on target | `use_gpu` is off but the LLVM library is missing on the target; install it (Ubuntu: `sudo apt install llvm`) |
| T004 | file transfer failed | rsync error; reason shown |
| I001 | result file not found | Solve first |
| I002 | result file unreadable | Damaged file; solve again. Runs solved before the switch to `.npz` give `I001`; solve them again. |
| P001 | unknown preset | The `quality` or `band` parm holds a name that is not in `PRESETS` |
| W013 | old LLVM for the cpu backend | Shown by check when `use_gpu` is off and the target's LLVM is older than 17. LLVM 15 aborts cpu solves with `LLVM ERROR: Cannot select`; LLVM 20 works. On Ubuntu 22.04 install `libllvm20` from apt.llvm.org |
| W012 | preset parms missing on the Null | Those parms keep their defaults; add them to the Null to let the preset set them |
| B001 | TOP node not found | No `../topnet1`, no node with the display flag in it, or a wrong `top_node` |
| B002 | no work items in range | Check `batch_start` and `batch_end` against the work item indices |
| B003 | no batch found | Batch export first, or check the `batch` parm |
| B004 | batch already running | Wait for it, or stop it on the target |
| B009 | invalid `batch_name` | Use only letters, digits, `_` and `-` |
| C001 | clear failed on the target | The target was reached but listing or deleting failed; the error is shown |
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

**G. CPU.** Test C with `use_gpu` off on a machine without GPU: same path, −77.91 dB, and −49.36 dB in the radio map cell under the TX (checked).

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
- **Below 1 GHz most building materials are extrapolated** (`W010`). For concrete the extrapolation still matches 3GPP (see Materials); for ground use the `soil_*` materials.
- **Some library values are unverified** (`W005`): leaf, stem, fruit, polycarbonate, polyethylene film, PVC, rockwool, and the lab fits for brick and concrete.
- **Sionna drops paths with a segment shorter than 1 cm** (`MIN_SEGMENT_LENGTH` in `sionna/rt/constants.py`). In paths and links, a closed object thinner than 1 cm (e.g. a thin stem modelled as a tube) blocks every path through it, as do two surfaces less than 1 cm apart along a ray, and a TX or RX within 1 cm of a surface. The radio map applies this limit only to diffraction, so there thin closed objects let rays through. Keep devices at least 1 to 2 cm from surfaces; model thin stems as single surfaces or leave them out.
- **No volumetric media.** Materials live on surfaces, so canopies must be built from surfaces; see test F.
- **Houdini is blocked while previz, solve or run is busy.** Batch solve runs in the background.
- **Radio maps grow with cells × TX**: 4 bytes per value, so 100,000 cells and 100 TX is 40 MB before compression.
- **Validation does not check** whether a device sits inside an object or below a floor.
- **Remote targets need `ssh` and `rsync`** on your machine (standard on Linux and macOS, not on Windows).
- Developed against Sionna RT 2.2.0.

## Update #1 (21-10-2026)

Procedural greenhouse variations from a TOP network, exported, solved as one batch on the Spark and loaded back per work item.

### Video

[![Video of the pipeline](https://img.youtube.com/vi/GcwktsATHTg/0.jpg)](https://www.youtube.com/watch?v=GcwktsATHTg)

https://www.youtube.com/watch?v=GcwktsATHTg

### Presentation

![Slide 1](docs/presentation_21-10-2026/HyROPA_presentatie_1.png)
![Slide 2](docs/presentation_21-10-2026/HyROPA_presentatie_2.png)
![Slide 3](docs/presentation_21-10-2026/HyROPA_presentatie_3.png)
![Slide 4](docs/presentation_21-10-2026/HyROPA_presentatie_4.png)
![Slide 5](docs/presentation_21-10-2026/HyROPA_presentatie_5.png)
![Slide 6](docs/presentation_21-10-2026/HyROPA_presentatie_6.png)
![Slide 7](docs/presentation_21-10-2026/HyROPA_presentatie_7.png)
![Slide 8](docs/presentation_21-10-2026/HyROPA_presentatie_8.png)
![Slide 9](docs/presentation_21-10-2026/HyROPA_presentatie_9.png)
![Slide 10](docs/presentation_21-10-2026/HyROPA_presentatie_10.png)
![Slide 11](docs/presentation_21-10-2026/HyROPA_presentatie_11.png)
![Slide 12](docs/presentation_21-10-2026/HyROPA_presentatie_12.png)
![Slide 13](docs/presentation_21-10-2026/HyROPA_presentatie_13.png)
![Slide 14](docs/presentation_21-10-2026/HyROPA_presentatie_14.png)
![Slide 15](docs/presentation_21-10-2026/HyROPA_presentatie_15.png)
![Slide 16](docs/presentation_21-10-2026/HyROPA_presentatie_16.png)
![Slide 17](docs/presentation_21-10-2026/HyROPA_presentatie_17.png)
![Slide 18](docs/presentation_21-10-2026/HyROPA_presentatie_18.png)
![Slide 19](docs/presentation_21-10-2026/HyROPA_presentatie_19.png)

### Annotated screenshots

Front view: greenhouse shell, TX frame with TX, RX, racks with plants

![Front view: greenhouse shell, TX frame with TX, RX, racks with plants](docs/presentation_21-10-2026/annotated_images/annotated_298ad846.png)

Greenhouse with rack rows, TX frame and RX

![Greenhouse with rack rows, TX frame and RX](docs/presentation_21-10-2026/annotated_images/annotated_cbe7a67c.png)

Greenhouse with a grid of racks, TX frame and RX

![Greenhouse with a grid of racks, TX frame and RX](docs/presentation_21-10-2026/annotated_images/annotated_7f4aaac7.png)

Close-up of the racks: trays, legs, plants, RX

![Close-up of the racks: trays, legs, plants, RX](docs/presentation_21-10-2026/annotated_images/annotated_00bbc1c9.png)

One variation: TX, links and RX

![One variation: TX, links and RX](docs/presentation_21-10-2026/annotated_images/annotated_23cd7903.png)

One variation: all paths

![One variation: all paths](docs/presentation_21-10-2026/annotated_images/annotated_7a2c2e1c.png)

Paths in several variations at once

![Paths in several variations at once](docs/presentation_21-10-2026/annotated_images/annotated_92642889.png)

Radio map under four racks

![Radio map under four racks](docs/presentation_21-10-2026/annotated_images/annotated_1e853020.png)

### Screenshots

![Screenshot 2026-10-20-212001](docs/presentation_21-10-2026/2026-10-20-212001_1300x940_scrot.png)
![Screenshot 2026-10-20-212214](docs/presentation_21-10-2026/2026-10-20-212214_1296x970_scrot.png)
![Screenshot 2026-10-20-212229](docs/presentation_21-10-2026/2026-10-20-212229_1295x995_scrot.png)
![Screenshot 2026-10-20-215721](docs/presentation_21-10-2026/2026-10-20-215721_1920x1034_scrot.png)
![Screenshot 2026-10-20-215730](docs/presentation_21-10-2026/2026-10-20-215730_1920x1032_scrot.png)
![Screenshot 2026-10-20-215744](docs/presentation_21-10-2026/2026-10-20-215744_1920x1028_scrot.png)
![Screenshot 2026-10-20-215809](docs/presentation_21-10-2026/2026-10-20-215809_1920x1031_scrot.png)
![Screenshot 2026-10-20-215850](docs/presentation_21-10-2026/2026-10-20-215850_1920x1032_scrot.png)
![Screenshot 2026-10-20-215912](docs/presentation_21-10-2026/2026-10-20-215912_1920x1029_scrot.png)
![Screenshot 2026-10-21-102447](docs/presentation_21-10-2026/2026-10-21-102447_1920x1061_scrot.png)
![Screenshot 2026-10-21-102633](docs/presentation_21-10-2026/2026-10-21-102633_1920x1060_scrot.png)
![Screenshot 2026-10-21-102655](docs/presentation_21-10-2026/2026-10-21-102655_1920x1028_scrot.png)
![Screenshot 2026-10-21-102800](docs/presentation_21-10-2026/2026-10-21-102800_1917x1033_scrot.png)

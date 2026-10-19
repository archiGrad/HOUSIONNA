# Houdini to Sionna RT

Run [Sionna RT](https://nvlabs.github.io/sionna/rt/) radio propagation simulations from a Houdini scene and bring the results back as geometry with attributes.

![Paths and radio map in Houdini](docs/preview.png)

## What it is

A set of Python functions called from one Houdini node, plus a solver script that runs in a separate virtual environment, either on the same machine or on a remote GPU server over SSH. Houdini handles geometry, device placement and visualisation. Sionna RT handles the physics on the GPU.

Buttons on the node:

| Button | Does |
|---|---|
| check | Reports the compute target: reachable, Sionna version, GPU, other GPU users |
| validate | Checks the scene: triangles only, names and materials set, sane units, devices present |
| export | Writes meshes, scene XML and device JSON into a timestamped run folder |
| previz | Has Sionna load the export and shows what it actually holds |
| solve | Computes paths between every TX and RX, and a radio map on every measurement surface |
| import | Loads paths, per-link results and radio maps |

## Folder structure

```
.
├── .venv/                      Sionna RT environment (not committed)
├── requirements.txt
├── docs/preview.png
└── houdini_files/
    ├── <scene>.hip
    └── sionna/
        ├── sionna_sop.py       functions pasted into the Houdini node
        ├── sionna_run.py       solver script, run by the venv Python
        ├── materials.json      custom material library
        ├── log.txt             log over all runs, same text as the terminal output
        ├── previz.bgeo.sc      latest results, read by File SOPs
        ├── paths.bgeo.sc
        ├── links.bgeo.sc
        ├── radiomap.bgeo.sc
        └── data/
            └── <YYYYMMDD_HHMMSSZ>/
                ├── meshes/<name>.ply
                ├── sionna_run.py         copy of the solver used for this run
                ├── <hip>_meta.json       git commit, uncommitted changes flag, Houdini version
                ├── <hip>_scene.xml
                ├── <hip>_materials.json
                ├── <hip>_txrx.json
                ├── <hip>_measure.json
                ├── <hip>_settings.json
                ├── <hip>_dump.json
                ├── <hip>_result.json
                ├── <hip>_radiomap.json
                ├── <hip>_log.txt
                ├── solver.log            full solver output of the last solve or previz
                └── <hip>_*.bgeo.sc
```

Every export creates a new run folder. Solve, previz and radiomap always work on the latest one.

On a remote target the run folder is mirrored to `<remote_root>/runs/<hip>/<stamp>/`:

```
<remote_root>/
├── venv/
└── runs/<hip>/<stamp>/
```

## Setup

Requires an NVIDIA GPU, Python 3.10 or later, and Houdini.

Sionna RT is only needed on the machine that computes: your own PC (local target) or a server (remote target).

```bash
python -m venv .venv
source .venv/bin/activate          # Linux; on Windows (Git Bash): .venv/Scripts/activate
pip install -r requirements.txt    # sionna-rt==2.2.0
```

In Houdini:

1. Add a Null SOP at the end of the scene network.
2. Add one Button parm per function with this callback (Python), changing the function name:

```python
exec(open(hou.expandString('$HIP/sionna/sionna_sop.py')).read()); on_validate()
```

Functions: `on_check`, `on_validate`, `on_export`, `on_previz`, `on_solve`, `on_import`.

All feedback is printed to the terminal Houdini was started from (and appended to `sionna/log.txt`), so start Houdini from a terminal. There are no pop-ups.

The code is read from `sionna/sionna_sop.py` on every press, so the file in git is the only copy. Nothing is pasted into the hip file.

## Compute target

A string parm `target` on the Null selects where the solver runs:

- `local` (or empty): the venv on this machine, at `$HIP/../.venv/bin/python3` (Windows: `$HIP/../.venv/Scripts/python.exe`). Override with a string parm `python_exe`.
- an SSH host alias, e.g. `spark`: a remote server. Override the remote folder with a string parm `remote_root` (default `~/Documents/HyROPA`).

To pick the target per machine, set the parm to `$SIONNA_TARGET` and define it in each machine's `houdini.env`, e.g. `SIONNA_TARGET = spark`.

Remote setup, once per server:

1. An alias in `~/.ssh/config` on your machine:
   ```
   Host spark
       HostName 192.108.2.65
       User dramco_spark
   ```
2. Key login, since Houdini cannot type a password: `ssh-keygen -t ed25519` (if you have no key yet), then `ssh-copy-id spark`.
3. On the server, a venv at `<remote_root>/venv` with `requirements.txt` installed.
4. `rsync` on both machines.

Each run: check that the server and venv exist and read the GPU status, mirror the run folder (without `.bgeo.sc` files) to the server, run the solver there, copy the results back. The solver refuses to run on a machine without a CUDA variant (T003).

## Preparing a scene

Merge everything into the Null. The scene stays Y up in Houdini; conversion to Sionna's Z up is done on export and reversed on import. Units are metres.

**Geometry** (primitive attributes, triangulated):

| Attribute | Type | Meaning |
|---|---|---|
| `name` | string | Object name. One mesh file per name. |
| `material` | string | ITU material type (e.g. `concrete`, `glass`, `metal`, `medium_dry_ground`) or a name from `materials.json` |
| `thickness` | float | Slab thickness in metres. 0 or absent: library default, else 0.1 |
| `scattering_coefficient` | float | 0 to 1, share of diffuse reflection (default 0) |

**Devices** (point attributes on loose points):

| Attribute | Type | Meaning |
|---|---|---|
| `role` | string | `tx` or `rx` |
| `name` | string | Unique name |
| `orientation` | vector | Yaw, pitch, roll in radians |
| `velocity` | vector | m/s |
| `power_dbm` | float | Transmit power, TX only |

**Measurement surfaces** for radio maps: any triangulated mesh with `material = "measure"` and its own `name`. Each triangle becomes one cell. They are not part of the scene Sionna traces against.

Solve computes paths when there is at least one RX, and a radio map when there is at least one measurement surface. Without either, validation fails (V107).

## Custom materials

`sionna/materials.json` holds materials outside the ITU list. Each entry has a `kind`, default `thickness`, a `source` and a `status`:

| Kind | Fields | Permittivity and conductivity |
|---|---|---|
| `fixed` | `relative_permittivity` plus one of `conductivity`, `loss_tangent`, `loss_factor` | constant permittivity; loss converted to conductivity at the run frequency |
| `water` | `temperature_c`, `ionic_conductivity` | Debye model (Liebe, Hufford, Manabe 1991) |
| `vegetation` | `moisture` (gravimetric, 0 to 1) | dual-dispersion model (Ulaby and El-Rayes 1987) |

Values are resolved at export for the current `frequency` and written to `<hip>_materials.json`. Changing the frequency requires a new export. Any material whose status is not `confirmed` raises warning W005.

## Running

1. check (once per session, or after changing target)
2. validate
3. export
4. previz (optional check)
5. solve
6. import

During solve and previz the terminal shows each file sent and received with its size, the solver's own progress lines from the target, and timings. Results appear as File SOPs next to the Null: `sionna_previz`, `sionna_paths`, `sionna_links`, `sionna_radiomap`.

## Results

**`sionna_paths`**: one polyline per propagation path.
Prim: `tx`, `rx`, `gain_db`, `tau`, `a_re`, `a_im`, `bounces`, `theta_t`, `phi_t`, `theta_r`, `phi_r`, `doppler`.
Point: `interaction` (1 specular, 2 diffuse, 4 refraction, 8 diffraction), `object`, `primitive`.

**`sionna_links`**: one line per TX/RX pair.
Prim: `num_paths`, `gain_db_coherent`, `gain_db_incoherent`, `delay_spread`, `cfr_db` (array). Detail: `cfr_frequencies`.

**`sionna_radiomap`**: the measurement triangles.
Prim: `path_gain_db` (array, one entry per TX), `path_gain_db_max`, `best_tx`, `best_tx_name`. Detail: `tx`.

Missing values are stored as -999.

## Settings

Defaults, each overridable by a parm of the same name on the Null:

| Parm | Default |
|---|---|
| `frequency` | 3.5e9 |
| `max_depth` | 3 |
| `samples` | 1000000 |
| `los`, `specular_reflection`, `refraction` | on |
| `diffuse_reflection`, `diffraction` | off |
| `bandwidth` | 100e6 |
| `cfr_points` | 256 |
| `radiomap_samples` | 10000000 |
| `max_paths_per_tx` | 100000 |
| `target` | local |
| `remote_root` | ~/Documents/HyROPA |
| `timeout` | 1800 (seconds) |

## Messages

Every message has a code and is written to `sionna/log.txt`.

| Prefix | Meaning |
|---|---|
| N | Information |
| W | Warning, does not block |
| V | Validation error |
| E | Export error |
| S | Solver error |
| I | Import error |
| T | Compute target error |

## Current limitations

- One isotropic, vertically polarised antenna per device
- Most library values are unverified; model coefficients still need checking against the source papers
- No volumetric media: canopies must be built from surfaces
- Houdini is blocked while the solver runs
- Results are exchanged as JSON, which gets slow for very large scenes
- Remote targets need `ssh` and `rsync` on your machine (standard on Linux and macOS, not on Windows)
- Developed against Sionna RT 2.2.0

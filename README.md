# Houdini to Sionna RT
testssss
Run [Sionna RT](https://nvlabs.github.io/sionna/rt/) radio propagation simulations from a Houdini scene and bring the results back as geometry with attributes.

![Paths and radio map in Houdini](Screenshot%202026-10-07%20220245.png)

## What it is

A set of Python functions living on one Houdini node, plus a solver script that runs in a separate virtual environment. Houdini handles geometry, device placement and visualisation. Sionna RT handles the physics on the GPU.

Buttons on the node:

| Button | Does |
|---|---|
| validate | Checks the scene: triangles only, names and materials set, sane units, devices present |
| export | Writes meshes, scene XML and device JSON into a timestamped run folder |
| previz | Has Sionna load the export and shows what it actually holds |
| solve | Computes propagation paths between every TX and RX |
| import | Loads paths and per-link results as polylines |
| radiomap | Computes coverage on measurement surfaces |

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
        ├── log.txt             log over all runs
        ├── previz.bgeo.sc      latest results, read by File SOPs
        ├── paths.bgeo.sc
        ├── links.bgeo.sc
        ├── radiomap.bgeo.sc
        └── data/
            └── <YYYYMMDD_HHMMSSZ>/
                ├── meshes/<name>.ply
                ├── <hip>_scene.xml
                ├── <hip>_txrx.json
                ├── <hip>_measure.json
                ├── <hip>_settings.json
                ├── <hip>_dump.json
                ├── <hip>_result.json
                ├── <hip>_radiomap.json
                ├── <hip>_log.txt
                └── <hip>_*.bgeo.sc
```

Every export creates a new run folder. Solve, previz and radiomap always work on the latest one.

## Setup

Requires an NVIDIA GPU, Python 3.10 or later, and Houdini.

```bash
python -m venv .venv
source .venv/Scripts/activate      # Windows, Git Bash
pip install -r requirements.txt    # sionna-rt==2.2.0
```

In Houdini:

1. Add a Null SOP at the end of the scene network.
2. Add a String parm `functions` (Multi-line String, Size 1, Language Python) and paste in `sionna_sop.py`.
3. Add one Button parm per function with this callback (Python), changing the function name:

```python
exec(hou.pwd().parm('functions').unexpandedString()); on_validate()
```

Functions: `on_validate`, `on_export`, `on_previz`, `on_solve`, `on_import`, `on_radiomap`.

The venv Python is expected at `$HIP/../.venv/Scripts/python.exe`. Override with a string parm `python_exe`.

## Preparing a scene

Merge everything into the Null. The scene stays Y up in Houdini; conversion to Sionna's Z up is done on export and reversed on import. Units are metres.

**Geometry** (primitive attributes, triangulated):

| Attribute | Type | Meaning |
|---|---|---|
| `name` | string | Object name. One mesh file per name. |
| `material` | string | ITU material type, e.g. `concrete`, `glass`, `metal`, `wood`, `brick`, `medium_dry_ground` |
| `thickness` | float | Slab thickness in metres (default 0.1) |
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

## Running

1. validate
2. export
3. previz (optional check)
4. solve, then import, for paths and links
5. radiomap, for coverage

Results appear as File SOPs next to the Null: `sionna_previz`, `sionna_paths`, `sionna_links`, `sionna_radiomap`.

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

## Current limitations

- One isotropic, vertically polarised antenna per device
- ITU materials only, no custom materials
- Houdini is blocked while the solver runs
- Results are exchanged as JSON, which gets slow for very large scenes
- Default paths assume Windows
- Developed against Sionna RT 2.2.0

# Scene assets

`basic_demo` loads Sionna RT's bundled `floor_wall` XML scene. `room_demo` builds its room surfaces from `config/room_demo.yaml` at run time and writes the exact OBJ meshes used by each run under that run's `outputs/.../generated_meshes/` directory. This keeps the baseline and moved-panel comparison meshes distinct and reproducible.

The procedural room uses x/y horizontal coordinates and z up. Its bounds are 10 m × 6 m × 3 m; the panel dimensions and location are in the YAML config.

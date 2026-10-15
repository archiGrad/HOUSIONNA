"""Pure, deterministic CEA toy-geometry generation, independent of Sionna RT."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _box(name: str, category: str, material_key: str,
         bounds: tuple[float, float, float, float, float, float]) -> dict[str, Any]:
    x0, x1, y0, y1, z0, z1 = map(float, bounds)
    if not (x1 > x0 and y1 > y0 and z1 > z0):
        raise ValueError(f"Object {name} has non-positive dimensions: {bounds}")
    vertices = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    faces = [
        (1, 4, 3, 2), (5, 6, 7, 8), (1, 2, 6, 5),
        (2, 3, 7, 6), (3, 4, 8, 7), (4, 1, 5, 8),
    ]
    return {
        "id": name,
        "category": category,
        "material_key": material_key,
        "bounds_m": {
            "x_min": x0, "x_max": x1, "y_min": y0,
            "y_max": y1, "z_min": z0, "z_max": z1,
        },
        "vertices": vertices,
        "faces": faces,
    }


def receiver_grid_positions(config: dict[str, Any]) -> list[list[float]]:
    """Generate the configured horizontal RX sample lattice at its fixed height."""
    grid = config["receiver_grid"]
    spacing = float(grid["spacing_m"])
    if spacing <= 0:
        raise ValueError("receiver_grid.spacing_m must be positive")

    def axis(low_key: str, high_key: str) -> list[float]:
        low, high = float(grid[low_key]), float(grid[high_key])
        if high <= low:
            raise ValueError(f"{high_key} must be greater than {low_key}")
        count = int((high - low) // spacing)
        # Correct small floating-point underflow at exact spacing multiples.
        while low + (count + 1) * spacing <= high + 1e-9:
            count += 1
        return [round(low + i * spacing, 9) for i in range(count + 1)]

    xs = axis("x_min_m", "x_max_m")
    ys = axis("y_min_m", "y_max_m")
    height = float(grid["height_m"])
    return [[x, y, height] for y in ys for x in xs]


def validate_cea_config(config: dict[str, Any]) -> None:
    greenhouse = config["greenhouse"]
    length, width, height = (float(greenhouse[k]) for k in ("length_m", "width_m", "height_m"))
    assert min(length, width, height) > 0, "Greenhouse dimensions must be positive"

    canopy = config["canopy"]
    rows = int(canopy["row_count"])
    row_length = float(canopy["row_length_m"])
    row_width = float(canopy["row_width_m"])
    row_spacing = float(canopy["row_spacing_m"])
    bottom = float(canopy["bottom_height_m"])
    row_height = float(canopy["row_height_m"])
    assert rows >= 1, "At least one canopy row is required when canopy is enabled"
    assert 0 < row_length <= length, "Canopy rows must fit along the greenhouse length"
    assert row_width > 0 and row_spacing > 0, "Canopy width and spacing must be positive"
    assert rows * row_width + (rows - 1) * row_spacing <= width, "Canopy rows do not fit across the greenhouse"
    assert bottom >= 0 and bottom + row_height <= height, "Canopy rows must fit vertically inside the greenhouse"

    tx = list(map(float, config["tx"]["position_m"]))
    assert 0 <= tx[0] <= length and 0 <= tx[1] <= width and 0 <= tx[2] <= height, "TX must be inside the greenhouse bounds"

    grid = config["receiver_grid"]
    positions = receiver_grid_positions(config)
    assert positions, "Receiver grid must not be empty"
    assert all(0 <= p[0] <= length and 0 <= p[1] <= width and 0 <= p[2] <= height for p in positions), "Receiver grid must fit inside greenhouse bounds"
    for receiver in grid["representative_receivers"]:
        x, y, z = map(float, receiver["position_m"])
        assert float(grid["x_min_m"]) <= x <= float(grid["x_max_m"]), f"{receiver['name']} x must lie in the configured RX grid"
        assert float(grid["y_min_m"]) <= y <= float(grid["y_max_m"]), f"{receiver['name']} y must lie in the configured RX grid"
        assert abs(z - float(grid["height_m"])) < 1e-9, f"{receiver['name']} z must match the RX grid height"

    structure = config["structure"]
    for x in structure["support_frame_x_m"]:
        assert 0 < float(x) < length, "Support frame positions must be inside the greenhouse"


def generate_cea_geometry(config: dict[str, Any]) -> dict[str, Any]:
    """Build named OBJ-ready boxes and a compact manifest from YAML parameters."""
    validate_cea_config(config)
    greenhouse = config["greenhouse"]
    length, width, height = (float(greenhouse[k]) for k in ("length_m", "width_m", "height_m"))
    wall_t = float(greenhouse["wall_thickness_m"])
    floor_t = float(greenhouse["floor_thickness_m"])
    objects: list[dict[str, Any]] = [
        _box("floor", "floor", "floor_placeholder", (0, length, 0, width, -floor_t, 0)),
        _box("greenhouse_shell_side_y0", "greenhouse_shell", "shell_glazing_placeholder",
             (0, length, 0, wall_t, 0, height)),
        _box("greenhouse_shell_side_ymax", "greenhouse_shell", "shell_glazing_placeholder",
             (0, length, width-wall_t, width, 0, height)),
        _box("greenhouse_shell_end_x0", "greenhouse_shell", "shell_glazing_placeholder",
             (0, wall_t, wall_t, width-wall_t, 0, height)),
        _box("greenhouse_shell_end_xmax", "greenhouse_shell", "shell_glazing_placeholder",
             (length-wall_t, length, wall_t, width-wall_t, 0, height)),
    ]
    if bool(greenhouse.get("include_roof", True)):
        objects.append(_box("greenhouse_shell_roof", "greenhouse_shell", "shell_glazing_placeholder",
                            (0, length, 0, width, height-wall_t, height)))

    structure = config["structure"]
    if bool(structure["include_rails"]):
        rail_count = int(structure["rail_count"])
        if rail_count < 1:
            raise ValueError("structure.rail_count must be at least one when rails are enabled")
        section = float(structure["rail_cross_section_m"])
        rail_z0 = height - 0.22 - section / 2
        rail_z1 = height - 0.22 + section / 2
        for index in range(rail_count):
            y_center = width * (index + 1) / (rail_count + 1)
            half = section / 2
            objects.append(_box(
                f"metal_structure_rail_{index+1:02d}", "metal_structure", "metal_placeholder",
                (wall_t, length-wall_t, y_center-half, y_center+half, rail_z0, rail_z1),
            ))

    section = float(structure["support_cross_section_m"])
    y_offset = float(structure["support_offset_y_m"])
    support_index = 0
    for x_center in map(float, structure["support_frame_x_m"]):
        for y_center in (y_offset, width-y_offset):
            support_index += 1
            half = section / 2
            objects.append(_box(
                f"metal_structure_support_{support_index:02d}", "metal_structure", "metal_placeholder",
                (x_center-half, x_center+half, y_center-half, y_center+half, 0, height-wall_t),
            ))

    canopy = config["canopy"]
    if bool(canopy["enabled"]):
        row_count = int(canopy["row_count"])
        row_length = float(canopy["row_length_m"])
        row_width = float(canopy["row_width_m"])
        row_spacing = float(canopy["row_spacing_m"])
        row_bottom = float(canopy["bottom_height_m"])
        row_top = row_bottom + float(canopy["row_height_m"])
        total_y = row_count * row_width + (row_count - 1) * row_spacing
        first_y = (width - total_y) / 2.0
        first_x = (length - row_length) / 2.0
        for index in range(row_count):
            y0 = first_y + index * (row_width + row_spacing)
            objects.append(_box(
                f"canopy_row_{index+1:02d}", "vegetation", "canopy_placeholder",
                (first_x, first_x+row_length, y0, y0+row_width, row_bottom, row_top),
            ))

    # Structural and shell proxies are generated within the greenhouse volume;
    # the floor's lower face is the sole intended geometry below z=0.
    for obj in objects:
        bounds = obj["bounds_m"]
        assert bounds["x_min"] >= -1e-9 and bounds["x_max"] <= length+1e-9
        assert bounds["y_min"] >= -1e-9 and bounds["y_max"] <= width+1e-9
        assert bounds["z_max"] <= height+1e-9
    canopy_objects = [obj for obj in objects if obj["category"] == "vegetation"]
    assert len(canopy_objects) == (int(canopy["row_count"]) if canopy["enabled"] else 0)
    return {
        "units": "m",
        "up_axis": "z",
        "bounds_m": {"x_min": 0.0, "x_max": length, "y_min": 0.0, "y_max": width,
                     "z_min": 0.0, "z_max": height},
        "objects": objects,
    }


def write_obj_assets(geometry: dict[str, Any], destination: Path) -> dict[str, Path]:
    destination.mkdir(parents=True, exist_ok=True)
    paths = {}
    for obj in geometry["objects"]:
        target = destination / f"{obj['id']}.obj"
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("# Procedural CEA demo geometry; units are meters.\n")
            for x, y, z in obj["vertices"]:
                handle.write(f"v {x:.9g} {y:.9g} {z:.9g}\n")
            for face in obj["faces"]:
                handle.write("f " + " ".join(str(i) for i in face) + "\n")
        paths[obj["id"]] = target
    return paths


def write_manifest(geometry: dict[str, Any], path: Path) -> None:
    manifest = {
        "units": geometry["units"],
        "up_axis": geometry["up_axis"],
        "bounds_m": geometry["bounds_m"],
        "objects": [{key: obj[key] for key in ("id", "category", "material_key", "bounds_m")}
                    for obj in geometry["objects"]],
    }
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

"""Config-driven geometry and scenario preparation for the vertical-farm demo."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from demos.cea_geometry import _box


ROOT = Path(__file__).resolve().parents[2]
FARM_SCENARIOS = ("farm_empty", "farm_proxy", "farm_dense")


def load_vertical_farm_config() -> dict[str, Any]:
    with (ROOT / "config" / "vertical_farm.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def air_gap_plane_heights(cfg: dict[str, Any]) -> list[float]:
    """Mid-height of the free air above each level's canopy, below the shelf, supports and grow light overhead.

    These are where a sensor could sit, so radio-map planes go here instead of through a canopy block.
    The same heights are used for every scenario (empty included), so maps stay comparable.
    """
    env, rf = cfg["environment"], cfg["rf_geometry"]
    levels = list(map(float, env["shelf_levels_m"]))
    height, panel_t = float(env["height_m"]), float(env["panel_thickness_m"])
    tray_t, frame = float(env["shelf_thickness_m"]), float(env["frame_cross_section_m"])
    lights = bool(env.get("grow_lights_enabled", True))
    light_t = float(env["grow_light_thickness_m"])
    heights = []
    for index, level in enumerate(levels):
        canopy_top = level+tray_t+float(rf["plant_zone_height_m"])
        if index+1 < len(levels):
            overhead = levels[index+1]-tray_t-max(frame, light_t if lights else 0.0)
        else:
            overhead = height-panel_t-(0.045 if lights else 0.0)
        if overhead-canopy_top < 0.02:
            raise ValueError(f"No air gap above the canopy on shelf level {index+1} for a radio-map plane "
                             f"(canopy top {canopy_top:.3f} m, overhead {overhead:.3f} m)")
        heights.append(round((canopy_top+overhead)/2, 4))
    return heights


def vertical_farm_scenario_config(base: dict[str, Any], name: str) -> dict[str, Any]:
    """Expand one YAML case into the common config contract used by the RT runner."""
    if name not in FARM_SCENARIOS:
        raise ValueError(f"Unknown vertical-farm scenario: {name}")
    cfg = copy.deepcopy(base)
    case = cfg["scenarios"][name]
    env = cfg["environment"]
    width, depth, height = (float(env[key]) for key in ("width_m", "depth_m", "height_m"))
    levels = list(map(float, env["shelf_levels_m"]))
    if min(width, depth, height, float(env["panel_thickness_m"]), float(env["shelf_thickness_m"])) <= 0:
        raise ValueError("Vertical-farm dimensions and panel/shelf thicknesses must be positive")
    if not levels or levels != sorted(levels):
        raise ValueError("environment.shelf_levels_m must be a nonempty ascending list")
    if any(level <= 0 or level >= height for level in levels):
        raise ValueError("Every shelf top must be inside the configured farm height")

    cfg["scenario"] = name
    cfg["description"] = (
        f"{case['label']}. Compact, semi-open indoor rack with {len(levels)} configurable growing levels. "
        "Dimensions and RF materials are artificial software-demo placeholders."
    )
    cfg["material_status"] = case["material_status"]
    cfg["rf_geometry"]["zones_per_level"] = int(case["zones_per_level"])
    canopy_material = case.get("canopy_material", "canopy_placeholder")
    if canopy_material not in cfg["materials"]:
        raise ValueError(f"Scenario {name} names an unknown canopy material: {canopy_material}")
    cfg["rf_geometry"]["canopy_material"] = canopy_material
    cfg["scene_dimensions_m"] = [width, depth, height]
    cfg["greenhouse"] = {
        "length_m": width, "width_m": depth, "height_m": height,
        "wall_thickness_m": float(env["panel_thickness_m"]),
        "floor_thickness_m": float(env["floor_thickness_m"]),
        "include_roof": True,
    }
    cfg["structure"] = {
        "type": "vertical rack frame",
        "shelf_levels_m": levels,
        "frame_cross_section_m": float(env["frame_cross_section_m"]),
    }
    cfg["canopy"] = {
        "enabled": int(case["zones_per_level"]) > 0,
        "zones_per_level": int(case["zones_per_level"]),
        "level_count": len(levels),
        "plant_zone_height_m": float(cfg["rf_geometry"]["plant_zone_height_m"]),
        "material": canopy_material,
    }
    cfg["transmitter"] = {
        "name": cfg["tx"]["name"],
        "position_m": list(map(float, cfg["tx"]["position_m"])),
        "orientation_rad": list(map(float, cfg["tx"]["orientation_rad"])),
        "power_dbm": float(cfg["tx"]["power_dbm"]),
    }
    cfg["receivers"] = [
        {"name": item["name"], "role": item["role"],
         "position_m": list(map(float, item["position_m"]))}
        for item in cfg["receiver_grid"]["representative_receivers"]
    ]

    grid = cfg["receiver_grid"]
    planes = []
    if grid.get("map_planes") == "air_gaps":
        heights = air_gap_plane_heights(cfg)
        primary = int(grid.get("primary_level", (len(heights)+1)//2))
        if not 1 <= primary <= len(heights):
            raise ValueError("receiver_grid.primary_level must name an existing shelf level")
        grid["height_m"] = heights[primary-1]  # the plane shown in the 3D viewer
        planes = [{"level": index+1, "height_m": z} for index, z in enumerate(heights)]
    x0, x1 = float(grid["x_min_m"]), float(grid["x_max_m"])
    y0, y1 = float(grid["y_min_m"]), float(grid["y_max_m"])
    cfg["radio_map"] = {
        **cfg["radio_map"],
        "center_m": [(x0+x1)/2, (y0+y1)/2, float(grid["height_m"])],
        "orientation_rad": [0.0, 0.0, 0.0],
        "size_m": [x1-x0, y1-y0],
        "cell_size_m": list(map(float, cfg["radio_map"]["cell_size_m"])),
        "planes": planes,
    }

    panel_t = float(env["panel_thickness_m"])
    tray_t = float(env["shelf_thickness_m"])
    visual = cfg["visual_plants"]
    if int(visual["columns"]) < 1 or int(visual["rows"]) < 1:
        raise ValueError("visual_plants.columns and rows must be positive")
    if int(visual["leaf_count_min"]) < 1 or int(visual["leaf_count_max"]) < int(visual["leaf_count_min"]):
        raise ValueError("visual leaf-count range must be positive and ascending")
    visual["visible_by_default"] = bool(case.get("visual_plants_visible_by_default", True))
    bed_x0 = panel_t + float(env["shelf_inset_x_m"])
    bed_x1 = width - panel_t - float(env["shelf_inset_x_m"])
    bed_y0 = float(env["shelf_front_y_m"])
    bed_y1 = min(depth-panel_t-0.04, bed_y0+float(env["shelf_depth_m"]))
    visual["shelves"] = []
    light_positions = []
    for index, level in enumerate(levels):
        visual["shelves"].append({
            "id": f"shelf_level_{index+1}",
            "level": index+1,
            "bounds_m": {
                "x_min": bed_x0, "x_max": bed_x1,
                "y_min": bed_y0, "y_max": bed_y1,
                "z_min": level+tray_t,
            },
            "columns": int(visual["columns"]),
            "rows": int(visual["rows"]),
            "plant_count": int(visual["columns"])*int(visual["rows"]),
        })
        if index+1 < len(levels):
            light_z = levels[index+1]-tray_t-float(env["grow_light_thickness_m"])
        else:
            light_z = height-panel_t-0.045
        light_positions.append([width/2, (bed_y0+bed_y1)/2, light_z])

    cfg["environment"].update({
        "grow_light_positions_m": light_positions,
        "shelf_count": len(levels),
    })
    cfg["visual_plants"] = visual
    cfg["model_metadata"] = {
        "dimensions_m": {"width": width, "depth": depth, "height": height},
        "shelf_levels_m": levels,
        "rf_zones_per_level": int(case["zones_per_level"]),
        "rf_canopy_material": canopy_material,
        "rf_plant_model_limitations": [
            "RF canopy zones are coarse solid boxes, not detailed leaf geometry.",
            "The crop material is an uncalibrated placeholder; no crop water-content or dielectric measurements were supplied.",
            "Cabinet/rack dimensions and enclosure properties are software-demo assumptions, not measured equipment data.",
            "No measurement validation; do not treat these results as real-farm coverage predictions.",
        ],
    }
    return cfg


def generate_vertical_farm_geometry(cfg: dict[str, Any]) -> dict[str, Any]:
    """Create named OBJ-ready RF objects from the vertical-farm YAML dimensions."""
    env = cfg["environment"]
    rf = cfg["rf_geometry"]
    width, depth, height = (float(env[key]) for key in ("width_m", "depth_m", "height_m"))
    panel_t = float(env["panel_thickness_m"])
    floor_t = float(env["floor_thickness_m"])
    tray_t = float(env["shelf_thickness_m"])
    frame = float(env["frame_cross_section_m"])
    levels = list(map(float, env["shelf_levels_m"]))
    if width <= 2*panel_t or depth <= 2*panel_t or height <= 0 or floor_t <= 0 or tray_t <= 0:
        raise ValueError("Vertical-farm dimensions and panel/shelf thicknesses must be positive and fit")

    objects: list[dict[str, Any]] = []

    def add(name: str, category: str, material: str,
            bounds: tuple[float, float, float, float, float, float], **metadata: Any) -> None:
        item = _box(name, category, material, bounds)
        if metadata:
            item["metadata"] = metadata
        objects.append(item)

    # A shallow floor lip grounds the compact cabinet and gives the outside TX a floor plane.
    add("farm_floor", "floor", "floor_placeholder",
        (-0.18, width+0.18, -0.40, depth+0.15, -floor_t, 0.0), rf_role="ground")
    add("enclosure_left_panel", "enclosure_panel", "enclosure_placeholder",
        (0.0, panel_t, 0.0, depth, 0.0, height), panel="left")
    add("enclosure_right_panel", "enclosure_panel", "enclosure_placeholder",
        (width-panel_t, width, 0.0, depth, 0.0, height), panel="right")
    add("enclosure_back_panel", "enclosure_panel", "enclosure_placeholder",
        (panel_t, width-panel_t, depth-panel_t, depth, 0.0, height-panel_t), panel="back")
    add("enclosure_top_panel", "enclosure_panel", "enclosure_placeholder",
        (0.0, width, 0.0, depth, height-panel_t, height), panel="top")
    if not bool(env.get("front_open", True)):
        add("enclosure_front_panel", "enclosure_panel", "enclosure_placeholder",
            (panel_t, width-panel_t, 0.0, panel_t, 0.0, height-panel_t), panel="front")

    # Four narrow posts form a readable rack frame; the front is intentionally open.
    post_x = (frame/2, width-frame/2)
    post_y = (frame/2, depth-panel_t-frame/2)
    post_index = 0
    for x in post_x:
        for y in post_y:
            post_index += 1
            add(f"rack_post_{post_index:02d}", "metal_structure", "metal_placeholder",
                (x-frame/2, x+frame/2, y-frame/2, y+frame/2, 0.0, height-panel_t),
                member="vertical rack post")

    shelf_x0 = panel_t+float(env["shelf_inset_x_m"])
    shelf_x1 = width-panel_t-float(env["shelf_inset_x_m"])
    shelf_y0 = float(env["shelf_front_y_m"])
    shelf_y1 = min(depth-panel_t-0.04, shelf_y0+float(env["shelf_depth_m"]))
    for index, level in enumerate(levels):
        shelf_id = f"shelf_level_{index+1}"
        if level+tray_t >= height-panel_t:
            raise ValueError(f"{shelf_id} does not fit below the cabinet top")
        add(f"{shelf_id}_tray", "shelf_tray", "tray_placeholder",
            (shelf_x0, shelf_x1, shelf_y0, shelf_y1, level-tray_t, level),
            shelf_id=shelf_id, level=index+1, rf_role="grow tray")
        for side, y in (("front", shelf_y0+frame/2), ("rear", shelf_y1-frame/2)):
            add(f"{shelf_id}_{side}_support", "metal_structure", "metal_placeholder",
                (shelf_x0, shelf_x1, y-frame/2, y+frame/2, level-tray_t-frame, level-tray_t),
                shelf_id=shelf_id, level=index+1, member="tray support")

        if bool(env.get("grow_lights_enabled", True)):
            if index+1 < len(levels):
                light_z = levels[index+1]-tray_t-float(env["grow_light_thickness_m"])
            else:
                light_z = height-panel_t-0.045
            light_t = float(env["grow_light_thickness_m"])
            add(f"{shelf_id}_grow_light", "grow_light", "equipment_placeholder",
                (shelf_x0+0.04, shelf_x1-0.04, shelf_y0+0.04, shelf_y0+0.075,
                 light_z, light_z+light_t), shelf_id=shelf_id, level=index+1,
                rf_role="simplified grow-light bar")

        zone_count = int(rf["zones_per_level"])
        if zone_count < 0:
            raise ValueError("rf_geometry.zones_per_level cannot be negative")
        if zone_count:
            usable_x0 = shelf_x0+float(rf["plant_zone_side_inset_m"])
            usable_x1 = shelf_x1-float(rf["plant_zone_side_inset_m"])
            usable_y0 = shelf_y0+0.025
            usable_y1 = min(shelf_y1-0.025, usable_y0+float(env["shelf_depth_m"])-0.05)
            gap = float(rf["inter_zone_gap_m"])
            zone_width = (usable_x1-usable_x0-(zone_count-1)*gap)/zone_count
            if zone_width <= 0 or usable_y1 <= usable_y0:
                raise ValueError("RF canopy zones do not fit inside the configured shelf beds")
            z0 = level+tray_t
            z1 = z0+float(rf["plant_zone_height_m"])
            if z1 >= height-panel_t:
                raise ValueError(f"RF canopy zone on {shelf_id} exceeds the configured cabinet height")
            for zone_index in range(zone_count):
                x0 = usable_x0+zone_index*(zone_width+gap)
                zone_id = f"rf_plant_zone_level_{index+1}_zone_{zone_index+1}"
                add(zone_id, "rf_plant_zone", rf.get("canopy_material", "canopy_placeholder"),
                    (x0, x0+zone_width, usable_y0, usable_y1, z0, z1),
                    shelf_id=shelf_id, level=index+1, zone=zone_index+1,
                    rf_role="coarse RF-only canopy proxy", visual_only=False)

    if bool(env.get("equipment_block_enabled", False)):
        equipment_w, equipment_d, equipment_h = 0.17, 0.12, 0.22
        add("controller_equipment_block", "equipment", "equipment_placeholder",
            (width-panel_t-equipment_w-0.04, width-panel_t-0.04,
             depth-panel_t-equipment_d, depth-panel_t-0.02, 0.05, 0.05+equipment_h),
            rf_role="simplified controller enclosure")

    bounds = {
        "x_min": min(item["bounds_m"]["x_min"] for item in objects),
        "x_max": max(item["bounds_m"]["x_max"] for item in objects),
        "y_min": min(item["bounds_m"]["y_min"] for item in objects),
        "y_max": max(item["bounds_m"]["y_max"] for item in objects),
        "z_min": min(item["bounds_m"]["z_min"] for item in objects),
        "z_max": max(item["bounds_m"]["z_max"] for item in objects),
    }
    return {"units": "m", "up_axis": "z", "bounds_m": bounds, "objects": objects}

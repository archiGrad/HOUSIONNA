"""Procedural CEA toy scene adapter for the existing Sionna RT PoC."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import yaml
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

from cea_geometry import generate_cea_geometry, receiver_grid_positions, write_manifest, write_obj_assets
from poc import (OUTPUT_DIR, ROOT, _load_rt, _map_array, _save_paths, _save_radio_map, _tensor_numpy,
                 _write_metadata)


SCENARIOS = ("empty", "narrow", "wide")


def _load_cea_config() -> dict[str, Any]:
    with (ROOT / "config" / "cea_demo.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _scenario_config(base: dict[str, Any], name: str) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    scenario = cfg["scenarios"][name]
    cfg["scenario"] = f"cea_{name}"
    cfg["description"] = {
        "empty": "Procedural CEA greenhouse shell and metal structure with canopy disabled.",
        "narrow": "Procedural CEA greenhouse with three narrow canopy proxy rows.",
        "wide": "Procedural CEA greenhouse with three wide canopy proxy rows.",
    }[name]
    cfg["canopy"]["enabled"] = bool(scenario["canopy_enabled"])
    cfg["canopy"]["row_width_m"] = float(scenario["row_width_m"])
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
    x0, x1 = float(grid["x_min_m"]), float(grid["x_max_m"])
    y0, y1 = float(grid["y_min_m"]), float(grid["y_max_m"])
    cfg["radio_map"] = {
        **cfg["radio_map"],
        "center_m": [(x0+x1)/2, (y0+y1)/2, float(grid["height_m"])],
        "orientation_rad": [0.0, 0.0, 0.0],
        "size_m": [x1-x0, y1-y0],
        "cell_size_m": list(map(float, cfg["radio_map"]["cell_size_m"])),
    }
    return cfg


def _plot_cea_scene(cfg: dict[str, Any], geometry: dict[str, Any], target: Path) -> None:
    bounds = geometry["bounds_m"]
    fig = plt.figure(figsize=(10, 6.5))
    ax = fig.add_subplot(111, projection="3d")
    palette = {
        "floor": ("#aab5bd", 0.42),
        "greenhouse_shell": ("#78b6cc", 0.13),
        "enclosure_panel": ("#91aaa8", 0.32),
        "metal_structure": ("#536777", 0.85),
        "shelf_tray": ("#607770", 0.86),
        "grow_light": ("#f0e2a0", 0.9),
        "equipment": ("#46565d", 0.9),
        "rf_plant_zone": ("#3f8a48", 0.34),
        "vegetation": ("#3f8a48", 0.60),
    }
    for obj in geometry["objects"]:
        color, alpha = palette.get(obj["category"], ("#71837e", 0.7))
        verts = [[obj["vertices"][i-1] for i in face] for face in obj["faces"]]
        ax.add_collection3d(Poly3DCollection(
            verts, facecolor=color, edgecolor="#263b49", linewidth=0.25, alpha=alpha))
    tx = cfg["transmitter"]
    ax.scatter(*tx["position_m"], color="#d52222", marker="*", s=150, label=tx["name"])
    for receiver in cfg["receivers"]:
        ax.scatter(*receiver["position_m"], color="#178044", marker="o", s=38,
                   label=receiver["name"])
    ax.set_xlim(bounds["x_min"], bounds["x_max"])
    ax.set_ylim(bounds["y_min"], bounds["y_max"])
    ax.set_zlim(bounds["z_min"], bounds["z_max"])
    ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)"); ax.set_zlabel("z (m), up")
    ax.set_title(f"{cfg.get('environment', {}).get('label', 'CEA greenhouse')} · {cfg['scenario']} geometry")
    ax.set_box_aspect((bounds["x_max"]-bounds["x_min"],
                       bounds["y_max"]-bounds["y_min"],
                       bounds["z_max"]-bounds["z_min"]))
    ax.view_init(elev=23, azim=-58)
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc="upper left", fontsize=8)
    fig.tight_layout()
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=170, bbox_inches="tight")
    plt.close(fig)


def _build_cea_scene(rt, mi, cfg: dict[str, Any], geometry: dict[str, Any], output_dir: Path):
    scene = rt.load_scene()
    material_cfg = cfg["materials"]
    materials = {}
    for key, value in material_cfg.items():
        materials[key] = rt.RadioMaterial(
            name=f"cea_{key}",
            thickness=float(value.get("thickness_m", 0.1)),
            relative_permittivity=float(value["relative_permittivity"]),
            conductivity=float(value["conductivity_s_per_m"]),
            scattering_coefficient=float(value.get("scattering_coefficient", 0.0)),
            xpd_coefficient=float(value.get("xpd_coefficient", 0.0)),
            scattering_pattern=value.get("scattering_pattern", "lambertian"),
            color=tuple(map(float, value["color_rgb"])),
        )
    asset_paths = write_obj_assets(geometry, output_dir / "generated_meshes")
    write_manifest(geometry, output_dir / "scene_manifest.json")
    objects = [
        rt.SceneObject(fname=str(asset_paths[obj["id"]]), name=obj["id"],
                       radio_material=materials[obj["material_key"]],
                       remove_duplicate_vertices=True)
        for obj in geometry["objects"]
    ]
    scene.add(list(materials.values()))
    scene.add(objects)
    scene.frequency = float(cfg["frequency_hz"])
    antenna = cfg["antenna"]
    make_array = lambda: rt.PlanarArray(
        num_rows=int(antenna["rows"]), num_cols=int(antenna["columns"]),
        pattern=antenna["pattern"], polarization=antenna["polarization"])
    scene.tx_array = make_array()
    scene.rx_array = make_array()
    tx_cfg = cfg["transmitter"]
    tx = rt.Transmitter(
        name=tx_cfg["name"], position=mi.Point3f(tx_cfg["position_m"]),
        orientation=mi.Point3f(tx_cfg["orientation_rad"]),
        power_dbm=float(tx_cfg["power_dbm"]), color=(0.9, 0.12, 0.12),
        display_radius=0.18)
    receivers = [
        rt.Receiver(name=item["name"], position=mi.Point3f(item["position_m"]),
                    color=(0.08, 0.48, 0.18), display_radius=0.14)
        for item in cfg["receivers"]
    ]
    scene.add([tx, *receivers])
    material_description = {
        key: {**value, "note": value.get("note", "DEMO PLACEHOLDER")}
        for key, value in material_cfg.items()
    }
    return scene, material_description


def _write_cea_viewer_data(cfg, output_dir: Path, geometry, path_summary, map_values, map_metadata):
    bounds = geometry["bounds_m"]
    map_db = 10.0 * np.log10(np.maximum(map_values, 1e-15))
    map_cfg = cfg["radio_map"]
    receiver_grid = cfg["receiver_grid"]
    data = {
        "scenario": cfg["scenario"],
        "description": cfg["description"],
        "frequency_hz": float(cfg["frequency_hz"]),
        "transmitter": cfg["transmitter"],
        "receivers": cfg["receivers"],
        "geometry": {
            "bounds_m": {key: bounds[key] for key in ("x_min", "x_max", "y_min", "y_max")},
            "objects": [{key: obj[key] for key in ("id", "category", "material_key", "bounds_m")}
                        for obj in geometry["objects"]],
        },
        "radio_map": {
            "values_db": map_db.tolist(), "center_m": map_cfg["center_m"],
            "size_m": map_metadata["requested_size_m"], "shape_yx": list(map_db.shape),
            "units": "10 log10(path gain), dB; values below 1e-15 are floored for display",
        },
        "paths": path_summary["paths"],
        "path_counts": path_summary["receivers"],
        "receiver_grid": {
            "positions_m": receiver_grid_positions(cfg),
            "spacing_m": float(receiver_grid["spacing_m"]),
            "height_m": float(receiver_grid["height_m"]),
            "sample_count": len(receiver_grid_positions(cfg)),
        },
        "canopy": cfg["canopy"],
        "environment": cfg.get("environment"),
        "scene_dimensions_m": cfg.get("scene_dimensions_m"),
        "scene_bounds_m": geometry["bounds_m"],
        "visual_plants": cfg.get("visual_plants"),
        "material_status": cfg.get("material_status"),
    }
    (output_dir / "viewer_data.json").write_text(json.dumps(data), encoding="utf-8")


def _run_scenario(rt, mi, cfg: dict[str, Any], name: str,
                  output_root: Path | None = None, include_paths: bool = False,
                  geometry_override: dict[str, Any] | None = None) -> dict[str, Any]:
    output_dir = (output_root or (OUTPUT_DIR / "cea")) / name
    output_dir.mkdir(parents=True, exist_ok=True)
    geometry = geometry_override if geometry_override is not None else generate_cea_geometry(cfg)
    _plot_cea_scene(cfg, geometry, output_dir / "scene.png")
    scene, material_description = _build_cea_scene(rt, mi, cfg, geometry, output_dir)
    with (output_dir / "config_snapshot.yaml").open("w", encoding="utf-8", newline="\n") as handle:
        yaml.safe_dump(cfg, handle, sort_keys=False)

    path_cfg = cfg["path_solver"]
    paths = rt.PathSolver(deterministic=True)(
        scene, max_depth=int(path_cfg["max_depth"]),
        samples_per_src=int(path_cfg["samples_per_source"]), seed=int(path_cfg["seed"]),
        los=bool(path_cfg["los"]), specular_reflection=bool(path_cfg["specular_reflection"]),
        diffuse_reflection=bool(path_cfg["diffuse_reflection"]),
        refraction=bool(path_cfg["refraction"]), diffraction=bool(path_cfg["diffraction"]))
    object_id_to_name = {
        int(scene_object.object_id): object_name
        for object_name, scene_object in scene.objects.items()
    }
    path_summary = _save_paths(paths, cfg, output_dir, object_id_to_name)

    map_cfg = cfg["radio_map"]
    seeds = [int(seed) for seed in map_cfg.get("seeds") or [map_cfg["seed"]]]

    def solve_map(center_m):
        solved = []
        for seed in seeds:
            radio_map = rt.RadioMapSolver()(
                scene, center=mi.Point3f(center_m),
                orientation=mi.Point3f(map_cfg["orientation_rad"]),
                size=mi.Point2f(map_cfg["size_m"]), cell_size=mi.Point2f(map_cfg["cell_size_m"]),
                samples_per_tx=int(map_cfg["samples_per_transmitter"]),
                max_depth=int(map_cfg["max_depth"]), los=bool(map_cfg["los"]),
                specular_reflection=bool(map_cfg["specular_reflection"]),
                diffuse_reflection=bool(map_cfg["diffuse_reflection"]),
                refraction=bool(map_cfg["refraction"]), diffraction=bool(map_cfg["diffraction"]),
                seed=seed)
            if len(seeds) == 1:
                return radio_map
            solved.append((_tensor_numpy(radio_map.path_gain), _tensor_numpy(radio_map.cell_centers)))
        # Independent seeds on the same grid: average the linear path gain, keep the shared cell centres.
        return SimpleNamespace(path_gain=np.mean([gain for gain, _ in solved], axis=0), cell_centers=solved[0][1])

    map_values, map_metadata = _save_radio_map(solve_map(map_cfg["center_m"]), cfg, output_dir)
    if len(seeds) > 1:
        map_metadata["seeds_averaged"] = seeds
        (output_dir / "radio_map_metadata.json").write_text(json.dumps(map_metadata, indent=2), encoding="utf-8")
    # Extra planes (vertical farm: one per level's air gap) use the same scene, solver settings and seeds.
    plane_maps = {}
    for plane in map_cfg.get("planes") or []:
        z = float(plane["height_m"])
        if abs(z-float(map_cfg["center_m"][2])) < 1e-9:
            values = map_values
        else:
            _, values = _map_array(solve_map([*map_cfg["center_m"][:2], z]))
        np.save(output_dir / f"radio_map_level{int(plane['level'])}.npy", values)
        plane_maps[int(plane["level"])] = values
    _write_metadata(mi, cfg, output_dir, material_description, path_summary, map_metadata)
    metadata_file = output_dir / "metadata.json"
    metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
    if "model_metadata" in cfg:
        metadata["scene_model"] = cfg["model_metadata"]
    else:
        metadata["cea"] = {
            "greenhouse": cfg["greenhouse"], "structure": cfg["structure"],
            "canopy": cfg["canopy"], "receiver_grid": cfg["receiver_grid"],
            "scene_manifest": "scene_manifest.json",
            "model_limitations": [
                "Artificial geometry and arbitrary dimensions; not a KU Leuven greenhouse model.",
                "Every custom RF property is a DEMO PLACEHOLDER.",
                "Canopy is an uncalibrated solid lossy block proxy; no water-content calibration, leaf/stem geometry, or validated scattering/refraction model.",
                "No measurement validation; do not draw real greenhouse coverage conclusions.",
            ],
        }
    metadata_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    _write_cea_viewer_data(cfg, output_dir, geometry, path_summary, map_values, map_metadata)
    result = {"cfg": cfg, "geometry": geometry, "map_values": map_values, "plane_maps": plane_maps,
              "path_summary": path_summary, "map_metadata": map_metadata,
              "viewer_data": json.loads((output_dir / "viewer_data.json").read_text(encoding="utf-8"))}
    if include_paths:
        result["paths"] = paths
        result["object_id_to_name"] = object_id_to_name
    return result


def _compare_configs(results: dict[str, dict[str, Any]]) -> None:
    def normalized(cfg):
        value = copy.deepcopy(cfg)
        value.pop("scenario", None); value.pop("description", None)
        value["canopy"].pop("enabled", None); value["canopy"].pop("row_width_m", None)
        return value
    base = normalized(results["empty"]["cfg"])
    for name in ("narrow", "wide"):
        assert normalized(results[name]["cfg"]) == base, (
            f"Scenario {name} changed a setting outside canopy enabled/row width")
        assert results[name]["cfg"]["transmitter"] == results["empty"]["cfg"]["transmitter"]
        assert results[name]["cfg"]["receivers"] == results["empty"]["cfg"]["receivers"]
    for name in SCENARIOS:
        geometry = results[name]["geometry"]
        canopy = [obj for obj in geometry["objects"] if obj["category"] == "vegetation"]
        expected = 0 if name == "empty" else int(results[name]["cfg"]["canopy"]["row_count"])
        assert len(canopy) == expected
        if name != "empty" and expected == 3:
            assert [obj["id"] for obj in canopy] == ["canopy_row_01", "canopy_row_02", "canopy_row_03"]
    widths = {
        name: [obj["bounds_m"]["y_max"]-obj["bounds_m"]["y_min"]
               for obj in results[name]["geometry"]["objects"] if obj["category"] == "vegetation"]
        for name in ("narrow", "wide")
    }
    assert widths["narrow"] != widths["wide"], "Changing row width did not change geometry"


def _write_comparison(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = OUTPUT_DIR / "cea" / "comparison"
    root.mkdir(parents=True, exist_ok=True)
    maps = {name: results[name]["map_values"] for name in SCENARIOS}
    shapes = {name: value.shape for name, value in maps.items()}
    assert len(set(shapes.values())) == 1, f"CEA radio map shapes differ: {shapes}"
    maps_db = {name: 10.0*np.log10(np.maximum(value, 1e-15)) for name, value in maps.items()}
    deltas = {name: maps_db[name]-maps_db["empty"] for name in ("narrow", "wide")}
    for name, delta in deltas.items():
        assert np.any(np.abs(delta) > 1e-6), f"{name} canopy produced no radio-map change"
        np.save(root / f"{name}_minus_empty_db.npy", delta)

    fields = ["scenario", "mean_path_gain_db", "median_path_gain_db",
              "min_path_gain_db", "max_path_gain_db", "map_rows", "map_columns"]
    with (root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for name in SCENARIOS:
            db = maps_db[name]
            writer.writerow({"scenario": name, "mean_path_gain_db": f"{np.mean(db):.8f}",
                             "median_path_gain_db": f"{np.median(db):.8f}",
                             "min_path_gain_db": f"{np.min(db):.8f}",
                             "max_path_gain_db": f"{np.max(db):.8f}",
                             "map_rows": db.shape[0], "map_columns": db.shape[1]})

    rx_names = [item["name"] for item in results["empty"]["cfg"]["receivers"]]
    with (root / "representative_receivers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["receiver", "empty_sum_coefficient_power",
            "narrow_sum_coefficient_power", "wide_sum_coefficient_power", "narrow_minus_empty_db",
            "wide_minus_empty_db"]); writer.writeheader()
        for receiver in rx_names:
            powers = {}
            for name in SCENARIOS:
                powers[name] = sum(row["magnitude"]**2 for row in results[name]["path_summary"]["paths"]
                                   if row["receiver"] == receiver)
            to_db = lambda value: 10*np.log10(max(value, 1e-30))
            writer.writerow({"receiver": receiver,
                "empty_sum_coefficient_power": f"{powers['empty']:.12g}",
                "narrow_sum_coefficient_power": f"{powers['narrow']:.12g}",
                "wide_sum_coefficient_power": f"{powers['wide']:.12g}",
                "narrow_minus_empty_db": f"{to_db(powers['narrow'])-to_db(powers['empty']):.8f}",
                "wide_minus_empty_db": f"{to_db(powers['wide'])-to_db(powers['empty']):.8f}"})

    map_cfg = results["empty"]["cfg"]["radio_map"]
    x_len, y_len = map_cfg["size_m"]; cx, cy, _ = map_cfg["center_m"]
    extent = [cx-x_len/2, cx+x_len/2, cy-y_len/2, cy+y_len/2]
    fig, axes = plt.subplots(2, 3, figsize=(15, 8), constrained_layout=True)
    for ax, name in zip(axes.flat[:3], SCENARIOS):
        im = ax.imshow(maps_db[name], origin="lower", extent=extent, aspect="equal", cmap="viridis")
        ax.set_title(f"{name.title()} · path gain (dB)"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    fig.colorbar(im, ax=axes.flat[:3], label="10 log10(path gain) (dB)", shrink=0.83)
    max_delta = max(1.0, *(float(np.max(np.abs(value))) for value in deltas.values()))
    for ax, name in zip(axes.flat[3:5], ("narrow", "wide")):
        imd = ax.imshow(deltas[name], origin="lower", extent=extent, aspect="equal",
                        cmap="coolwarm", vmin=-max_delta, vmax=max_delta)
        ax.set_title(f"{name.title()} − empty (dB)"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    fig.colorbar(imd, ax=axes.flat[3:5], label="Δ 10 log10(path gain) (dB)", shrink=0.83)
    axes.flat[5].axis("off")
    axes.flat[5].text(0.02, 0.9, "Controlled change: canopy enabled and row width.\n"
        "All other simulation settings are held fixed.\n\n"
        "Maps display path gain, not RSS or received power.\n"
        "Changes can be locally positive or negative.", va="top", fontsize=12)
    fig.savefig(root / "radio_map_comparison.png", dpi=170)
    plt.close(fig)

    stats = {}
    for name, delta in deltas.items():
        stats[name] = {"mean_absolute_delta_db": float(np.mean(np.abs(delta))),
                       "max_absolute_delta_db": float(np.max(np.abs(delta))),
                       "cells_changed_over_1_db": int(np.count_nonzero(np.abs(delta)>1.0))}
    comparison = {
        "description": "Empty, narrow-canopy, and wide-canopy CEA toy greenhouse comparison.",
        "frequency_hz": float(results["empty"]["cfg"]["frequency_hz"]),
        "unchanged_parameters": ["greenhouse dimensions and shell", "metal structure", "frequency",
            "materials", "transmitter and orientation", "receiver points and grid", "solver and map settings"],
        "changed_parameters": ["canopy.enabled", "canopy.row_width_m"],
        "difference_quantity": "Canopy scenario minus empty 10*log10(path_gain), with path gain floored at 1e-15 for display.",
        "stats": stats,
        "maps": {name: results[name]["viewer_data"]["radio_map"] for name in SCENARIOS},
        "deltas_db": {name: value.tolist() for name, value in deltas.items()},
        "bounds_m": results["empty"]["viewer_data"]["geometry"]["bounds_m"],
        "geometry": {name: results[name]["viewer_data"]["geometry"] for name in SCENARIOS},
        "transmitter": results["empty"]["viewer_data"]["transmitter"],
        "receivers": results["empty"]["viewer_data"]["receivers"],
    }
    (root / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (root / "viewer_data.json").write_text(json.dumps(comparison), encoding="utf-8")
    return stats


def run_cea(scenario: str | None = None) -> None:
    if scenario is not None and scenario not in SCENARIOS:
        raise ValueError(f"Unknown CEA scenario: {scenario}")
    base = _load_cea_config()
    names = SCENARIOS if scenario is None else (scenario,)
    rt, mi = _load_rt()
    results = {}
    for name in names:
        cfg = _scenario_config(base, name)
        results[name] = _run_scenario(rt, mi, cfg, name)
        paths = sum(item["valid_path_count"] for item in results[name]["path_summary"]["receivers"])
        shape = results[name]["map_metadata"]["plotted_array_shape"]
        print(f"CEA {name} OK: {paths} valid paths; radio map {shape}.")
    if scenario is None:
        _compare_configs(results)
        stats = _write_comparison(results)
        print("CEA comparison OK: " + "; ".join(
            f"{name} mean abs diff={values['mean_absolute_delta_db']:.3f} dB, "
            f"max abs diff={values['max_absolute_delta_db']:.3f} dB"
            for name, values in stats.items()))
        print(f"CEA outputs: {OUTPUT_DIR / 'cea'}")

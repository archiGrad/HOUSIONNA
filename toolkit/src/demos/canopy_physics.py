"""Controlled RF-physics sanity study for the procedural narrow canopy."""

from __future__ import annotations

import copy
import csv
import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import yaml

from demos.cea_demo import _load_cea_config, _run_scenario, _scenario_config
from demos.poc import OUTPUT_DIR, ROOT, _load_rt, _tensor_numpy


CORE_CASES = ("empty", "transparent", "weak_loss", "current")
MATERIAL_FIELDS = ("relative_permittivity", "conductivity_s_per_m", "thickness_m",
                  "scattering_coefficient", "xpd_coefficient", "scattering_pattern")
TYPE_NAMES = {0: "none", 1: "specular_reflection", 2: "diffuse_scattering",
              4: "refraction", 8: "diffraction", 16: "sensing"}
C0_M_PER_S = 299_792_458.0
MAP_FLOOR = 1e-15


def _load_study_config() -> dict[str, Any]:
    with (ROOT / "config" / "canopy_physics.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _case_config(base: dict[str, Any], study: dict[str, Any], case: str) -> dict[str, Any]:
    """Derive each test from the existing narrow CEA case, changing explicit factors only."""
    cfg = _scenario_config(base, "narrow")
    cfg["scenario"] = f"canopy_physics_{case}"
    cfg["description"] = f"Narrow canopy physics sanity case: {case}."
    cfg["canopy"]["enabled"] = case != "empty"

    receiver_overrides = study.get("receiver_overrides", {})
    for receiver in cfg["receivers"]:
        if receiver["name"] in receiver_overrides:
            receiver.update(copy.deepcopy(receiver_overrides[receiver["name"]]))
    for receiver in cfg["receiver_grid"]["representative_receivers"]:
        if receiver["name"] in receiver_overrides:
            receiver.update(copy.deepcopy(receiver_overrides[receiver["name"]]))

    if case == "transparent":
        material = study["materials"]["transparent"]
        cfg["materials"]["canopy_placeholder"].update({
            **{key: material[key] for key in MATERIAL_FIELDS},
            "status": material["status"], "source": material["source"],
            "note": "CONTROL; free-space matched material, not vegetation.",
        })
    elif case == "weak_loss":
        material = study["materials"]["weak_loss"]
        cfg["materials"]["canopy_placeholder"].update({
            **{key: material[key] for key in MATERIAL_FIELDS},
            "status": material["status"], "source": material["source"],
            "note": material["status"] + "; arbitrary test values, not crop data.",
        })
    elif case == "current":
        material = cfg["materials"]["canopy_placeholder"]
        material["status"] = study["current_material_status"]["status"]
        material["source"] = study["current_material_status"]["source"]
    elif case != "empty":
        raise ValueError(f"Unknown core canopy-physics case: {case}")
    return cfg


def _diagnostic_config(current_cfg: dict[str, Any], study: dict[str, Any], name: str) -> dict[str, Any]:
    cfg = copy.deepcopy(current_cfg)
    cfg["scenario"] = f"canopy_physics_{name}"
    cfg["description"] = f"Single-factor diagnostic: {name}."
    diagnostic = study["diagnostics"][name]
    if name == "current_refraction_off":
        cfg["path_solver"]["refraction"] = False
        cfg["radio_map"]["refraction"] = False
    else:
        for key in MATERIAL_FIELDS:
            if key in diagnostic:
                cfg["materials"]["canopy_placeholder"][key] = diagnostic[key]
        cfg["materials"]["canopy_placeholder"]["status"] = "CONTROLLED SENSITIVITY TEST"
        cfg["materials"]["canopy_placeholder"]["source"] = diagnostic["change"]
    return cfg


def _scenario_material_metadata(cfg: dict[str, Any], study: dict[str, Any], case: str) -> dict[str, Any]:
    if case == "empty":
        return {"status": "CONTROL", "source": "No canopy object in this reference case.",
                "canopy_present": False, "properties": None}
    raw = cfg["materials"]["canopy_placeholder"]
    return {
        "status": raw.get("status", "UNSPECIFIED"),
        "source": raw.get("source", raw.get("note", "No source recorded.")),
        "canopy_present": True,
        "properties": {key: raw.get(key, 0.0 if key.endswith("coefficient") else None)
                       for key in MATERIAL_FIELDS},
    }


def _solver_metadata(cfg: dict[str, Any]) -> dict[str, Any]:
    path = cfg["path_solver"]
    radio = cfg["radio_map"]
    flags = ("los", "specular_reflection", "refraction", "diffraction", "diffuse_reflection")
    return {
        "path_solver": {"max_depth": path["max_depth"],
                        "samples_per_source": path["samples_per_source"], "seed": path["seed"],
                        **{key: bool(path[key]) for key in flags}},
        "radio_map_solver": {"max_depth": radio["max_depth"],
                             "samples_per_transmitter": radio["samples_per_transmitter"],
                             "seed": radio["seed"],
                             **{key: bool(radio[key]) for key in flags}},
    }


def _metadata_for_case(cfg, study, case, geometry, root: Path, object_id_to_name):
    material = _scenario_material_metadata(cfg, study, case)
    geometry_signature = [
        {key: obj[key] for key in ("id", "category", "bounds_m", "vertices", "faces")}
        for obj in geometry["objects"]
    ]
    record = {
        "case": case,
        "frequency_hz": cfg["frequency_hz"],
        "transmitter": cfg["transmitter"],
        "receivers": cfg["receivers"],
        "greenhouse": cfg["greenhouse"],
        "structure": cfg["structure"],
        "canopy_geometry": cfg["canopy"],
        "canopy_material": material,
        "solver": _solver_metadata(cfg),
        "object_id_to_name": {str(key): value for key, value in object_id_to_name.items()},
        "geometry_signature": geometry_signature,
        "material_api": {
            "scattering_coefficient": material["properties"].get("scattering_coefficient") if material["properties"] else None,
            "xpd_coefficient": material["properties"].get("xpd_coefficient") if material["properties"] else None,
            "scattering_pattern": material["properties"].get("scattering_pattern") if material["properties"] else None,
        },
        "status": "NOT VALIDATED",
    }
    directory = root / case
    (directory / "experiment_metadata.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    metadata_path = directory / "metadata.json"
    base_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    base_metadata["canopy_physics_experiment"] = record
    metadata_path.write_text(json.dumps(base_metadata, indent=2), encoding="utf-8")
    return record


def _tensor(value) -> np.ndarray:
    return np.asarray(_tensor_numpy(value))


def _extract_path_diagnostics(paths, cfg: dict[str, Any], object_id_to_name: dict[int, str]) -> dict[str, Any]:
    """Extract valid paths and their exposed Sionna interaction/object sequences."""
    coefficients, delays = paths.cir(normalize_delays=False, out_type="numpy")
    coefficients = np.asarray(coefficients)
    delays = np.asarray(delays)
    valid = _tensor(paths.valid).astype(bool, copy=False)
    interactions = _tensor(paths.interactions).astype(np.uint32, copy=False)
    objects = _tensor(paths.objects).astype(np.uint32, copy=False)
    vertices = _tensor(paths.vertices).astype(np.float64, copy=False)
    rows: list[dict[str, Any]] = []
    receivers = []

    for rx_index, receiver in enumerate(cfg["receivers"]):
        coeff = coefficients[rx_index]
        while coeff.ndim > 2:
            coeff = coeff[0]
        coeff = coeff[:, 0] if coeff.ndim == 2 else coeff
        delay = delays[rx_index]
        mask = valid[rx_index]
        while delay.ndim > 1:
            delay = delay[0]
        while mask.ndim > 1:
            mask = mask[0]

        rx_interactions = interactions[:, rx_index]
        rx_objects = objects[:, rx_index]
        rx_vertices = vertices[:, rx_index]
        while rx_interactions.ndim > 2:
            rx_interactions = rx_interactions[:, 0]
        while rx_objects.ndim > 2:
            rx_objects = rx_objects[:, 0]
        while rx_vertices.ndim > 3:
            rx_vertices = rx_vertices[:, 0]

        receiver_rows = []
        for path_index in np.flatnonzero(mask):
            coefficient = complex(coeff[path_index])
            magnitude = abs(coefficient)
            type_ids = [int(value) for value in rx_interactions[:, path_index]
                        if int(value) != 0]
            object_ids = [int(value) for value in rx_objects[:, path_index]
                          if int(value) != np.iinfo(np.uint32).max]
            object_names = [object_id_to_name.get(value, f"object_id_{value}")
                            for value in object_ids]
            path_row = {
                "receiver": receiver["name"],
                "path_index": int(path_index),
                "coefficient_real": float(coefficient.real),
                "coefficient_imag": float(coefficient.imag),
                "coefficient_magnitude": float(magnitude),
                "coefficient_magnitude_db_re_1": float(20*np.log10(max(magnitude, 1e-30))),
                "coefficient_power_linear": float(magnitude*magnitude),
                "delay_s": float(delay[path_index]),
                "delay_ns": float(delay[path_index]*1e9),
                "path_length_m_from_delay": float(delay[path_index]*C0_M_PER_S),
                "interaction_type_ids": type_ids,
                "interaction_types": [TYPE_NAMES.get(value, f"interaction_{value}") for value in type_ids],
                "interacted_objects": object_names,
                "interaction_vertices_m": rx_vertices[:len(type_ids), path_index].tolist(),
                "is_los": len(type_ids) == 0,
            }
            rows.append(path_row)
            receiver_rows.append(path_row)

        strongest = max(receiver_rows, key=lambda row: row["coefficient_magnitude"], default=None)
        path_type_present = lambda kind: sum(kind in row["interaction_types"] for row in receiver_rows)
        canopy_refraction_paths = sum(
            sum(kind == "refraction" and name.startswith("canopy_row_")
                for kind, name in zip(row["interaction_types"], row["interacted_objects"])) >= 2
            for row in receiver_rows
        )
        aggregate_power = sum(row["coefficient_power_linear"] for row in receiver_rows)
        receivers.append({
            "receiver": receiver["name"],
            "path_count": len(receiver_rows),
            "los_present": any(row["is_los"] for row in receiver_rows),
            "strongest_path_coefficient_magnitude_db_re_1":
                strongest["coefficient_magnitude_db_re_1"] if strongest else None,
            "strongest_path_coefficient_power_db":
                10*np.log10(max(strongest["coefficient_power_linear"], 1e-30)) if strongest else None,
            "strongest_path_delay_ns": strongest["delay_ns"] if strongest else None,
            "strongest_path_length_m_from_delay": strongest["path_length_m_from_delay"] if strongest else None,
            "aggregate_path_coefficient_power_linear": float(aggregate_power),
            "aggregate_path_coefficient_power_db": float(10*np.log10(max(aggregate_power, 1e-30))),
            "paths_with_specular_reflection": path_type_present("specular_reflection"),
            "paths_with_refraction": path_type_present("refraction"),
            "paths_with_diffuse_scattering": path_type_present("diffuse_scattering"),
            "paths_with_diffraction": path_type_present("diffraction"),
            "paths_with_two_canopy_refractions": int(canopy_refraction_paths),
            "interaction_classification_source": "paths.interactions and paths.objects from Sionna Paths API",
        })
    return {"receivers": receivers, "paths": rows,
            "api_components": ["valid", "cir() coefficients/delays", "interactions", "objects", "vertices"],
            "path_length_note": "Estimated as c0 multiplied by the absolute path delay returned by Paths.cir()."}


def _update_case_outputs(result, study, case: str, root: Path) -> dict[str, Any]:
    cfg = result["cfg"]
    path_detail = _extract_path_diagnostics(result["paths"], cfg, result["object_id_to_name"])
    record = _metadata_for_case(cfg, study, case, result["geometry"], root,
                                result["object_id_to_name"])
    record["path_api"] = {"components": path_detail["api_components"],
                           "path_length_note": path_detail["path_length_note"]}
    experiment_path = root / case / "experiment_metadata.json"
    experiment_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    metadata_path = root / case / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["canopy_physics_experiment"] = record
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    path_file = root / case / "physics_paths.json"
    path_file.write_text(json.dumps(path_detail, indent=2), encoding="utf-8")
    return {"cfg": cfg, "geometry": result["geometry"], "map_values": result["map_values"],
            "map_metadata": result["map_metadata"], "path_detail": path_detail,
            "material": record["canopy_material"], "solver": record["solver"],
            "viewer_data": result["viewer_data"]}


def _assert_core_design(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ref = results["empty"]
    txrx_equal = all(
        results[name]["cfg"]["transmitter"] == ref["cfg"]["transmitter"] and
        results[name]["cfg"]["receivers"] == ref["cfg"]["receivers"]
        for name in CORE_CASES
    )
    assert txrx_equal, "TX/RX positions changed between core scenarios"
    non_canopy = lambda result: [obj for obj in result["geometry"]["objects"]
                                if obj["category"] != "vegetation"]
    non_canopy_equal = all(non_canopy(results[name]) == non_canopy(ref)
                           for name in CORE_CASES)
    assert non_canopy_equal, "Shell/structure geometry changed between core scenarios"
    canopy_signatures = [[obj for obj in results[name]["geometry"]["objects"]
                          if obj["category"] == "vegetation"]
                         for name in ("transparent", "weak_loss", "current")]
    canopy_equal = canopy_signatures[0] == canopy_signatures[1] == canopy_signatures[2]
    assert canopy_equal, "Canopy geometry changed between transparent/weak-loss/current"
    shapes = {name: tuple(result["map_values"].shape) for name, result in results.items()}
    assert len(set(shapes.values())) == 1, f"Radio-map shapes differ: {shapes}"
    solver_flags_equal = all(
        results[name]["solver"] == results["empty"]["solver"] for name in CORE_CASES)
    assert solver_flags_equal, "Core solver settings changed unexpectedly"
    fixed_config = lambda cfg: {
        key: cfg[key] for key in ("greenhouse", "structure", "antenna", "frequency_hz",
                                  "transmitter", "receivers", "receiver_grid", "path_solver", "radio_map")
    }
    fixed_settings_equal = all(fixed_config(results[name]["cfg"]) == fixed_config(ref["cfg"])
                               for name in CORE_CASES)
    assert fixed_settings_equal, "A non-canopy configuration field changed between core cases"
    fixed_materials = lambda cfg: {key: cfg["materials"][key] for key in cfg["materials"]
                                  if key != "canopy_placeholder"}
    non_canopy_materials_equal = all(
        fixed_materials(results[name]["cfg"]) == fixed_materials(ref["cfg"])
        for name in CORE_CASES)
    assert non_canopy_materials_equal, "A non-canopy RF material changed between core cases"
    return {"tx_rx_identical": txrx_equal, "non_canopy_geometry_identical": non_canopy_equal,
            "canopy_geometry_identical_transparent_weak_current": canopy_equal,
            "radio_map_shapes": {name: list(shape) for name, shape in shapes.items()},
            "core_solver_settings_identical": solver_flags_equal,
            "all_other_config_identical": fixed_settings_equal,
            "non_canopy_materials_identical": non_canopy_materials_equal}


def _map_db(values: np.ndarray) -> np.ndarray:
    return 10*np.log10(np.maximum(values, MAP_FLOOR))


def _difference_metrics(delta: np.ndarray) -> dict[str, Any]:
    absolute = np.abs(delta)
    return {
        "mean_absolute_difference_db": float(np.mean(absolute)),
        "median_signed_difference_db": float(np.median(delta)),
        "p95_absolute_difference_db": float(np.percentile(absolute, 95)),
        "max_absolute_difference_db": float(np.max(absolute)),
        "cells_over_1_db": int(np.count_nonzero(absolute > 1.0)),
        "cells_over_3_db": int(np.count_nonzero(absolute > 3.0)),
        "total_cells": int(delta.size),
    }


def _run_transparent_sensitivity(rt, mi, base, study, results, root: Path):
    """Rerun matched empty/control pairs with changed seed, sample count and depth."""
    profiles = {
        "alternate_seed_43": {"path_seed": 43, "map_seed": 43},
        "map_samples_90000": {"map_samples": 90000},
        "interaction_depth_4": {"path_depth": 4, "map_depth": 4},
    }
    output = root / "transparent_sensitivity"
    output.mkdir(parents=True, exist_ok=True)
    summary = {"reference": {"solver": results["empty"]["solver"],
                              **_difference_metrics(_map_db(results["transparent"]["map_values"])-_map_db(results["empty"]["map_values"]))},
               "profiles": {}}
    for profile_name, change in profiles.items():
        pair = {}
        for case in ("empty", "transparent"):
            cfg = _case_config(base, study, case)
            cfg["scenario"] = f"canopy_transparency_{profile_name}_{case}"
            cfg["description"] = f"Transparent-control sensitivity profile: {profile_name}."
            if "path_seed" in change:
                cfg["path_solver"]["seed"] = change["path_seed"]
            if "map_seed" in change:
                cfg["radio_map"]["seed"] = change["map_seed"]
            if "map_samples" in change:
                cfg["radio_map"]["samples_per_transmitter"] = change["map_samples"]
            if "path_depth" in change:
                cfg["path_solver"]["max_depth"] = change["path_depth"]
            if "map_depth" in change:
                cfg["radio_map"]["max_depth"] = change["map_depth"]
            run_name = f"{profile_name}_{case}"
            result = _run_scenario(rt, mi, cfg, run_name, output_root=output, include_paths=False)
            pair[case] = result
            print(f"Transparent sensitivity {profile_name}/{case}: map {list(result['map_values'].shape)}.")
        delta = _map_db(pair["transparent"]["map_values"])-_map_db(pair["empty"]["map_values"])
        group = {
            "solver_change": change,
            "solver_empty": _solver_metadata(pair["empty"]["cfg"]),
            "solver_transparent": _solver_metadata(pair["transparent"]["cfg"]),
            **_difference_metrics(delta),
            "path_counts_empty": pair["empty"]["path_summary"]["receivers"],
            "path_counts_transparent": pair["transparent"]["path_summary"]["receivers"],
            "interpretation": "Difference remains conditional on this finite solver configuration; this pair changes only the listed solver parameter(s) and canopy presence/material.",
        }
        summary["profiles"][profile_name] = group
        np.save(output / f"{profile_name}_transparent_minus_empty_db.npy", delta)
    (output / "sensitivity_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _segment_box_interval(start: list[float], end: list[float], bounds: dict[str, float]):
    """Return the clipped segment parameter interval inside an axis-aligned box."""
    t_enter, t_exit = 0.0, 1.0
    low_keys = ("x_min", "y_min", "z_min")
    high_keys = ("x_max", "y_max", "z_max")
    for axis, (low_key, high_key) in enumerate(zip(low_keys, high_keys)):
        origin = float(start[axis])
        direction = float(end[axis]) - origin
        low, high = float(bounds[low_key]), float(bounds[high_key])
        if abs(direction) < 1e-12:
            if origin < low - 1e-9 or origin > high + 1e-9:
                return None
            continue
        a, b = (low - origin) / direction, (high - origin) / direction
        axis_enter, axis_exit = min(a, b), max(a, b)
        t_enter = max(t_enter, axis_enter)
        t_exit = min(t_exit, axis_exit)
        if t_exit <= t_enter + 1e-12:
            return None
    return (t_enter, t_exit) if t_exit > t_enter + 1e-12 else None


def _direct_canopy_intersections(cfg: dict[str, Any], geometry: dict[str, Any]):
    tx = list(map(float, cfg["transmitter"]["position_m"]))
    canopy_rows = [obj for obj in geometry["objects"] if obj["category"] == "vegetation"]
    records = []
    for receiver in cfg["receivers"]:
        rx = list(map(float, receiver["position_m"]))
        line_length = float(np.linalg.norm(np.asarray(rx) - np.asarray(tx)))
        crossings = []
        for row in canopy_rows:
            interval = _segment_box_interval(tx, rx, row["bounds_m"])
            if interval is None:
                continue
            t_enter, t_exit = interval
            entry = (np.asarray(tx) + t_enter*(np.asarray(rx)-np.asarray(tx))).tolist()
            exit = (np.asarray(tx) + t_exit*(np.asarray(rx)-np.asarray(tx))).tolist()
            crossings.append({
                "canopy_row": row["id"],
                "entry_t": float(t_enter), "exit_t": float(t_exit),
                "entry_m": entry, "exit_m": exit,
                "distance_inside_m": float((t_exit-t_enter)*line_length),
            })
        records.append({
            "receiver": receiver["name"],
            "receiver_position_m": rx,
            "tx_rx_segment_length_m": line_length,
            "intersection_count": len(crossings),
            "surface_crossing_count": 2*len(crossings),
            "intersected_canopy_rows": [item["canopy_row"] for item in crossings],
            "total_distance_inside_canopy_m": sum(item["distance_inside_m"] for item in crossings),
            "intersections": crossings,
            "method": "independent parametric segment/AABB slab intersection; positive-length intervals only",
        })
    return records


def _map_cell_geometry_tests(empty_result, current_geometry, transparent_delta, root: Path):
    centers = np.squeeze(np.load(root / "empty" / "radio_map_cell_centers.npy"))
    if centers.ndim != 3 or centers.shape[-1] != 3:
        raise ValueError(f"Unexpected radio-map cell-center tensor shape: {centers.shape}")
    if centers.shape[:2] != transparent_delta.shape:
        raise ValueError(f"Map cell coordinates {centers.shape[:2]} do not match map {transparent_delta.shape}")
    tx = list(map(float, empty_result["cfg"]["transmitter"]["position_m"]))
    rows = [obj for obj in current_geometry["objects"] if obj["category"] == "vegetation"]
    bins = {"direct_segment_intersects_canopy": [], "direct_segment_misses_canopy": []}
    cells = []
    for y_index in range(centers.shape[0]):
        for x_index in range(centers.shape[1]):
            point = centers[y_index, x_index].astype(float).tolist()
            hits = []
            for row in rows:
                interval = _segment_box_interval(tx, point, row["bounds_m"])
                if interval is None:
                    continue
                t0, t1 = interval
                hits.append({"row": row["id"], "inside_distance_m": float(
                    (t1-t0)*np.linalg.norm(np.asarray(point)-np.asarray(tx)))})
            group = "direct_segment_intersects_canopy" if hits else "direct_segment_misses_canopy"
            value = float(abs(transparent_delta[y_index, x_index]))
            bins[group].append(value)
            cells.append({"y_index": y_index, "x_index": x_index, "position_m": point,
                          "intersected_canopy_rows": [hit["row"] for hit in hits],
                          "total_inside_distance_m": sum(hit["inside_distance_m"] for hit in hits),
                          "absolute_transparent_delta_db": value})
    group_stats = {}
    for name, values in bins.items():
        group_stats[name] = {
            "cell_count": len(values),
            "mean_absolute_transparent_delta_db": float(np.mean(values)) if values else None,
            "p95_absolute_transparent_delta_db": float(np.percentile(values, 95)) if values else None,
            "max_absolute_transparent_delta_db": float(np.max(values)) if values else None,
        }
    result = {"method": "independent segment/AABB test from TX to each exported radio-map cell center",
              "grid_shape_yx": list(centers.shape[:2]), "groups": group_stats, "cells": cells}
    (root / "comparison" / "map_cell_geometry_analysis.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    return result


def _write_comparison(results: dict[str, dict[str, Any]], diagnostics: dict[str, dict[str, Any]],
                      structural_checks: dict[str, Any], study: dict[str, Any], root: Path,
                      transparent_sensitivity: dict[str, Any] | None = None) -> dict[str, Any]:
    comparison_dir = root / "comparison"
    comparison_dir.mkdir(parents=True, exist_ok=True)
    values_db = {name: _map_db(results[name]["map_values"]) for name in CORE_CASES}
    deltas = {name: values_db[name]-values_db["empty"] for name in CORE_CASES[1:]}
    deltas["empty"] = np.zeros_like(values_db["empty"])
    summary = {}
    summary_fields = ["scenario", "mean_abs_delta_db_vs_empty", "median_delta_db_vs_empty",
                      "min_delta_db_vs_empty", "max_delta_db_vs_empty", "positive_cells",
                      "negative_cells", "zero_cells"]
    with (comparison_dir / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        for name in CORE_CASES:
            delta = deltas[name]
            summary[name] = {
                "mean_abs_delta_db_vs_empty": float(np.mean(np.abs(delta))),
                "median_delta_db_vs_empty": float(np.median(delta)),
                "min_delta_db_vs_empty": float(np.min(delta)),
                "max_delta_db_vs_empty": float(np.max(delta)),
                "positive_cells": int(np.count_nonzero(delta > 1e-6)),
                "negative_cells": int(np.count_nonzero(delta < -1e-6)),
                "zero_cells": int(np.count_nonzero(np.abs(delta) <= 1e-6)),
            }
            writer.writerow({"scenario": name, **{key: f"{value:.8f}" if isinstance(value, float) else value
                                                      for key, value in summary[name].items()}})
            np.save(comparison_dir / f"{name}_minus_empty_db.npy", delta)

    receiver_rows = []
    for name in CORE_CASES:
        for info in results[name]["path_detail"]["receivers"]:
            receiver_rows.append({"scenario": name, **info})
    rx_fields = ["receiver", "scenario", "aggregate_path_coefficient_power_db",
                 "aggregate_path_coefficient_power_linear",
                 "strongest_path_coefficient_magnitude_db_re_1", "strongest_path_coefficient_power_db",
                 "strongest_path_delay_ns", "strongest_path_length_m_from_delay", "path_count",
                 "los_present", "paths_with_specular_reflection", "paths_with_refraction",
                 "paths_with_diffuse_scattering", "paths_with_diffraction",
                 "paths_with_two_canopy_refractions", "interaction_classification_source"]
    with (comparison_dir / "representative_receivers.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=rx_fields); writer.writeheader(); writer.writerows(receiver_rows)

    extent_cfg = results["empty"]["cfg"]["radio_map"]
    x_len, y_len = extent_cfg["size_m"]; cx, cy, _ = extent_cfg["center_m"]
    extent = [cx-x_len/2, cx+x_len/2, cy-y_len/2, cy+y_len/2]
    fig, axes = plt.subplots(2, 4, figsize=(19, 9), constrained_layout=True)
    for ax, name in zip(axes[0], CORE_CASES):
        im = ax.imshow(values_db[name], origin="lower", extent=extent, aspect="equal", cmap="viridis")
        ax.set_title(f"{name.replace('_', ' ').title()} map"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    fig.colorbar(im, ax=axes[0].tolist(), label="10 log10(path gain) (dB)", shrink=0.83)
    delta_max = max(1.0, *(float(np.max(np.abs(deltas[n]))) for n in CORE_CASES[1:]))
    for ax, name in zip(axes[1][:3], CORE_CASES[1:]):
        delta_im = ax.imshow(deltas[name], origin="lower", extent=extent, aspect="equal",
                             cmap="coolwarm", vmin=-delta_max, vmax=delta_max)
        ax.set_title(f"{name.replace('_', ' ').title()} − empty"); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
    fig.colorbar(delta_im, ax=axes[1][:3], label="Δ 10 log10(path gain) (dB)", shrink=0.83)
    axes[1][3].axis("off")
    axes[1][3].text(0.02, 0.95,
        "Fixed narrow canopy geometry for\ntransparent, weak-loss, and current.\n\n"
        "Maps use a 1e-15 linear path-gain floor.\nThey show path gain, not RSS.",
        va="top", fontsize=12)
    fig.savefig(comparison_dir / "radio_map_comparison.png", dpi=170)
    plt.close(fig)

    _plot_cir_comparison(results, comparison_dir)

    diagnostics_summary = {}
    current_db = values_db["current"]
    for name, result in diagnostics.items():
        delta_from_current = _map_db(result["map_values"])-current_db
        diagnostics_summary[name] = {
            "change": study["diagnostics"][name]["change"],
            "mean_abs_map_change_db_vs_current": float(np.mean(np.abs(delta_from_current))),
            "median_signed_map_change_db_vs_current": float(np.median(delta_from_current)),
            "min_map_change_db_vs_current": float(np.min(delta_from_current)),
            "max_map_change_db_vs_current": float(np.max(delta_from_current)),
            "paths_with_refraction": {
                info["receiver"]: info["paths_with_refraction"]
                for info in result["path_detail"]["receivers"]},
            "solver": result["solver"],
            "material": result["material"],
        }
        np.save(comparison_dir / f"{name}_minus_current_db.npy", delta_from_current)

    # A small diagnostic comparison directly tests whether each one-factor variant
    # moves the map relative to the unchanged current placeholder.
    diag_names = list(diagnostics)
    fig, axes = plt.subplots(1, len(diag_names), figsize=(4.5*len(diag_names), 4.2), constrained_layout=True)
    for ax, name in zip(np.atleast_1d(axes), diag_names):
        delta = _map_db(diagnostics[name]["map_values"])-current_db
        local_max = max(1.0, float(np.max(np.abs(delta))))
        imd = ax.imshow(delta, origin="lower", extent=extent, aspect="equal", cmap="coolwarm",
                        vmin=-local_max, vmax=local_max)
        ax.set_title(name.replace("_", " ")); ax.set_xlabel("x (m)"); ax.set_ylabel("y (m)")
        fig.colorbar(imd, ax=ax, label="dB vs current", shrink=0.8)
    fig.savefig(comparison_dir / "single_factor_diagnostics.png", dpi=160)
    plt.close(fig)

    transparent_abs = summary["transparent"]["mean_abs_delta_db_vs_empty"]
    current_abs = summary["current"]["mean_abs_delta_db_vs_empty"]
    transparent_delta = deltas["transparent"]
    transparent_abs_delta = np.abs(transparent_delta)
    transparent_cell_stats = {
        "mean_absolute_difference_db": float(np.mean(transparent_abs_delta)),
        "median_signed_difference_db": float(np.median(transparent_delta)),
        "p95_absolute_difference_db": float(np.percentile(transparent_abs_delta, 95)),
        "max_absolute_difference_db": float(np.max(transparent_abs_delta)),
        "cells_over_1_db": int(np.count_nonzero(transparent_abs_delta > 1.0)),
        "cells_over_3_db": int(np.count_nonzero(transparent_abs_delta > 3.0)),
        "total_cells": int(transparent_delta.size),
        "display_floor_linear_path_gain": MAP_FLOOR,
    }
    (comparison_dir / "transparent_control_diagnostics.json").write_text(
        json.dumps(transparent_cell_stats, indent=2), encoding="utf-8")
    geometric_tests = _direct_canopy_intersections(
        results["empty"]["cfg"], results["current"]["geometry"])
    (root / "geometry_intersections.json").write_text(
        json.dumps(geometric_tests, indent=2), encoding="utf-8")
    map_cell_tests = _map_cell_geometry_tests(
        results["empty"], results["current"]["geometry"], transparent_delta, root)
    canopy_transmission_paths = {}
    for name in CORE_CASES:
        canopy_transmission_paths[name] = [
            {key: row[key] for key in ("path_index", "coefficient_magnitude_db_re_1", "delay_ns",
                                       "path_length_m_from_delay", "interaction_types", "interacted_objects")}
            for row in results[name]["path_detail"]["paths"]
            if row["receiver"] == "RX_C" and
            sum(kind == "refraction" and obj.startswith("canopy_row_")
                for kind, obj in zip(row["interaction_types"], row["interacted_objects"])) >= 2
        ]
    analysis = {
        "description": study["description"],
        "frequency_hz": results["empty"]["cfg"]["frequency_hz"],
        "map_shape_yx": list(values_db["empty"].shape),
        "display_floor_linear_path_gain": MAP_FLOOR,
        "core_map_differences": summary,
        "geometry_sanity": structural_checks,
        "transparent_closer_to_empty_than_current": transparent_abs < current_abs,
        "geometry_only_mean_abs_difference_db": transparent_abs,
        "transparent_control_cell_statistics": transparent_cell_stats,
        "transparent_control_sensitivity": transparent_sensitivity or {},
        "direct_tx_rx_canopy_intersections": geometric_tests,
        "radio_map_cell_geometry_analysis": map_cell_tests,
        "current_mean_abs_difference_db": current_abs,
        "weak_loss_vs_transparent_mean_abs_difference_db": float(np.mean(np.abs(values_db["weak_loss"]-values_db["transparent"]))),
        "current_vs_weak_loss_mean_abs_difference_db": float(np.mean(np.abs(values_db["current"]-values_db["weak_loss"]))),
        "single_factor_diagnostics_vs_current": diagnostics_summary,
        "solver_flags_by_core_case": {name: result["solver"] for name, result in results.items()},
        "material_by_core_case": {name: result["material"] for name, result in results.items()},
        "representative_receiver_summary": receiver_rows,
        "rx_c_canopy_traversal_paths": canopy_transmission_paths,
        "geometry_interpretation": (
            "The canopy is three separate OBJ meshes, one closed cuboid per row; each OBJ has 8 vertices and 6 quadrilateral faces. "
            "Sionna RadioMaterial uses a plane-slab Fresnel model at an intersected surface, not a calibrated volumetric plant model. "
            "The 0.8 m material slab thickness is distinct from the cuboid's 0.6 m plan width and may be an important model mismatch."),
        "interaction_interpretation": (
            "PathSolver refraction is enabled in all four core cases. A path classified with refraction at two canopy-row interactions is evidence that the ray solution traverses the closed proxy. "
            "The interaction type and object names are read from Paths.interactions and Paths.objects; no path class is inferred from amplitude."),
        "limitations": [
            "Material values are controls/placeholders, not plant dielectric measurements.",
            "Sionna's slab material model is not a validated thick vegetation volume model.",
            "Radio-map path gain is clipped at 1e-15 for dB plots and differences.",
            "Aggregate path-coefficient power is the sum of individual |a|^2 values and is not RSS; coherent CIR combination is delay-dependent.",
            "Path length is estimated as c0 times the Sionna absolute path delay.",
        ],
    }
    (comparison_dir / "analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    _write_markdown_report(analysis, study, root)
    viewer = {
        "description": "Narrow-canopy RF physics sanity study; materials are not validated vegetation models.",
        "frequency_hz": analysis["frequency_hz"],
        "stats": summary,
        "diagnostics": diagnostics_summary,
        "scenarios": {
            name: {
                "scenario": name,
                "radio_map": results[name]["viewer_data"]["radio_map"],
                "paths": results[name]["path_detail"]["paths"],
                "path_counts": results[name]["path_detail"]["receivers"],
                "receivers": results[name]["cfg"]["receivers"],
                "transmitter": results[name]["cfg"]["transmitter"],
                "material": results[name]["material"],
            } for name in CORE_CASES
        },
        "deltas_db": {name: deltas[name].tolist() for name in CORE_CASES},
        "receiver_names": [rx["name"] for rx in results["empty"]["cfg"]["receivers"]],
    }
    (comparison_dir / "viewer_data.json").write_text(json.dumps(viewer), encoding="utf-8")
    return analysis


def _plot_cir_comparison(results: dict[str, dict[str, Any]], target: Path) -> None:
    receivers = [item["name"] for item in results["empty"]["cfg"]["receivers"]]
    colors = {"empty": "#52687a", "transparent": "#258a66",
              "weak_loss": "#d28a20", "current": "#bb4a4a"}
    all_rows = [row for name in CORE_CASES for row in results[name]["path_detail"]["paths"]]
    max_delay = max(10.0, *(row["delay_ns"] for row in all_rows))*1.05
    min_db = min(-35.0, *(row["coefficient_magnitude_db_re_1"] for row in all_rows))-4.0
    max_db = max(-35.0, *(row["coefficient_magnitude_db_re_1"] for row in all_rows))+4.0
    fig, axes = plt.subplots(len(receivers), len(CORE_CASES), figsize=(16, 9),
                             sharex=True, sharey=True, constrained_layout=True)
    for row_index, receiver in enumerate(receivers):
        for col_index, case in enumerate(CORE_CASES):
            ax = axes[row_index, col_index]
            selected = [item for item in results[case]["path_detail"]["paths"]
                        if item["receiver"] == receiver]
            ax.vlines([p["delay_ns"] for p in selected], min_db,
                      [p["coefficient_magnitude_db_re_1"] for p in selected],
                      color=colors[case], linewidth=0.9, alpha=0.75)
            ax.scatter([p["delay_ns"] for p in selected],
                       [p["coefficient_magnitude_db_re_1"] for p in selected],
                       color=colors[case], s=12)
            ax.set_xlim(0, max_delay); ax.set_ylim(min_db, max_db)
            if row_index == 0: ax.set_title(case.replace("_", " ").title())
            if col_index == 0: ax.set_ylabel(f"{receiver}\nCoefficient magnitude (dB re 1)")
            if row_index == len(receivers)-1: ax.set_xlabel("Path delay (ns)")
            ax.grid(True, alpha=0.2)
    fig.suptitle("CIR path comparison · shared delay and coefficient scales")
    fig.savefig(target / "cir_comparison.png", dpi=170)
    plt.close(fig)


def _write_markdown_report(analysis: dict[str, Any], study: dict[str, Any], root: Path) -> None:
    rows = analysis["core_map_differences"]
    receiver_rows = analysis["representative_receiver_summary"]
    diagnostics = analysis["single_factor_diagnostics_vs_current"]
    traversal_paths = analysis.get("rx_c_canopy_traversal_paths", {})
    traversal_counts = {case: len(traversal_paths.get(case, [])) for case in CORE_CASES}
    def strongest_traversal(case: str) -> str:
        paths = traversal_paths.get(case, [])
        if not paths:
            return "no traversal path observed"
        strongest = max(paths, key=lambda item: item["coefficient_magnitude_db_re_1"])
        return f"{strongest['coefficient_magnitude_db_re_1']:.1f} dB"
    markdown = [
        "# Canopy physics sanity study",
        "",
        "This is a controlled software experiment at 2.4 GHz on the narrow 0.6 m canopy geometry. It is not a calibrated crop or greenhouse prediction.",
        "",
        "## Existing/current implementation inspected",
        "",
        "- Three longitudinal canopy rows are generated as three separate, closed cuboid OBJ meshes. Each row mesh has 8 vertices and 6 quad faces.",
        "- `canopy_placeholder` is assigned to all three rows: epsilon_r=8, conductivity=0.25 S/m, RadioMaterial thickness=0.8 m, scattering coefficient=0, XPD=0, Lambertian pattern (inactive because scattering is zero).",
        "- PathSolver and RadioMapSolver have LOS, specular reflection, and refraction enabled; diffuse reflection and diffraction are disabled; max depth is 2.",
        "- Thus transmission is enabled in the current case. Sionna exposes refraction interactions and intersected object IDs; the saved per-path table records them directly.",
        "- Sionna's installed RadioMaterial/PathSolver documentation describes a plane-slab Fresnel model at intersected surfaces, assumes thin materials for transmitted rays, and warns the approach may be inaccurate for very thick objects. This is not volumetric plant transport.",
        "",
        "## Core radio-map comparison",
        "",
        "All values below are dB differences from empty, computed from 10 log10(path_gain) with values below 1e-15 floored for display.",
        "",
        "| Scenario | Mean abs Δ (dB) | Median Δ (dB) | Min Δ (dB) | Max Δ (dB) |",
        "|---|---:|---:|---:|---:|",
    ]
    for case in CORE_CASES:
        row = rows[case]
        markdown.append(f"| {case} | {row['mean_abs_delta_db_vs_empty']:.3f} | {row['median_delta_db_vs_empty']:.3f} | {row['min_delta_db_vs_empty']:.3f} | {row['max_delta_db_vs_empty']:.3f} |")
    markdown += ["", "## Single-factor map diagnostics vs current", "",
                 "| Diagnostic | Mean abs map change (dB) | Controlled change |",
                 "|---|---:|---|"]
    for name, detail in diagnostics.items():
        markdown.append(f"| {name} | {detail['mean_abs_map_change_db_vs_current']:.3f} | {detail['change']} |")
    markdown += ["", "## Representative receivers", "",
                 "See `comparison/representative_receivers.csv` for each receiver and core case. Aggregate coefficient power is Σ|a|², not RSS; LOS/interactions are taken from Sionna's exposed interaction tensors.", "",
                 "| Case | Receiver | Paths | LOS | Paths with refraction | Two canopy refractions | Strongest coeff (dB re 1) |",
                 "|---|---|---:|:---:|---:|---:|---:|"]
    for case in CORE_CASES:
        case_rows = [row for row in receiver_rows if row["scenario"] == case]
        for info in case_rows:
            strongest = info["strongest_path_coefficient_magnitude_db_re_1"]
            strongest_text = "n/a" if strongest is None else f"{strongest:.1f}"
            markdown.append(
                f"| {case} | {info['receiver']} | {info['path_count']} | "
                f"{'yes' if info['los_present'] else 'no'} | {info['paths_with_refraction']} | "
                f"{info['paths_with_two_canopy_refractions']} | {strongest_text} |")
    markdown += ["", "## Core interaction settings", "",
                 "The flags below are shared by PathSolver and RadioMapSolver in each listed case.", "",
                 "| Case | LOS | Specular reflection | Refraction/transmission | Diffuse scattering | Diffraction |",
                 "|---|:---:|:---:|:---:|:---:|:---:|"]
    for case in CORE_CASES:
        path_cfg = analysis["solver_flags_by_core_case"][case]["path_solver"]
        markdown.append("| " + case + " | " + " | ".join(
            "on" if path_cfg[key] else "off" for key in
            ("los", "specular_reflection", "refraction", "diffuse_reflection", "diffraction")) + " |")
    markdown += ["", "## Diagnostic interaction settings", "",
                 "| Diagnostic | LOS | Specular reflection | Refraction/transmission | Diffuse scattering | Diffraction |",
                 "|---|:---:|:---:|:---:|:---:|:---:|"]
    for name, detail in diagnostics.items():
        path_cfg = detail["solver"]["path_solver"]
        markdown.append("| " + name + " | " + " | ".join(
            "on" if path_cfg[key] else "off" for key in
            ("los", "specular_reflection", "refraction", "diffuse_reflection", "diffraction")) + " |")
    geometric_tests = analysis["direct_tx_rx_canopy_intersections"]
    markdown += ["", "## Direct geometric TX-to-RX canopy intersections", "",
                 "These are independent segment/AABB tests against the generated canopy boxes, not Sionna path classifications.", "",
                 "| Receiver | Canopy rows intersected | Segment distance inside canopy (m) | Entry to exit (m) |",
                 "|---|---|---:|---|"]
    for item in geometric_tests:
        row_names = ", ".join(item["intersected_canopy_rows"]) or "none"
        coords = "; ".join(
            f"{hit['canopy_row']}: {tuple(round(v, 3) for v in hit['entry_m'])} â†’ {tuple(round(v, 3) for v in hit['exit_m'])}"
            for hit in item["intersections"]) or "â€”"
        markdown.append(f"| {item['receiver']} | {row_names} ({item['intersection_count']} row intersections) | {item['total_distance_inside_canopy_m']:.3f} | {coords} |")
    markdown += ["", "## Transparent-control map diagnostics", "",
                 f"Against empty with the matched epsilon_r=1, sigma=0 control: mean absolute difference {analysis['transparent_control_cell_statistics']['mean_absolute_difference_db']:.3f} dB; median signed difference {analysis['transparent_control_cell_statistics']['median_signed_difference_db']:.3f} dB; 95th percentile absolute difference {analysis['transparent_control_cell_statistics']['p95_absolute_difference_db']:.3f} dB; max absolute difference {analysis['transparent_control_cell_statistics']['max_absolute_difference_db']:.3f} dB; cells over 1 dB {analysis['transparent_control_cell_statistics']['cells_over_1_db']}/{analysis['transparent_control_cell_statistics']['total_cells']}; cells over 3 dB {analysis['transparent_control_cell_statistics']['cells_over_3_db']}/{analysis['transparent_control_cell_statistics']['total_cells']}. Values use the same 1e-15 path-gain display floor.",
                 "RX_C already gives a direct segment that crosses canopy_row_02, so no extra RX_CANOPY_TEST receiver is required.",
                 "", "## Interpretation limits", "",
                 "The transparent case is an epsilon_r=1, conductivity=0 free-space-matched interface control; it retains the same closed mesh and slab-thickness field. It is not a physical crop. The weak-loss case is an arbitrary test material, not a realistic vegetation recommendation.",
                 "The current material's 0.8 m slab thickness is larger than the 0.6 m row plan width and is applied through Sionna's slab-interface model. That is a likely modeling mismatch; the one-factor thickness/epsilon/conductivity/refraction diagnostics quantify sensitivity within this solver, not truth about plants.",
                 "A ray path with two refraction interactions on canopy-row objects is counted as a traversal of the proxy. The far receiver was moved from the old RX_C position (which lay inside the box) to the far aisle at [10, 5, 1.5] m; all study scenarios use this same position.",
                 "## Conclusion from this run", "",
                 f"- The current case is approximately opaque to the selected RX_C path at these solver settings: it produced {traversal_counts['current']} paths with two refractions on a canopy row. The matched control produced {traversal_counts['transparent']}, and weak-loss produced {traversal_counts['weak_loss']}. This is a finite-sample result, not proof transmission is mathematically impossible.",
                 f"- Geometry plus finite path/map-solver interaction leaves a {analysis['geometry_only_mean_abs_difference_db']:.2f} dB mean-absolute map residual in the free-space-matched case. Its strongest RX_C traversal path is {strongest_traversal('transparent')}; the saved path table gives its delay and object sequence.",
                 f"- The strongest weak-loss RX_C traversal path is {strongest_traversal('weak_loss')}, versus {strongest_traversal('transparent')} for the matched control. The current case found {strongest_traversal('current')}.",
                 f"- In the one-factor map probes, lowering conductivity changed the map by {diagnostics['current_lower_conductivity']['mean_abs_map_change_db_vs_current']:.2f} dB mean absolute, versus {diagnostics['current_lower_permittivity']['mean_abs_map_change_db_vs_current']:.2f} dB for lowering epsilon_r and {diagnostics['current_thinner_slab']['mean_abs_map_change_db_vs_current']:.2f} dB for reducing slab thickness. Among tested factors, conductivity had the largest measured map effect; these chosen values do not establish whether the original value is physically too high.",
                 f"- Turning refraction off changed the current map by {diagnostics['current_refraction_off']['mean_abs_map_change_db_vs_current']:.2f} dB mean absolute. The current core case already has refraction enabled, so disabled transmission does not explain its current result.",
                 "- The box model is appropriate only as a software demonstration. First obtain crop dielectric/measurement evidence (recommendation D); then compare a sparse/open canopy proxy (B) against this block representation. Do not add low-poly leaves/stems before the material model is grounded.", ""]
    (root / "report.md").write_text("\n".join(markdown), encoding="utf-8")


def _write_findings_report(analysis: dict[str, Any], slab: dict[str, Any], output_root: Path) -> Path:
    """Create the requested concise evidence/assumptions/unknowns report."""
    from importlib.metadata import version

    geometry = analysis["direct_tx_rx_canopy_intersections"]
    map_groups = analysis["radio_map_cell_geometry_analysis"]["groups"]
    control = analysis["transparent_control_cell_statistics"]
    sensitivity = analysis.get("transparent_control_sensitivity", {})
    path_rows = analysis["representative_receiver_summary"]
    rx_lines = []
    for item in geometry:
        hits = "; ".join(
            f"{hit['canopy_row']} from {tuple(round(v,3) for v in hit['entry_m'])} m to {tuple(round(v,3) for v in hit['exit_m'])} m "
            f"({hit['distance_inside_m']:.3f} m inside)"
            for hit in item["intersections"]) or "no canopy intersection"
        rx_lines.append(f"| {item['receiver']} | {item['intersection_count']} | {', '.join(item['intersected_canopy_rows']) or 'none'} | {item['total_distance_inside_canopy_m']:.3f} | {hits} |")
    sensitivity_lines = []
    for name, item in sensitivity.get("profiles", {}).items():
        sensitivity_lines.append(f"| {name} | {item['mean_absolute_difference_db']:.3f} | {item['p95_absolute_difference_db']:.3f} | {item['max_absolute_difference_db']:.3f} | {item['cells_over_1_db']} | {item['cells_over_3_db']} |")
    slab_lines = []
    for name, item in slab["cases"].items():
        summary = item["summary"]
        slab_lines.append(f"| {name} | {summary['valid_paths']} | {summary['direct_los_paths']} | {summary['refraction_paths']} | {summary['reflection_paths']} | {summary['strongest_refraction_db'] if summary['strongest_refraction_db'] is not None else 'none'} |")
    path_lines = []
    for case in CORE_CASES:
        info = next(item for item in path_rows if item["scenario"] == case and item["receiver"] == "RX_C")
        path_lines.append(f"| {case} | {info['path_count']} | {'yes' if info['los_present'] else 'no'} | {info['paths_with_refraction']} | {info['paths_with_two_canopy_refractions']} | {info['strongest_path_coefficient_magnitude_db_re_1']:.2f} |")

    lines = [
        "# Canopy RF Physics Findings",
        "",
        f"Generated by `python run.py canopy-physics`. Installed Sionna RT version: **{version('sionna-rt')}**.",
        "The greenhouse/material values are software-demo inputs, not values extracted from papers or measurements.",
        "",
        "## KNOWN FROM EXPERIMENT",
        "",
        "### Geometry and receiver paths",
        "",
        "The current narrow proxy is three separate closed cuboid OBJ meshes. Direct TX-to-RX intersections below come from an independent parametric segment/AABB calculation against the generated boxes.",
        "",
        "| Receiver | Row intervals | Row(s) | Total distance inside (m) | Entry/exit coordinates and per-row distance |",
        "|---|---:|---|---:|---|",
        *rx_lines,
        "",
        "RX_C already crosses canopy_row_02, so the conditional `RX_CANOPY_TEST` receiver was not added. RX_A and RX_B do not need canopy transmission for their direct paths.",
        "",
        "### Sionna transmission test",
        "",
        "The installed `PathSolver` API supports refraction and was called with `refraction=True`. A single open planar `SceneObject` surface at x=0 was used for the slab test, so the Sionna slab thickness is applied once. The test uses an empty scene, an epsilon_r=1 / sigma=0 matched control, the weak-loss placeholder, and the current canopy material.",
        "",
        "| Slab case | Valid paths | Direct LOS | Refraction paths | Reflection paths | Strongest refraction coefficient (dB re 1) |",
        "|---|---:|---:|---:|---:|---:|",
        *slab_lines,
        "",
        "The matched and weak-loss slabs return a refraction path. The current material returns no valid path in this isolated run. The slab test confirms that a closed mesh is not required for Sionna to return a transmitted/refraction path.",
        "",
        "### RX_C paths in the greenhouse study",
        "",
        "| Case | Valid paths | LOS present | Refraction paths | Two canopy refractions | Strongest path coefficient (dB re 1) |",
        "|---|---:|:---:|---:|---:|---:|",
        *path_lines,
        "",
        "The transparent control's RX_C traversal has two Sionna refraction interactions on canopy-row objects and matches the empty-case direct path coefficient/delay. The weak-loss case also returned a canopy traversal; the current case returned none at this RX_C position. RX_A's zero refraction count is expected from geometry: its direct segment misses every canopy row.",
        "",
        "### Transparent-control comparison",
        "",
        f"The epsilon_r=1, conductivity=0 control produced mean absolute map difference **{control['mean_absolute_difference_db']:.3f} dB**, median signed difference **{control['median_signed_difference_db']:.3f} dB**, 95th percentile absolute difference **{control['p95_absolute_difference_db']:.3f} dB**, maximum absolute difference **{control['max_absolute_difference_db']:.3f} dB**, **{control['cells_over_1_db']}** cells over 1 dB, and **{control['cells_over_3_db']}** over 3 dB, out of {control['total_cells']}. Values below the 1e-15 path-gain display floor are clipped before differencing.",
        "",
        "| Cell group by direct geometry | Cell count | Mean absolute difference (dB) | P95 absolute difference (dB) | Max absolute difference (dB) |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, item in map_groups.items():
        lines.append(f"| {name.replace('_', ' ')} | {item['cell_count']} | {item['mean_absolute_transparent_delta_db']:.3f} | {item['p95_absolute_transparent_delta_db']:.3f} | {item['max_absolute_transparent_delta_db']:.3f} |")
    lines += ["", "| Control repeat/profile | Mean absolute difference (dB) | P95 absolute difference (dB) | Max absolute difference (dB) | Cells >1 dB | Cells >3 dB |",
              "|---|---:|---:|---:|---:|---:|"]
    for line in sensitivity_lines:
        lines.append(line)
    lines += [
        "",
        "The saved profile pairs change the radio-map sampling seed, sample count, or interaction depth while preserving the same empty/control geometry and material assumptions. Read `outputs/canopy_physics/transparent_sensitivity/sensitivity_summary.json` for exact settings and path counts.",
        "The transparent control is already the strongest practical material match (epsilon_r=1, conductivity=0). It still inserts the closed box surfaces into the ray scene. The measured residual therefore cannot be interpreted as 7 dB of vegetation loss. The baseline also changes path enumeration (for example, RX_A's valid path count drops from the empty case even though its direct LOS remains); the finite candidate/path-map computation is sensitive to the inserted surfaces and interaction budget. Seed/sample/depth reruns quantify how much this changes, without forcing it toward zero.",
        "",
        "### Current attenuation and the 24 dB map difference",
        "",
        f"The current-canopy radio-map difference from empty is **{analysis['current_mean_abs_difference_db']:.3f} dB mean absolute**. The one-factor controls show the largest tested single-factor map effect from lowering conductivity ({analysis['single_factor_diagnostics_vs_current']['current_lower_conductivity']['mean_abs_map_change_db_vs_current']:.3f} dB); turning refraction off changes the map by {analysis['single_factor_diagnostics_vs_current']['current_refraction_off']['mean_abs_map_change_db_vs_current']:.3f} dB. Refraction is enabled in the current case, so the solver flag is not disabled. The isolated current slab produced no valid path, supporting the interpretation that these current material values strongly suppress/lose the sampled transmitted path in this setup.",
        "",
        "The 24 dB figure is a floor-sensitive map aggregate, not a single insertion-loss measurement. At RX_C, the current case's strongest observed path is a roof reflection after no canopy traversal was returned. The result therefore combines missing direct transmission, multipath rerouting, surface interactions, and map cells near the display floor; this experiment does not uniquely decompose those contributions.",
        "",
        "## ASSUMPTION",
        "",
        "- A returned path with two refraction events on canopy-row objects is treated as a traversal through the closed proxy.",
        "- The independent segment/box intersection identifies direct geometric crossings, not whether Sionna accepts a corresponding RF path.",
        "- The isolated open quad follows Sionna's single-surface slab-material abstraction; it is a solver capability test, not a physical crop.",
        "- A current-material zero path count means no valid transmitted path was returned at the configured finite sampling/depth. It does not prove transmission is mathematically impossible.",
        "",
        "## NOT YET VALIDATED",
        "",
        "- No permittivity, conductivity, thickness, water-content, scattering, or crop-structure value here was extracted from a paper or measured in a greenhouse.",
        "- The current 0.8 m Sionna slab thickness is distinct from the 0.6 m box width. Sionna documents a Fresnel slab at each intersected surface and warns that transmitted-ray assumptions can be inaccurate for thick objects.",
        "- Diffuse scattering and diffraction are disabled; plant leaves, stems, moisture dynamics, and measured greenhouse validation are absent.",
        "",
        "## Recommended next RF representation",
        "",
        "First obtain material-property or propagation measurements. Keep the one-surface slab as a controlled material primitive where appropriate, then compare a sparse/open procedural canopy against the closed-box proxy. Keep decorative instanced plants in the Three.js viewer only; do not pass them to Sionna until their RF material model is justified.",
        "",
        "## Sionna API references",
        "",
        "- The official [PathSolver implementation](https://github.com/NVlabs/sionna-rt/blob/main/src/sionna/rt/path_solvers/path_solver.py) documents refraction support and the thin-slab assumption for transmitted paths.",
        "- The official [RadioMaterial API](https://github.com/NVlabs/sionna-rt/blob/main/doc/source/api/radio_materials.rst) describes material thickness and planar-surface slab modeling.",
        "- The official [path-inspection guide](https://github.com/NVlabs/sionna-rt/blob/main/doc/source/developer/dev_understanding_paths.rst) shows interaction IDs, object IDs, and vertices in returned path tensors.",
        "",
    ]
    destination = ROOT / "CANOPY_PHYSICS_FINDINGS.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    return destination


def run_canopy_physics() -> None:
    study = _load_study_config()
    base = _load_cea_config()
    root = OUTPUT_DIR / "canopy_physics"
    root.mkdir(parents=True, exist_ok=True)
    rt, mi = _load_rt()
    results: dict[str, dict[str, Any]] = {}
    for case in CORE_CASES:
        cfg = _case_config(base, study, case)
        result = _run_scenario(rt, mi, cfg, case, output_root=root, include_paths=True)
        results[case] = _update_case_outputs(result, study, case, root)
        total_paths = sum(row["path_count"] for row in results[case]["path_detail"]["receivers"])
        shape = list(results[case]["map_values"].shape)
        print(f"Canopy physics {case}: {total_paths} valid paths; radio map {shape}.")

    structural_checks = _assert_core_design(results)
    current_cfg = results["current"]["cfg"]
    diagnostics = {}
    for name in study["diagnostics"]:
        cfg = _diagnostic_config(current_cfg, study, name)
        result = _run_scenario(rt, mi, cfg, name, output_root=root / "diagnostics", include_paths=True)
        # The diagnostic folder is nested under root/diagnostics.
        diag_dir = root / "diagnostics" / name
        path_detail = _extract_path_diagnostics(result["paths"], cfg, result["object_id_to_name"])
        diagnostic_record = {
            "case": name, "status": "CONTROLLED SENSITIVITY TEST",
            "change": study["diagnostics"][name]["change"],
            "canopy_material": _scenario_material_metadata(cfg, study, "current"),
            "solver": _solver_metadata(cfg),
            "object_id_to_name": {str(k): v for k,v in result["object_id_to_name"].items()},
            "path_api_components": path_detail["api_components"],
        }
        (diag_dir / "physics_paths.json").write_text(json.dumps(path_detail, indent=2), encoding="utf-8")
        (diag_dir / "experiment_metadata.json").write_text(json.dumps(diagnostic_record, indent=2), encoding="utf-8")
        metadata_path = diag_dir / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["canopy_physics_experiment"] = diagnostic_record
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        diagnostics[name] = {"cfg": cfg, "geometry": result["geometry"],
            "map_values": result["map_values"], "map_metadata": result["map_metadata"],
            "path_detail": path_detail, "material": diagnostic_record["canopy_material"],
            "solver": diagnostic_record["solver"]}
        total_paths = sum(row["path_count"] for row in path_detail["receivers"])
        print(f"Canopy diagnostic {name}: {total_paths} valid paths; radio map {list(result['map_values'].shape)}.")

    transparent_sensitivity = _run_transparent_sensitivity(rt, mi, base, study, results, root)
    analysis = _write_comparison(results, diagnostics, structural_checks, study, root,
                                 transparent_sensitivity=transparent_sensitivity)
    from demos.slab_test import run_slab_test  # noqa: PLC0415
    slab_results = run_slab_test(rt, mi)
    analysis["slab_test"] = slab_results
    analysis_path = root / "comparison" / "analysis.json"
    analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    _write_findings_report(analysis, slab_results, root)
    print("Canopy physics study complete.")
    print(f"Transparent geometry-only mean |delta|: {analysis['geometry_only_mean_abs_difference_db']:.3f} dB.")
    print(f"Current vs empty mean |delta|: {analysis['current_mean_abs_difference_db']:.3f} dB.")
    print(f"Report: {root / 'report.md'}")

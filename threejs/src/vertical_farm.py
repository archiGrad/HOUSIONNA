"""Run the controlled Sionna RT vertical-farm scenario family."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from cea_demo import _run_scenario
from poc import OUTPUT_DIR, _load_rt
from vertical_farm_geometry import (
    FARM_SCENARIOS,
    generate_vertical_farm_geometry,
    load_vertical_farm_config,
    vertical_farm_scenario_config,
)


def _save_comparison(results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    root = OUTPUT_DIR / "vertical_farm" / "comparison"
    root.mkdir(parents=True, exist_ok=True)
    maps_db = {
        name: 10.0*np.log10(np.maximum(result["map_values"], 1e-15))
        for name, result in results.items()
    }
    shapes = {name: values.shape for name, values in maps_db.items()}
    if len(set(shapes.values())) != 1:
        raise AssertionError(f"Vertical-farm radio-map grids differ: {shapes}")

    deltas = {}
    for name in FARM_SCENARIOS[1:]:
        delta = maps_db[name]-maps_db[FARM_SCENARIOS[0]]
        deltas[name] = delta
        folder = OUTPUT_DIR / "vertical_farm" / name
        viewer_data = results[name]["viewer_data"]
        viewer_data["difference_map_db"] = delta.tolist()
        (folder / "viewer_data.json").write_text(json.dumps(viewer_data), encoding="utf-8")
        np.save(root / f"{name}_minus_empty_db.npy", delta)

    rows = []
    for name, delta in deltas.items():
        rows.append({
            "scenario": name,
            "mean_absolute_delta_db": float(np.mean(np.abs(delta))),
            "max_absolute_delta_db": float(np.max(np.abs(delta))),
            "cells_changed_over_1_db": int(np.count_nonzero(np.abs(delta) > 1.0)),
        })
    comparison = {
        "description": "Controlled vertical-farm RF proxy comparison against the empty rack.",
        "frequency_hz": float(results[FARM_SCENARIOS[0]]["cfg"]["frequency_hz"]),
        "unchanged_parameters": [
            "cabinet/rack geometry", "shelf count and heights", "materials",
            "transmitter and receivers", "radio-map grid", "solver and seed",
            "decorative visual plant layout",
        ],
        "changed_parameter": "rf_geometry.zones_per_level",
        "difference_quantity": "scenario minus empty 10*log10(path gain); path gain floored at 1e-15 for display",
        "stats": rows,
        "deltas_db": {name: value.tolist() for name, value in deltas.items()},
    }
    (root / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    (root / "viewer_data.json").write_text(json.dumps(comparison), encoding="utf-8")
    return comparison


def _validate_controlled_cases(results: dict[str, dict[str, Any]]) -> None:
    baseline_objects = [
        (obj["id"], obj["bounds_m"])
        for obj in results[FARM_SCENARIOS[0]]["geometry"]["objects"]
        if obj["category"] != "rf_plant_zone"
    ]
    for name in FARM_SCENARIOS[1:]:
        cfg = results[name]["cfg"]
        assert cfg["transmitter"] == results[FARM_SCENARIOS[0]]["cfg"]["transmitter"]
        assert cfg["receivers"] == results[FARM_SCENARIOS[0]]["cfg"]["receivers"]
        objects = [
            (obj["id"], obj["bounds_m"])
            for obj in results[name]["geometry"]["objects"]
            if obj["category"] != "rf_plant_zone"
        ]
        assert objects == baseline_objects, f"{name} changed non-canopy RF geometry"
    expected = {
        "farm_empty": 0,
        "farm_proxy": len(results["farm_proxy"]["cfg"]["environment"]["shelf_levels_m"]),
        "farm_dense": 2*len(results["farm_dense"]["cfg"]["environment"]["shelf_levels_m"]),
    }
    for name, count in expected.items():
        actual = sum(obj["category"] == "rf_plant_zone" for obj in results[name]["geometry"]["objects"])
        assert actual == count, f"{name} expected {count} RF zones, found {actual}"


def run_vertical_farm() -> None:
    """Run three reproducible, one-factor RF cases and export viewer-ready data."""
    base = load_vertical_farm_config()
    rt, mi = _load_rt()
    root = OUTPUT_DIR / "vertical_farm"
    results: dict[str, dict[str, Any]] = {}
    for name in FARM_SCENARIOS:
        cfg = vertical_farm_scenario_config(base, name)
        geometry = generate_vertical_farm_geometry(cfg)
        results[name] = _run_scenario(
            rt, mi, cfg, name, output_root=root, geometry_override=geometry)
        paths = sum(item["valid_path_count"] for item in results[name]["path_summary"]["receivers"])
        shape = results[name]["map_metadata"]["plotted_array_shape"]
        zone_count = sum(obj["category"] == "rf_plant_zone" for obj in geometry["objects"])
        print(f"Vertical farm {name} OK: {zone_count} RF canopy zones, {paths} valid paths; radio map {shape}.")

    _validate_controlled_cases(results)
    comparison = _save_comparison(results)
    for item in comparison["stats"]:
        print(f"{item['scenario']} minus empty: mean |delta|={item['mean_absolute_delta_db']:.3f} dB, "
              f"max |delta|={item['max_absolute_delta_db']:.3f} dB")
    print(f"Vertical-farm outputs: {root}")

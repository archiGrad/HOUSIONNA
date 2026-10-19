"""Run the controlled Sionna RT vertical-farm scenario family."""

from __future__ import annotations

import copy
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


ZONES = ("front_opening", "over_canopy", "rack_other", "outside")
ZONE_LABELS = {
    "front_opening": "in front of the rack (TX side)",
    "over_canopy": "inside the rack, over the canopy footprint",
    "rack_other": "inside the rack, beside the canopy",
    "outside": "behind or beside the rack",
}


def _apply_run_profile(base: dict[str, Any], profile: str) -> dict[str, Any]:
    profiles = base.get("run_profiles") or {}
    if profile not in profiles:
        raise ValueError(f"Unknown run profile {profile!r}; defined: {', '.join(profiles) or 'none'}")
    settings = profiles[profile]
    cfg = copy.deepcopy(base)
    cfg["path_solver"]["samples_per_source"] = (
        int(cfg["path_solver"]["samples_per_source"])*int(settings.get("path_samples_multiplier", 1)))
    cfg["radio_map"]["samples_per_transmitter"] = (
        int(cfg["radio_map"]["samples_per_transmitter"])*int(settings.get("map_samples_multiplier", 1)))
    if settings.get("map_seeds"):
        cfg["radio_map"]["seeds"] = [int(seed) for seed in settings["map_seeds"]]
    return cfg


def _cell_zones(centers_xy: np.ndarray, cfg: dict[str, Any], geometry: dict[str, Any]) -> np.ndarray:
    """Label each map cell by where it sits relative to the rack and this scenario's canopy footprint."""
    width, depth, _ = map(float, cfg["scene_dimensions_m"])
    x, y = centers_xy[..., 0], centers_xy[..., 1]
    over = np.zeros(x.shape, dtype=bool)
    for obj in geometry["objects"]:
        if obj["category"] == "rf_plant_zone":
            b = obj["bounds_m"]
            over |= (x >= b["x_min"]) & (x <= b["x_max"]) & (y >= b["y_min"]) & (y <= b["y_max"])
    in_rack = (x >= 0.0) & (x <= width) & (y >= 0.0) & (y <= depth)
    labels = np.full(x.shape, "outside", dtype=object)
    labels[y < 0.0] = "front_opening"
    labels[in_rack] = "rack_other"
    labels[in_rack & over] = "over_canopy"
    return labels


def _zone_report(results: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Canopy effect per map plane and zone, plus coverage against a receiver sensitivity.

    The median change is taken over cells that receive signal in both maps; cells with no signal are
    counted through coverage instead of being compared against the 1e-15 display floor.
    """
    empty = results[FARM_SCENARIOS[0]]
    centers = np.load(OUTPUT_DIR / "vertical_farm" / FARM_SCENARIOS[0] / "radio_map_cell_centers.npy")[..., :2]
    sensitivity = float(empty["cfg"].get("analysis", {}).get("receiver_sensitivity_dbm", -90.0))
    threshold_db = sensitivity-float(empty["cfg"]["transmitter"]["power_dbm"])
    to_db = lambda values: 10.0*np.log10(np.maximum(values, 1e-15))  # noqa: E731
    planes = empty["cfg"]["radio_map"].get("planes") or [
        {"level": None, "height_m": float(empty["cfg"]["radio_map"]["center_m"][2])}]
    rows = []
    for name in FARM_SCENARIOS[1:]:
        labels = _cell_zones(centers, results[name]["cfg"], results[name]["geometry"])
        for plane in planes:
            e = empty["plane_maps"].get(plane["level"], empty["map_values"])
            p = results[name]["plane_maps"].get(plane["level"], results[name]["map_values"])
            zones = {}
            for zone in ZONES:
                mask = labels == zone
                if not mask.any():
                    continue
                lit = mask & (e > 0) & (p > 0)
                delta = to_db(p[lit])-to_db(e[lit])
                zones[zone] = {
                    "cells": int(mask.sum()),
                    "cells_with_signal_in_both": int(lit.sum()),
                    "median_delta_db": float(np.median(delta)) if lit.any() else None,
                    "p10_delta_db": float(np.percentile(delta, 10)) if lit.any() else None,
                    "p90_delta_db": float(np.percentile(delta, 90)) if lit.any() else None,
                    "coverage_empty": float(np.mean(to_db(e[mask]) >= threshold_db)),
                    "coverage_scenario": float(np.mean(to_db(p[mask]) >= threshold_db)),
                }
            rows.append({
                "scenario": name, "level": plane["level"], "height_m": plane["height_m"],
                "coverage_empty": float(np.mean(to_db(e) >= threshold_db)),
                "coverage_scenario": float(np.mean(to_db(p) >= threshold_db)),
                "zones": zones,
            })
    threshold = {
        "receiver_sensitivity_dbm": sensitivity,
        "tx_power_dbm": float(empty["cfg"]["transmitter"]["power_dbm"]),
        "min_path_gain_db": threshold_db,
        "note": "DEMO PLACEHOLDER sensitivity; coverage = share of cells with TX power + path gain >= sensitivity",
    }
    return rows, threshold


def _save_comparison(results: dict[str, dict[str, Any]], profile: str | None = None) -> dict[str, Any]:
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
        "stats_note": ("Floored statistics over the viewer plane only; dominated by cells without signal. "
                       "Use zone_report for the canopy effect."),
        "deltas_db": {name: value.tolist() for name, value in deltas.items()},
        "run_profile": profile or "default",
        "zone_labels": ZONE_LABELS,
    }
    comparison["zone_report"], comparison["coverage_threshold"] = _zone_report(results)

    # The viewer gets every level's map (and its difference to the empty rack) plus this scenario's zone rows.
    to_db = lambda values: 10.0*np.log10(np.maximum(values, 1e-15))  # noqa: E731
    empty_planes = results[FARM_SCENARIOS[0]]["plane_maps"]
    for name, result in results.items():
        planes = []
        for plane in result["cfg"]["radio_map"].get("planes") or []:
            values_db = to_db(result["plane_maps"][plane["level"]])
            entry = {"level": plane["level"], "height_m": plane["height_m"], "values_db": values_db.tolist()}
            if name != FARM_SCENARIOS[0]:
                entry["difference_db"] = (values_db-to_db(empty_planes[plane["level"]])).tolist()
            planes.append(entry)
        viewer_data = result["viewer_data"]
        viewer_data.update({
            "map_planes": planes,
            "zone_report": [row for row in comparison["zone_report"] if row["scenario"] == name],
            "coverage_threshold": comparison["coverage_threshold"],
            "zone_labels": ZONE_LABELS,
        })
        (OUTPUT_DIR / "vertical_farm" / name / "viewer_data.json").write_text(json.dumps(viewer_data), encoding="utf-8")
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


def _validate_map_planes(results: dict[str, dict[str, Any]]) -> None:
    """Map planes must pass through free air: no shelf, support, light or canopy may span their height."""
    for name, result in results.items():
        for plane in result["cfg"]["radio_map"].get("planes") or []:
            z = float(plane["height_m"])
            for obj in result["geometry"]["objects"]:
                if obj["category"] in ("floor", "enclosure_panel"):
                    continue
                if obj.get("metadata", {}).get("member") == "vertical rack post":
                    continue
                b = obj["bounds_m"]
                assert not (b["z_min"] < z < b["z_max"]), (
                    f"{name}: level-{plane['level']} map plane at z={z:.3f} m cuts through {obj['id']}")


def run_vertical_farm(profile: str | None = None) -> None:
    """Run three reproducible, one-factor RF cases and export viewer-ready data."""
    base = load_vertical_farm_config()
    if profile:
        base = _apply_run_profile(base, profile)
        print(f"Run profile {profile}: {base['radio_map']['samples_per_transmitter']} map samples, "
              f"seeds {base['radio_map'].get('seeds', [base['radio_map']['seed']])}")
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
    _validate_map_planes(results)
    comparison = _save_comparison(results, profile)
    threshold = comparison["coverage_threshold"]
    print(f"Canopy effect vs empty rack: median change over cells with signal in both, and coverage at "
          f"{threshold['receiver_sensitivity_dbm']:.0f} dBm (placeholder sensitivity)")
    for item in comparison["zone_report"]:
        level = f"level {item['level']}" if item["level"] is not None else "map"
        zones = ", ".join(
            f"{zone.replace('_', ' ')} {stats['median_delta_db']:+.1f} dB"
            for zone, stats in item["zones"].items() if stats["median_delta_db"] is not None)
        print(f"  {item['scenario']} {level} (z={item['height_m']:.2f} m): coverage "
              f"{item['coverage_empty']:.0%} -> {item['coverage_scenario']:.0%} | {zones}")
    print(f"Vertical-farm outputs: {root}")

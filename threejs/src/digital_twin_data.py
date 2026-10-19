"""Build a viewer payload from the project config and saved Sionna outputs."""

from __future__ import annotations

import json
import hashlib
from math import log10
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml
from integrations.housionna_performance import atomic_json

from cea_demo import _load_cea_config, _scenario_config
from cea_geometry import generate_cea_geometry
from canopy_physics import _case_config, _load_study_config
from vertical_farm_geometry import (
    FARM_SCENARIOS,
    generate_vertical_farm_geometry,
    load_vertical_farm_config,
    vertical_farm_scenario_config,
)


SCENARIO_LABELS = {
    "farm_empty": "Vertical farm · Empty rack",
    "farm_proxy": "Vertical farm · RF plant proxy",
    "farm_dense": "Vertical farm · Dense RF proxy",
    "empty": "Empty",
    "transparent": "Transparent control",
    "weak_loss": "Weak-loss placeholder",
    "current": "Current canopy",
    "narrow": "Narrow canopy",
    "wide": "Wide canopy",
}


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _housionna_content_signature(document: dict[str, Any]) -> str:
    """Hash normalized RF/scene content while ignoring import IDs and timestamps."""
    assets = document.get("assets", {})
    normalized_scenarios = []
    geometry_hashes = {}
    measurement_hashes = {}
    for scenario_key in document.get("scenario_order", []):
        scenario = document.get("scenarios", {}).get(scenario_key, {})
        geometry = assets.get("geometries", {}).get(scenario.get("geometry_ref"), {})
        geometry_content = {
            "units": geometry.get("units"), "up_axis": geometry.get("up_axis"),
            "bounds_m": geometry.get("bounds_m"),
            "objects": [{
                "id": row.get("id"), "name": row.get("name"), "category": row.get("category"),
                "material_key": row.get("material_key") or row.get("metadata", {}).get("material_name"),
                "bounds_m": row.get("bounds_m"), "mesh_format": row.get("mesh_format"),
                "vertices": row.get("vertices"), "faces": row.get("faces"),
                "metadata": row.get("metadata"),
            } for row in geometry.get("objects", [])],
        }
        if id(geometry) not in geometry_hashes:
            geometry_hashes[id(geometry)] = hashlib.sha256(json.dumps(geometry_content,sort_keys=True,separators=(",", ":"),allow_nan=False).encode()).hexdigest()
        surfaces = []
        for surface in scenario.get("radio_map", {}).get("surfaces", []):
            mesh = assets.get("meshes", {}).get(surface.get("mesh_ref"), {})
            if id(mesh) not in measurement_hashes:
                measurement_hashes[id(mesh)] = hashlib.sha256(json.dumps({"vertices_m":mesh.get("vertices_m"),"faces":mesh.get("faces")},sort_keys=True,separators=(",", ":"),allow_nan=False).encode()).hexdigest()
            surfaces.append({
                "name": surface.get("name"), "values_db": surface.get("values_db"),
                "quantity": surface.get("quantity"), "units": surface.get("units"),
                "measurement_geometry_sha256": measurement_hashes[id(mesh)],
            })
        radio_map = {key: value for key, value in scenario.get("radio_map", {}).items()
                     if key != "surfaces"}
        normalized_scenarios.append({
            "geometry_sha256": geometry_hashes[id(geometry)],
            **{key: scenario.get(key) for key in (
                "frequency_hz", "greenhouse", "environment", "scene_dimensions_m", "scene_bounds_m",
                "materials", "antenna", "transmitter", "receivers", "paths",
                "links", "path_count", "solver", "material_status", "visual_plants", "difference_map_db")},
            "radio_map": radio_map,
            "radio_surfaces": surfaces,
        })
    encoded = json.dumps(normalized_scenarios, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rx_metrics(path_rows: list[dict[str, Any]], receiver_names: list[str]) -> list[dict[str, Any]]:
    result = []
    for receiver_name in receiver_names:
        selected = [path for path in path_rows if path["receiver"] == receiver_name]
        strongest = max(selected, key=lambda row: row.get("magnitude_db", row.get("coefficient_magnitude_db_re_1", -300)), default=None)
        aggregate_power = sum(float(row.get("coefficient_power_linear", row.get("magnitude", row.get("coefficient_magnitude", 0.0))**2)) for row in selected)
        interaction_counts = {
            kind: sum(kind in row.get("interaction_types", []) for row in selected)
            for kind in ("specular_reflection", "refraction", "diffuse_reflection", "diffuse_scattering", "diffraction")
        }
        result.append({
            "receiver": receiver_name,
            "path_count": len(selected),
            "los_present": any(not row.get("interaction_types") for row in selected),
            "strongest_path_db": None if strongest is None else strongest.get(
                "magnitude_db", strongest.get("coefficient_magnitude_db_re_1")),
            "strongest_path_delay_ns": None if strongest is None else strongest.get(
                "delay_s", strongest.get("delay_ns", 0.0) * 1e-9) * 1e9,
            "aggregate_path_coefficient_power_db": 10.0 * log10(max(aggregate_power, 1e-30)),
            "aggregate_path_coefficient_power_linear": aggregate_power,
            "aggregate_power_definition": "sum of individual |a|^2; not RSS",
            "interaction_path_counts": interaction_counts,
        })
    return result


def _entry(name: str, cfg: dict[str, Any], geometry: dict[str, Any],
           radio_map: dict[str, Any], paths: list[dict[str, Any]],
           receivers: list[dict[str, Any]], receiver_metrics: list[dict[str, Any]],
           difference_map: list[list[float]] | None, material_status: str,
           solver: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "label": SCENARIO_LABELS[name],
        "description": cfg.get("description", ""),
        "frequency_hz": float(cfg["frequency_hz"]),
        "greenhouse": cfg["greenhouse"],
        "environment": cfg.get("environment"),
        "scene_dimensions_m": cfg.get("scene_dimensions_m"),
        "scene_bounds_m": geometry.get("bounds_m"),
        "structure_config": cfg["structure"],
        "canopy_config": cfg["canopy"],
        "geometry": geometry,
        "materials": cfg["materials"],
        "antenna": cfg["antenna"],
        "transmitter": cfg["transmitter"],
        "receivers": receivers,
        "receiver_metrics": receiver_metrics,
        "radio_map": radio_map,
        "difference_map_db": difference_map,
        "paths": paths,
        "path_count": len(paths),
        "material_status": material_status,
        "solver": solver,
        "visual_plants": cfg.get("visual_plants", {
            "visualization_only": True,
            "in_sionna_scene": False,
            "spacing_m": 0.42,
            "seed": 186,
            "label": "Decorative crop instances; not simulation geometry",
        }),
    }


def build_viewer_scene(project_root: Path) -> Path:
    """Combine current run artifacts without running or inventing RF results."""
    project_root = Path(project_root).resolve()
    output_root = project_root / "outputs"
    base = _load_cea_config()
    study = _load_study_config()

    physics_comparison = _read_json(output_root / "canopy_physics" / "comparison" / "viewer_data.json")
    cea_comparison = _read_json(output_root / "cea" / "comparison" / "viewer_data.json")
    scenarios: dict[str, dict[str, Any]] = {}

    farm_config = load_vertical_farm_config()
    farm_outputs_ready = all((output_root / "vertical_farm" / name / "viewer_data.json").is_file()
                             for name in FARM_SCENARIOS)
    if farm_outputs_ready:
        for name in FARM_SCENARIOS:
            cfg = vertical_farm_scenario_config(farm_config, name)
            geometry = generate_vertical_farm_geometry(cfg)
            saved = _read_json(output_root / "vertical_farm" / name / "viewer_data.json")
            metrics = _rx_metrics(saved["paths"], [rx["name"] for rx in saved["receivers"]])
            scenarios[name] = _entry(
                name, cfg, geometry, saved["radio_map"], saved["paths"], saved["receivers"], metrics,
                saved.get("difference_map_db"), saved["material_status"],
                solver=_read_json(output_root / "vertical_farm" / name / "metadata.json").get("solver"),
            )
            # Per-level air-gap maps and the zone report, when the run produced them.
            scenarios[name].update({key: saved[key] for key in (
                "map_planes", "zone_report", "coverage_threshold", "zone_labels") if key in saved})

    for name in ("empty", "transparent", "weak_loss", "current"):
        cfg = _case_config(base, study, name)
        geometry = generate_cea_geometry(cfg)
        saved = physics_comparison["scenarios"][name]
        paths = saved["paths"]
        metrics = _rx_metrics(paths, [rx["name"] for rx in saved["receivers"]])
        scenarios[name] = _entry(
            name, cfg, geometry, saved["radio_map"], paths, saved["receivers"], metrics,
            physics_comparison["deltas_db"].get(name), saved["material"]["status"],
            solver=_read_json(output_root / "canopy_physics" / name / "experiment_metadata.json").get("solver"),
        )

    for name in ("narrow", "wide"):
        cfg = _scenario_config(base, name)
        geometry = generate_cea_geometry(cfg)
        saved = _read_json(output_root / "cea" / name / "viewer_data.json")
        path_summary = _read_json(output_root / "cea" / name / "paths.json")
        metrics = _rx_metrics(path_summary["paths"], [rx["name"] for rx in saved["receivers"]])
        material = "CURRENT PLACEHOLDER" if cfg["canopy"]["enabled"] else "CONTROL"
        scenarios[name] = _entry(
            name, cfg, geometry, saved["radio_map"], path_summary["paths"], saved["receivers"], metrics,
            cea_comparison["deltas_db"].get(name), material,
            solver=_read_json(output_root / "cea" / name / "metadata.json").get("solver"),
        )

    try:
        sionna_version = version("sionna-rt")
    except PackageNotFoundError:
        sionna_version = "unknown"
    scene = {
        "schema_version": 1,
        "source": "Generated from config/vertical_farm.yaml, config/cea_demo.yaml, config/canopy_physics.yaml, and saved Sionna outputs.",
        "sionna_version": sionna_version,
        "backend": {"runtime": "Sionna RT local CPU/LLVM run", "host": platform.platform()},
        "scenario_order": [*(FARM_SCENARIOS if farm_outputs_ready else ()), "empty", "transparent", "weak_loss", "current", "narrow", "wide"],
        "featured_scenario": "farm_proxy" if farm_outputs_ready else "current",
        "scenario_labels": SCENARIO_LABELS,
        "scenarios": scenarios,
        "semantics": {
            "rf_geometry": "The objects in each scenario geometry are generated Sionna RF simulation objects. Vertical-farm plant zones are coarse RF-only proxies.",
            "visual_plants": "Detailed decorative Three.js instances only; never passed to Sionna and unchanged across vertical-farm RF cases.",
            "difference_map": "scenario minus empty in dB; loaded from the saved comparison result.",
        },
    }

    # Integration adapters write a normalized, viewer-facing document. Merge
    # those documents here so the Three.js app never reads an external schema.
    integration_root = output_root / "integrations" / "housionna"
    imported_assets = {"geometries": {}, "meshes": {}}
    imported_featured = None
    if integration_root.is_dir():
        import_files = sorted(
            integration_root.glob("*/viewer_import.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        # Older sessions may have produced a path-addressed import and then a
        # content-addressed import of the exact same RF data. Keep the newest
        # normalized copy in the viewer while retaining both files on disk.
        newest_semantic_copy: dict[tuple[str, str], Path] = {}
        semantic_keys: dict[Path, tuple[str, str]] = {}
        import_documents = {}
        for import_file in import_files:
            imported = _read_json(import_file)
            import_documents[import_file] = imported
            if imported.get("schema_version") != 1:
                continue
            provenance = imported.get("provenance", {})
            metadata = imported.get("run_metadata", {})
            source_name = (metadata.get("run_id") if isinstance(metadata, dict) else None) or provenance.get("source_run_name") or import_file.parent.name
            semantic_key = (str(source_name), _housionna_content_signature(imported))
            semantic_keys[import_file] = semantic_key
            newest_semantic_copy[semantic_key] = import_file
        for import_file in import_files:
            semantic_key = semantic_keys.get(import_file)
            if semantic_key is not None and newest_semantic_copy.get(semantic_key) != import_file:
                continue
            imported = import_documents.pop(import_file)
            if imported.get("schema_version") != 1:
                raise ValueError(f"Unsupported HOUSIONNA viewer import schema in {import_file}")
            payload_assets = imported.get("assets", {})
            for asset_kind in ("geometries", "meshes"):
                imported_assets[asset_kind].update(payload_assets.get(asset_kind, {}))
            imported_order = imported.get("scenario_order", [])
            imported_scenarios = imported.get("scenarios", {})
            if not isinstance(imported_order, list) or not isinstance(imported_scenarios, dict):
                raise ValueError(f"Malformed HOUSIONNA viewer import in {import_file}")
            for name in imported_order:
                if name not in imported_scenarios:
                    raise ValueError(f"HOUSIONNA import {import_file} references missing scenario {name!r}")
                if name in scenarios:
                    raise ValueError(f"Imported scenario name conflicts with an existing scenario: {name}")
                scenario = imported_scenarios[name]
                scenario["import_id"] = import_file.parent.name
                provenance = scenario.get("provenance")
                if isinstance(provenance, dict):
                    # The normalized import on disk retains the exact local
                    # source location. The browser-facing document needs only
                    # run IDs and must not publish machine-specific paths.
                    provenance.pop("source_run_folder", None)
                metadata = scenario.setdefault("run_metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}
                    scenario["run_metadata"] = metadata
                metadata.setdefault("import_id", import_file.parent.name)
                metadata.setdefault("run_id", imported.get("run_metadata", {}).get("run_id")
                                    if isinstance(imported.get("run_metadata"), dict)
                                    else imported.get("provenance", {}).get("source_run_name"))
                scenarios[name] = scenario
                scene["scenario_order"].append(name)
                scene["scenario_labels"][name] = scenario.get("label", name)
            featured = imported.get("featured_scenario")
            if featured in imported_scenarios:
                imported_featured = featured

    if imported_assets["geometries"] or imported_assets["meshes"]:
        scene["assets"] = imported_assets
    if imported_featured:
        scene["featured_scenario"] = imported_featured
        scene["semantics"]["housionna_imports"] = (
            "Imported HOUSIONNA runs are normalized by src/integrations/housionna.py; "
            "each transmitter is a selectable viewer scenario."
        )
    target = output_root / "digital_twin" / "viewer_scene.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, scene, compact=True)
    return target

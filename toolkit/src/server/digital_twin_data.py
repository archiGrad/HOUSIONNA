"""Build a viewer payload from the project config and saved Sionna outputs."""

from __future__ import annotations

import json
import hashlib
from math import log10
import platform
import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import yaml
from housionna.performance import atomic_json

from demos.cea_demo import _load_cea_config, _scenario_config
from demos.cea_geometry import generate_cea_geometry
from demos.canopy_physics import _case_config, _load_study_config
from demos.vertical_farm_geometry import (
    FARM_SCENARIOS,
    generate_vertical_farm_geometry,
    load_vertical_farm_config,
    vertical_farm_scenario_config,
)


SCENARIO_LABELS = {
    "farm_empty": "Vertical farm · Empty rack",
    "farm_proxy": "Vertical farm · RF plant proxy",
    "farm_dense": "Vertical farm · Dense canopy proxy",
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



SUMMARY_SCHEMA = 1
STUB_FIELDS = ("name", "label", "description", "source_type", "import_id", "run_metadata", "frequency_hz",
               "transmitter", "solver", "material_status", "scene_dimensions_m", "scene_bounds_m")


def _prepare_import(import_file: Path, imported: dict[str, Any]) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    """Validate one normalized import and give it the browser-facing shape (no local paths)."""
    if imported.get("schema_version") != 1:
        raise ValueError(f"Unsupported HOUSIONNA viewer import schema in {import_file}")
    order = imported.get("scenario_order", [])
    scenarios = imported.get("scenarios", {})
    if not isinstance(order, list) or not isinstance(scenarios, dict):
        raise ValueError(f"Malformed HOUSIONNA viewer import in {import_file}")
    import_id = import_file.parent.name
    run_id = (imported.get("run_metadata", {}).get("run_id") if isinstance(imported.get("run_metadata"), dict)
              else imported.get("provenance", {}).get("source_run_name"))
    for name in order:
        if name not in scenarios:
            raise ValueError(f"HOUSIONNA import {import_file} references missing scenario {name!r}")
        scenario = scenarios[name]
        scenario["import_id"] = import_id
        provenance = scenario.get("provenance")
        if isinstance(provenance, dict):
            # The import on disk keeps the exact local source location; the browser needs only run IDs.
            provenance.pop("source_run_folder", None)
        metadata = scenario.setdefault("run_metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
            scenario["run_metadata"] = metadata
        metadata.setdefault("import_id", import_id)
        metadata.setdefault("run_id", run_id)
    return order, scenarios, imported.get("assets", {})


def _scenario_stub(scenario: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    """The few values the run list, stepper and series chart need, so the viewer loads full runs on demand."""
    surfaces = scenario.get("radio_map", {}).get("surfaces", []) or []
    meshes = assets.get("meshes", {})
    boxes = [meshes[row["mesh_ref"]]["bounds_m"] for row in surfaces
             if row.get("mesh_ref") in meshes and meshes[row["mesh_ref"]].get("bounds_m")]
    bounds = ({f"{axis}_{side}": (min if side == "min" else max)(box[f"{axis}_{side}"] for box in boxes)
               for axis in "xyz" for side in ("min", "max")} if boxes else None)
    values = sorted(value for row in surfaces for value in row.get("values_db") or [] if value is not None)
    cells = sum(len(row.get("values_db") or []) for row in surfaces)
    gains = [row["gain_db_coherent"] for row in scenario.get("links", []) or [] if row.get("gain_db_coherent") is not None]
    stub = {key: scenario.get(key) for key in STUB_FIELDS}
    stub.update(stub=True, summary={
        "surface_bounds": bounds,
        "median_db": values[len(values)//2] if values else None,  # same rule as the viewer's medianDb
        "mean_link_db": sum(gains)/len(gains) if gains else None,
        "reached_pct": 100.0*len(values)/cells if cells else None,
        "path_count": len(scenario.get("paths", []) or []),
    })
    return stub


def _import_summary(import_file: Path) -> dict[str, Any]:
    """Stubs and dedupe key for one import, cached next to it and rebuilt only when the import changes."""
    stat = import_file.stat()
    signature = [stat.st_size, stat.st_mtime_ns]
    cache_file = import_file.with_name("viewer_summary.json")
    try:
        cached = _read_json(cache_file)
        if cached.get("schema") == SUMMARY_SCHEMA and cached.get("source_signature") == signature:
            return cached
    except (OSError, ValueError):
        pass
    imported = _read_json(import_file)
    content_signature = _housionna_content_signature(imported)
    order, scenarios, assets = _prepare_import(import_file, imported)
    metadata = imported.get("run_metadata", {})
    source_name = ((metadata.get("run_id") if isinstance(metadata, dict) else None)
                   or imported.get("provenance", {}).get("source_run_name") or import_file.parent.name)
    summary = {
        "schema": SUMMARY_SCHEMA, "source_signature": signature,
        "semantic_key": [str(source_name), content_signature],
        "featured_scenario": imported.get("featured_scenario"),
        "scenario_order": order,
        "stubs": {name: _scenario_stub(scenarios[name], assets) for name in order},
    }
    atomic_json(cache_file, summary, compact=True)
    return summary


SPLIT_SCHEMA = 1
_SPLIT_LOCK = threading.Lock()


def _scenario_payload(import_id: str, name: str, scenario: dict[str, Any], assets: dict[str, Any]) -> dict[str, Any]:
    """One transmitter's scenario with only the geometry and meshes it references."""
    geometry_ref = scenario.get("geometry_ref")
    mesh_refs = {row.get("mesh_ref") for row in (scenario.get("radio_map") or {}).get("surfaces") or [] if row.get("mesh_ref")}
    return {"schema_version": 1, "import_id": import_id, "scenario_order": [name], "scenarios": {name: scenario},
            "assets": {"geometries": {key: value for key, value in assets.get("geometries", {}).items() if key == geometry_ref},
                       "meshes": {key: value for key, value in assets.get("meshes", {}).items() if key in mesh_refs}}}


def housionna_viewer_payload(project_root: Path, import_id: str, scenario: str | None = None) -> dict[str, Any]:
    """Viewer data for one import (all transmitters), or for one of its scenarios when ``scenario`` is given.

    Joris's multi-TX runs reach 76 MB (15 TX, 70k paths), too much for a browser to parse at once, so the viewer
    asks for one transmitter. The first such request splits the import into viewer_split/<n>.json, one file per
    scenario, rebuilt whenever viewer_import.json changes.
    """
    from housionna.importer import _valid_run_id, read_import
    if not _valid_run_id(import_id):
        raise ValueError("Invalid imported run identifier")
    import_file = Path(project_root).resolve() / "outputs" / "integrations" / "housionna" / import_id / "viewer_import.json"
    if scenario is None:
        document = read_import(project_root, import_id)
        order, scenarios, assets = _prepare_import(import_file, document)
        return {"schema_version": 1, "import_id": import_id, "scenario_order": order,
                "scenarios": {name: scenarios[name] for name in order},
                "assets": {"geometries": assets.get("geometries", {}), "meshes": assets.get("meshes", {})}}
    split = import_file.with_name("viewer_split")
    with _SPLIT_LOCK:
        if not import_file.is_file():
            raise FileNotFoundError("Imported HOUSIONNA run was not found")
        stat = import_file.stat()
        signature = [stat.st_size, stat.st_mtime_ns]
        try:
            manifest = _read_json(split / "manifest.json")
            current = manifest.get("schema") == SPLIT_SCHEMA and manifest.get("source_signature") == signature
        except (OSError, ValueError, AttributeError):
            current = False
        if not current:
            order, scenarios, assets = _prepare_import(import_file, read_import(project_root, import_id))
            split.mkdir(exist_ok=True)
            files = {}
            for index, name in enumerate(order):
                atomic_json(split / f"{index}.json", _scenario_payload(import_id, name, scenarios[name], assets), compact=True)
                files[name] = f"{index}.json"
            manifest = {"schema": SPLIT_SCHEMA, "source_signature": signature, "files": files}
            atomic_json(split / "manifest.json", manifest, compact=True)
    file_name = manifest["files"].get(scenario)
    if not file_name:
        raise FileNotFoundError(f"Scenario {scenario!r} is not part of import {import_id}")
    return _read_json(split / file_name)


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

    # Integration adapters write a normalized, viewer-facing document per import. The scene file carries
    # only a small stub per HOUSIONNA scenario; the viewer fetches a run's full data when it is selected
    # (/api/housionna/imports/<id>/viewer). This keeps the scene file and its rebuild small however many
    # procedural runs are imported.
    integration_root = output_root / "integrations" / "housionna"
    imported_featured = None
    if integration_root.is_dir():
        import_files = sorted(
            integration_root.glob("*/viewer_import.json"),
            key=lambda path: path.stat().st_mtime_ns,
        )
        summaries = {import_file: _import_summary(import_file) for import_file in import_files}
        # Older sessions may have produced a path-addressed import and then a content-addressed import of
        # the exact same RF data. Keep the newest copy in the viewer while retaining both files on disk.
        newest_semantic_copy = {tuple(summary["semantic_key"]): import_file for import_file, summary in summaries.items()}
        for import_file, summary in summaries.items():
            if newest_semantic_copy.get(tuple(summary["semantic_key"])) != import_file:
                continue
            for name in summary["scenario_order"]:
                if name in scenarios:
                    raise ValueError(f"Imported scenario name conflicts with an existing scenario: {name}")
                scenarios[name] = summary["stubs"][name]
                scene["scenario_order"].append(name)
                scene["scenario_labels"][name] = summary["stubs"][name].get("label", name)
            if summary.get("featured_scenario") in summary["stubs"]:
                imported_featured = summary["featured_scenario"]

    if imported_featured:
        scene["featured_scenario"] = imported_featured
        scene["semantics"]["housionna_imports"] = (
            "Imported HOUSIONNA runs are normalized by src/housionna/importer.py; "
            "each transmitter is a selectable viewer scenario."
        )
    target = output_root / "digital_twin" / "viewer_scene.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(target, scene, compact=True)
    return target

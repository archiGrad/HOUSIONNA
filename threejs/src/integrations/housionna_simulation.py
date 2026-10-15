"""Run real Sionna RT paths against an original HOUSIONNA XML/PLY export.

This module loads the source Mitsuba XML directly. It never edits or copies into
the HOUSIONNA run folder; all result artifacts are written beneath outputs/live.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import json
import hashlib
import math
from pathlib import Path
import subprocess
import sys
import time
import traceback
from typing import Any
import uuid
import threading
import re

import numpy as np

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from integrations.housionna_performance import Timings, ImportCache, atomic_json, runtime_identity

from integrations.housionna import (  # noqa: E402
    _devices,
    _one_file,
    _read_json,
    _source_fingerprint,
    configured_runs_directory,
    read_import,
    _paths_for_tx,
    _links_for_tx,
    _receiver_metrics,
)


def resolve_source_run(project_root: Path, run_id: str) -> Path:
    """Resolve one direct child run folder without allowing traversal/symlinks."""
    if (not isinstance(run_id, str) or not run_id or run_id in {".", ".."} or
            any(character in run_id for character in ("/", "\\", ":"))):
        raise ValueError("source_run_id must be a run folder name")
    runs_root = configured_runs_directory(project_root).resolve()
    folder = (runs_root / run_id).resolve()
    if folder.parent != runs_root or not folder.is_dir():
        raise ValueError(f"HOUSIONNA run {run_id!r} is not available under the configured runs directory")
    return folder


def _source_documents(folder: Path, *, include_result: bool = True) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any], list[dict], list[dict]]:
    scene_file = _one_file(folder, "_scene.xml")
    txrx_file = _one_file(folder, "_txrx.json")
    settings_file = _one_file(folder, "_settings.json")
    result_file = _one_file(folder, "_result.json")
    assert scene_file and txrx_file and settings_file and result_file
    devices = _read_json(txrx_file)
    tx_devices, rx_devices = _devices(devices)
    settings = _read_json(settings_file)
    original = _read_json(result_file) if include_result else {}
    if not isinstance(settings, dict) or not isinstance(original, dict):
        raise ValueError("HOUSIONNA settings and result artifacts must be JSON objects")
    if include_result and (not isinstance(original.get("paths"), list) or not isinstance(original.get("links"), list)):
        raise ValueError("HOUSIONNA result must contain paths and links arrays")
    return scene_file, settings, original, devices, tx_devices, rx_devices


def _db(amplitude: float) -> float | None:
    return 20.0 * math.log10(amplitude) if amplitude > 0 else None


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _path_and_link_rows(paths: Any, scene: Any, tx_name: str, tx_position: list[float],
                        rx_rows: list[dict[str, Any]], settings: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """Serialize the Sionna Paths object using HOUSIONNA's existing result schema."""
    tx_index = list(scene.transmitters).index(tx_name)
    rx_names = [row["name"] for row in rx_rows]
    scene_rx_names = list(scene.receivers)
    rx_indices = [scene_rx_names.index(name) for name in rx_names]

    a = (paths.a[0].numpy()[:, 0, :, 0, :] +
         1j * paths.a[1].numpy()[:, 0, :, 0, :])
    tau = paths.tau.numpy()[:, 0, :, 0, :]
    valid = paths.valid.numpy()[:, 0, :, 0, :].astype(bool)
    interactions = paths.interactions.numpy()[:, :, 0, :, 0, :]
    objects = paths.objects.numpy()[:, :, 0, :, 0, :]
    primitives = paths.primitives.numpy()[:, :, 0, :, 0, :]
    vertices = paths.vertices.numpy()[:, :, 0, :, 0, :, :]
    extras = {
        key: getattr(paths, key).numpy()[:, 0, :, 0, :]
        for key in ("theta_t", "phi_t", "theta_r", "phi_r", "doppler")
    }
    object_names = {int(obj.object_id): name for name, obj in scene.objects.items()}
    rx_positions = {row["name"]: row["position_m"] for row in rx_rows}
    path_rows: list[dict[str, Any]] = []
    link_rows: list[dict[str, Any]] = []
    fc = float(settings["frequency"])
    bandwidth = float(settings.get("bandwidth", 0.0))
    cfr_points = max(1, int(settings.get("cfr_points", 1)))
    frequencies = fc + np.linspace(-bandwidth / 2.0, bandwidth / 2.0, cfr_points)

    for rx_name, rx_index in zip(rx_names, rx_indices):
        for path_index in range(a.shape[-1]):
            if not valid[rx_index, tx_index, path_index]:
                continue
            hops = [depth for depth in range(interactions.shape[0])
                    if int(interactions[depth, rx_index, tx_index, path_index]) != 0]
            coefficient = complex(a[rx_index, tx_index, path_index])
            path = {
                "tx": tx_name,
                "rx": rx_name,
                "vertices": [tx_position] + [
                    vertices[depth, rx_index, tx_index, path_index].tolist() for depth in hops
                ] + [rx_positions[rx_name]],
                "interactions": [int(interactions[depth, rx_index, tx_index, path_index]) for depth in hops],
                "objects": [object_names.get(int(objects[depth, rx_index, tx_index, path_index]), "")
                            for depth in hops],
                "primitives": [int(primitives[depth, rx_index, tx_index, path_index]) for depth in hops],
                "a_re": coefficient.real,
                "a_im": coefficient.imag,
                "gain_db": _db(abs(coefficient)),
                "tau": float(tau[rx_index, tx_index, path_index]),
            }
            path.update({key: float(values[rx_index, tx_index, path_index])
                         for key, values in extras.items()})
            path_rows.append(path)

        valid_paths = valid[rx_index, tx_index]
        coefficients = a[rx_index, tx_index, valid_paths].astype(np.complex128)
        delays = tau[rx_index, tx_index, valid_paths].astype(np.float64)
        link: dict[str, Any] = {
            "tx": tx_name,
            "rx": rx_name,
            "vertices": [tx_position, rx_positions[rx_name]],
            "num_paths": int(valid_paths.sum()),
        }
        if len(coefficients):
            powers = np.abs(coefficients) ** 2
            frequency_response = (coefficients[None, :] *
                                  np.exp(-2j * np.pi * frequencies[:, None] * delays[None, :])).sum(axis=1)
            response_at_carrier = (coefficients * np.exp(-2j * np.pi * fc * delays)).sum()
            mean_delay = float((powers * delays).sum() / powers.sum())
            link.update({
                "gain_db_coherent": _db(abs(response_at_carrier)),
                "gain_db_incoherent": _db(math.sqrt(float(powers.sum()))),
                "delay_spread": math.sqrt(float((powers * (delays - mean_delay) ** 2).sum() / powers.sum())),
                "cfr_db": [_db(float(value)) for value in np.abs(frequency_response)],
            })
        link_rows.append(link)
    return path_rows, link_rows


def _group_paths(paths: list[dict[str, Any]]) -> dict[tuple, list[dict[str, Any]]]:
    groups: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for path in paths:
        signature = (tuple(path.get("interactions", [])), tuple(path.get("objects", [])))
        groups[signature].append(path)
    for rows in groups.values():
        rows.sort(key=lambda row: float(row.get("tau", 0.0)))
    return groups


def _path_comparison(source_rows: list[dict], rerun_rows: list[dict]) -> dict[str, Any]:
    source_groups = _group_paths(source_rows)
    rerun_groups = _group_paths(rerun_rows)
    delay_errors_ns: list[float] = []
    coefficient_errors: list[float] = []
    coefficient_db_errors: list[float] = []
    vertex_errors_m: list[float] = []
    matched = 0
    for signature in source_groups.keys() | rerun_groups.keys():
        old = source_groups.get(signature, [])
        new = rerun_groups.get(signature, [])
        for source, current in zip(old, new):
            matched += 1
            delay_errors_ns.append(abs(float(source["tau"]) - float(current["tau"])) * 1e9)
            source_a = complex(float(source["a_re"]), float(source["a_im"]))
            current_a = complex(float(current["a_re"]), float(current["a_im"]))
            coefficient_errors.append(abs(source_a - current_a))
            if source.get("gain_db") is not None and current.get("gain_db") is not None:
                coefficient_db_errors.append(abs(float(source["gain_db"]) - float(current["gain_db"])))
            source_vertices = source.get("vertices", [])[1:-1]
            current_vertices = current.get("vertices", [])[1:-1]
            if len(source_vertices) == len(current_vertices):
                vertex_errors_m.extend(math.dist(a, b) for a, b in zip(source_vertices, current_vertices))

    def error_summary(values: list[float], unit: str) -> dict[str, Any]:
        return {
            "unit": unit,
            "mean_absolute": float(np.mean(values)) if values else None,
            "maximum_absolute": float(max(values)) if values else None,
            "sample_count": len(values),
        }

    return {
        "matched_by_receiver_and_interaction_signature": matched,
        "unmatched_source_paths": len(source_rows) - matched,
        "unmatched_rerun_paths": len(rerun_rows) - matched,
        "absolute_delay_error": error_summary(delay_errors_ns, "ns"),
        "complex_coefficient_error": error_summary(coefficient_errors, "linear amplitude"),
        "coefficient_magnitude_db_error": error_summary(coefficient_db_errors, "dB re 1"),
        "interaction_vertex_error": error_summary(vertex_errors_m, "m"),
    }


def compare_with_source(original: dict[str, Any], rerun: dict[str, Any],
                        tx_name: str, receiver_names: list[str]) -> dict[str, Any]:
    comparisons = []
    for receiver_name in receiver_names:
        old_paths = [row for row in original.get("paths", [])
                     if row.get("tx") == tx_name and row.get("rx") == receiver_name]
        new_paths = [row for row in rerun.get("paths", [])
                     if row.get("tx") == tx_name and row.get("rx") == receiver_name]
        old_link = next((row for row in original.get("links", [])
                         if row.get("tx") == tx_name and row.get("rx") == receiver_name), {})
        new_link = next((row for row in rerun.get("links", [])
                         if row.get("tx") == tx_name and row.get("rx") == receiver_name), {})
        old_strongest = max(old_paths, key=lambda row: float(row.get("gain_db") or -math.inf), default=None)
        new_strongest = max(new_paths, key=lambda row: float(row.get("gain_db") or -math.inf), default=None)
        comparisons.append({
            "receiver": receiver_name,
            "path_count": {"original": len(old_paths), "rerun": len(new_paths)},
            "los": {"original": any(not row.get("interactions") for row in old_paths),
                    "rerun": any(not row.get("interactions") for row in new_paths)},
            "strongest_path_coefficient_db": {
                "original": old_strongest.get("gain_db") if old_strongest else None,
                "rerun": new_strongest.get("gain_db") if new_strongest else None,
            },
            "strongest_path_delay_ns": {
                "original": float(old_strongest["tau"]) * 1e9 if old_strongest else None,
                "rerun": float(new_strongest["tau"]) * 1e9 if new_strongest else None,
            },
            "aggregate_channel_gain_db": {
                "coherent": {"original": old_link.get("gain_db_coherent"),
                             "rerun": new_link.get("gain_db_coherent")},
                "incoherent": {"original": old_link.get("gain_db_incoherent"),
                               "rerun": new_link.get("gain_db_incoherent")},
            },
            "delay_spread_ns": {
                "original": float(old_link["delay_spread"]) * 1e9 if old_link.get("delay_spread") is not None else None,
                "rerun": float(new_link["delay_spread"]) * 1e9 if new_link.get("delay_spread") is not None else None,
            },
            "path_match_errors": _path_comparison(old_paths, new_paths),
        })
    return {"comparison_method": "paths grouped by RX and interaction/object sequence; within groups sorted by delay",
            "receivers": comparisons}


def run_path_rerun(project_root: Path, *, run_id: str, transmitter: str,
                   receiver_names: list[str] | None = None,
                   tx_position: list[float] | None = None,
                   tx_orientation: list[float] | None = None,
                   frequency_hz: float | None = None,
                   solver: dict[str, Any] | None = None,
                   samples_per_src: int | None = None,
                   seed: int = 42,
                   deterministic: bool = False,
                   output_dir: Path | None = None,
                   progress_callback: Any = None,
                   import_id: str | None = None) -> dict[str, Any]:
    """Run PathSolver on one source TX and a bounded RX subset; save a new run."""
    project_root = Path(project_root).resolve()
    folder = resolve_source_run(project_root, run_id)
    scene_file, source_settings, original, raw_devices, tx_devices, rx_devices = _source_documents(folder)
    tx_by_name = {row["name"]: row for row in tx_devices}
    rx_by_name = {row["name"]: row for row in rx_devices}
    if transmitter not in tx_by_name:
        raise ValueError(f"Unknown transmitter {transmitter!r} in HOUSIONNA run {run_id}")
    if receiver_names is None:
        receiver_names = [row["name"] for row in rx_devices[:3]]
    if not isinstance(receiver_names, list) or not 1 <= len(receiver_names) <= 8:
        raise ValueError("Select between one and eight receivers for a path rerun")
    if len(set(receiver_names)) != len(receiver_names) or any(name not in rx_by_name for name in receiver_names):
        raise ValueError("receiver_ids must be unique names from the selected HOUSIONNA run")
    rx_ordered = [row for row in rx_devices if row["name"] in set(receiver_names)]

    tx_source = tx_by_name[transmitter]
    position = tx_position if tx_position is not None else list(tx_source["position_m"])
    orientation = tx_orientation if tx_orientation is not None else list(tx_source["orientation_rad"])
    if not isinstance(position, list) or len(position) != 3 or not isinstance(orientation, list) or len(orientation) != 3:
        raise ValueError("TX position and orientation must be 3D vectors")
    position = [_finite_float(value, "tx_position") for value in position]
    orientation = [_finite_float(value, "tx_orientation") for value in orientation]

    frequency = _finite_float(frequency_hz if frequency_hz is not None else source_settings["frequency"], "frequency_hz")
    if not 100_000_000 <= frequency <= 6_000_000_000:
        raise ValueError("frequency_hz must be between 100 MHz and 6 GHz")
    solver = dict(solver or {})
    allowed_solver = {"max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction"}
    if set(solver) - allowed_solver:
        raise ValueError(f"Unsupported solver field(s): {', '.join(sorted(set(solver)-allowed_solver))}")
    solve_settings = {key: source_settings[key] for key in allowed_solver if key in source_settings}
    solve_settings.update(solver)
    depth = solve_settings.get("max_depth", 3)
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 5:
        raise ValueError("max_depth must be an integer from 1 to 5")
    for key in ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction"):
        if not isinstance(solve_settings.get(key), bool):
            raise ValueError(f"solver.{key} must be a boolean")
    sample_count = int(samples_per_src if samples_per_src is not None else source_settings.get("samples", 100_000))
    if not 1 <= sample_count <= 2_000_000:
        raise ValueError("samples_per_src must be from 1 to 2,000,000")
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
        raise ValueError("seed must be a non-negative 32-bit integer")

    output_dir = Path(output_dir) if output_dir else (
        project_root / "outputs" / "live" / "housionna-reruns" / uuid.uuid4().hex)
    output_dir = output_dir.resolve()
    output_dir.relative_to((project_root / "outputs" / "live").resolve())
    if output_dir.exists():
        raise ValueError(f"Simulation output folder already exists: {output_dir.name}")
    started_at = datetime.now(timezone.utc).isoformat()
    start_monotonic = time.monotonic()

    if progress_callback:
        progress_callback("preparing", "Loading the original Mitsuba scene and RF materials")
    from rt_backend import load_rt as _load_rt

    rt, mi = _load_rt()
    scene = rt.load_scene(str(scene_file), merge_shapes=False)
    scene.frequency = frequency
    scene.tx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    tx_kw = {"power_dbm": tx_source["power_dbm"]} if tx_source["power_dbm"] is not None else {}
    scene.add(rt.Transmitter(
        name=transmitter,
        position=mi.Point3f(position),
        orientation=mi.Point3f(orientation),
        **tx_kw,
    ))
    for rx in rx_ordered:
        scene.add(rt.Receiver(
            name=rx["name"],
            position=mi.Point3f(rx["position_m"]),
            orientation=mi.Point3f(rx["orientation_rad"]),
        ))
    if progress_callback:
        progress_callback("running", "Calculating propagation paths with Sionna RT")
    paths = rt.PathSolver(deterministic=deterministic)(
        scene,
        max_depth=depth,
        samples_per_src=sample_count,
        synthetic_array=False,
        los=solve_settings["los"],
        specular_reflection=solve_settings["specular_reflection"],
        diffuse_reflection=solve_settings["diffuse_reflection"],
        refraction=solve_settings["refraction"],
        diffraction=solve_settings["diffraction"],
        seed=seed,
    )
    raw_paths, raw_links = _path_and_link_rows(paths, scene, transmitter, position, rx_ordered,
                                                {**source_settings, "frequency": frequency})
    bandwidth = float(source_settings.get("bandwidth", 0.0))
    cfr_points = max(1, int(source_settings.get("cfr_points", 1)))
    frequencies = frequency + np.linspace(-bandwidth / 2.0, bandwidth / 2.0, cfr_points)
    rerun_result = {
        "sionna_rt": getattr(rt, "__version__", "unknown"),
        "variant": mi.variant(),
        "settings": {**source_settings, **solve_settings, "frequency": frequency,
                      "samples": sample_count, "seed": seed, "deterministic": deterministic},
        "cfr_frequencies": frequencies.tolist(),
        "paths": raw_paths,
        "links": raw_links,
    }
    duration_seconds = round(time.monotonic() - start_monotonic, 3)
    comparison = compare_with_source(original, rerun_result, transmitter, receiver_names)
    source_sha256, source_hashes = _source_fingerprint(folder)
    if progress_callback:
        progress_callback("exporting", "Normalizing path and receiver results")

    viewer_result = None
    rf_materials: dict[str, Any] = {}
    if import_id:
        imported = read_import(project_root, import_id)
        source_scenario = next((row for row in imported.get("scenarios", {}).values()
                                if row.get("transmitter", {}).get("name") == transmitter), None)
        if source_scenario is None or source_scenario.get("provenance", {}).get("run_folder_name") != run_id:
            raise ValueError("The selected normalized import does not match this HOUSIONNA run and transmitter")
        rf_materials = source_scenario.get("materials", {})
        geometry = imported.get("assets", {}).get("geometries", {}).get(source_scenario.get("geometry_ref"), {})
        scene_object_names = {str(item.get("name") or item.get("id"))
                              for item in geometry.get("objects", [])}
        tx_name_set = {row["name"] for row in tx_devices}
        rx_name_set = {row["name"] for row in rx_devices}
        normalized_paths = _paths_for_tx(rerun_result, transmitter, tx_name_set, rx_name_set, scene_object_names)
        normalized_links = _links_for_tx(rerun_result, transmitter, tx_name_set, rx_name_set)
        metrics = _receiver_metrics(receiver_names, normalized_paths, normalized_links)
        viewer_result = {
            "name": source_scenario["name"],
            "source_type": "housionna",
            "import_id": import_id,
            "source_run_id": run_id,
            "transmitter": {**tx_source, "position_m": position, "orientation_rad": orientation},
            "receivers": rx_ordered,
            "frequency_hz": frequency,
            "paths": normalized_paths,
            "links": normalized_links,
            "receiver_metrics": metrics,
            "path_count": len(normalized_paths),
            "solver": {
                "path_solver": {"max_depth": depth, "samples_per_source": sample_count,
                                **{key: solve_settings[key] for key in
                                   ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")}},
                "radio_map_solver": source_scenario.get("solver", {}).get("radio_map_solver", {}),
            },
        }
    output_dir.mkdir(parents=True, exist_ok=False)
    request_config = {
        "source_run_id": run_id,
        "import_id": import_id,
        "source_sha256": source_sha256,
        "transmitter": transmitter,
        "tx_position_m": position,
        "tx_orientation_rad": orientation,
        "tx_power_dbm": tx_source["power_dbm"],
        "receiver_ids": receiver_names,
        "receiver_positions_m": {row["name"]: row["position_m"] for row in rx_ordered},
        "frequency_hz": frequency,
        "solver": solve_settings,
        "samples_per_src": sample_count,
        "seed": seed,
        "deterministic": deterministic,
        "antenna": {"tx": "1x1 iso, V polarization", "rx": "1x1 iso, V polarization"},
        "source_files_sha256": source_hashes,
        "rf_materials": rf_materials,
    }
    metadata = {
        "run_id": output_dir.name,
        "source_run_id": run_id,
        "import_id": import_id,
        "source_sha256": source_sha256,
        "scene_xml": scene_file.name,
        "scene_geometry": "Original Mitsuba XML and referenced source PLY meshes loaded with rt.load_scene(merge_shapes=False)",
        "material_source": "ITU radio materials loaded from original Mitsuba XML",
        "transmitter": transmitter,
        "tx_power_dbm": tx_source["power_dbm"],
        "receiver_ids": receiver_names,
        "receiver_positions_m": {row["name"]: row["position_m"] for row in rx_ordered},
        "frequency_hz": frequency,
        "solver": rerun_result["settings"],
        "rf_materials": rf_materials,
        "software": {"sionna_rt": rerun_result["sionna_rt"], "variant": rerun_result["variant"]},
        "started_at_utc": started_at,
        "duration_seconds": duration_seconds,
        "path_count": len(raw_paths),
        "link_count": len(raw_links),
        "baseline_comparison": "Original HOUSIONNA result.json for the same TX/RX names; path matching groups interaction/object signatures and sorts by delay.",
        "source_seed_assumption": "The HOUSIONNA runner calls PathSolver() without arguments; Sionna RT 2.2.0 defaults deterministic=False and call seed=42.",
        "comparison": comparison,
    }
    (output_dir / "config.json").write_text(json.dumps(request_config, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "paths.json").write_text(json.dumps(raw_paths, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "links.json").write_text(json.dumps(raw_links, indent=2, allow_nan=False), encoding="utf-8")
    (output_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, allow_nan=False), encoding="utf-8")
    rerun_result["run_id"] = output_dir.name
    rerun_result["transmitter"] = {**tx_source, "position_m": position, "orientation_rad": orientation}
    rerun_result["receivers"] = rx_ordered
    rerun_result["metadata"] = metadata
    (output_dir / "result.json").write_text(json.dumps(rerun_result, indent=2, allow_nan=False), encoding="utf-8")
    if viewer_result is not None:
        (output_dir / "viewer_result.json").write_text(json.dumps(viewer_result, indent=2, allow_nan=False), encoding="utf-8")
    return {"run_id": output_dir.name, "output_dir": output_dir, "result": rerun_result,
            "comparison": comparison, "metadata": metadata, "viewer_result": viewer_result}


RADIO_MAP_QUALITY = {
    "low": {"samples_per_tx": 100_000},
    "medium": {"samples_per_tx": 500_000},
    "high": {"samples_per_tx": 2_000_000},
}


def run_radio_map_rerun(project_root: Path, *, run_id: str, import_id: str,
                        transmitter: str, tx_position: list[float],
                        tx_orientation: list[float], frequency_hz: float,
                        solver: dict[str, Any], quality: str,
                        seed: int = 42, progress_callback: Any = None,
                        output_dir: Path | None = None,
                        normalized_import_file: Path | None = None) -> dict[str, Any]:
    """Recompute one TX radio map on HOUSIONNA's original triangular PLY surface."""
    profile = Timings()
    if quality not in RADIO_MAP_QUALITY:
        raise ValueError("Radio-map quality must be low, medium, or high")
    project_root = Path(project_root).resolve()
    folder = resolve_source_run(project_root, run_id)
    with profile.stage("source_json"):
        scene_file, source_settings, _, _, tx_devices, _ = _source_documents(folder, include_result=False)
    source_tx = next((row for row in tx_devices if row["name"] == transmitter), None)
    if source_tx is None:
        raise ValueError(f"Unknown transmitter {transmitter!r} in HOUSIONNA run {run_id}")
    with profile.stage("normalized_import_json"):
        imported = _read_json(normalized_import_file) if normalized_import_file else read_import(project_root, import_id)
    source_scenario = next((row for row in imported.get("scenarios", {}).values()
                            if row.get("transmitter", {}).get("name") == transmitter), None)
    if source_scenario is None or source_scenario.get("provenance", {}).get("run_folder_name") != run_id:
        raise ValueError("The selected normalized import does not match this HOUSIONNA run and transmitter")
    with profile.stage("source_hash_before_solver"):
        expected_hash=source_scenario.get("provenance", {}).get("source_sha256")
        if _source_fingerprint(folder)[0] != expected_hash:
            raise ValueError("The source export changed after import; reload the export before simulating")
    surfaces = source_scenario.get("radio_map", {}).get("surfaces", [])
    if not surfaces:
        raise ValueError("This HOUSIONNA run has no imported triangular radio-map measurement surface")
    mesh_name = surfaces[0]["name"]
    measurement_file = folder / "meshes" / f"{mesh_name}.ply"
    if not measurement_file.is_file():
        raise ValueError(f"Original measurement mesh {mesh_name!r} is missing from the source run")
    tx_position = [_finite_float(value, "tx_position") for value in tx_position]
    tx_orientation = [_finite_float(value, "tx_orientation") for value in tx_orientation]
    if len(tx_position) != 3 or len(tx_orientation) != 3:
        raise ValueError("TX position and orientation must be 3D vectors")
    frequency = _finite_float(frequency_hz, "frequency_hz")
    if not 100_000_000 <= frequency <= 6_000_000_000:
        raise ValueError("frequency_hz must be between 100 MHz and 6 GHz")
    allowed = {"max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction"}
    if set(solver) - allowed:
        raise ValueError("Unsupported radio-map solver setting")
    solve = {key: source_settings[key] for key in allowed if key in source_settings}
    solve.update(solver)
    depth = solve.get("max_depth", 3)
    if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 5:
        raise ValueError("max_depth must be an integer from 1 to 5")
    if any(not isinstance(solve.get(key), bool) for key in ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction")):
        raise ValueError("Radio-map solver flags must be booleans")
    sample_count = RADIO_MAP_QUALITY[quality]["samples_per_tx"]
    output_dir = Path(output_dir) if output_dir else (
        project_root / "outputs" / "live" / "housionna-maps" / uuid.uuid4().hex)
    output_dir = output_dir.resolve()
    output_dir.relative_to((project_root / "outputs" / "live").resolve())
    if output_dir.exists():
        raise ValueError(f"Radio-map output folder already exists: {output_dir.name}")
    start = time.monotonic()
    if progress_callback:
        progress_callback("preparing", "Loading original scene and measurement triangles")
    from rt_backend import load_rt as _load_rt
    with profile.stage("rt_initialization"):
        rt, mi = _load_rt()
    with profile.stage("scene_xml_ply_materials"):
        scene = rt.load_scene(str(scene_file), merge_shapes=False)
    with profile.stage("devices_and_antennas"):
        scene.frequency = frequency
        scene.tx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
        scene.rx_array = rt.PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
        tx_kw = {"power_dbm": source_tx["power_dbm"]} if source_tx["power_dbm"] is not None else {}
        scene.add(rt.Transmitter(name=transmitter, position=mi.Point3f(tx_position),
                                 orientation=mi.Point3f(tx_orientation), **tx_kw))
    if progress_callback:
        progress_callback("loading", "Loading original measurement PLY and checking triangle order")
    with profile.stage("measurement_ply"):
        measurement_surface = mi.load_dict({"type": "ply", "filename": str(measurement_file), "face_normals": True})
    with profile.stage("triangle_alignment"):
        shape_data = mi.traverse(measurement_surface)
        loaded_vertices = np.asarray(shape_data["vertex_positions"], dtype=np.float64).reshape(-1, 3)
        loaded_faces = np.asarray(shape_data["faces"], dtype=np.int64).reshape(-1, 3)
        geometry = imported.get("assets", {}).get("meshes", {}).get(surfaces[0].get("mesh_ref"), {})
        faces = np.asarray(geometry.get("faces", []), dtype=np.int64)
        vertices = np.asarray(geometry.get("vertices_m", []), dtype=np.float64)
        if (faces.shape != loaded_faces.shape or vertices.shape != loaded_vertices.shape or
                not np.array_equal(faces, loaded_faces)):
            raise ValueError("Source PLY triangle count/order does not match the imported measurement mesh")
        coordinate_errors = np.linalg.norm(vertices - loaded_vertices, axis=1)
        if coordinate_errors.size and float(coordinate_errors.max()) > 1e-6:
            raise ValueError("Source measurement-mesh coordinates do not match the imported viewer asset")
    if progress_callback:
        progress_callback("running", f"Calculating {quality} radio map ({sample_count:,} samples), selected TX {transmitter}")
    with profile.stage("solver"):
        radio_map = rt.RadioMapSolver()(
            scene, measurement_surface=measurement_surface, samples_per_tx=sample_count,
            seed=seed, **solve,
        )
        import drjit as dr
        dr.eval(radio_map.path_gain)
        dr.sync_thread()
    if progress_callback:
        progress_callback("processing", "Extracting path gain and processing triangle values")
    with profile.stage("data_extraction"):
        gain = np.asarray(radio_map.path_gain.numpy(), dtype=np.float64).reshape(-1)
    if len(gain) != len(faces):
        raise ValueError(f"Sionna returned {len(gain)} map values for {len(faces)} source measurement triangles")
    with profile.stage("normalization"):
        values_db = [10.0 * math.log10(float(value)) if math.isfinite(float(value)) and float(value) > 0 else None
                     for value in gain]
    duration = round(time.monotonic() - start, 3)
    with profile.stage("source_hashing"):
        source_sha256, source_hashes = _source_fingerprint(folder)
        if source_sha256 != expected_hash:
            raise ValueError("The source export changed during calculation; this result is not cached. Reload the export.")
    metadata = {
        "run_id": output_dir.name,
        "source_run_id": run_id,
        "source_sha256": source_sha256,
        "import_id": import_id,
        "transmitter": transmitter,
        "tx_position_m": tx_position,
        "tx_orientation_rad": tx_orientation,
        "frequency_hz": frequency,
        "measurement_surface": mesh_name,
        "measurement_mesh_ref": surfaces[0]["mesh_ref"],
        "measurement_triangle_count": len(faces),
        "tx_power_dbm": source_tx["power_dbm"],
        "rf_materials": source_scenario.get("materials", {}),
        "quality": quality,
        "samples_per_tx": sample_count,
        "solver": {**solve, "seed": seed},
        "seed_reproducibility": "seed is supplied to RadioMapSolver; bitwise repeatability across runs/backends is not claimed",
        "software": {"sionna_rt": getattr(rt, "__version__", "unknown"), "variant": mi.variant()},
        "duration_seconds": duration,
        "solver_seconds": profile.seconds["solver"],
        "valid_triangle_count": sum(value is not None for value in values_db),
        "missing_fraction": sum(value is None for value in values_db) / len(values_db) if values_db else 1.0,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "source_files_sha256": source_hashes,
        "coordinate_system": "Original HOUSIONNA Sionna-frame metres; Z up",
        "quantity": "path_gain",
        "missing_value": None,
    }
    surface = {"name": mesh_name, "mesh_ref": surfaces[0]["mesh_ref"], "values_db": values_db,
               "quantity": "path_gain", "units": "10 log10(path gain), dB; missing/non-finite values are null"}
    with profile.stage("comparison"):
        original_surface = surfaces[0]
        map_compatible = (frequency == float(source_scenario.get("frequency_hz", -1)) and
                          original_surface.get("quantity") == "path_gain" and
                          original_surface.get("mesh_ref") == surface.get("mesh_ref") and
                          len(original_surface.get("values_db", [])) == len(values_db))
        deltas = [float(new) - float(old) for old, new in zip(original_surface.get("values_db", []), values_db)
                  if map_compatible and old is not None and new is not None and
                  math.isfinite(float(old)) and math.isfinite(float(new))]
        comparison = {
            "compatible": bool(map_compatible),
            "method": "rerun minus original path_gain_db in source PLY triangle order",
            "reason": ("Carrier frequency, quantity, mesh reference, and face count match; only jointly valid cells were compared."
                       if map_compatible else "Frequency, output quantity, measurement mesh reference, or face count differs."),
            "valid_cells": len(deltas) if map_compatible else 0,
            "mean_delta_db": (float(np.mean(deltas)) if deltas and map_compatible else None),
            "mean_absolute_delta_db": (float(np.mean(np.abs(deltas))) if deltas and map_compatible else None),
            "minimum_delta_db": (float(min(deltas)) if deltas and map_compatible else None),
            "maximum_delta_db": (float(max(deltas)) if deltas and map_compatible else None),
            "rms_delta_db": (float(math.sqrt(np.mean(np.square(deltas)))) if deltas and map_compatible else None),
            "source_face_count": len(faces),
            "maximum_loaded_vertex_error_m": float(coordinate_errors.max()) if coordinate_errors.size else 0.0,
        }
    if progress_callback:
        progress_callback("exporting", "Saving radio-map values and provenance")
    output_dir.mkdir(parents=True, exist_ok=False)
    documents = {"config.json": {
        "source_run_id": run_id, "source_sha256": source_sha256, "import_id": import_id,
        "transmitter": transmitter, "tx_position_m": tx_position, "tx_orientation_rad": tx_orientation,
        "tx_power_dbm": source_tx["power_dbm"],
        "frequency_hz": frequency, "solver": metadata["solver"], "quality": quality,
        "samples_per_tx": sample_count, "seed": seed, "source_files_sha256": source_hashes,
        "rf_materials": source_scenario.get("materials", {}),
    },
                 "radio_map.json": {"surfaces": [surface], "metadata": metadata},
                 "comparison.json": comparison}
    with profile.stage("serialization"):
        encoded = {name: json.dumps(document, allow_nan=False, separators=(",", ":"))
                   for name, document in documents.items()}
    with profile.stage("file_writing"):
        for name, text in encoded.items():
            (output_dir / name).write_text(text, encoding="utf-8")
    metadata["duration_seconds"] = round(time.perf_counter() - profile.started, 6)
    metadata["profile"] = profile.payload()
    atomic_json(output_dir / "metadata.json", metadata)
    atomic_json(output_dir / "profile.json", profile.payload())
    return {"run_id": output_dir.name, "output_dir": output_dir, "surface": surface,
            "metadata": metadata, "comparison": comparison}


def _pairwise_experiment_comparison(case_a: dict[str, Any], case_b: dict[str, Any],
                                    receiver_names: list[str]) -> dict[str, Any]:
    result_a, result_b = case_a["result"], case_b["result"]
    rows = []
    for receiver_name in receiver_names:
        paths_a = [row for row in result_a["paths"] if row["rx"] == receiver_name]
        paths_b = [row for row in result_b["paths"] if row["rx"] == receiver_name]
        link_a = next((row for row in result_a["links"] if row["rx"] == receiver_name), {})
        link_b = next((row for row in result_b["links"] if row["rx"] == receiver_name), {})
        strongest_a = max(paths_a, key=lambda row: row.get("gain_db") if row.get("gain_db") is not None else -math.inf, default=None)
        strongest_b = max(paths_b, key=lambda row: row.get("gain_db") if row.get("gain_db") is not None else -math.inf, default=None)

        def difference(field: str) -> float | None:
            left, right = link_a.get(field), link_b.get(field)
            if left is None or right is None:
                return None
            return float(right) - float(left)

        rows.append({
            "receiver": receiver_name,
            "path_count": {"case_a": len(paths_a), "case_b": len(paths_b), "delta": len(paths_b)-len(paths_a)},
            "los": {"case_a": any(not row.get("interactions") for row in paths_a),
                    "case_b": any(not row.get("interactions") for row in paths_b)},
            "strongest_path_gain_db": {
                "case_a": strongest_a.get("gain_db") if strongest_a else None,
                "case_b": strongest_b.get("gain_db") if strongest_b else None,
                "delta_db": (float(strongest_b["gain_db"])-float(strongest_a["gain_db"])
                             if strongest_a and strongest_b and strongest_a.get("gain_db") is not None and strongest_b.get("gain_db") is not None else None),
            },
            "strongest_path_delay_ns": {
                "case_a": float(strongest_a["tau"])*1e9 if strongest_a else None,
                "case_b": float(strongest_b["tau"])*1e9 if strongest_b else None,
                "delta_ns": ((float(strongest_b["tau"])-float(strongest_a["tau"]))*1e9
                             if strongest_a and strongest_b else None),
            },
            "aggregate_channel_gain_db": {
                "coherent": {"case_a": link_a.get("gain_db_coherent"), "case_b": link_b.get("gain_db_coherent"),
                             "delta_db": difference("gain_db_coherent")},
                "incoherent": {"case_a": link_a.get("gain_db_incoherent"), "case_b": link_b.get("gain_db_incoherent"),
                               "delta_db": difference("gain_db_incoherent")},
            },
            "delay_spread_ns": {
                "case_a": float(link_a["delay_spread"])*1e9 if link_a.get("delay_spread") is not None else None,
                "case_b": float(link_b["delay_spread"])*1e9 if link_b.get("delay_spread") is not None else None,
                "delta_ns": ((float(link_b["delay_spread"])-float(link_a["delay_spread"]))*1e9
                             if link_a.get("delay_spread") is not None and link_b.get("delay_spread") is not None else None),
            },
            "path_match_errors": _path_comparison(paths_a, paths_b),
        })
    return {"controlled_comparison": True,
            "only_changed_rf_input": "transmitter position",
            "comparison_method": "paths grouped by RX and interaction/object sequence; within groups sorted by delay",
            "receivers": rows}


def run_controlled_position_experiment(project_root: Path, *, run_id: str, transmitter: str,
                                       receiver_names: list[str], offset_m: list[float] | None = None,
                                       samples_per_src: int | None = None,
                                       seed: int = 42) -> dict[str, Any]:
    """Run the same deterministic configuration at original and moved TX poses."""
    folder = resolve_source_run(project_root, run_id)
    _, _, _, _, tx_devices, _ = _source_documents(folder)
    source_tx = next((row for row in tx_devices if row["name"] == transmitter), None)
    if source_tx is None:
        raise ValueError(f"Unknown transmitter {transmitter!r} in HOUSIONNA run {run_id}")
    offset_m = list(offset_m or [0.5, 0.5, 0.0])
    if not isinstance(offset_m, list) or len(offset_m) != 3:
        raise ValueError("offset_m must be a 3D vector")
    offset = [_finite_float(value, "offset_m") for value in offset_m]
    original_position = list(source_tx["position_m"])
    moved_position = [round(original_position[index] + offset[index], 6) for index in range(3)]
    experiment_id = uuid.uuid4().hex
    experiment_dir = (Path(project_root).resolve() / "outputs" / "live" / "housionna-experiments" / experiment_id)
    experiment_dir.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    common = {
        "project_root": Path(project_root),
        "run_id": run_id,
        "transmitter": transmitter,
        "receiver_names": receiver_names,
        "samples_per_src": samples_per_src,
        "seed": seed,
        "deterministic": True,
    }
    case_a = run_path_rerun(**common, tx_position=original_position, output_dir=experiment_dir / "case_a")
    case_b = run_path_rerun(**common, tx_position=moved_position, output_dir=experiment_dir / "case_b")
    comparison = _pairwise_experiment_comparison(case_a, case_b, receiver_names)
    case_a_config = json.loads((case_a["output_dir"] / "config.json").read_text(encoding="utf-8"))
    case_b_config = json.loads((case_b["output_dir"] / "config.json").read_text(encoding="utf-8"))
    for key in ("source_run_id", "source_sha256", "transmitter", "tx_orientation_rad", "receiver_ids",
                "frequency_hz", "solver", "samples_per_src", "seed", "deterministic", "antenna"):
        if case_a_config[key] != case_b_config[key]:
            raise RuntimeError(f"Controlled experiment changed RF input {key!r} between cases")
    metadata = {
        "experiment_id": experiment_id,
        "source_run_id": run_id,
        "transmitter": transmitter,
        "case_a_position_m": original_position,
        "case_b_position_m": moved_position,
        "tx_position_offset_m": offset,
        "receiver_ids": receiver_names,
        "frequency_hz": case_a_config["frequency_hz"],
        "solver": case_a_config["solver"],
        "samples_per_src": case_a_config["samples_per_src"],
        "seed": seed,
        "deterministic": True,
        "case_a_run_id": case_a["run_id"],
        "case_b_run_id": case_b["run_id"],
        "duration_seconds": round(time.monotonic() - started, 3),
        "only_rf_input_changed": "TX position",
        "results": comparison,
    }
    (experiment_dir / "metadata.json").write_text(json.dumps(metadata, indent=2, allow_nan=False), encoding="utf-8")
    (experiment_dir / "comparison.json").write_text(json.dumps(comparison, indent=2, allow_nan=False), encoding="utf-8")
    return {"experiment_id": experiment_id, "output_dir": experiment_dir, "metadata": metadata,
            "comparison": comparison, "case_a": case_a, "case_b": case_b}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py housionna-rerun")
    parser.add_argument("--run-id", required=True, help="Direct child folder name under configured HOUSIONNA runs")
    parser.add_argument("--transmitter", default="tx_0")
    parser.add_argument("--receivers", nargs="+", help="Receiver names; defaults to the first three exported receivers")
    parser.add_argument("--samples", type=int, help="Override exported samples-per-source value")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--deterministic", action="store_true",
                        help="Use deterministic PathSolver mode instead of the source runner default")
    args = parser.parse_args(argv)
    project_root = Path(__file__).resolve().parents[2]
    output = run_path_rerun(
        project_root,
        run_id=args.run_id,
        transmitter=args.transmitter,
        receiver_names=args.receivers,
        samples_per_src=args.samples,
        seed=args.seed,
        deterministic=args.deterministic,
    )
    print(json.dumps({"run_id": output["run_id"], "output_dir": str(output["output_dir"]),
                      "duration_seconds": output["metadata"]["duration_seconds"],
                      "path_count": output["metadata"]["path_count"],
                      "comparison": output["comparison"]}, indent=2, allow_nan=False))
    return 0


def position_test_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py housionna-position-test")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--transmitter", default="tx_0")
    parser.add_argument("--receivers", nargs="+", required=True)
    parser.add_argument("--offset", nargs=3, type=float, default=[0.5, 0.5, 0.0], metavar=("DX", "DY", "DZ"))
    parser.add_argument("--samples", type=int)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args(argv)
    output = run_controlled_position_experiment(
        Path(__file__).resolve().parents[2], run_id=args.run_id,
        transmitter=args.transmitter, receiver_names=args.receivers,
        offset_m=args.offset, samples_per_src=args.samples, seed=args.seed,
    )
    print(json.dumps({"experiment_id": output["experiment_id"],
                      "output_dir": str(output["output_dir"]),
                      "duration_seconds": output["metadata"]["duration_seconds"],
                      "comparison": output["comparison"]}, indent=2, allow_nan=False))
    return 0


class HousionnaSimulationApiError(ValueError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class HousionnaLiveSimulationManager:
    """Serializes imported-scene Sionna jobs in isolated Python processes."""

    def __init__(self, project_root: Path):
        self.project_root = Path(project_root).resolve()
        self.live_root = self.project_root / "outputs" / "live"
        self.jobs_root = self.live_root / ".housionna-jobs"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict[str, Any]] = {}
        self.active_job_id: str | None = None
        self.import_cache = ImportCache(2)
        self.runtime = runtime_identity(self.project_root)
        self.timeouts = {"paths": 180, "low": 120, "medium": 300, "high": 600}
        try:
            import yaml
            config = yaml.safe_load((self.project_root / "config/housionna.yaml").read_text(encoding="utf-8")) or {}
            overrides = config.get("housionna", {}).get("worker_timeout_seconds", {})
            self.timeouts.update({key: value for key, value in overrides.items()
                                  if key in self.timeouts and isinstance(value, int) and 5 <= value <= 3600})
        except (OSError, ValueError):
            pass

    @staticmethod
    def _valid_id(value: Any) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None

    @staticmethod
    def _number(value: Any, field: str) -> float:
        try:
            return _finite_float(value, field)
        except (ValueError, TypeError) as error:
            raise HousionnaSimulationApiError(400, str(error)) from error

    def _normalize(self, payload: Any, *, map_job: bool) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise HousionnaSimulationApiError(400, "Request body must be a JSON object")
        allowed = {"source_run_id", "import_id", "transmitter", "receiver_ids", "tx_position",
                   "tx_orientation", "frequency_hz", "solver", "samples_per_src", "seed", "quality"}
        if set(payload) - allowed:
            raise HousionnaSimulationApiError(400, f"Unsupported request field(s): {', '.join(sorted(set(payload)-allowed))}")
        run_id = payload.get("source_run_id")
        import_id = payload.get("import_id")
        transmitter = payload.get("transmitter")
        if (not isinstance(import_id, str) or
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", import_id) is None or
                ".." in import_id):
            raise HousionnaSimulationApiError(400, "import_id must be a normalized HOUSIONNA import identifier")
        if not isinstance(transmitter, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", transmitter):
            raise HousionnaSimulationApiError(400, "transmitter must be a valid exported device name")
        if not isinstance(run_id, str):
            raise HousionnaSimulationApiError(400, "source_run_id is required")
        try:
            folder = resolve_source_run(self.project_root, run_id)
            _, settings, _, _, tx_devices, rx_devices = _source_documents(folder, include_result=False)
            with self.lock:
                imported = self.import_cache.read(self.project_root, import_id, read_import)
        except FileNotFoundError as error:
            raise HousionnaSimulationApiError(404, "The selected normalized HOUSIONNA import was not found") from error
        except (OSError, ValueError, KeyError, AssertionError) as error:
            raise HousionnaSimulationApiError(400, f"The selected HOUSIONNA export is invalid: {error}") from error
        source_scenario = next((row for row in imported.get("scenarios", {}).values()
                                if row.get("transmitter", {}).get("name") == transmitter), None)
        if (source_scenario is None or
                source_scenario.get("provenance", {}).get("run_folder_name") != run_id):
            raise HousionnaSimulationApiError(400, "import_id, source_run_id, and transmitter must refer to the same imported scene")
        source_sha256, source_hashes = _source_fingerprint(folder)
        if source_sha256 != source_scenario.get("provenance", {}).get("source_sha256"):
            raise HousionnaSimulationApiError(409, "The source export changed after import. Reload selected export before simulating.")
        tx_source = next((row for row in tx_devices if row["name"] == transmitter), None)
        if tx_source is None:
            raise HousionnaSimulationApiError(400, f"Unknown transmitter {transmitter!r}")

        raw_position = payload.get("tx_position", tx_source["position_m"])
        raw_orientation = payload.get("tx_orientation", tx_source["orientation_rad"])
        if not isinstance(raw_position, list) or len(raw_position) != 3:
            raise HousionnaSimulationApiError(400, "tx_position must be [x, y, z] in metres")
        if not isinstance(raw_orientation, list) or len(raw_orientation) != 3:
            raise HousionnaSimulationApiError(400, "tx_orientation must be three radians values")
        position = [self._number(value, f"tx_position[{index}]") for index, value in enumerate(raw_position)]
        orientation = [self._number(value, f"tx_orientation[{index}]") for index, value in enumerate(raw_orientation)]
        if any(abs(value) > 2 * math.pi for value in orientation):
            raise HousionnaSimulationApiError(400, "tx_orientation values must be within -2π and 2π radians")

        assets = imported.get("assets", {})
        scene = assets.get("geometries", {}).get(source_scenario.get("geometry_ref"), {})
        bounds = scene.get("bounds_m", {})
        for index, axis in enumerate(("x", "y", "z")):
            low, high = bounds.get(f"{axis}_min"), bounds.get(f"{axis}_max")
            if not isinstance(low, (int, float)) or not isinstance(high, (int, float)):
                raise HousionnaSimulationApiError(400, "Imported scene has no valid spatial bounds")
            margin = max(1.0, (high - low) * 0.25)
            if not low - margin <= position[index] <= high + margin:
                raise HousionnaSimulationApiError(400, f"TX {'XYZ'[index]} is outside scene bounds plus {margin:.2f} m margin")

        receiver_by_name = {row["name"]: row for row in rx_devices}
        raw_receivers = payload.get("receiver_ids", [row["name"] for row in rx_devices[:3]])
        if (not isinstance(raw_receivers, list) or not 1 <= len(raw_receivers) <= 8 or
                any(not isinstance(name, str) or name not in receiver_by_name for name in raw_receivers) or
                len(set(raw_receivers)) != len(raw_receivers)):
            raise HousionnaSimulationApiError(400, "receiver_ids must contain one to eight unique RX names from the selected run")
        receivers = [row["name"] for row in rx_devices if row["name"] in set(raw_receivers)]

        frequency = self._number(payload.get("frequency_hz", settings.get("frequency")), "frequency_hz")
        if not 100_000_000 <= frequency <= 6_000_000_000:
            raise HousionnaSimulationApiError(400, "frequency_hz must be between 100 MHz and 6 GHz")
        solver = payload.get("solver", {})
        allowed_solver = {"max_depth", "los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction"}
        if not isinstance(solver, dict) or set(solver) - allowed_solver:
            raise HousionnaSimulationApiError(400, "solver contains unsupported settings")
        resolved_solver = {key: settings[key] for key in allowed_solver if key in settings}
        resolved_solver.update(solver)
        depth = resolved_solver.get("max_depth", 3)
        if isinstance(depth, bool) or not isinstance(depth, int) or not 1 <= depth <= 5:
            raise HousionnaSimulationApiError(400, "solver.max_depth must be an integer from 1 to 5")
        for key in ("los", "specular_reflection", "diffuse_reflection", "refraction", "diffraction"):
            if not isinstance(resolved_solver.get(key), bool):
                raise HousionnaSimulationApiError(400, f"solver.{key} must be a boolean")
        raw_samples = payload.get("samples_per_src", settings.get("samples", 100_000))
        if isinstance(raw_samples, bool) or not isinstance(raw_samples, int) or not 1 <= raw_samples <= 2_000_000:
            raise HousionnaSimulationApiError(400, "samples_per_src must be an integer from 1 to 2,000,000")
        seed = payload.get("seed", 42)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**31 - 1:
            raise HousionnaSimulationApiError(400, "seed must be a non-negative 32-bit integer")
        normalized = {
            "source_run_id": run_id, "import_id": import_id, "transmitter": transmitter,
            "receiver_ids": receivers, "tx_position": position, "tx_orientation": orientation,
            "frequency_hz": frequency, "solver": resolved_solver,
            "samples_per_src": raw_samples, "seed": seed, "deterministic": True,
            "task": "radio_map" if map_job else "paths",
        }
        if map_job:
            quality = payload.get("quality", "low")
            if not isinstance(quality, str) or quality.lower() not in RADIO_MAP_QUALITY:
                raise HousionnaSimulationApiError(400, "quality must be low, medium, or high")
            normalized["quality"] = quality.lower()
        normalized["source_sha256"] = source_sha256
        normalized["source_files_sha256"] = source_hashes
        rf_request = {**normalized, "runtime": self.runtime,
                      "antenna": {"tx": "1x1 iso V", "rx": "1x1 iso V"},
                      "tx_power_dbm": tx_source["power_dbm"]}
        if map_job:
            for unused in ("receiver_ids", "samples_per_src", "deterministic"):
                rf_request.pop(unused, None)
            rf_request["samples_per_tx"] = RADIO_MAP_QUALITY[normalized["quality"]]["samples_per_tx"]
        normalized["cache_key"] = hashlib.sha256(json.dumps(rf_request, sort_keys=True, allow_nan=False,
                                                           separators=(",", ":")).encode()).hexdigest()
        if map_job:
            mesh_refs={surface["mesh_ref"] for surface in source_scenario.get("radio_map",{}).get("surfaces",[])}
            normalized["_worker_import"]={"schema_version":1,"scenarios":{transmitter:source_scenario},
                "assets":{"meshes":{ref:assets.get("meshes",{}).get(ref,{}) for ref in mesh_refs}}}
        return normalized

    def _find_cached(self, cache_key: str) -> str | None:
        for folder_name, artifact in (("housionna-reruns", "viewer_result.json"),
                                      ("housionna-maps", "radio_map.json")):
            for record in (self.live_root / folder_name).glob("*/execution.json"):
                try:
                    record.resolve().relative_to(self.live_root.resolve())
                    execution = json.loads(record.read_text(encoding="utf-8"))
                    status_file=self.jobs_root/record.parent.name/'status.json'
                    if status_file.is_file() and json.loads(status_file.read_text(encoding='utf-8')).get('status')=='failed':
                        continue
                    if execution.get("cache_key") == cache_key and execution.get("status") == "completed":
                        if ((record.parent / artifact).is_file() and (record.parent / "metadata.json").is_file()
                                and (record.parent / "comparison.json").is_file()
                                and json.loads((record.parent / "metadata.json").read_text(encoding="utf-8")).get("run_id") == record.parent.name):
                            return record.parent.name
                except (OSError, ValueError):
                    continue
        return None

    def _spawn(self, job: dict) -> None:
        import os
        env = dict(os.environ, PYTHONUNBUFFERED="1", HYROPA_JOB_LAUNCHED_NS=str(time.perf_counter_ns()))
        with (job["job_folder"] / "worker.log").open("ab") as log:
            job["process"] = subprocess.Popen(job["command"], cwd=self.project_root,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        atomic_json(job["job_folder"] / "process.json", {"pid": job["process"].pid,
                    "started_at_utc": datetime.now(timezone.utc).isoformat()})

    def start(self, payload: Any, *, map_job: bool = False) -> dict[str, Any]:
        requested_at = time.perf_counter()
        normalized = self._normalize(payload, map_job=map_job)
        with self.lock:
            if self.active_job_id:
                active = self.jobs[self.active_job_id]
                if active.get("cache_key") == normalized["cache_key"]:
                    return self._public(active)
                raise HousionnaSimulationApiError(409, "A HOUSIONNA Sionna simulation is already running")
            cached_id = self._find_cached(normalized["cache_key"])
            if cached_id:
                saved = self.status(cached_id)
                return {**saved, "cache_hit": True, "message": "Loaded cached simulation",
                        "lookup_seconds": round(time.perf_counter() - requested_at, 6)}
            job_id = uuid.uuid4().hex
            job_folder = self.jobs_root / job_id
            job_folder.mkdir(parents=True, exist_ok=False)
            output_base = "housionna-maps" if map_job else "housionna-reruns"
            output_dir = self.live_root / output_base / job_id
            timeout = self.timeouts[normalized.get("quality", "paths")]
            spec = {**normalized, "job_id": job_id, "project_root": str(self.project_root),
                    "output_dir": str(output_dir), "job_folder": str(job_folder), "timeout_seconds": timeout}
            worker_import=normalized.pop("_worker_import",None)
            spec.pop("_worker_import",None)
            if worker_import is not None:
                snapshot=job_folder / "selected_tx_import.json"
                snapshot.write_text(json.dumps(worker_import,allow_nan=False,separators=(",", ":")),encoding="utf-8")
                spec["normalized_import_file"]=str(snapshot)
            spec_file = job_folder / "request.json"
            atomic_json(spec_file, spec)
            job = {"job_id": job_id, "status": "queued", "stage": "queued", "cache_hit": False,
                   "message": "Preparing isolated Sionna worker", "started_monotonic": time.perf_counter(),
                   "started_at_utc": datetime.now(timezone.utc).isoformat(),
                   "job_folder": job_folder, "output_dir": output_dir, "task": normalized["task"],
                   "source_run_id": normalized["source_run_id"], "import_id": normalized["import_id"],
                   "transmitter": normalized["transmitter"], "timeout_seconds": timeout, "attempt": 1,
                   "cache_key": normalized["cache_key"], "request": normalized,
                   "submission_seconds": round(time.perf_counter() - requested_at, 6),
                   "command": [sys.executable, str(self.project_root / "run.py"), "housionna-worker", "--spec", str(spec_file)]}
            try:
                self._spawn(job)
            except OSError as error:
                raise HousionnaSimulationApiError(503, "Could not start isolated Sionna worker") from error
            self.jobs[job_id] = job
            self.active_job_id = job_id
            # Only terminal in-memory records are evicted; scientific artifacts stay on disk.
            for old_id in list(self.jobs):
                if len(self.jobs) <= 32:
                    break
                if old_id != job_id and self.jobs[old_id]["status"] in {"completed", "failed"}:
                    self.jobs.pop(old_id)
            threading.Thread(target=self._monitor, args=(job_id,), daemon=True,
                             name=f"housionna-sionna-{job_id[:8]}").start()
            return self._public(job)

    def _fail(self, job: dict, message: str, *, code: int | None = None) -> None:
        document = {"status": "failed", "stage": "failed", "message": "Sionna calculation stopped",
                    "error": message, "diagnostic_id": job["job_id"], "return_code": code,
                    "duration_seconds": round(time.perf_counter() - job["started_monotonic"], 6),
                    "updated_at_utc": datetime.now(timezone.utc).isoformat()}
        atomic_json(job["job_folder"] / "status.json", document)
        job.update(document)

    @staticmethod
    def _stop_worker(job: dict) -> None:
        # Windows venv launchers can have a real Python child. Kill only the
        # descendants of this still-owned Popen handle, then reap the launcher.
        process=job["process"]
        if process.poll() is None:
            import psutil
            try:
                children=psutil.Process(process.pid).children(recursive=True)
            except (psutil.Error,TypeError,ValueError):
                children=[]
            for child in reversed(children):
                try:child.kill()
                except psutil.Error:pass
        process.kill()
        process.wait(timeout=5)

    def _monitor(self, job_id: str) -> None:
        job = self.jobs[job_id]
        deadline = job["started_monotonic"] + job["timeout_seconds"]
        try:
            while True:
                try:
                    code = job["process"].wait(timeout=max(.01, deadline - time.perf_counter()))
                except subprocess.TimeoutExpired:
                    self._stop_worker(job)
                    with self.lock:
                        self._fail(job, f"The worker exceeded the {job['timeout_seconds']} s safety limit and was terminated. Previous results are retained; inspect diagnostics or adjust the configured limit.")
                    break
                with self.lock:
                    self._refresh(job, allow_completed=True)
                    if code == 0 and job.get("status") == "completed":
                        elapsed = round(time.perf_counter() - job["started_monotonic"], 6)
                        execution = {"status": "completed", "cache_key": job["cache_key"],
                                     "request": job["request"], "runtime": self.runtime,
                                     "worker_wall_seconds": elapsed, "submission_seconds": job["submission_seconds"],
                                     "attempts": job["attempt"], "cache_hit": False}
                        atomic_json(job["output_dir"] / "execution.json", execution)
                        job["duration_seconds"] = elapsed
                        job["execution"] = execution
                        atomic_json(job["job_folder"] / "status.json", {"status":"completed","stage":"completed",
                                    "message":"Sionna results are saved and ready","duration_seconds":elapsed,"run_id":job_id})
                        break
                    log = (job["job_folder"] / "worker.log").read_text(encoding="utf-8", errors="replace")[-8000:]
                    native_jit_error = "Failed to materialize symbols" in log
                    native_error = native_jit_error or (code & 0xffffffff) in {0xc0000374,0xc0000005}
                    if native_error and job["attempt"] == 1 and not job["output_dir"].exists() and time.perf_counter() < deadline:
                        job.update(status="preparing", stage="retrying", message="Native RT failure; retrying once in a fresh isolated worker", attempt=2)
                        atomic_json(job["job_folder"] / "status.json", {"status": "preparing", "stage": "retrying", "message": job["message"]})
                        self._spawn(job)
                        continue
                    try:
                        failure = json.loads((job["job_folder"] / "failure.json").read_text(encoding="utf-8"))
                        message = failure["error"]
                    except (OSError, ValueError, KeyError):
                        message = ("The CPU/LLVM compiler failed to link generated symbols. The worker exited; previous results are retained. Retry the request or use a compatible Linux/CUDA backend."
                                   if native_jit_error else f"The Sionna worker exited with code {code} before completing. Inspect diagnostics for this job and retry.")
                    self._fail(job, message, code=code)
                    break
        except Exception as error:
            with self.lock:
                if job["process"].poll() is None:
                    self._stop_worker(job)
                self._fail(job, f"Worker supervision failed ({type(error).__name__}); the worker was stopped. See backend diagnostics.")
            traceback.print_exc()
        finally:
            with self.lock:
                if self.active_job_id == job_id:
                    self.active_job_id = None

    def _refresh(self, job: dict[str, Any], *, allow_completed: bool = False) -> None:
        # Never let an earlier on-disk progress message undo an exit/timeout failure.
        if job.get("status") in {"failed", "completed"}:
            return
        try:
            status = json.loads((job["job_folder"] / "status.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if status.get("status") in {"queued", "preparing", "running", "exporting", "completed", "failed"}:
            # Completion is published by the supervisor after execution provenance is saved.
            if status["status"] == "completed" and (not allow_completed or job["process"].poll() is None):
                status.update(status="exporting", stage="exporting", message="Finalizing saved results")
            job.update({key: value for key, value in status.items() if key in {"status", "stage", "message", "error", "duration_seconds", "run_id", "diagnostic_id"}})

    def _public(self, job: dict[str, Any]) -> dict[str, Any]:
        self._refresh(job)
        private = {"process", "started_monotonic", "job_folder", "output_dir", "return_code", "command", "request", "cache_key"}
        result = {key: value for key, value in job.items() if key not in private}
        result["elapsed_seconds"] = (job.get("duration_seconds") if job["status"] in {"completed", "failed"}
                                     else round(time.perf_counter() - job["started_monotonic"], 1))
        return result

    def active(self) -> dict | None:
        with self.lock:
            return self._public(self.jobs[self.active_job_id]) if self.active_job_id else None

    def status(self, job_id: str) -> dict[str, Any] | None:
        if not self._valid_id(job_id):
            return None
        with self.lock:
            job = self.jobs.get(job_id)
            if job:
                return self._public(job)
        job_folder = self.jobs_root / job_id
        try:
            job_folder.resolve().relative_to(self.jobs_root.resolve())
            saved=json.loads((job_folder / "status.json").read_text(encoding="utf-8"))
            spec=json.loads((job_folder / "request.json").read_text(encoding="utf-8"))
            if saved.get("status") == "failed":
                return {**saved,"job_id":job_id,"task":spec.get("task")}
        except (OSError,ValueError):
            pass
        for task, folder_name in (("paths", "housionna-reruns"), ("radio_map", "housionna-maps")):
            output_dir = self.live_root / folder_name / job_id
            try:
                output_dir.resolve().relative_to((self.live_root / folder_name).resolve())
                metadata_file = output_dir / "metadata.json"
                metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if metadata.get("run_id") == job_id:
                return {"job_id": job_id, "run_id": job_id, "task": task,
                        "status": "completed", "stage": "completed",
                        "message": "Saved Sionna results are ready",
                        "duration_seconds": metadata.get("duration_seconds"),
                        "started_at_utc": metadata.get("started_at_utc", metadata.get("timestamp_utc"))}
        return None

    def latest(self, source_run_id: str, import_id: str, transmitter: str) -> dict[str, Any]:
        matches: dict[str, list[tuple[str, str]]] = {"path": [], "radio_map": []}
        for task, folder_name, metadata_name, artifact in (
            ("path", "housionna-reruns", "metadata.json", "viewer_result.json"),
            ("radio_map", "housionna-maps", "metadata.json", "radio_map.json"),
        ):
            root = self.live_root / folder_name
            if not root.is_dir():
                continue
            for candidate in root.iterdir():
                if not self._valid_id(candidate.name) or not candidate.is_dir():
                    continue
                try:
                    candidate.resolve().relative_to(root.resolve())
                    status_file=self.jobs_root/candidate.name/'status.json'
                    if status_file.is_file() and json.loads(status_file.read_text(encoding='utf-8')).get('status')=='failed':
                        continue
                    metadata = json.loads((candidate / metadata_name).read_text(encoding="utf-8"))
                    artifact_file = candidate / artifact
                    if not artifact_file.is_file():
                        continue
                    artifact_import_id = metadata.get("import_id")
                    if artifact_import_id is None:
                        artifact_document = json.loads(artifact_file.read_text(encoding="utf-8"))
                        artifact_metadata = artifact_document.get("metadata")
                        artifact_import_id = (artifact_document.get("import_id") or
                                              (artifact_metadata.get("import_id")
                                               if isinstance(artifact_metadata, dict) else None))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if (metadata.get("source_run_id") == source_run_id and
                        artifact_import_id == import_id and
                        metadata.get("transmitter") == transmitter):
                    sort_value = str(metadata.get("started_at_utc") or metadata.get("timestamp_utc") or "")
                    matches[task].append((sort_value, candidate.name))
        latest_path = max(matches["path"], default=("", None))[1]
        latest_map = max(matches["radio_map"], default=("", None))[1]
        return {"source_run_id": source_run_id, "import_id": import_id, "transmitter": transmitter,
                "latest_path_run_id": latest_path, "latest_radio_map_run_id": latest_map}

    def result(self, job_id: str) -> dict[str, Any] | None:
        current = self.status(job_id)
        if current is None:
            return None
        if current["status"] != "completed":
            return current
        with self.lock:
            job = self.jobs.get(job_id)
        if job:
            task, output_dir = job["task"], job["output_dir"]
        else:
            task = current["task"]
            folder_name = "housionna-reruns" if task == "paths" else "housionna-maps"
            output_dir = self.live_root / folder_name / job_id
        if task == "paths":
            try:
                viewer_result = json.loads((output_dir / "viewer_result.json").read_text(encoding="utf-8"))
                comparison = json.loads((output_dir / "comparison.json").read_text(encoding="utf-8"))
                metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {**current, "status": "failed", "error": "Completed Sionna output is incomplete"}
            try:
                metadata["execution"] = json.loads((output_dir / "execution.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
            return {**current, "result": viewer_result, "comparison": comparison, "metadata": metadata}
        try:
            radio_map = json.loads((output_dir / "radio_map.json").read_text(encoding="utf-8"))
            comparison = json.loads((output_dir / "comparison.json").read_text(encoding="utf-8"))
            metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {**current, "status": "failed", "error": "Completed radio-map output is incomplete"}
        try:
            metadata["execution"] = json.loads((output_dir / "execution.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        radio_map["metadata"] = metadata
        return {**current, "radio_map": radio_map, "comparison": comparison}


def simulation_worker_main(argv: list[str] | None = None) -> int:
    import os
    entry_ns = time.perf_counter_ns()
    boot_ns = int(os.environ.get("HYROPA_WORKER_BOOT_NS", entry_ns))
    launched_ns = int(os.environ.get("HYROPA_JOB_LAUNCHED_NS", boot_ns))
    parser = argparse.ArgumentParser(prog="run.py housionna-worker")
    parser.add_argument("--spec", required=True)
    args = parser.parse_args(argv)
    spec_file = Path(args.spec).resolve()
    spec = json.loads(spec_file.read_text(encoding="utf-8"))
    job_folder = Path(spec["job_folder"]).resolve()
    project_root = Path(spec["project_root"]).resolve()

    def write_status(status: str, message: str, **extra: Any) -> None:
        public_status = "preparing" if status == "loading" else "exporting" if status == "processing" else status
        document = {"status": public_status, "stage": status, "message": message,
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(), **extra}
        atomic_json(job_folder / "status.json", document)

    started = time.monotonic()
    try:
        expected_source=spec.get('source_sha256')
        if expected_source and _source_fingerprint(resolve_source_run(project_root,spec['source_run_id']))[0] != expected_source:
            raise ValueError('The source export changed after job submission; reload the export.')
        if spec["task"] == "paths":
            result = run_path_rerun(
                project_root, run_id=spec["source_run_id"], import_id=spec["import_id"],
                transmitter=spec["transmitter"], receiver_names=spec["receiver_ids"],
                tx_position=spec["tx_position"], tx_orientation=spec["tx_orientation"],
                frequency_hz=spec["frequency_hz"], solver=spec["solver"],
                samples_per_src=spec["samples_per_src"], seed=spec["seed"],
                deterministic=spec["deterministic"], output_dir=Path(spec["output_dir"]),
                progress_callback=lambda stage, message: write_status(stage, message),
            )
            duration = result["metadata"]["duration_seconds"]
        else:
            result = run_radio_map_rerun(
                project_root, run_id=spec["source_run_id"], import_id=spec["import_id"],
                transmitter=spec["transmitter"], tx_position=spec["tx_position"],
                tx_orientation=spec["tx_orientation"], frequency_hz=spec["frequency_hz"],
                solver=spec["solver"], quality=spec["quality"], seed=spec["seed"],
                progress_callback=lambda stage, message: write_status(stage, message),
                output_dir=Path(spec["output_dir"]),
                normalized_import_file=Path(spec["normalized_import_file"]) if spec.get("normalized_import_file") else None,
            )
            duration = result["metadata"]["duration_seconds"]
        profile = result["metadata"].setdefault("profile", {"stages_seconds": {}})
        if expected_source and result['metadata'].get('source_sha256') != expected_source:
            raise ValueError('The source export changed during calculation; the result is not cached.')
        profile["stages_seconds"].update(process_startup=round((boot_ns-launched_ns)/1e9, 6),
                                         python_imports=round((entry_ns-boot_ns)/1e9, 6))
        atomic_json(Path(spec["output_dir"]) / "profile.json", profile)
        atomic_json(Path(spec["output_dir"]) / "metadata.json", result["metadata"])
        write_status("completed", "Sionna results are saved and ready", duration_seconds=duration,
                     run_id=result["run_id"])
        return 0
    except Exception as error:
        traceback_text = traceback.format_exc()
        (job_folder / "traceback.txt").write_text(traceback_text, encoding="utf-8")
        safe_message = str(error)
        safe_message = safe_message.replace(str(project_root), "<project>")
        safe_message = re.sub(r"(?i)\b[a-z]:\\[^\r\n\"']+", "<local path>", safe_message)
        safe_message = f"{type(error).__name__}: {safe_message[:360]}"
        (job_folder / "failure.json").write_text(json.dumps({"error": safe_message}, indent=2), encoding="utf-8")
        write_status("failed", "Sionna simulation failed", error=safe_message,
                     duration_seconds=round(time.monotonic() - started, 3))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

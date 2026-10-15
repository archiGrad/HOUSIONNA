"""Minimal free-space-to-free-space Sionna transmission test across one slab surface."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import numpy as np

from cea_demo import _load_cea_config
from poc import OUTPUT_DIR, ROOT, _save_paths


C0 = 299_792_458.0
CASES = ("no_slab", "transparent", "weak_loss", "current")


def _materials() -> dict[str, dict[str, Any]]:
    base = _load_cea_config()
    current = base["materials"]["canopy_placeholder"]
    return {
        "transparent": {
            "status": "CONTROL",
            "source": "Free-space matched eps_r=1, sigma=0 test surface; not vegetation.",
            "relative_permittivity": 1.0, "conductivity_s_per_m": 0.0,
            "thickness_m": 0.8, "scattering_coefficient": 0.0, "xpd_coefficient": 0.0,
        },
        "weak_loss": {
            "status": "WEAK-LOSS DEMO PLACEHOLDER",
            "source": "Arbitrary mild-loss test input; not crop measurement or paper data.",
            "relative_permittivity": 2.0, "conductivity_s_per_m": 0.01,
            "thickness_m": 0.8, "scattering_coefficient": 0.0, "xpd_coefficient": 0.0,
        },
        "current": {
            "status": "CURRENT PLACEHOLDER",
            "source": "Existing config/cea_demo.yaml canopy_placeholder values.",
            "relative_permittivity": float(current["relative_permittivity"]),
            "conductivity_s_per_m": float(current["conductivity_s_per_m"]),
            "thickness_m": float(current["thickness_m"]),
            "scattering_coefficient": float(current.get("scattering_coefficient", 0.0)),
            "xpd_coefficient": float(current.get("xpd_coefficient", 0.0)),
        },
    }


def _single_run(rt, mi, case: str, material: dict[str, Any] | None,
                root: Path, base: dict[str, Any]) -> dict[str, Any]:
    output = root / case
    output.mkdir(parents=True, exist_ok=True)
    scene = rt.load_scene()
    scene.frequency = float(base["frequency_hz"])
    antenna = base["antenna"]
    scene.tx_array = rt.PlanarArray(num_rows=int(antenna["rows"]), num_cols=int(antenna["columns"]),
                                    pattern=antenna["pattern"], polarization=antenna["polarization"])
    scene.rx_array = rt.PlanarArray(num_rows=int(antenna["rows"]), num_cols=int(antenna["columns"]),
                                    pattern=antenna["pattern"], polarization=antenna["polarization"])
    object_id_to_name = {}
    if material is not None:
        rf_material = rt.RadioMaterial(
            name=f"slab_test_{case}",
            thickness=float(material["thickness_m"]),
            relative_permittivity=float(material["relative_permittivity"]),
            conductivity=float(material["conductivity_s_per_m"]),
            scattering_coefficient=float(material["scattering_coefficient"]),
            xpd_coefficient=float(material["xpd_coefficient"]),
            scattering_pattern="lambertian", color=(0.47, 0.61, 0.45),
        )
        scene.add(rf_material)
        # Sionna's RadioMaterial is a slab at an intersected surface. A single
        # open quad avoids applying the slab model twice at a box's two faces.
        plane_path = output / "slab_surface.obj"
        plane_path.write_text(
            "# single plane surface; slab thickness is an RF material property\n"
            "v 0 -1.5 0\n"
            "v 0 1.5 0\n"
            "v 0 1.5 2\n"
            "v 0 -1.5 2\n"
            "f 1 2 3 4\n",
            encoding="utf-8",
        )
        slab = rt.SceneObject(fname=str(plane_path), name="slab_surface",
                              radio_material=rf_material, remove_duplicate_vertices=True)
        scene.add(slab)
        object_id_to_name[int(slab.object_id)] = "slab_surface"

    tx_cfg = {"name": "TX", "position_m": [-2.0, 0.0, 1.0],
              "orientation_rad": [0.0, 0.0, 0.0], "power_dbm": 23.0}
    rx_cfg = {"name": "RX", "role": "opposite side of slab", "position_m": [2.0, 0.0, 1.0]}
    tx = rt.Transmitter(name="TX", position=mi.Point3f(tx_cfg["position_m"]),
                        orientation=mi.Point3f(tx_cfg["orientation_rad"]), power_dbm=tx_cfg["power_dbm"])
    rx = rt.Receiver(name="RX", position=mi.Point3f(rx_cfg["position_m"]))
    scene.add([tx, rx])
    paths = rt.PathSolver(deterministic=True)(
        scene, max_depth=2, samples_per_src=24000, seed=42, los=True,
        specular_reflection=True, diffuse_reflection=False, refraction=True, diffraction=False,
    )
    path_summary = _save_paths(paths, {"receivers": [rx_cfg]}, output, object_id_to_name, allow_empty=True)
    rows = path_summary["paths"]
    refractions = [row for row in rows if "refraction" in row["interaction_types"]]
    reflections = [row for row in rows if "specular_reflection" in row["interaction_types"]]
    direct = [row for row in rows if not row["interaction_types"]]
    metadata = {
        "case": case,
        "purpose": "Test Sionna RT slab transmission in an isolated TX -> slab -> RX geometry.",
        "frequency_hz": float(base["frequency_hz"]),
        "transmitter": tx_cfg,
        "receiver": rx_cfg,
        "surface_geometry": "single open planar quad at x=0 spanning y=[-1.5,1.5] m and z=[0,2] m; absent for no_slab",
        "rf_material": material,
        "solver": {"sionna_rt_path_solver": "PathSolver", "max_depth": 2,
                   "samples_per_source": 24000, "seed": 42, "deterministic": True,
                   "los": True, "specular_reflection": True, "refraction": True,
                   "diffuse_reflection": False, "diffraction": False},
        "path_api": "paths.valid, paths.cir(), paths.interactions, paths.objects, paths.vertices",
        "status": "NOT VALIDATED",
        "summary": {"valid_paths": len(rows), "direct_los_paths": len(direct),
                    "refraction_paths": len(refractions), "reflection_paths": len(reflections),
                    "strongest_refraction_db": max((row["magnitude_db"] for row in refractions), default=None)},
        "paths": rows,
    }
    (output / "experiment_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def run_slab_test(rt=None, mi=None) -> dict[str, Any]:
    if rt is None or mi is None:
        from poc import _load_rt
        rt, mi = _load_rt()
    base = _load_cea_config()
    output_root = OUTPUT_DIR / "slab_test"
    output_root.mkdir(parents=True, exist_ok=True)
    materials = _materials()
    results = {}
    for case in CASES:
        results[case] = _single_run(rt, mi, case, None if case == "no_slab" else materials[case], output_root, base)
        item = results[case]["summary"]
        print(f"Slab test {case}: {item['valid_paths']} paths, {item['refraction_paths']} refraction, {item['reflection_paths']} reflection.")

    summary = {
        "description": "Isolated, single-surface Sionna RadioMaterial slab test.",
        "sionna_api_supports_refraction": True,
        "solver_refraction_enabled": True,
        "single_surface_used": True,
        "cases": results,
    }
    (output_root / "slab_test.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    fields = ["case", "material_status", "valid_paths", "direct_los_paths", "refraction_paths",
              "reflection_paths", "strongest_path_db", "strongest_path_delay_ns",
              "strongest_refraction_db", "strongest_refraction_delay_ns"]
    with (output_root / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for case, detail in results.items():
            paths = detail["paths"]
            strongest = max(paths, key=lambda row: row["magnitude_db"], default=None)
            transmitted = [row for row in paths if "refraction" in row["interaction_types"]]
            strongest_transmitted = max(transmitted, key=lambda row: row["magnitude_db"], default=None)
            writer.writerow({
                "case": case,
                "material_status": (detail["rf_material"] or {}).get("status", "NO SLAB"),
                "valid_paths": detail["summary"]["valid_paths"],
                "direct_los_paths": detail["summary"]["direct_los_paths"],
                "refraction_paths": detail["summary"]["refraction_paths"],
                "reflection_paths": detail["summary"]["reflection_paths"],
                "strongest_path_db": None if strongest is None else f"{strongest['magnitude_db']:.6f}",
                "strongest_path_delay_ns": None if strongest is None else f"{strongest['delay_s']*1e9:.6f}",
                "strongest_refraction_db": None if strongest_transmitted is None else f"{strongest_transmitted['magnitude_db']:.6f}",
                "strongest_refraction_delay_ns": None if strongest_transmitted is None else f"{strongest_transmitted['delay_s']*1e9:.6f}",
            })
    return summary

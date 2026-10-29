"""Sampling-convergence study for the vertical-farm radio maps.

Runs farm_empty and farm_proxy with 1x, 10x, 100x ... the configured sample counts and several random seeds,
writes every run to outputs/convergence/, and prints how much the maps and the canopy effect vary between seeds.
When different seeds agree, the radio map is sampled densely enough to trust.

    python scripts/vertical_farm_convergence.py
    python scripts/vertical_farm_convergence.py --multipliers 1 10 100 --seeds 71 72 73 74
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from demos.cea_demo import _run_scenario  # noqa: E402
from demos.poc import _load_rt  # noqa: E402
from demos.vertical_farm_geometry import (  # noqa: E402
    generate_vertical_farm_geometry,
    load_vertical_farm_config,
    vertical_farm_scenario_config,
)

SCENARIOS = ("farm_empty", "farm_proxy")
FLOOR = 1e-15  # same display floor the project uses for dB maps


def to_db(gain: np.ndarray) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(gain, FLOOR))


def run_one(rt, mi, base: dict, scenario: str, multiplier: int, seed: int, run_root: Path,
            diffraction: bool, diffuse: bool, canopy_scattering: float | None) -> np.ndarray:
    cfg = vertical_farm_scenario_config(base, scenario)
    cfg["path_solver"]["samples_per_source"] = int(cfg["path_solver"]["samples_per_source"]) * multiplier
    cfg["path_solver"]["seed"] = seed
    cfg["radio_map"]["samples_per_transmitter"] = int(cfg["radio_map"]["samples_per_transmitter"]) * multiplier
    cfg["radio_map"]["seed"] = seed
    for solver in ("path_solver", "radio_map"):
        if diffraction:
            cfg[solver]["diffraction"] = True
        if diffuse:
            cfg[solver]["diffuse_reflection"] = True
    if canopy_scattering is not None:
        # Diffuse reflection only has an effect on materials with a non-zero scattering coefficient.
        cfg["materials"]["canopy_placeholder"]["scattering_coefficient"] = canopy_scattering
    geometry = generate_vertical_farm_geometry(cfg)
    _run_scenario(rt, mi, cfg, scenario, output_root=run_root, geometry_override=geometry)
    return np.squeeze(np.load(run_root / scenario / "radio_map.npy"))


def summarise(maps: dict[str, np.ndarray]) -> dict:
    """maps[scenario] has shape (seeds, rows, cols) of linear path gain."""
    empty, proxy = maps["farm_empty"], maps["farm_proxy"]
    out: dict = {"seeds": int(empty.shape[0]), "cells": int(empty[0].size)}
    for name, stack in maps.items():
        positive = stack > 0
        all_positive = positive.all(axis=0)
        some_positive = positive.any(axis=0)
        flips = some_positive & ~all_positive  # zero for some seeds, non-zero for others
        std_db = to_db(stack[:, all_positive]).std(axis=0) if all_positive.any() else np.array([np.nan])
        out[name] = {
            "zero_cells_per_seed": [int((~p).sum()) for p in positive],
            "cells_flipping_between_seeds": int(flips.sum()),
            "per_cell_std_db_mean": float(np.nanmean(std_db)),
            "per_cell_std_db_max": float(np.nanmax(std_db)),
        }
    # Canopy effect, two robust ways: median change over cells lit in both maps, and the change in total received gain.
    median_delta, total_delta = [], []
    for e, p in zip(empty, proxy):
        both = (e > 0) & (p > 0)
        median_delta.append(float(np.median(to_db(p[both]) - to_db(e[both]))) if both.any() else float("nan"))
        total_delta.append(float(10 * np.log10(p.sum() / e.sum())) if e.sum() > 0 and p.sum() > 0 else float("nan"))
    out["canopy_median_delta_db"] = median_delta
    out["canopy_total_gain_delta_db"] = total_delta
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--multipliers", type=int, nargs="+", default=[1, 10, 100, 1000])
    parser.add_argument("--seeds", type=int, nargs="+", default=[71, 72, 73])
    parser.add_argument("--out", type=Path, default=ROOT / "outputs" / "convergence")
    parser.add_argument("--diffraction", action="store_true", help="enable diffraction in both solvers")
    parser.add_argument("--diffuse", action="store_true", help="enable diffuse reflection in both solvers")
    parser.add_argument("--canopy-scattering", type=float, default=None,
                        help="scattering coefficient (0-1) for the canopy material; needed for --diffuse to matter")
    args = parser.parse_args()

    base = load_vertical_farm_config()
    rt, mi = _load_rt()
    print(f"Mitsuba variant: {mi.variant()}")
    print(f"Physics: diffraction={args.diffraction}, diffuse={args.diffuse}, canopy scattering={args.canopy_scattering}")
    args.out.mkdir(parents=True, exist_ok=True)

    results = {}
    for multiplier in args.multipliers:
        maps = {name: [] for name in SCENARIOS}
        for seed in args.seeds:
            run_root = args.out / f"x{multiplier}_seed{seed}"
            for scenario in SCENARIOS:
                started = time.perf_counter()
                maps[scenario].append(run_one(rt, mi, base, scenario, multiplier, seed, run_root,
                                              args.diffraction, args.diffuse, args.canopy_scattering))
                print(f"x{multiplier:<5} seed {seed} {scenario:<11} {time.perf_counter() - started:6.1f} s", flush=True)
        results[f"x{multiplier}"] = summarise({k: np.stack(v) for k, v in maps.items()})

    (args.out / "summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("\nSeed-to-seed spread of the radio map (lower is better; ~1 dB or less = converged)")
    print(f"{'samples':>8} | {'cells flipping':>14} | {'per-cell std dB (mean/max)':>26} | {'no-signal cells empty | canopy':>30} | {'canopy median dB':>17}")
    for key, item in results.items():
        flips = item["farm_proxy"]["cells_flipping_between_seeds"] + item["farm_empty"]["cells_flipping_between_seeds"]
        std_mean = max(item["farm_proxy"]["per_cell_std_db_mean"], item["farm_empty"]["per_cell_std_db_mean"])
        std_max = max(item["farm_proxy"]["per_cell_std_db_max"], item["farm_empty"]["per_cell_std_db_max"])
        zero_empty = "/".join(str(v) for v in item["farm_empty"]["zero_cells_per_seed"])
        zero_canopy = "/".join(str(v) for v in item["farm_proxy"]["zero_cells_per_seed"])
        median = "/".join(f"{v:.2f}" for v in item["canopy_median_delta_db"])
        print(f"{key:>8} | {flips:>14} | {std_mean:>11.2f} / {std_max:<11.2f} | {zero_empty:>13} | {zero_canopy:<13} | {median:>17}")
    print(f"\nPer-run outputs and summary.json: {args.out}")


if __name__ == "__main__":
    main()

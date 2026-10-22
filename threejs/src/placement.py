"""Transmitter placement: choose k of the candidate transmitters of one run for the best worst-case receiver.

    python run.py placement --run 20261020_183214Z        # results in outputs/placement/<run>/

Every transmitter of the run is a candidate position. For each subset size k the script finds the subset that
maximises, at the worst receiver,

* ble_margin       the best-server communication margin, max over the chosen transmitters (paper eq. worst case);
* wpt_coherent     incident power with coherent maximum-ratio transmission, P sum_i |h_ij|^2, the total power P
                   shared by the chosen transmitters and the beam focused on one receiver at a time;
* wpt_incoherent   incident power with P split equally and no phase alignment, (P/k) sum_i g_ij;
* wpt_single       incident power with all of P on the best chosen transmitter, P max_i |h_ij|^2.

With up to 16 candidates every subset is evaluated (exhaustive); beyond that a greedy search is used. The spread
over all subsets of each size is reported too, so the gain of choosing positions well is visible.
"""
from __future__ import annotations

import argparse
from itertools import combinations
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from application_engine import ROOT, RunChannels, _jsonable, db, link_margins_db, load_channels, load_config

OBJECTIVES = {
    "ble_margin": ("Worst-case BLE margin", "dB"),
    "wpt_coherent": ("Coherent MRT", "dBm"),
    "wpt_incoherent": ("Equal split, incoherent", "dBm"),
    "wpt_single": ("Best single TX", "dBm"),
}
EXHAUSTIVE_LIMIT = 16


def subset_scores(run: RunChannels, subsets: np.ndarray, config: dict[str, Any]) -> dict[str, np.ndarray]:
    """Worst-receiver score of each subset (rows of transmitter indices, all of one size k)."""
    total_w = 10 ** ((float(config["wpt"]["total_power_dbm"]) - 30) / 10)
    k = subsets.shape[1]
    margins = link_margins_db(run, config["communication"]["ble_1m"])         # (n_tx, n_rx)
    power = np.abs(run.h) ** 2
    worst = lambda values: values.min(axis=1)                                   # noqa: E731  over receivers
    return {
        "ble_margin": worst(margins[subsets].max(axis=1)),
        "wpt_coherent": db(worst(total_w * power[subsets].sum(axis=1))) + 30,
        "wpt_incoherent": db(worst(total_w / k * run.gain_incoherent[subsets].sum(axis=1))) + 30,
        "wpt_single": db(worst(total_w * power[subsets].max(axis=1))) + 30,
    }


def _greedy(run: RunChannels, config: dict[str, Any], objective: str, k_max: int) -> list[list[int]]:
    chosen: list[int] = []
    picks = []
    for _ in range(k_max):
        options = [i for i in range(run.h.shape[0]) if i not in chosen]
        trial = np.array([chosen + [i] for i in options])
        best = options[int(np.argmax(subset_scores(run, trial, config)[objective]))]
        chosen.append(best)
        picks.append(sorted(chosen))
    return picks


def optimise(run: RunChannels, config: dict[str, Any], k_max: int | None = None) -> dict[str, Any]:
    n = run.h.shape[0]
    k_max = min(k_max or n, n)
    exhaustive = n <= EXHAUSTIVE_LIMIT
    greedy = {objective: _greedy(run, config, objective, k_max) for objective in OBJECTIVES}
    sizes = []
    for k in range(1, k_max + 1):
        row: dict[str, Any] = {"k": k, "objectives": {}}
        if exhaustive:
            subsets = np.array(list(combinations(range(n), k)))
            scores = subset_scores(run, subsets, config)
            row["subsets_evaluated"] = len(subsets)
        for objective in OBJECTIVES:
            greedy_subset = np.array([greedy[objective][k - 1]])
            item = {"greedy_subset": [run.tx_names[i] for i in greedy_subset[0]],
                    "greedy_value": float(subset_scores(run, greedy_subset, config)[objective][0])}
            if exhaustive:
                values = scores[objective]
                best = int(np.argmax(values))
                item.update(best_subset=[run.tx_names[i] for i in subsets[best]], best_value=float(values[best]),
                            median=float(np.median(values)), p10=float(np.percentile(values, 10)),
                            p90=float(np.percentile(values, 90)), worst=float(values.min()))
            row["objectives"][objective] = item
        sizes.append(row)
    return {"run_id": run.run_id, "import_id": run.import_id, "frequency_hz": run.frequency_hz,
            "candidates": {name: run.tx_positions_m[i].tolist() for i, name in enumerate(run.tx_names)},
            "receivers": len(run.rx_names), "exhaustive": exhaustive, "sizes": sizes,
            "total_power_dbm": float(config["wpt"]["total_power_dbm"]),
            "ble_profile": config["communication"]["ble_1m"]}


def figures(result: dict[str, Any], run: RunChannels, config: dict[str, Any], out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    written = []
    ks = [row["k"] for row in result["sizes"]]
    key = "best_value" if result["exhaustive"] else "greedy_value"

    fig, (top, bottom) = plt.subplots(2, 1, figsize=(3.5, 4.2), sharex=True)
    colors = {"wpt_coherent": "tab:red", "wpt_incoherent": "tab:orange", "wpt_single": "tab:blue"}
    for objective, color in colors.items():
        values = [row["objectives"][objective][key] for row in result["sizes"]]
        top.plot(ks, values, marker="o", markersize=3, linewidth=1.4, color=color, label=OBJECTIVES[objective][0])
        if result["exhaustive"]:
            top.fill_between(ks, [row["objectives"][objective]["p10"] for row in result["sizes"]],
                             [row["objectives"][objective]["p90"] for row in result["sizes"]], color=color, alpha=0.12,
                             linewidth=0)
    top.set_ylabel("Worst-case incident\nRF power (dBm)")
    top.grid(alpha=0.3, linewidth=0.5)
    top.legend(fontsize=6.5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    ble = [row["objectives"]["ble_margin"][key] for row in result["sizes"]]
    bottom.plot(ks, ble, marker="o", markersize=3, linewidth=1.4, color="0.2")
    if result["exhaustive"]:
        bottom.fill_between(ks, [row["objectives"]["ble_margin"]["p10"] for row in result["sizes"]],
                            [row["objectives"]["ble_margin"]["p90"] for row in result["sizes"]], color="0.2", alpha=0.12,
                            linewidth=0)
    bottom.set_ylabel("Worst-case BLE\nmargin (dB)")
    bottom.set_xlabel("Number of transmitters k")
    bottom.grid(alpha=0.3, linewidth=0.5)
    bottom.set_xticks([k for k in ks if k % 2 == 1])
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"placement_vs_k.{suffix}", dpi=200)
        written.append(out / f"placement_vs_k.{suffix}")
    plt.close(fig)

    # Top view: receivers coloured by coherent incident power for the best 3-transmitter subset, all candidates shown.
    k_show = min(3, len(result["sizes"]))
    chosen = result["sizes"][k_show - 1]["objectives"]["wpt_coherent"].get("best_subset") or \
        result["sizes"][k_show - 1]["objectives"]["wpt_coherent"]["greedy_subset"]
    index = [run.tx_names.index(name) for name in chosen]
    total_w = 10 ** ((float(config["wpt"]["total_power_dbm"]) - 30) / 10)
    p_dbm = db(total_w * (np.abs(run.h[index]) ** 2).sum(axis=0)) + 30
    fig, ax = plt.subplots(figsize=(3.5, 3.6))
    points = ax.scatter(run.rx_positions_m[:, 0], run.rx_positions_m[:, 1], c=p_dbm, cmap="viridis", s=18)
    ax.scatter(run.tx_positions_m[:, 0], run.tx_positions_m[:, 1], marker="^", s=30, facecolors="none",
               edgecolors="0.45", linewidths=0.8, label="Candidate TX")
    ax.scatter(run.tx_positions_m[index, 0], run.tx_positions_m[index, 1], marker="^", s=55, color="tab:red",
               label=f"Chosen TX (k={k_show})")
    worst = int(np.argmin(p_dbm))
    ax.scatter(*run.rx_positions_m[worst, :2], s=70, facecolors="none", edgecolors="tab:red", linewidths=1.0,
               label="Worst receiver")
    ax.set_aspect("equal")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("y (m)")
    ax.legend(fontsize=6.5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=3)
    fig.colorbar(points, ax=ax, label="Coherent incident power (dBm)", shrink=0.8)
    fig.tight_layout()
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"placement_top_k{k_show}.{suffix}", dpi=200)
        written.append(out / f"placement_top_k{k_show}.{suffix}")
    plt.close(fig)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py placement", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", required=True, help="run id (newest import of it) or import id")
    parser.add_argument("--k-max", type=int, help="largest subset size (default: all candidates)")
    parser.add_argument("--config", type=Path, help="application profiles (default config/applications.yaml)")
    parser.add_argument("--out", type=Path, help="output folder (default outputs/placement/<run>)")
    args = parser.parse_args(argv)
    from integrations.housionna import list_imports
    rows = sorted((row for row in list_imports(ROOT) if args.run in (row["run_id"], row["import_id"])),
                  key=lambda row: row.get("imported_at_utc") or "")
    if not rows:
        print(f"No import found for {args.run}")
        return 2
    config = load_config(args.config)
    run = load_channels(ROOT, rows[-1]["import_id"])
    if run.h.shape[0] < 2:
        print("Placement needs a run with at least two transmitters")
        return 2
    result = optimise(run, config, args.k_max)
    out = args.out or ROOT / "outputs" / "placement" / run.run_id.replace(".", "_")
    out.mkdir(parents=True, exist_ok=True)
    (out / "placement.json").write_text(json.dumps(_jsonable(result), indent=2), encoding="utf-8")
    written = [out / "placement.json"] + figures(result, run, config, out)
    key = "best_value" if result["exhaustive"] else "greedy_value"
    print(f"{run.run_id}: {run.h.shape[0]} candidate TX, {run.h.shape[1]} receivers, "
          f"{'exhaustive' if result['exhaustive'] else 'greedy'} search")
    print(f"{'k':>3}  " + "  ".join(f"{OBJECTIVES[o][0][:22]:>22s}" for o in OBJECTIVES))
    for row in result["sizes"]:
        cells = []
        for objective in OBJECTIVES:
            item = row["objectives"][objective]
            spread = f" [{item['median']:6.1f}]" if "median" in item else ""
            cells.append(f"{item[key]:7.1f}{spread} {OBJECTIVES[objective][1]:>3s}".rjust(22))
        print(f"{row['k']:>3}  " + "  ".join(cells))
    print("(best subset, [median over all subsets of that size])")
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0

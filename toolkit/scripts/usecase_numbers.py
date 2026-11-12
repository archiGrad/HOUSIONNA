"""Every number of the paper's use case (table, text and distribution figure) from the imported runs.

    python scripts/usecase_numbers.py                                   # every study of the paper, one by one
    python scripts/usecase_numbers.py --study moisture [--study ...]    # some of them (STUDIES below)
    python scripts/usecase_numbers.py --batch <batch> [--batch <batch> ...]

The runs of all --batch are pooled and keyed by their wedge parameters and carrier frequency, so the frequencies may
come from separate batches of the same scenes or from a wedged frequency within one batch: a parameter that takes one
value per carrier frequency only restates it and is left out of the key. The use case is evaluated at
--power-frequency (default 915 MHz); the BLE uplink at --ble-frequency (default 2.437 GHz) and the gains at every other
frequency come from the run with the same parameters. Rows are labelled by the parameters that vary between them;
--group picks the parameters instead.

Each work item has one or more gateways (--gateway, default ap_) and sensor nodes (--sensors, default plant_sensor_);
the channels are oriented gateway-to-sensor by reciprocity (engine.orient), whichever side transmitted. Sensor nodes
with a surface within 1 cm towards any gateway are excluded automatically (engine.screening): Sionna RT discards
those path segments. Gains are incoherent sums over the paths, from the best gateway. The RF power at a sensor node is
the coherent value at its position with the gateways sharing wpt.total_power_dbm, for two strategies: all power on the
best gateway (single_best) and coherent maximum-ratio transmission (coherent_mrt), equal for one gateway; --strategy
picks the one in the table and figure. A sensor node without any path from a gateway counts as not powered; the worst
gain, the BLE margin and the point-versus-local-mean spread are taken over the nodes with a path, and the nodes
without one are counted per row (no path). A sensor node is powered within an hour when its harvester charges a 346 uF
buffer from 0.05 V to 4.5 V in that time (constant DC power). Writes outputs/casestudy/<first batch>/
usecase_numbers.json, usecase_rows.tex (table rows), usecase_strategies.tex (both strategies, when a work item has more
than one gateway) and usecase_rf_cdf.pdf (distribution of the RF power per row).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from engine.application_engine import (  # noqa: E402
    RunChannels, _jsonable, db, harvest_w, harvester_threshold_dbm, load_channels, load_config, orient,
    reporting_interval_s, wpt_received_power_w,
)
from engine.screening import too_close  # noqa: E402

# The studies of the paper, each one evaluated on its own: the final batches of 10 Nov 2026 (hip v3, sensor nodes
# 2 cm from the mesh and oriented along the stem), every one wedged over plant_stage and one more parameter.
# The viewer shows the same four (viewer/src/studies.js).
STUDIES = {
    "species": ["V2_batch_01_20261110_125549Z"],     # plant_species
    "frequency": ["v2_batch_02_20261110_154706Z"],   # 868 MHz, 915 MHz, 2.437 GHz, 5.18 GHz
    "ap_density": ["V2_batch_03_20261110_155715Z"],  # 1 to 23 gateways
    "moisture": ["bacth_04_20261110_160139Z"],       # leaf moisture 20 to 90 %
}
HARVESTERS = ("aem40940_921_fit", "p1110b_915_fit")
STRATEGIES = ("single_best", "coherent_mrt")
HOUR_S = 3600.0
SAME_CARRIER = 0.005           # relative tolerance when matching a carrier frequency
# The storage buffer, charged from (almost) empty to the target voltage as in the AMBIENT-6G webtool. The datasheet
# curves give P_DC at one output voltage, so the charge time is C (V1^2 - V0^2) / (2 P_DC) at constant power.
BUFFER_F, V_START, V_TARGET = 346e-6, 0.05, 4.5


def frequency_parameters(runs: list[RunChannels]) -> set[str]:
    """Wedge parameters that only restate the carrier: one value per frequency, over more than one frequency."""
    if len({run.frequency_hz for run in runs}) < 2:
        return set()
    out = set()
    for name in set().union(*(run.parameters for run in runs)):
        per_carrier: dict[float, object] = {}
        if all(per_carrier.setdefault(run.frequency_hz, run.parameters.get(name)) == run.parameters.get(name)
               for run in runs) and len(set(per_carrier.values())) > 1:
            out.add(name)
    return out


def group_runs(runs: list[RunChannels]) -> tuple[dict[tuple, dict[float, RunChannels]], set[str]]:
    """{wedge parameters without the frequency ones: {carrier frequency: run}}, and the frequency parameters."""
    carrier = frequency_parameters(runs)
    out: dict[tuple, dict[float, RunChannels]] = {}
    for run in runs:
        key = tuple(sorted((k, v) for k, v in run.parameters.items() if k not in carrier))
        by_carrier = out.setdefault(key, {})
        if run.frequency_hz in by_carrier:
            raise SystemExit(f"{by_carrier[run.frequency_hz].run_id} and {run.run_id} have the same parameters "
                             f"{dict(key)} at {run.frequency_hz / 1e9:g} GHz")
        by_carrier[run.frequency_hz] = run
    return out, carrier


def runs_of(batches: list[str], gateway: str, sensors: str) -> list[RunChannels]:
    """The oriented runs of the batches that have gateways and sensor nodes."""
    out = []
    for batch in batches:
        found = [orient(load_channels(ROOT, path.name), gateway, sensors)
                 for path in sorted((ROOT / "outputs" / "integrations" / "housionna").glob(f"{batch}_wi*"))]
        found = [run for run in found if run.rx_names and run.tx_names]
        if not found:
            raise SystemExit(f"no imported runs of {batch} with {gateway}* and {sensors}* (python run.py import-housionna)")
        out += found
    return out


def at(by_carrier: dict[float, RunChannels], hz: float) -> RunChannels | None:
    return next((run for f, run in by_carrier.items() if abs(f - hz) <= SAME_CARRIER * hz), None)


def varying(keys: list[tuple]) -> list[str]:
    """The parameters that take more than one value over the keys."""
    names = sorted(set().union(*(dict(key) for key in keys)))
    return [name for name in names if len({dict(key).get(name) for key in keys}) > 1]


def label(key: tuple, names: list[str]) -> str:
    return ", ".join(f"{k}={v}" for k, v in key if k in names) or "all"


def evaluate(run: RunChannels, keep: list[int], p_gw_w: float, harvesters: dict[str, dict],
             buffer_j: float) -> dict[str, object]:
    """Gains from the best gateway and, per strategy, the RF power and charging of the kept sensor nodes.

    A sensor node without any path from any gateway has no gain (-inf dB) and no RF power: it counts as a node that
    is not powered, but is left out of the worst gain and the point-versus-local-mean statistic (has_path False)."""
    gains = run.gain_incoherent[:, keep]
    best = gains.argmax(axis=0)
    columns = np.arange(len(keep))
    has_path = gains.max(axis=0) > 0
    gain_db = db(gains[best, columns])
    coherent_db = db(np.abs(run.h[:, keep][best, columns]) ** 2)
    out = {"gain_db": gain_db, "has_path": has_path,
           "below_local_mean_db": (gain_db - coherent_db)[has_path & np.isfinite(coherent_db)], "strategies": {}}
    incident = wpt_received_power_w(run, p_gw_w)
    for strategy in STRATEGIES:
        p_rf_w = incident[strategy][keep]
        charge_s = {name: reporting_interval_s(harvest_w(p_rf_w, h), buffer_j, 0.0) for name, h in harvesters.items()}
        p_rf_dbm = db(p_rf_w) + 30.0
        out["strategies"][strategy] = {
            "p_rf_dbm": [float(v) for v in p_rf_dbm], "p_rf_median_dbm": float(np.median(p_rf_dbm)),
            "within_hour": {name: int(np.sum(t <= HOUR_S)) for name, t in charge_s.items()},
            "charge_time_median_s": {name: float(np.median(t)) for name, t in charge_s.items()}}
    return out


def cdf_figure(groups: dict[str, np.ndarray], thresholds: dict[str, float], out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # Wide enough for the legend beside the axes: one line per row, so the curves stay readable.
    fig, ax = plt.subplots(figsize=(7.0, 4.2))
    for name, values in groups.items():
        values = np.sort(values[np.isfinite(values)])
        if values.size:
            ax.step(values, np.arange(1, values.size + 1) / values.size, where="post", label=name, linewidth=1.2)
    for harvester, level in thresholds.items():
        ax.axvline(level, color="0.5", linewidth=0.8, linestyle="--")
        ax.text(level + 0.3, 0.02, harvester, rotation=90, fontsize=7, color="0.35", va="bottom",
                transform=ax.get_xaxis_transform())
    ax.set_xlabel("RF power at the sensor node (dBm)")
    ax.set_ylabel("Fraction of sensor nodes")
    ax.set_ylim(0, 1.02)
    ax.grid(alpha=0.3, linewidth=0.5)
    ax.legend(fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.01, 1.0), borderaxespad=0.0)
    fig.tight_layout()
    written = []
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"usecase_rf_cdf.{suffix}", dpi=200, bbox_inches="tight")
        written.append(out / f"usecase_rf_cdf.{suffix}")
    plt.close(fig)
    return written


def finite_min(values) -> float | None:
    """The smallest finite value, None when there is none."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    return float(values.min()) if values.size else None


def fmt(value: float | None, math: bool = True) -> str:
    """One decimal, in math mode for the table; -- for no value."""
    if value is None or not np.isfinite(value):
        return "--"
    return f"${value:.1f}$" if math else f"{value:.1f}"


def study(batches: list[str], args: argparse.Namespace, names: list[str]) -> int:
    """The use case over the pooled runs of the batches; writes outputs/casestudy/<first batch>/."""
    config = load_config()
    ble = config["communication"]["ble_1m"]
    p_gw_dbm = float(config["wpt"]["total_power_dbm"])
    buffer_j = 0.5 * BUFFER_F * (V_TARGET ** 2 - V_START ** 2)
    harvesters = {name: load_config(harvester=name)["wpt"]["harvester"] for name in names}

    grouped, carrier_parameters = group_runs(runs_of(batches, args.gateway, args.sensors))
    power = {key: run for key, by_carrier in grouped.items() if (run := at(by_carrier, args.power_frequency))}
    if not power:
        raise SystemExit(f"no run at {args.power_frequency / 1e9:g} GHz in {', '.join(batches)} (--power-frequency)")
    shown = args.group or varying(list(power))
    rows, cdf, all_p_rf, fading, gains_at = [], {}, [], [], {}
    for key, run in power.items():
        excluded = too_close(run.run_id, args.gateway, args.sensors)
        keep = [j for j, name in enumerate(run.rx_names) if name not in excluded]
        row = {"group": label(key, shown), "parameters": dict(key), "run_id": run.run_id,
               "gateways": len(run.tx_names), "sensor_nodes": len(keep),
               "excluded": {name: round(distance * 100, 2) for name, distance in excluded.items()}}
        rows.append(row)
        if not keep:
            row["note"] = "every sensor node within 1 cm of a surface towards a gateway"
            continue
        names_kept = [run.rx_names[j] for j in keep]
        result = evaluate(run, keep, 10 ** ((p_gw_dbm - 30) / 10), harvesters, buffer_j)
        chosen = result["strategies"][args.strategy]
        fading += list(result["below_local_mean_db"])
        all_p_rf += chosen["p_rf_dbm"]
        cdf[row["group"]] = np.array(chosen["p_rf_dbm"])
        row.update(no_path=int(np.sum(~result["has_path"])),
                   no_path_nodes=[name for name, ok in zip(names_kept, result["has_path"]) if not ok],
                   gain_median_db=float(np.median(result["gain_db"])),
                   gain_worst_db=finite_min(result["gain_db"]),
                   p_rf_median_dbm=chosen["p_rf_median_dbm"], p_rf_dbm=chosen["p_rf_dbm"],
                   within_hour=chosen["within_hour"], charge_time_median_s=chosen["charge_time_median_s"],
                   strategies=result["strategies"])
        if (other := at(grouped[key], args.ble_frequency)) is not None:
            index = [other.rx_names.index(name) for name in names_kept if name in other.rx_names]
            margin = ble["tx_power_dbm"] + db(other.gain_incoherent[:, index].max(axis=0)) - ble["sensitivity_dbm"] \
                - ble["reserve_db"]
            row["ble_worst_margin_db"] = finite_min(margin)
            row["ble_no_path"] = int(np.sum(~np.isfinite(margin)))
        for f, other in grouped[key].items():
            index = [other.rx_names.index(name) for name in names_kept if name in other.rx_names]
            gains_at.setdefault(f, []).extend(db(other.gain_incoherent[:, index].max(axis=0)))

    medians = {f: float(np.median(values)) for f, values in sorted(gains_at.items())}
    f0 = next(iter(power.values())).frequency_hz
    evaluated = [row for row in rows if row["sensor_nodes"]]
    multi = any(row["gateways"] > 1 for row in evaluated)
    ble_rows = [row for row in evaluated if "ble_worst_margin_db" in row]
    summary = {
        "batches": batches, "power_frequency_hz": f0, "ble_frequency_hz": args.ble_frequency,
        "frequency_parameters": sorted(carrier_parameters), "row_parameters": shown, "strategy": args.strategy,
        "sensor_nodes": sum(row["sensor_nodes"] for row in evaluated),
        "excluded": sum(len(row["excluded"]) for row in rows),
        "no_path": sum(row["no_path"] for row in evaluated),
        "within_hour_total": {name: sum(row["within_hour"][name] for row in evaluated) for name in names},
        "within_hour_total_by_strategy": {s: {name: sum(row["strategies"][s]["within_hour"][name] for row in evaluated)
                                              for name in names} for s in STRATEGIES},
        "gain_median_db": {f"{f / 1e9:g} GHz": value for f, value in medians.items()},
        "gain_drop_db": {f"{f / 1e9:g} GHz": medians[f0] - value for f, value in medians.items()},
        "free_space_drop_db": {f"{f / 1e9:g} GHz": 20 * np.log10(f / f0) for f in medians},
        "p_rf_median_dbm": float(np.median(all_p_rf)),
        "ble_worst_margin_db": min((row["ble_worst_margin_db"] for row in ble_rows
                                    if row["ble_worst_margin_db"] is not None), default=None),
        "ble_no_path": sum(row["ble_no_path"] for row in ble_rows) if ble_rows else None,
        "point_below_local_mean_db": ({"median": float(np.median(fading)), "max": float(np.max(fading))}
                                      if fading else None),
        "sensor_nodes_at_threshold": {name: int(np.sum(np.array(all_p_rf) >= harvester_threshold_dbm(h)))
                                      for name, h in harvesters.items()},
        "buffer": {"capacitance_uf": BUFFER_F * 1e6, "v_start": V_START, "v_target": V_TARGET, "energy_mj": buffer_j * 1e3},
        "gateway_dbm": p_gw_dbm,
        "harvesters": {name: h["label"] for name, h in harvesters.items()}, "rows": rows,
    }
    out = ROOT / "outputs" / "casestudy" / batches[0]
    out.mkdir(parents=True, exist_ok=True)
    (out / "usecase_numbers.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    tex = ["% python scripts/usecase_numbers.py: rows of the use-case table. Worst gain and BLE margin are over the",
           "% sensor nodes with a path (-- when none has one); no path: sensor nodes without any path, not powered",
           "% The same sensor nodes recur in every row, so the counts are out of the row's n (x/n) and not summed.",
           "% group & no path & gain median & worst & BLE worst & P_RF median & " + " & ".join(names)]
    for row in evaluated:
        n = row["sensor_nodes"]
        cells = [row["group"].replace("_", "\\_"), str(row["no_path"]),
                 fmt(row["gain_median_db"]), fmt(row["gain_worst_db"]),
                 fmt(row.get("ble_worst_margin_db"), math=False), fmt(row["p_rf_median_dbm"])] \
            + [f"{row['within_hour'][name]}/{n}" for name in names]
        tex.append(" & ".join(cells) + " \\\\")
    (out / "usecase_rows.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    written = [out / "usecase_numbers.json", out / "usecase_rows.tex"]
    if multi:
        tex = ["% python scripts/usecase_numbers.py: rows per gateway strategy",
               "% group & gateways & n & P_RF median " + " & ".join(STRATEGIES) + " & within 1 h "
               + " & ".join(f"{s} {name}" for s in STRATEGIES for name in names)]
        for row in evaluated:
            cells = [row["group"].replace("_", "\\_"), str(row["gateways"]), str(row["sensor_nodes"])] \
                + [fmt(row["strategies"][s]["p_rf_median_dbm"]) for s in STRATEGIES] \
                + [str(row["strategies"][s]["within_hour"][name]) for s in STRATEGIES for name in names]
            tex.append(" & ".join(cells) + " \\\\")
        (out / "usecase_strategies.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
        written.append(out / "usecase_strategies.tex")
    thresholds = {harvesters[name]["label"].split(" at ")[0].split(", ")[0]: harvester_threshold_dbm(harvesters[name])
                  for name in names}
    written += cdf_figure(cdf, thresholds, out)

    print(f"== {', '.join(batches)}")
    if carrier_parameters:
        print(f"frequency given by {', '.join(sorted(carrier_parameters))}")
    for row in rows:
        if not row["sensor_nodes"]:
            print(f"{row['group']}: excluded ({row['note']})")
            continue
        counts = " / ".join(str(row["within_hour"][name]) for name in names)
        gateways = f", {row['gateways']} gateways" if multi else ""
        no_path = f", no path {row['no_path']}" if row["no_path"] else ""
        ble_text = fmt(row.get("ble_worst_margin_db"), math=False)
        if row.get("ble_no_path"):
            ble_text += f" (no path {row['ble_no_path']})"
        print(f"{row['group']}: n={row['sensor_nodes']} (excluded {len(row['excluded'])}{no_path}){gateways}, gain "
              f"{fmt(row['gain_median_db'], math=False)} / {fmt(row['gain_worst_db'], math=False)} dB, "
              f"BLE {ble_text} dB, P_RF {fmt(row['p_rf_median_dbm'], math=False)} dBm, within 1 h {counts}")
    print(f"total: {summary['sensor_nodes']} sensor nodes ({summary['no_path']} without a path), within 1 h "
          f"({args.strategy}) " + ", ".join(f"{name} {value}" for name, value in summary["within_hour_total"].items()))
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", action="append", help="batch (repeatable, pooled into one study)")
    parser.add_argument("--study", action="append", choices=list(STUDIES),
                        help="study of the paper (repeatable; default all of them when no --batch is given)")
    parser.add_argument("--power-frequency", type=float, default=915e6, help="carrier of the power transfer (Hz)")
    parser.add_argument("--ble-frequency", type=float, default=2.437e9, help="carrier of the BLE uplink (Hz)")
    parser.add_argument("--gateway", default="ap_", help="name prefix of the gateways (default ap_)")
    parser.add_argument("--sensors", default="plant_sensor_", help="name prefix of the sensor nodes")
    parser.add_argument("--group", action="append", help="parameter in the row labels (repeatable; default the varying ones)")
    parser.add_argument("--strategy", choices=STRATEGIES, default="coherent_mrt",
                        help="gateway strategy in the table and figure (default coherent_mrt)")
    parser.add_argument("--harvester", action="append", help=f"harvester (repeatable; default {', '.join(HARVESTERS)})")
    args = parser.parse_args(argv)
    if args.batch and args.study:
        parser.error("--batch and --study exclude each other")
    names = args.harvester or list(HARVESTERS)
    studies = [args.batch] if args.batch else [STUDIES[name] for name in (args.study or STUDIES)]
    for batches in studies:
        study(batches, args, names)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Every number of the paper's use case (table, text and distribution figure) from the imported runs.

    python scripts/usecase_numbers.py                                   # the batches of the current paper
    python scripts/usecase_numbers.py --batch <915 MHz batch> --ble-batch <2.437 GHz batch> [--compare-batch <...>]

Each batch has one gateway (--gateway, default ap_) and sensor nodes (--sensors, default plant_sensor_) per work item;
the channels are oriented gateway-to-sensor by reciprocity (engine.orient), whichever side transmitted. Work items are
grouped by their wedge parameters (e.g. plant_type and growth_stage, or plant_id); --group picks the parameters.
Sensor nodes with a surface within 1 cm towards the gateway are excluded automatically (engine.screening): Sionna RT
discards those path segments. Gains are incoherent sums over the paths; the RF power at a sensor node is the coherent
value at its position with the gateway at wpt.total_power_dbm. A sensor node is powered within an hour when its
harvester charges a 346 uF buffer from 0.05 V to 4.5 V in that time (constant DC power). Writes outputs/casestudy/<batch>/usecase_numbers.json,
usecase_rows.tex (table rows) and usecase_rf_cdf.pdf (distribution of the RF power per group).
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
    _jsonable, db, harvest_w, harvester_threshold_dbm, load_channels, load_config, orient, reporting_interval_s,
)
from engine.screening import too_close  # noqa: E402

DEFAULTS = {"batch": "batch_1_0_20261030_055729Z", "ble_batch": "batch_1_0_20261030_060650Z",
            "compare_batch": ["batch_1_0_20261030_060904Z"]}
HARVESTERS = ("aem40940_921_fit", "p1110b_915_fit")
HOUR_S = 3600.0
# The storage buffer, charged from (almost) empty to the target voltage as in the AMBIENT-6G webtool. The datasheet
# curves give P_DC at one output voltage, so the charge time is C (V1^2 - V0^2) / (2 P_DC) at constant power.
BUFFER_F, V_START, V_TARGET = 346e-6, 0.05, 4.5


def runs_of(batch: str, gateway: str, sensors: str) -> dict[tuple, object]:
    """The oriented runs of a batch with sensor nodes, keyed by their sorted wedge parameters."""
    out = {}
    for path in sorted((ROOT / "outputs" / "integrations" / "housionna").glob(f"{batch}_wi*")):
        run = orient(load_channels(ROOT, path.name), gateway, sensors)
        if run.rx_names and run.tx_names:
            out[tuple(sorted(run.parameters.items()))] = run
    if not out:
        raise SystemExit(f"no imported runs of {batch} with {gateway}* and {sensors}* (python run.py import-housionna)")
    return out


def label(key: tuple, group: list[str] | None) -> str:
    items = [(k, v) for k, v in key if not group or k in group]
    return ", ".join(f"{k}={v}" for k, v in items) or "all"


def cdf_figure(groups: dict[str, np.ndarray], thresholds: dict[str, float], out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    for name, values in groups.items():
        values = np.sort(values[np.isfinite(values)])
        if values.size:
            ax.step(values, np.arange(1, values.size + 1) / values.size, where="post", label=name, linewidth=1.3)
    for harvester, level in thresholds.items():
        ax.axvline(level, color="0.5", linewidth=0.8, linestyle="--")
        ax.text(level + 0.5, 0.98, harvester, rotation=90, fontsize=6, color="0.4", va="top",
                transform=ax.get_xaxis_transform())
    ax.set_xlabel("RF power at the sensor node (dBm)")
    ax.set_ylabel("Fraction of sensor nodes")
    ax.grid(alpha=0.3, linewidth=0.5)
    ax.legend(fontsize=6.5, frameon=False, loc="upper left")
    fig.tight_layout()
    written = []
    for suffix in ("pdf", "png"):
        fig.savefig(out / f"usecase_rf_cdf.{suffix}", dpi=200)
        written.append(out / f"usecase_rf_cdf.{suffix}")
    plt.close(fig)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", default=DEFAULTS["batch"], help="batch at the power frequency (915 MHz)")
    parser.add_argument("--ble-batch", default=DEFAULTS["ble_batch"], help="the same scenes at 2.437 GHz")
    parser.add_argument("--compare-batch", action="append", help="the same scenes at further frequencies")
    parser.add_argument("--gateway", default="ap_", help="name prefix of the gateway (default ap_)")
    parser.add_argument("--sensors", default="plant_sensor_", help="name prefix of the sensor nodes")
    parser.add_argument("--group", action="append", help="wedge parameter to group by (repeatable; default all)")
    parser.add_argument("--harvester", action="append", help=f"harvester (repeatable; default {', '.join(HARVESTERS)})")
    args = parser.parse_args(argv)
    compare = args.compare_batch if args.compare_batch is not None else (
        DEFAULTS["compare_batch"] if args.batch == DEFAULTS["batch"] else [])
    names = args.harvester or list(HARVESTERS)
    config = load_config()
    ble = config["communication"]["ble_1m"]
    p_gw_dbm = float(config["wpt"]["total_power_dbm"])
    buffer_j = 0.5 * BUFFER_F * (V_TARGET ** 2 - V_START ** 2)
    harvesters = {name: load_config(harvester=name)["wpt"]["harvester"] for name in names}

    power = runs_of(args.batch, args.gateway, args.sensors)
    ble_runs = runs_of(args.ble_batch, args.gateway, args.sensors) if args.ble_batch else {}
    others = {batch: runs_of(batch, args.gateway, args.sensors) for batch in compare}
    rows, cdf, all_gain, all_p_rf, fading, gains_at = [], {}, [], [], [], {}
    for key, run in power.items():
        excluded = too_close(run.run_id, args.gateway, args.sensors)
        keep = [j for j, name in enumerate(run.rx_names) if name not in excluded]
        row = {"group": label(key, args.group), "parameters": dict(key), "sensor_nodes": len(keep),
               "excluded": {name: round(distance * 100, 2) for name, distance in excluded.items()}}
        if not keep:
            row["note"] = "every sensor node within 1 cm of a surface towards the gateway"
            rows.append(row)
            continue
        names_kept = [run.rx_names[j] for j in keep]
        gain = db(run.gain_incoherent[0][keep])
        p_rf_dbm = p_gw_dbm + db(np.abs(run.h[0][keep]) ** 2)
        p_rf_w = 10 ** ((p_rf_dbm - 30) / 10)
        all_gain += list(gain)
        all_p_rf += list(p_rf_dbm)
        fading += list(gain - db(np.abs(run.h[0][keep]) ** 2))
        cdf[row["group"]] = p_rf_dbm
        row.update(gain_median_db=float(np.median(gain)), gain_worst_db=float(gain.min()),
                   p_rf_median_dbm=float(np.median(p_rf_dbm)), p_rf_dbm=[float(v) for v in p_rf_dbm])
        charge_s = {name: reporting_interval_s(harvest_w(p_rf_w, h), buffer_j, 0.0) for name, h in harvesters.items()}
        row["within_hour"] = {name: int(np.sum(t <= HOUR_S)) for name, t in charge_s.items()}
        row["charge_time_median_s"] = {name: float(np.median(t)) for name, t in charge_s.items()}
        if key in ble_runs:
            other = ble_runs[key]
            index = [other.rx_names.index(name) for name in names_kept if name in other.rx_names]
            margin = ble["tx_power_dbm"] + db(other.gain_incoherent[0][index]) - ble["sensitivity_dbm"] - ble["reserve_db"]
            row["ble_worst_margin_db"] = float(margin.min())
        for batch, runs in [(args.batch, power), (args.ble_batch, ble_runs)] + list(others.items()):
            if key in runs:
                other = runs[key]
                index = [other.rx_names.index(name) for name in names_kept if name in other.rx_names]
                gains_at.setdefault((batch, other.frequency_hz), []).extend(db(other.gain_incoherent[0][index]))
        rows.append(row)

    medians = {f: float(np.median(values)) for (_, f), values in gains_at.items()}
    f0 = power[next(iter(power))].frequency_hz
    evaluated = [row for row in rows if row["sensor_nodes"]]
    summary = {
        "batch": args.batch, "ble_batch": args.ble_batch, "compare_batches": compare,
        "sensor_nodes": sum(row["sensor_nodes"] for row in evaluated),
        "excluded": sum(len(row["excluded"]) for row in rows),
        "within_hour_total": {name: sum(row["within_hour"][name] for row in evaluated) for name in names},
        "gain_median_db": {f"{f / 1e9:g} GHz": value for f, value in medians.items()},
        "gain_drop_db": {f"{f / 1e9:g} GHz": medians[f0] - value for f, value in medians.items()},
        "free_space_drop_db": {f"{f / 1e9:g} GHz": 20 * np.log10(f / f0) for f in medians},
        "p_rf_median_dbm": float(np.median(all_p_rf)),
        "ble_worst_margin_db": min((row["ble_worst_margin_db"] for row in evaluated if "ble_worst_margin_db" in row),
                                   default=None),
        "point_below_local_mean_db": {"median": float(np.median(fading)), "max": float(np.max(fading))},
        "sensor_nodes_at_threshold": {name: int(np.sum(np.array(all_p_rf) >= harvester_threshold_dbm(h)))
                                      for name, h in harvesters.items()},
        "buffer": {"capacitance_uf": BUFFER_F * 1e6, "v_start": V_START, "v_target": V_TARGET, "energy_mj": buffer_j * 1e3},
        "gateway_dbm": p_gw_dbm,
        "harvesters": {name: h["label"] for name, h in harvesters.items()}, "rows": rows,
    }
    out = ROOT / "outputs" / "casestudy" / args.batch
    out.mkdir(parents=True, exist_ok=True)
    (out / "usecase_numbers.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    tex = ["% python scripts/usecase_numbers.py: rows of the use-case table",
           "% group & n & gain median & worst & BLE worst & P_RF median & " + " & ".join(names)]
    for row in evaluated:
        cells = [row["group"].replace("_", "\\_"), str(row["sensor_nodes"]), f"${row['gain_median_db']:.1f}$",
                 f"${row['gain_worst_db']:.1f}$", f"{row.get('ble_worst_margin_db', float('nan')):.1f}",
                 f"${row['p_rf_median_dbm']:.1f}$"] + [str(row["within_hour"][name]) for name in names]
        tex.append(" & ".join(cells) + " \\\\")
    (out / "usecase_rows.tex").write_text("\n".join(tex) + "\n", encoding="utf-8")
    thresholds = {harvesters[name]["label"].split(" at ")[0].split(", ")[0]: harvester_threshold_dbm(harvesters[name])
                  for name in names}
    written = [out / "usecase_numbers.json", out / "usecase_rows.tex"] + cdf_figure(cdf, thresholds, out)

    for row in rows:
        if not row["sensor_nodes"]:
            print(f"{row['group']}: excluded ({row['note']})")
            continue
        counts = " / ".join(str(row["within_hour"][name]) for name in names)
        print(f"{row['group']}: n={row['sensor_nodes']} (excluded {len(row['excluded'])}), gain "
              f"{row['gain_median_db']:.1f} / {row['gain_worst_db']:.1f} dB, BLE {row.get('ble_worst_margin_db', float('nan')):.1f} dB, "
              f"P_RF {row['p_rf_median_dbm']:.1f} dBm, within 1 h {counts}")
    print(f"total: {summary['sensor_nodes']} sensor nodes, within 1 h "
          + ", ".join(f"{name} {value}" for name, value in summary["within_hour_total"].items()))
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

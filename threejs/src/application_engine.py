"""Application engine: communication and wireless-power metrics from imported HOUSIONNA runs.

    python run.py apps --batch 20261021_092146Z        # one batch
    python run.py apps --import <import id>             # one run
    python run.py apps                                  # every imported run

Implements the application metrics of the paper (Section "Application metrics and RF technologies"):

* received power and link margin per transmitter-receiver pair, the best-server margin per receiver, coverage, and
  the worst case over a set of scenarios (a batch);
* RF wireless power transfer with a total power budget shared by the transmitters of a run, for four strategies:
  all power on the best transmitter, equal split without phase alignment (incoherent), equal split in phase without
  channel knowledge, and coherent maximum-ratio transmission;
* harvested DC power from a rectifier efficiency curve, and the reporting interval a node can sustain for a given
  energy per measurement cycle.

The narrowband channel of a link is h = sum_k a_k exp(-j 2 pi f_c tau_k). The exported path coefficients are Sionna
RT's Paths.a, which do not contain the propagation phase (a line-of-sight path has phase 0); Paths.cir() would
return them with that phase applied. Checked against free space and against the exporter's coherent link gain.
Received power for communication uses the incoherent gain sum_k |a_k|^2, a local average that does not depend on
the exact receiver position at the scale of a wavelength.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
WPT_STRATEGIES = {
    "single_best": "All power on the best transmitter",
    "equal_incoherent": "Equal split, no phase alignment",
    "equal_in_phase": "Equal split, in phase, no channel knowledge",
    "coherent_mrt": "Coherent maximum-ratio transmission",
}


@dataclass
class RunChannels:
    """Channels of one imported run: n_tx transmitters by n_rx receivers."""
    import_id: str
    run_id: str
    frequency_hz: float
    tx_names: list[str]
    tx_power_dbm: np.ndarray
    rx_names: list[str]
    rx_positions_m: np.ndarray
    h: np.ndarray                      # narrowband channel sum_k a_k exp(-j2 pi f_c tau_k), shape (n_tx, n_rx)
    gain_incoherent: np.ndarray        # linear sum_k |a_k|^2, shape (n_tx, n_rx); 0 where no path
    path_counts: np.ndarray            # paths found per link
    parameters: dict[str, Any] = field(default_factory=dict)
    batch_id: str | None = None
    tx_positions_m: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))


def load_config(path: Path | None = None, harvester: str | None = None) -> dict[str, Any]:
    """Application profiles; wpt.harvester (or the harvester argument) names an entry of the harvesters section."""
    with Path(path or ROOT / "config" / "applications.yaml").open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    wpt = config.get("wpt")
    name = harvester or (wpt or {}).get("harvester")
    if wpt and isinstance(name, str):
        library = config.get("harvesters", {})
        if name not in library:
            raise ValueError(f"Unknown harvester {name!r}; choose from {', '.join(library)}")
        wpt["harvester"] = {"name": name, **library[name]}
    return config


def channels_from_payload(payload: dict[str, Any]) -> RunChannels:
    """Build the channel matrices from a viewer payload (all transmitters of one import)."""
    scenarios = [payload["scenarios"][name] for name in payload["scenario_order"]]
    if not scenarios:
        raise ValueError("The import has no scenarios")
    rx_rows: dict[str, list[float]] = {}
    for scenario in scenarios:
        for row in scenario.get("receivers") or []:
            rx_rows.setdefault(row["name"], row["position_m"])
    rx_names = sorted(rx_rows, key=lambda name: (len(name), name))
    rx_index = {name: j for j, name in enumerate(rx_names)}
    n_tx, n_rx = len(scenarios), len(rx_names)
    h = np.zeros((n_tx, n_rx), dtype=np.complex128)
    gain = np.zeros((n_tx, n_rx))
    counts = np.zeros((n_tx, n_rx), dtype=int)
    for i, scenario in enumerate(scenarios):
        carrier = float(scenario["frequency_hz"])
        for path in scenario.get("paths") or []:
            j = rx_index.get(path.get("receiver"))
            if j is None:
                continue
            a = complex(float(path["a_real"]), float(path["a_imag"]))
            h[i, j] += a * np.exp(-2j * np.pi * carrier * float(path["delay_s"]))
            gain[i, j] += abs(a) ** 2
            counts[i, j] += 1
    first = scenarios[0]
    meta = first.get("run_metadata") or {}
    return RunChannels(
        import_id=str(payload.get("import_id") or first.get("import_id")),
        run_id=str(meta.get("run_id") or first.get("import_id")),
        frequency_hz=float(first["frequency_hz"]),
        tx_names=[scenario["transmitter"]["name"] for scenario in scenarios],
        tx_power_dbm=np.array([float(scenario["transmitter"].get("power_dbm", 0.0)) for scenario in scenarios]),
        rx_names=rx_names,
        rx_positions_m=np.array([rx_rows[name] for name in rx_names], dtype=float),
        h=h, gain_incoherent=gain, path_counts=counts,
        parameters=dict(meta.get("parameters") or {}),
        batch_id=(meta.get("batch") or {}).get("id"),
        tx_positions_m=np.array([scenario["transmitter"]["position_m"] for scenario in scenarios], dtype=float),
    )


def load_channels(project_root: Path, import_id: str) -> RunChannels:
    from digital_twin_data import housionna_viewer_payload
    return channels_from_payload(housionna_viewer_payload(Path(project_root), import_id))


def db(value: np.ndarray | float) -> np.ndarray:
    with np.errstate(divide="ignore"):
        return 10.0 * np.log10(np.asarray(value, dtype=float))


# --- communication -------------------------------------------------------------------------------------------------

def link_margins_db(run: RunChannels, profile: dict[str, Any]) -> np.ndarray:
    """M_ij = P_t + G_ij - S - L_impl - M_reserve (dB), with G the incoherent gain; -inf where no path.

    P_t is the profile's tx_power_dbm when given (e.g. an uplink from a 0 dBm node; the channel is reciprocal),
    otherwise the transmit power of each transmitter in the run.
    """
    received = transmit_power_dbm(run.tx_power_dbm, profile)[:, None] + db(run.gain_incoherent)
    return received - float(profile["sensitivity_dbm"]) - float(profile.get("implementation_loss_db", 0.0)) \
        - float(profile.get("reserve_db", 0.0))


def transmit_power_dbm(run_power_dbm: np.ndarray, profile: dict[str, Any]) -> np.ndarray:
    if profile.get("tx_power_dbm") is None:
        return np.asarray(run_power_dbm, dtype=float)
    return np.full(len(run_power_dbm), float(profile["tx_power_dbm"]))


def communication_summary(run: RunChannels, profile: dict[str, Any]) -> dict[str, Any]:
    margins = link_margins_db(run, profile)
    best = margins.max(axis=0)                 # best server per receiver: max_i M_ij
    return {
        "best_margin_db": best,
        "best_server": [run.tx_names[i] for i in margins.argmax(axis=0)],
        "worst_margin_db": float(best.min()),   # min_j max_i M_ij
        "coverage": float(np.mean(best >= 0.0)),
    }


# --- wireless power transfer ----------------------------------------------------------------------------------------

def wpt_received_power_w(run: RunChannels, total_power_w: float, rx_gain_dbi: float = 0.0) -> dict[str, np.ndarray]:
    """Incident RF power per receiver for each strategy, with sum_i |w_i|^2 = total_power_w (paper eq. wpt).

    single_best      P max_i |h_ij|^2
    equal_incoherent (P/N) sum_i sum_k |a_k|^2        independent phases, averaged
    equal_in_phase   (P/N) |sum_i h_ij|^2              synchronised carriers, no channel knowledge
    coherent_mrt     P sum_i |h_ij|^2                  w_i = sqrt(P) h_ij* / ||h_j||, the optimum for receiver j
    """
    n_tx = run.h.shape[0]
    g_rx = 10 ** (rx_gain_dbi / 10)
    power = np.abs(run.h) ** 2
    return {
        "single_best": total_power_w * power.max(axis=0) * g_rx,
        "equal_incoherent": total_power_w / n_tx * run.gain_incoherent.sum(axis=0) * g_rx,
        "equal_in_phase": total_power_w / n_tx * np.abs(run.h.sum(axis=0)) ** 2 * g_rx,
        "coherent_mrt": total_power_w * power.sum(axis=0) * g_rx,
    }


def net_power_curve(harvester: dict[str, Any], project_root: Path = ROOT) -> list[tuple[float, float]]:
    """[(P_in dBm, net power W)] from measured buffer charge times (harvester.charge_time_csv).

    P_net = 1/2 C (V_on^2 - V_off^2) / t between successive measurements, 1/2 C V_on^2 / t from a cold start; the
    capacitors measured at each input power are averaged. The result includes conversion losses, leakage and the
    quiescent currents during charging.
    """
    buffer = harvester["buffer"]
    start = harvester.get("start", "successive")
    v_on, v_off = float(buffer["v_on_v"]), float(buffer["v_off_v"])
    rows: dict[float, list[float]] = {}
    with (Path(project_root) / harvester["charge_time_csv"]).open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row["start"] != start:
                continue
            capacitance = float(buffer["capacitors_f"][row["capacitor"]])
            energy = 0.5 * capacitance * (v_on ** 2 - (v_off ** 2 if start == "successive" else 0.0))
            rows.setdefault(float(row["input_power_dbm"]), []).append(energy / float(row["charge_time_s"]))
    if not rows:
        raise ValueError(f"No {start!r} rows in {harvester['charge_time_csv']}")
    return sorted((p_in, float(np.mean(values))) for p_in, values in rows.items())


def harvest_w(p_rf_w: np.ndarray, harvester: dict[str, Any], project_root: Path = ROOT) -> np.ndarray:
    """Usable DC power for an incident RF power, from measured charge times or from an efficiency curve.

    Measured points are interpolated in log power over dBm. Below the first point nothing is harvested (the device
    does not start); above the last point the last efficiency is kept.
    """
    if "charge_time_csv" not in harvester:
        return harvested_power_w(p_rf_w, efficiency_curve(harvester, project_root))
    points = np.array(net_power_curve(harvester, project_root))
    p_rf = np.asarray(p_rf_w, dtype=float)
    p_dbm = db(p_rf) + 30.0
    inside = np.exp(np.interp(p_dbm, points[:, 0], np.log(points[:, 1])))
    last_efficiency = points[-1, 1] / 10 ** ((points[-1, 0] - 30) / 10)
    out = np.where(p_dbm > points[-1, 0], p_rf * last_efficiency, inside)
    return np.where(p_dbm < points[0, 0], 0.0, out)


def harvester_threshold_dbm(harvester: dict[str, Any], project_root: Path = ROOT) -> float:
    if "charge_time_csv" in harvester:
        return float(net_power_curve(harvester, project_root)[0][0])
    return float(min(point[0] for point in efficiency_curve(harvester, project_root)))


def efficiency_curve(harvester: dict[str, Any], project_root: Path = ROOT) -> list[list[float]]:
    """[[P_in dBm, efficiency]] given inline (efficiency_curve) or from a rectifier envelope (efficiency_csv).

    From the envelope (scripts/import_ambient6g.py): the measured frequency closest to harvester.frequency_hz, for one
    rectifier or, with rectifier "best", the better of the rectifiers at each input power.
    """
    if "efficiency_csv" not in harvester:
        return harvester["efficiency_curve"]
    with (Path(project_root) / harvester["efficiency_csv"]).open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(line for line in handle if not line.startswith("#")))
    rectifier = harvester.get("rectifier", "best")
    if rectifier != "best":
        rows = [row for row in rows if row["rectifier"] == rectifier]
    if not rows:
        raise ValueError(f"No rows for rectifier {rectifier!r} in {harvester['efficiency_csv']}")
    target_mhz = float(harvester["frequency_hz"]) / 1e6
    nearest = min({float(row["frequency_mhz"]) for row in rows}, key=lambda f: abs(f - target_mhz))
    best: dict[float, float] = {}
    for row in rows:
        if float(row["frequency_mhz"]) == nearest:
            p_in = float(row["input_power_dbm"])
            best[p_in] = max(best.get(p_in, 0.0), float(row["efficiency"]))
    return [[p_in, best[p_in]] for p_in in sorted(best)]


def harvested_power_w(p_rf_w: np.ndarray, curve: list[list[float]]) -> np.ndarray:
    """DC power from a rectifier efficiency curve [[P_in dBm, efficiency], ...], interpolated in dBm.

    Nothing is harvested below the first point; above the last point the last efficiency is kept.
    """
    points = np.array(sorted(curve), dtype=float)
    p_dbm = db(np.asarray(p_rf_w, dtype=float)) + 30.0
    efficiency = np.interp(p_dbm, points[:, 0], points[:, 1], left=0.0, right=points[-1, 1])
    efficiency = np.where(p_dbm < points[0, 0], 0.0, efficiency)
    return efficiency * np.asarray(p_rf_w, dtype=float)


def reporting_interval_s(p_dc_w: np.ndarray, cycle_energy_j: float, quiescent_w: float) -> np.ndarray:
    """Shortest sustainable interval between cycles: E_cycle / (P_DC - P_quiescent); inf if the node cannot run."""
    net = np.asarray(p_dc_w, dtype=float) - quiescent_w
    with np.errstate(divide="ignore"):
        return np.where(net > 0, cycle_energy_j / np.where(net > 0, net, 1.0), np.inf)


def wpt_summary(run: RunChannels, cfg: dict[str, Any]) -> dict[str, Any]:
    total_w = 10 ** ((float(cfg["total_power_dbm"]) - 30) / 10)
    harvester = cfg["harvester"]
    p_rf = wpt_received_power_w(run, total_w, float(cfg.get("rx_antenna_gain_dbi", 0.0)))
    out: dict[str, Any] = {"strategies": {}}
    for strategy, values in p_rf.items():
        p_dc = harvest_w(values, harvester)
        out["strategies"][strategy] = {
            "p_rf_dbm": db(values) + 30.0,
            "p_dc_w": p_dc,
            "interval_s": {name: reporting_interval_s(p_dc, float(energy), float(cfg.get("quiescent_power_w", 0.0)))
                           for name, energy in cfg["cycles_j"].items()},
        }
    design = float(harvester.get("frequency_hz", run.frequency_hz))
    out["frequency_warning"] = (None if abs(run.frequency_hz - design) <= 0.1 * design else
                                f"Run at {run.frequency_hz/1e9:.3g} GHz, harvester curve for {design/1e9:.3g} GHz")
    return out


# --- runs, batches and output ---------------------------------------------------------------------------------------

def evaluate_run(run: RunChannels, config: dict[str, Any]) -> dict[str, Any]:
    return {"communication": {name: communication_summary(run, profile)
                              for name, profile in config.get("communication", {}).items()},
            "wpt": wpt_summary(run, config["wpt"]) if config.get("wpt") else None}


def _imports_in_scope(project_root: Path, batches: list[str] | None, imports: list[str] | None) -> list[str]:
    from integrations.housionna import list_imports
    rows = list_imports(project_root)
    newest: dict[str, dict[str, Any]] = {}
    for row in sorted(rows, key=lambda item: item.get("imported_at_utc") or ""):
        newest[row["run_id"]] = row          # one import per run: the most recent revision
    chosen = []
    for row in newest.values():
        batch = row["run_id"].split(".", 1)[0] if "." in row["run_id"] else None
        if imports and row["import_id"] not in imports:
            continue
        if batches and batch not in batches:
            continue
        chosen.append(row["import_id"])
    return sorted(chosen)


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def write_outputs(results: list[tuple[RunChannels, dict[str, Any]]], config: dict[str, Any], out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    rows = []
    for run, result in results:
        wpt = result["wpt"]
        for j, rx in enumerate(run.rx_names):
            row = {"run_id": run.run_id, "import_id": run.import_id, "frequency_hz": run.frequency_hz, "rx": rx,
                   **{f"param_{key}": value for key, value in run.parameters.items()}}
            for name, summary in result["communication"].items():
                row[f"{name}_best_margin_db"] = float(summary["best_margin_db"][j])
                row[f"{name}_best_server"] = summary["best_server"][j]
            if wpt:
                for strategy, values in wpt["strategies"].items():
                    row[f"wpt_{strategy}_p_rf_dbm"] = float(values["p_rf_dbm"][j])
                    row[f"wpt_{strategy}_p_dc_uw"] = float(values["p_dc_w"][j] * 1e6)
                    for cycle, interval in values["interval_s"].items():
                        row[f"wpt_{strategy}_{cycle}_interval_s"] = float(interval[j])
            rows.append(row)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (out / "per_receiver.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    written.append(out / "per_receiver.csv")

    summary = {
        "config": config,
        "runs": [{"run_id": run.run_id, "import_id": run.import_id, "frequency_hz": run.frequency_hz,
                  "parameters": run.parameters, "transmitters": run.tx_names, "receivers": run.rx_names,
                  "communication": {name: {"worst_margin_db": item["worst_margin_db"], "coverage": item["coverage"]}
                                    for name, item in result["communication"].items()},
                  "wpt_frequency_warning": (result["wpt"] or {}).get("frequency_warning")}
                 for run, result in results],
        "worst_case_over_runs": {name: min(result["communication"][name]["worst_margin_db"] for _, result in results)
                                 for name in config.get("communication", {})},
    }
    (out / "summary.json").write_text(json.dumps(_jsonable(summary), indent=2), encoding="utf-8")
    written.append(out / "summary.json")
    written += _figures(results, config, out)
    return written


def _figures(results: list[tuple[RunChannels, dict[str, Any]]], config: dict[str, Any], out: Path) -> list[Path]:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    written = []
    if config.get("wpt") and results:
        # Harvested power per receiver over all runs in scope, one curve per strategy (empirical CDF).
        fig, ax = plt.subplots(figsize=(3.5, 2.6))
        short = {"single_best": "Best single TX", "equal_incoherent": "Equal split, incoherent",
                 "equal_in_phase": "Equal split, in phase", "coherent_mrt": "Coherent MRT"}
        for strategy, label in short.items():
            values = np.concatenate([result["wpt"]["strategies"][strategy]["p_rf_dbm"] for _, result in results])
            values = np.sort(values[np.isfinite(values)])
            if values.size:
                ax.step(values, np.arange(1, values.size + 1) / values.size, where="post", label=label, linewidth=1.4)
        threshold = harvester_threshold_dbm(config["wpt"]["harvester"])
        ax.axvline(threshold, color="0.5", linewidth=0.8, linestyle="--")
        ax.set_xlabel("Incident RF power (dBm)")
        ax.set_ylabel("Fraction of receivers")
        ax.grid(alpha=0.3, linewidth=0.5)
        ax.legend(fontsize=6.5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
        fig.tight_layout()
        for suffix in ("pdf", "png"):
            fig.savefig(out / f"wpt_rf_power_cdf.{suffix}", dpi=200)
            written.append(out / f"wpt_rf_power_cdf.{suffix}")
        plt.close(fig)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run.py apps", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--batch", action="append", help="evaluate the imported runs of this batch (repeatable)")
    parser.add_argument("--import", dest="imports", action="append", help="evaluate this import id (repeatable)")
    parser.add_argument("--config", type=Path, help="application profiles (default config/applications.yaml)")
    parser.add_argument("--harvester", help="harvester from the config's harvesters section (default wpt.harvester)")
    parser.add_argument("--out", type=Path, help="output folder (default outputs/applications/<scope>)")
    args = parser.parse_args(argv)
    config = load_config(args.config, args.harvester)
    ids = _imports_in_scope(ROOT, args.batch, args.imports)
    if not ids:
        print("No imported runs in scope; import them in the viewer first (Import all).")
        return 2
    results = []
    for import_id in ids:
        run = load_channels(ROOT, import_id)
        results.append((run, evaluate_run(run, config)))
    scope = "_".join(args.batch) if args.batch else ("selected" if args.imports else "all")
    if args.harvester:
        scope += f"_{args.harvester}"
    out = args.out or ROOT / "outputs" / "applications" / scope
    written = write_outputs(results, config, out)
    for name in config.get("communication", {}):
        worst = min(result["communication"][name]["worst_margin_db"] for _, result in results)
        coverage = np.mean([result["communication"][name]["coverage"] for _, result in results])
        print(f"{config['communication'][name].get('label', name)}: worst-case margin {worst:.1f} dB, "
              f"mean coverage {coverage*100:.0f}% over {len(results)} run(s)")
    if config.get("wpt"):
        print(f"WPT harvester: {config['wpt']['harvester'].get('label', config['wpt']['harvester'].get('name'))}")
        for strategy, label in WPT_STRATEGIES.items():
            p = np.concatenate([result["wpt"]["strategies"][strategy]["p_rf_dbm"] for _, result in results])
            print(f"WPT {label}: median incident power {np.median(p[np.isfinite(p)]):.1f} dBm")
        warnings = {result["wpt"]["frequency_warning"] for _, result in results if result["wpt"]["frequency_warning"]}
        for warning in sorted(warnings):
            print(f"note: {warning}; the energy figures are illustrative")
    print("written:", ", ".join(str(path.relative_to(ROOT)) for path in written))
    return 0

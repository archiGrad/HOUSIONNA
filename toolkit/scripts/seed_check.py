"""How much the use case moves with the ray-tracing seed: a batch solved again with other seeds, point links only.

    python scripts/seed_check.py <batch>                              # seeds 42 43 44 at 915 MHz
    python scripts/seed_check.py <batch> --seeds 42 43 44 45 --frequency 2.437e9 --device cpu

The seed in a work item's settings (42 in the Houdini batches) is Sionna's: it picks the rays that are traced, so a
path through a gap in the canopy can be found with one seed and missed with another. It has nothing to do with the
plant placement in Houdini. This copies the work items at --frequency from houdini_files/sionna/batches/<batch>/
(read only) to outputs/reruns/<batch>_seeds/seed<N>/, without their results and without the measurement surface (the
use case needs the point links, not the radio map), sets the seed and solves every item with the batch's own
sionna_run.py. Solved items are kept, so a second call only solves what is missing. Seed 42 is solved again too:
against the original it shows whether this machine reproduces the batch at all, before the seeds are compared.

Per work item and seed it reports, against the original batch: the change of the gain per sensor node (best gateway,
incoherent, dB), the number of sensor nodes that gain or lose every path, and the number powered within an hour per
harvester (coherent RF power with the gateways sharing wpt.total_power_dbm, as in scripts/usecase_numbers.py).
Writes outputs/reruns/<batch>_seeds/seed_check.json.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT.parent / "houdini_files" / "sionna" / "batches"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from engine.application_engine import harvest_w, load_config, reporting_interval_s  # noqa: E402
from engine.screening import too_close  # noqa: E402
from usecase_numbers import BUFFER_F, HARVESTERS, HOUR_S, SAME_CARRIER, V_START, V_TARGET  # noqa: E402

RESULTS = ("_result.npz", "_radiomap.npz", "done.json", "failed.json", "links.bgeo.sc", "paths.bgeo.sc",
           "radiomap.bgeo.sc", "progress.json", "solver.log")
NO_PATH_DB = -900.0  # sionna_run.py writes -999 dB for a link without paths


def items_at(batch: Path, frequency_hz: float) -> list[Path]:
    out = []
    for item in sorted(p for p in batch.iterdir() if p.is_dir() and p.name.startswith("wi")):
        settings = json.loads(next(item.glob("*_settings.json")).read_text(encoding="utf-8"))
        if abs(settings["frequency"] - frequency_hz) <= SAME_CARRIER * frequency_hz and any(item.glob("*_result.npz")):
            out.append(item)
    return out


def prepare(item: Path, target: Path, seed: int) -> Path:
    """A copy of the work item without results and radio map, with the seed set."""
    out = target / item.name
    if not out.is_dir():
        shutil.copytree(item, out, ignore=lambda folder, names: [
            name for name in names if name.endswith(RESULTS) or name.endswith("_measure.json")])
    settings_file = next(out.glob("*_settings.json"))
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    settings["seed"] = seed
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return out


def links(item: Path) -> dict[str, object]:
    """Gateway x sensor coherent and incoherent gains (linear power, 0 without paths) and the device names."""
    data = np.load(next(item.glob("*_result.npz")))
    tx, rx = [str(n) for n in data["tx"]], [str(n) for n in data["rx"]]
    coherent, incoherent = data["link_gain_db_coherent"], data["link_gain_db_incoherent"]  # [rx, tx]
    to_linear = lambda g: np.where(g > NO_PATH_DB, 10 ** (np.asarray(g, dtype=float) / 10), 0.0)  # noqa: E731
    return {"tx": tx, "rx": rx, "coherent": to_linear(coherent), "incoherent": to_linear(incoherent)}


def oriented(result: dict, gateway: str, sensors: str) -> tuple[list[str], np.ndarray, np.ndarray]:
    """Sensor names and gateway x sensor (coherent, incoherent) power gains, whichever side transmitted."""
    tx, rx = result["tx"], result["rx"]
    if any(n.startswith(gateway) for n in rx):
        g = [i for i, n in enumerate(rx) if n.startswith(gateway)]
        s = [j for j, n in enumerate(tx) if n.startswith(sensors)]
        return [tx[j] for j in s], result["coherent"][np.ix_(g, s)], result["incoherent"][np.ix_(g, s)]
    g = [j for j, n in enumerate(tx) if n.startswith(gateway)]
    s = [i for i, n in enumerate(rx) if n.startswith(sensors)]
    return [rx[i] for i in s], result["coherent"][np.ix_(s, g)].T, result["incoherent"][np.ix_(s, g)].T


def metrics(names: list[str], coherent: np.ndarray, incoherent: np.ndarray, keep: list[str], p_gw_w: float,
            harvesters: dict[str, dict], buffer_j: float) -> dict[str, object]:
    index = [names.index(n) for n in keep]
    best = incoherent[:, index].max(axis=0)
    # Coherent MRT over the gateways: P sum_i |h_i|^2 at the node (single gateway: P |h|^2).
    p_rf_w = p_gw_w * coherent[:, index].sum(axis=0)
    with np.errstate(divide="ignore"):
        gain_db = 10 * np.log10(best)
    return {"gain_db": gain_db, "has_path": best > 0,
            "within_hour": {name: int(np.sum(reporting_interval_s(harvest_w(p_rf_w, h), buffer_j, 0.0) <= HOUR_S))
                            for name, h in harvesters.items()}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="batch folder name under houdini_files/sionna/batches/")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 43, 44])
    parser.add_argument("--frequency", type=float, default=915e6, help="carrier of the work items to solve (Hz)")
    parser.add_argument("--gateway", default="ap_")
    parser.add_argument("--sensors", default="plant_sensor_")
    parser.add_argument("--device", choices=("gpu", "cpu"), default="gpu")
    args = parser.parse_args(argv)
    source = BATCHES / args.batch
    if not (source / "sionna_run.py").is_file():
        print(f"No batch with sionna_run.py at {source}")
        return 2
    items = items_at(source, args.frequency)
    if not items:
        print(f"No solved work item at {args.frequency / 1e9:g} GHz in {source}")
        return 2
    root = ROOT / "outputs" / "reruns" / f"{args.batch}_seeds"

    for seed in args.seeds:
        target = root / f"seed{seed}"
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "sionna_run.py", target / "sionna_run.py")
        for item in items:
            out = prepare(item, target, seed)
            if any(out.glob("*_result.npz")):
                continue
            print(f"== seed {seed}, {item.name}", flush=True)
            with open(out / "solver.log", "w", encoding="utf-8") as log:
                solved = subprocess.run([sys.executable, "sionna_run.py", "solve", item.name, args.device],
                                        cwd=target, stdout=log, stderr=subprocess.STDOUT)
            if solved.returncode or not any(out.glob("*_result.npz")):
                print(f"solving {item.name} with seed {seed} failed (exit {solved.returncode}), see {out / 'solver.log'}")
                return 2

    config = load_config()
    p_gw_w = 10 ** ((float(config["wpt"]["total_power_dbm"]) - 30) / 10)
    buffer_j = 0.5 * BUFFER_F * (V_TARGET ** 2 - V_START ** 2)
    harvesters = {name: load_config(harvester=name)["wpt"]["harvester"] for name in HARVESTERS}
    report = {"batch": args.batch, "frequency_hz": args.frequency, "seeds": args.seeds, "items": []}
    for item in items:
        meta = json.loads(next(item.glob("*_meta.json")).read_text(encoding="utf-8"))
        wedge = {k: v for k, v in meta.get("wedge", {}).items()
                 if k not in ("runs", "wedgeindex", "wedgetotal", "wedgecount", "wedgenum", "wedgeattribs")}
        names, coherent, incoherent = oriented(links(item), args.gateway, args.sensors)
        excluded = too_close(f"{args.batch}.{item.name}", args.gateway, args.sensors)
        keep = [n for n in names if n not in excluded]
        original = metrics(names, coherent, incoherent, keep, p_gw_w, harvesters, buffer_j)
        row = {"item": item.name, "parameters": wedge, "sensor_nodes": len(keep),
               "original": {"within_hour": original["within_hour"], "no_path": int(np.sum(~original["has_path"]))},
               "seeds": {}}
        for seed in args.seeds:
            names_s, coherent_s, incoherent_s = oriented(links(root / f"seed{seed}" / item.name), args.gateway,
                                                         args.sensors)
            again = metrics(names_s, coherent_s, incoherent_s, keep, p_gw_w, harvesters, buffer_j)
            both = original["has_path"] & again["has_path"]
            delta = again["gain_db"][both] - original["gain_db"][both]
            row["seeds"][seed] = {
                "gain_change_db": {"median_abs": float(np.median(np.abs(delta))) if delta.size else None,
                                   "max_abs": float(np.max(np.abs(delta))) if delta.size else None,
                                   "worst_node": keep[int(np.flatnonzero(both)[np.argmax(np.abs(delta))])]
                                   if delta.size else None},
                "paths_lost": int(np.sum(original["has_path"] & ~again["has_path"])),
                "paths_gained": int(np.sum(~original["has_path"] & again["has_path"])),
                "within_hour": again["within_hour"]}
        report["items"].append(row)

    root.mkdir(parents=True, exist_ok=True)
    (root / "seed_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"{args.batch} at {args.frequency / 1e9:g} GHz, gain change against the original (seed 42) per sensor node, "
          f"and powered within 1 h ({' / '.join(HARVESTERS)})")
    for row in report["items"]:
        label = ", ".join(f"{k}={v}" for k, v in row["parameters"].items()) or row["item"]
        counts = " / ".join(str(v) for v in row["original"]["within_hour"].values())
        print(f"{row['item']} {label}: n={row['sensor_nodes']}, original within 1 h {counts}, "
              f"no path {row['original']['no_path']}")
        for seed, s in row["seeds"].items():
            change = s["gain_change_db"]
            text = "--" if change["median_abs"] is None else \
                f"median |dG| {change['median_abs']:.2f} dB, max {change['max_abs']:.1f} dB ({change['worst_node']})"
            print(f"   seed {seed}: {text}, paths lost {s['paths_lost']} gained {s['paths_gained']}, within 1 h "
                  + " / ".join(str(v) for v in s["within_hour"].values()))
    print(f"written: {(root / 'seed_check.json').relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

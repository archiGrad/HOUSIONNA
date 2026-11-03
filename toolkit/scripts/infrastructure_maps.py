"""Solve a HOUSIONNA batch again with the access points as transmitters, for their radio maps.

    python scripts/infrastructure_maps.py <batch>                 # results in outputs/reruns/<batch>_aptx/
    python scripts/infrastructure_maps.py <batch> --prefix ap_ --sensors plant_sensor_ --device cpu

Sionna computes a radio map per transmitter: the gain from it to every cell of the measurement surface. When the
infrastructure was exported as a receiver (the sensors transmit to the access point), the batch has maps from the
sensors, not the coverage of the access points, and a map cannot be turned around by reciprocity like a point link.
This copies the batch from houdini_files/sionna/batches/ without its results, makes the devices named --prefix the
transmitters and those named --sensors the receivers, and solves every work item with the batch's own sionna_run.py
(the exported scene, materials and settings are unchanged). It then imports the runs, so that

    python run.py maps --batch <batch>_aptx --infrastructure ap_

gives the coverage per crop configuration and the worst case per cell. The access points transmit --power-dbm;
the path gains and maps do not depend on it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BATCHES = ROOT.parent / "houdini_files" / "sionna" / "batches"
RESULTS = ("_result.npz", "_radiomap.npz", "done.json", "links.bgeo.sc", "paths.bgeo.sc", "radiomap.bgeo.sc", "_log.txt")


def swap_roles(source: Path, target: Path, prefix: str, sensors: str, power_dbm: float) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    for path in source.iterdir():
        if path.is_file() and path.name not in ("status.json", "batch.log"):
            shutil.copy2(path, target / path.name)
    items = []
    for item in sorted(p for p in source.iterdir() if p.is_dir()):
        out = target / item.name
        shutil.copytree(item, out, dirs_exist_ok=True,
                        ignore=lambda folder, names: [name for name in names if name.endswith(RESULTS)])
        txrx = next(out.glob("*_txrx.json"))
        devices = json.loads(txrx.read_text(encoding="utf-8"))
        everyone = devices["tx"] + devices["rx"]
        tx = [dict(d, power_dbm=power_dbm) for d in everyone if d["name"].startswith(prefix)]
        # Without sensors (e.g. the scene without plants) the other devices receive: the importer needs paths, and
        # the maps do not depend on the receivers.
        receivers = [d for d in everyone if d["name"].startswith(sensors)] or \
            [d for d in everyone if not d["name"].startswith(prefix)]
        rx = [{k: v for k, v in d.items() if k != "power_dbm"} for d in receivers]
        txrx.write_text(json.dumps({"tx": tx, "rx": rx}, indent=2), encoding="utf-8")
        print(f"{item.name}: {len(tx)} transmitters, {len(rx)} receivers")
        if tx:
            items.append(out)
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batch", help="batch folder name under houdini_files/sionna/batches/")
    parser.add_argument("--prefix", default="ap_", help="name prefix of the access points (default ap_)")
    parser.add_argument("--sensors", default="plant_sensor_", help="name prefix of the sensors (default plant_sensor_)")
    parser.add_argument("--power-dbm", type=float, default=30.0)
    parser.add_argument("--device", choices=("gpu", "cpu"), default="gpu")
    args = parser.parse_args(argv)
    source = BATCHES / args.batch
    if not (source / "sionna_run.py").is_file():
        print(f"No batch with sionna_run.py at {source}")
        return 2
    target = ROOT / "outputs" / "reruns" / f"{args.batch}_aptx"
    items = swap_roles(source, target, args.prefix, args.sensors, args.power_dbm)
    if not items:
        print(f"No device named {args.prefix}* in the batch")
        return 2
    for item in items:
        print(f"== solve {item.name}")
        solved = subprocess.run([sys.executable, "sionna_run.py", "solve", item.name, args.device], cwd=target)
        if solved.returncode:
            print(f"solving {item.name} failed (exit {solved.returncode})")
            return 2
        imported = subprocess.run([sys.executable, str(ROOT / "run.py"), "import-housionna", str(item)], cwd=ROOT)
        if imported.returncode:
            return 2
    print(f"done: python run.py maps --batch {target.name} --infrastructure {args.prefix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

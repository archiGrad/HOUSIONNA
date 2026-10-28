"""Rectifier efficiency envelopes from the AMBIENT-6G harvester dataset.

    python scripts/import_ambient6g.py                    # download from GitHub
    python scripts/import_ambient6g.py --source <dir>     # or read a local copy (<dir>/<rectifier>_<band>/...)

Dataset: https://github.com/AMBIENT-6G/dataset-harvesters (webtool https://ambient-6g.github.io/dataset-harvesters/).
It measures the rectifiers of the e-peas AEM30940 evaluation kits (C031 at 915 MHz, C041 at 2450 MHz) without the
charger: DC power into a load held at a target voltage of 0.25 to 2 V, for 850-950 and 2450-2550 MHz and -25 to
+10 dBm. The envelope keeps, per rectifier, frequency and input power, the best efficiency over the target
voltages (rows with a saturated power reading are dropped): what an ideal maximum-power-point charger could take from
the rectifier. It is an upper bound for a
complete harvester such as data/devices/cappelle2025 (charger losses, leakage and quiescent currents excluded).

Writes data/devices/ambient6g/rectifier_envelope.csv (efficiency as a fraction).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "AMBIENT-6G/dataset-harvesters"
RECTIFIERS = ("SMS7630005LF", "SMS7621005LF")       # "low" and "high" input power variants
BANDS = (915, 2450)
TARGETS_MV = (250, 500, 750, 1000, 1250, 1500, 1750, 2000)
# The DC power is stored as an unsigned 32-bit count of pW: rows at 2^32 - 1 (4.29 mW, above about +6 dBm in) are
# clipped, and their efficiency is computed from the clipped power. They are left out.
SATURATED_PW = 2 ** 32 - 1
OUT = ROOT /"data" / "devices" / "ambient6g" / "rectifier_envelope.csv"


def _read(source: Path | None, ref: str, folder: str, name: str) -> str:
    if source:
        return (source / folder / name).read_text(encoding="utf-8")
    url = f"https://raw.githubusercontent.com/{REPO}/{ref}/{folder}/{name}"
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def envelope(measurements: dict[int, str]) -> list[dict[str, float]]:
    """Best efficiency over target voltages per (frequency, input power); measurements maps target mV to CSV text."""
    best: dict[tuple[float, float], dict[str, float]] = {}
    for target_mv, text in measurements.items():
        for row in csv.DictReader(io.StringIO(text)):
            if float(row["pwr_pw"]) >= SATURATED_PW:
                continue
            key =(float(row["frequency_mhz"]), float(row["level_dbm"]))
            efficiency = float(row["efficiency"]) / 100.0        # the dataset gives percent
            if key not in best or efficiency > best[key]["efficiency"]:
                best[key] = {"frequency_mhz": key[0], "input_power_dbm": key[1], "efficiency": efficiency,
                             "target_mv": float(target_mv)}
    return [best[key] for key in sorted(best)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, help="local copy of the dataset instead of downloading")
    parser.add_argument("--ref", default="main", help="git ref to download (default main)")
    args = parser.parse_args(argv)
    ref = args.ref
    if not args.source and ref == "main":
        with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/commits/main", timeout=60) as response:
            ref = json.load(response)["sha"]
    rows = []
    for band in BANDS:
        for rectifier in RECTIFIERS:
            folder = f"{rectifier}_{band}"
            measured = {t: _read(args.source, ref, folder, f"{folder}_measured_t{t}.csv") for t in TARGETS_MV}
            rows += [{"rectifier": rectifier, "band_mhz": band, **row} for row in envelope(measured)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        handle.write(f"# {REPO} @ {ref if not args.source else 'local copy'}; best efficiency over target voltages\n")
        writer = csv.DictWriter(handle, fieldnames=["rectifier", "band_mhz", "frequency_mhz", "input_power_dbm",
                                                    "efficiency", "target_mv"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} rows -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

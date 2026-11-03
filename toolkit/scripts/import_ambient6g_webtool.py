"""Harvester curves from the AMBIENT-6G dataset, as selected in its webtool, for the application engine.

    python scripts/import_ambient6g_webtool.py                  # downloads the pinned commit
    python scripts/import_ambient6g_webtool.py --source <clone> # from a local clone

Dataset: https://github.com/AMBIENT-6G/dataset-harvesters (webtool https://ambient-6g.github.io/dataset-harvesters/).
Takes three series at 915 MHz: the e-peas AEM40940 at 921 MHz (datasheet, target voltage 0) and the SMS7621005LF
and SMS7630005LF rectifiers measured at 912.5 MHz with a 2000 mV target voltage. The engine uses the data points
themselves, interpolated in dB and zero below the lowest point: the webtool's quadratic fits are made in linear
units, are dominated by the milliwatt points, and are wrong by up to two orders of magnitude, or negative, below
-10 dBm. Rows whose DC power is clipped at 2^32 - 1 pW are left out.

Writes data/devices/ambient6g/webtool_harvesters.csv (efficiency as a fraction).
"""
from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
REPO = "AMBIENT-6G/dataset-harvesters"
REF = "18f01bf190f51175dc058387937e3301f42d5af0"
SATURATED_PW = 2 ** 32 - 1
# (name in the output, file in the dataset, measured frequency in MHz, source)
SERIES = (
    ("AEM40940", "AEM40940_921/AEM40940_921_datasheet_t0.csv", 921.0, "datasheet"),
    ("SMS7621005LF", "SMS7621005LF_915/SMS7621005LF_915_measured_t2000.csv", 912.5, "measured"),
    ("SMS7630005LF", "SMS7630005LF_915/SMS7630005LF_915_measured_t2000.csv", 912.5, "measured"),
)
OUT = ROOT / "data" / "devices" / "ambient6g" / "webtool_harvesters.csv"


def _read(source: Path | None, ref: str, name: str) -> str:
    if source:
        return (source / name).read_text(encoding="utf-8")
    with urllib.request.urlopen(f"https://raw.githubusercontent.com/{REPO}/{ref}/{name}", timeout=60) as response:
        return response.read().decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, help="local clone of the dataset instead of downloading")
    parser.add_argument("--ref", default=REF, help=f"dataset commit (default {REF[:7]})")
    args = parser.parse_args(argv)
    rows = []
    for name, path, frequency_mhz, kind in SERIES:
        target_mv = path.rsplit("_t", 1)[1].removesuffix(".csv")
        for row in csv.DictReader(io.StringIO(_read(args.source, args.ref, path))):
            if float(row["frequency_mhz"]) != frequency_mhz or float(row["pwr_pw"]) >= SATURATED_PW:
                continue
            rows.append({"rectifier": name, "source": kind, "frequency_mhz": frequency_mhz,
                         "input_power_dbm": float(row["level_dbm"]),
                         "efficiency": float(row["efficiency"]) / 100.0,        # the dataset gives percent
                         "target_mv": float(target_mv)})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as handle:
        handle.write(f"# {REPO} @ {args.ref}; webtool series, data points (not the quadratic fits)\n")
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    for name, *_ in SERIES:
        points = [row for row in rows if row["rectifier"] == name]
        print(f"{name}: {len(points)} points, {min(p['input_power_dbm'] for p in points):g} to "
              f"{max(p['input_power_dbm'] for p in points):g} dBm")
    print(f"written: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

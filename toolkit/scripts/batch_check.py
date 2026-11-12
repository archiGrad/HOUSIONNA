"""Check exported HOUSIONNA batches before they go into the use case.

    python scripts/batch_check.py <batch folder> [<batch folder> ...]

Reports, per batch:
  - JSON files that do not parse, and files with git conflict markers (a broken batch.json stops import-housionna);
  - sensor nodes exported with orientation (0, 0, 0), i.e. upright;
  - work items without a result;
  - as a note only: orientations that stay identical between plant stages while the sensor nodes move.
Exit code 1 when any problem (not a note) is found. The --sensors prefix (default plant_sensor_) picks the sensor nodes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

MARKERS = ("<<<<<<< ", "<<<<<<<<", ">>>>>>> ", ">>>>>>>>")
MOVED_M = 0.01      # a sensor node that moves more than this between stages has grown with its plant
SAME_RAD = 1e-3     # orientations closer than this are the same (exports differ in float noise)


def broken_files(batch: Path) -> list[str]:
    out = []
    for path in sorted(batch.rglob("*.json")):
        text = path.read_text(encoding="utf-8", errors="replace")
        if any(line.startswith(MARKERS) for line in text.splitlines()):
            out.append(f"{path.relative_to(batch)}: git conflict markers")
            continue
        try:
            json.loads(text)
        except ValueError as error:
            out.append(f"{path.relative_to(batch)}: not valid JSON ({error})")
    return out


def one(folder: Path, suffix: str) -> Path | None:
    found = sorted(folder.glob(f"*{suffix}"))
    return found[0] if found else None


def items(batch: Path, sensors: str) -> list[dict]:
    """Per work item: wedge parameters and {sensor name: (position, orientation)}."""
    out = []
    for folder in sorted(p for p in batch.glob("wi*") if p.is_dir()):
        meta, txrx = one(folder, "_meta.json"), one(folder, "_txrx.json")
        try:
            wedge = json.loads(meta.read_text(encoding="utf-8")).get("wedge", {}) if meta else {}
            devices = json.loads(txrx.read_text(encoding="utf-8")) if txrx else {}
        except ValueError:
            continue    # reported by broken_files
        nodes = {d["name"]: (tuple(d["position"]), tuple(d.get("orientation", (0, 0, 0))))
                 for d in devices.get("tx", []) + devices.get("rx", []) if d["name"].startswith(sensors)}
        out.append({"item": folder.name, "wedge": wedge, "nodes": nodes, "result": one(folder, "_result.npz") is not None})
    return out


def stale_orientations(found: list[dict]) -> list[str]:
    """Pairs of work items of different plant stages whose sensor nodes moved but kept every orientation."""
    out = []
    for i, a in enumerate(found):
        for b in found[i + 1:]:
            sa, sb = a["wedge"].get("plant_stage"), b["wedge"].get("plant_stage")
            if sa is None or sb is None or sa == sb or a["nodes"].keys() != b["nodes"].keys() or not a["nodes"]:
                continue
            if all(max(abs(p - q) for p, q in zip(a["nodes"][n][1], b["nodes"][n][1])) <= SAME_RAD for n in a["nodes"]):
                moved = max(sum((p - q) ** 2 for p, q in zip(a["nodes"][n][0], b["nodes"][n][0])) ** 0.5 for n in a["nodes"])
                if moved > MOVED_M:
                    other = {k: v for k, v in a["wedge"].items() if k in b["wedge"] and k != "plant_stage"
                             and a["wedge"][k] == b["wedge"][k] and k.startswith(("plant_", "moisture", "ap_", "frequency"))}
                    out.append(f"{a['item']} (stage {sa}) and {b['item']} (stage {sb}){' ' + str(other) if other else ''}: "
                               f"same orientations, sensor nodes moved up to {moved * 100:.0f} cm")
    return out


def check(batch: Path, sensors: str) -> int:
    problems = broken_files(batch)
    found = items(batch, sensors)
    problems += [f"{x['item']}: no result" for x in found if not x["result"]]
    upright = sum(1 for x in found for _, o in x["nodes"].values() if all(c == 0 for c in o))
    total = sum(len(x["nodes"]) for x in found)
    if upright:
        problems.append(f"{upright} of {total} sensor nodes have orientation (0, 0, 0) (upright)")
    # Orientations that repeat between stages can be correct (confirmed for the 10 Nov 2026 batches), so they are
    # reported as a note to look at, not a problem.
    stale = stale_orientations(found)
    notes = [f"{len(stale)} pairs of stages with unchanged orientations, e.g. " + "; ".join(stale[:3])] if stale else []
    print(f"== {batch.name}: {len(found)} work items, {total} sensor nodes, "
          + (f"{len(problems)} problem(s)" if problems else "ok") + (f", {len(notes)} note(s)" if notes else ""))
    for line in problems:
        print("  -", line)
    for line in notes:
        print("  note:", line)
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("batches", nargs="+", type=Path, help="batch folders (with wi000, wi001, ...)")
    parser.add_argument("--sensors", default="plant_sensor_", help="name prefix of the sensor nodes")
    args = parser.parse_args(argv)
    return max(check(batch, args.sensors) for batch in args.batches)


if __name__ == "__main__":
    sys.exit(main())

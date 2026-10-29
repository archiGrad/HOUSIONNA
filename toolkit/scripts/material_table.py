"""Radio materials of the Houdini exporter evaluated per frequency, with the loss of one crossing.

    python scripts/material_table.py                     # results in outputs/validation/

Reads houdini_files/sionna/materials.json and evaluates every material with the exporter's own model functions
(resolve() and its helpers in houdini_files/sionna/sionna_sop.py, taken from the source without importing Houdini).
For each material and frequency it reports the relative permittivity, the conductivity, whether the frequency lies
inside the material's stated range, and the transmission loss of one surface crossing: Sionna treats each crossed
surface as a slab of the material's thickness (ITU-R P.2040, normal incidence, scripts/reference_cases.py). A closed
object is crossed twice, and a closed object thinner than 1 cm blocks every path (reference case D).
"""
from __future__ import annotations

import ast
import csv
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
HOUDINI = ROOT.parent / "houdini_files" / "sionna"
sys.path.insert(0, str(ROOT / "scripts"))

from reference_cases import slab_transmission  # noqa: E402

FREQUENCIES = {"868 MHz": 868e6, "915 MHz": 915e6, "2.437 GHz": 2.437e9, "3.5 GHz": 3.5e9, "5.18 GHz": 5.18e9}
MODEL_FUNCTIONS = ("water_eps", "vegetation_eps", "pure_water", "soil_eps", "itu_row", "measured_ranges",
                   "outside_range", "resolve")
DEFAULT_THICKNESS_M = 0.1                       # Sionna's default for a radio material without thickness
OUT = ROOT / "outputs" / "validation"


def exporter_models(source: Path = HOUDINI / "sionna_sop.py") -> dict:
    """The material functions of the exporter, compiled from its source; it imports hou, so it is not imported."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in MODEL_FUNCTIONS]
    missing = set(MODEL_FUNCTIONS) - {node.name for node in nodes}
    if missing:
        raise RuntimeError(f"{source} no longer defines {', '.join(sorted(missing))}")
    namespace = {"math": math, "EPS0": 8.8541878128e-12, "MOISTURE_KINDS": ("vegetation", "soil")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(source), "exec"), namespace)
    return namespace


def table(library: dict, models: dict) -> list[dict]:
    rows = []
    for name, entry in library.items():
        thickness = float(entry.get("thickness", DEFAULT_THICKNESS_M))
        for label, f in FREQUENCIES.items():
            eps_r, sigma = models["resolve"](entry, f)
            loss = -10 * math.log10(max(slab_transmission(eps_r, sigma, thickness, f), 1e-30))
            rows.append({"material": name, "kind": entry.get("kind", "fixed"), "frequency": label,
                         "frequency_hz": f, "eps_r": eps_r, "sigma_s_per_m": sigma, "thickness_m": thickness,
                         "loss_per_crossing_db": loss, "outside_range": models["outside_range"](entry, f),
                         "status": entry.get("status", "")})
    return rows


def main() -> int:
    library = json.loads((HOUDINI / "materials.json").read_text(encoding="utf-8"))
    rows = table(library, exporter_models())
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "material_losses.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    shown = ("leaf", "stem", "fruit", "water", "nutrient_solution", "rockwool_wet", "soil_loam", "polyethylene_film",
             "polycarbonate", "glass", "concrete_dry", "steel")
    print(f"{'material':18s} {'t (mm)':>7s}  " + "  ".join(f"{label:>10s}" for label in FREQUENCIES))
    for name in shown:
        cells = [r for r in rows if r["material"] == name]
        if cells:
            print(f"{name:18s} {cells[0]['thickness_m'] * 1e3:7.1f}  "
                  + "  ".join(f"{r['loss_per_crossing_db']:8.2f}{'*' if r['outside_range'] else ' '} " for r in cells))
    print("loss per crossing in dB at normal incidence; * outside the material's stated frequency range")
    print("written:", path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

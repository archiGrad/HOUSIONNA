"""Harvester models of the application engine: efficiency against incident RF power at 915 MHz.

    python scripts/harvester_figure.py                   # outputs/validation/harvester_models.pdf/png

Compares the measured plant sensor of Cappelle et al. 2025 (net power stored in the buffer, from the charge times)
with the rectifier alone at its best load voltage, for the high-power input path the sensor uses and the low-power
path of the same AEM30940 kit (AMBIENT-6G dataset). The curves come from config/applications.yaml through the engine.
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.application_engine import harvest_w, harvester_threshold_dbm, load_config  # noqa: E402

CURVES = {  # harvester name: (label, colour, line style)
    "cappelle2025_chain": ("Sensor, measured", "black", "-"),
    "rectifier_bound_915": ("Rectifier, high-power path", "tab:purple", "--"),
    "rectifier_low_915": ("Rectifier, low-power path", "tab:green", "-."),
}
OUT = ROOT / "outputs" / "validation"


def main() -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    p_dbm = np.linspace(-25.0, 0.0, 501)
    p_w = 10 ** ((p_dbm - 30) / 10)
    fig, ax = plt.subplots(figsize=(3.5, 2.6))
    for name, (label, colour, style) in CURVES.items():
        harvester = load_config(harvester=name)["wpt"]["harvester"]
        efficiency = harvest_w(p_w, harvester) / p_w * 100
        ax.plot(p_dbm, np.where(efficiency > 0, efficiency, np.nan), color=colour, linestyle=style,
                linewidth=1.4, label=label)
    threshold = harvester_threshold_dbm(load_config()["wpt"]["harvester"])
    ax.axvline(threshold, color="0.5", linewidth=0.8, linestyle=":")
    ax.annotate(f"sensor starts\n{threshold:g} dBm", xy=(threshold, 52), xytext=(threshold - 0.4, 52),
                ha="right", va="center", fontsize=6.5, color="0.35")
    ax.set_xlim(-25, 0)
    ax.set_ylim(0, 65)
    ax.set_xlabel("Incident RF power at 915 MHz (dBm)")
    ax.set_ylabel("Efficiency (%)")
    ax.grid(alpha=0.3, linewidth=0.5)
    ax.legend(fontsize=6.5, frameon=False, loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    fig.tight_layout()
    OUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("pdf", "png"):
        fig.savefig(OUT / f"harvester_models.{suffix}", dpi=200)
    plt.close(fig)
    print("written:", ", ".join(str((OUT / f"harvester_models.{s}").relative_to(ROOT)) for s in ("pdf", "png")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

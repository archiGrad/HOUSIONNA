"""Harvester model from the measured charge times of Cappelle et al. 2025 (Fig. 4)."""
from __future__ import annotations

import csv
from pathlib import Path
import re
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from engine.application_engine import harvest_w, link_margins_db, load_config, net_power_curve  # noqa: E402
from test_application_engine import toy_run  # noqa: E402

FIGURE = ROOT / "data" / "IEEE_Sensors_2025___RF_Power_Plant_Sensor_GROWTH_1" / "figures" / "energy_harvesting.tex"
CSV = ROOT / "data" / "devices" / "cappelle2025" / "fig4_charge_time.csv"


class CappelleHarvesterTests(unittest.TestCase):
    def setUp(self):
        self.harvester = load_config()["wpt"]["harvester"]

    @unittest.skipUnless(FIGURE.is_file(), "paper source not present")
    def test_csv_matches_the_paper_figure(self):
        # The figure source lists four tables (470 uF cold, 1 mF cold, 470 uF successive, 1 mF successive) in minutes.
        tables = re.findall(r"table \{%\s*(.*?)\};", FIGURE.read_text(encoding="utf-8"), flags=re.S)
        order = [("470uF", "cold"), ("1mF", "cold"), ("470uF", "successive"), ("1mF", "successive")]
        self.assertEqual(len(tables), 4)
        rows = list(csv.DictReader(CSV.open(encoding="utf-8")))
        for (capacitor, start), table in zip(order, tables):
            figure = [tuple(map(float, line.split())) for line in table.strip().splitlines()]
            ours = [(float(r["input_power_dbm"]), float(r["charge_time_s"]) / 60) for r in rows
                    if r["capacitor"] == capacitor and r["start"] == start]
            np.testing.assert_allclose(ours, figure, rtol=1e-12)

    def test_both_buffers_give_the_same_net_power(self):
        # A physical consistency check on the measurements: the harvester does not depend on the buffer size.
        buffer = self.harvester["buffer"]
        rows = [r for r in csv.DictReader(CSV.open(encoding="utf-8")) if r["start"] == "successive"]
        net = {}
        for r in rows:
            energy = 0.5 * buffer["capacitors_f"][r["capacitor"]] * (buffer["v_on_v"] ** 2 - buffer["v_off_v"] ** 2)
            net.setdefault(float(r["input_power_dbm"]), []).append(energy / float(r["charge_time_s"]))
        for p_in, values in net.items():
            self.assertLess(abs(values[0] - values[1]) / np.mean(values), 0.2, p_in)

    def test_threshold_interpolation_and_extrapolation(self):
        curve = net_power_curve(self.harvester)
        self.assertEqual(curve[0][0], -15.0)
        p_in_dbm = np.array([-16.0, -15.0, -12.5, 0.0, 10.0])
        p_dc = harvest_w(10 ** ((p_in_dbm - 30) / 10), self.harvester)
        self.assertEqual(p_dc[0], 0.0)                              # below the minimum input power
        np.testing.assert_allclose(p_dc[1:4], [curve[0][1], curve[1][1], curve[-1][1]])
        self.assertAlmostEqual(p_dc[4] / 1e-2, p_dc[3] / 1e-3)      # constant efficiency above 0 dBm

    def test_profile_transmit_power_for_the_uplink(self):
        run = toy_run([[1e-6]], power_dbm=30.0)                      # -60 dB gain, gateway at 30 dBm
        downlink = link_margins_db(run, {"sensitivity_dbm": -95.0})
        uplink = link_margins_db(run, {"sensitivity_dbm": -95.0, "tx_power_dbm": 0.0})
        self.assertAlmostEqual(downlink[0, 0] - uplink[0, 0], 30.0)


if __name__ == "__main__":
    unittest.main()

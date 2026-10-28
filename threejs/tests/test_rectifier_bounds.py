"""Rectifier upper bounds from the AMBIENT-6G dataset and named harvesters in the application config."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from application_engine import efficiency_curve, harvest_w, harvester_threshold_dbm, load_config  # noqa: E402
from import_ambient6g import SATURATED_PW, envelope  # noqa: E402

HEADER = "frequency_mhz,level_dbm,efficiency,buffer_voltage_mv,resistance,pwr_pw\n"


def dbm_to_w(p_dbm):
    return 10 ** ((np.asarray(p_dbm, dtype=float) - 30) / 10)


class EnvelopeTests(unittest.TestCase):
    def test_best_target_voltage_percent_and_saturated_rows(self):
        measured = {
            250: HEADER + "915,-10,20.0,250,1,1\n915,0,30.0,250,1,1\n915,10,42.95,250,0,%d\n" % SATURATED_PW,
            1000: HEADER + "915,-10,10.0,1000,1,1\n915,0,50.0,1000,1,1\n915,10,20.0,1000,1,1\n",
        }
        rows = {row["input_power_dbm"]: row for row in envelope(measured)}
        self.assertEqual((rows[-10.0]["efficiency"], rows[-10.0]["target_mv"]), (0.2, 250.0))
        self.assertEqual((rows[0.0]["efficiency"], rows[0.0]["target_mv"]), (0.5, 1000.0))
        self.assertEqual((rows[10.0]["efficiency"], rows[10.0]["target_mv"]), (0.2, 1000.0))   # clipped row dropped


class NamedHarvesterTests(unittest.TestCase):
    def test_default_and_override(self):
        self.assertEqual(load_config()["wpt"]["harvester"]["name"], "cappelle2025_chain")
        self.assertEqual(load_config(harvester="rectifier_bound_2450")["wpt"]["harvester"]["frequency_hz"], 2450e6)
        with self.assertRaises(ValueError):
            load_config(harvester="no_such_harvester")

    @unittest.skipUnless((ROOT / "data" / "devices" / "ambient6g" / "rectifier_envelope.csv").is_file(),
                         "run scripts/import_ambient6g.py first")
    def test_bound_lies_above_the_measured_device(self):
        # The rectifier alone at its best load cannot deliver less than the complete chain behind it.
        chain = load_config()["wpt"]["harvester"]
        bound = load_config(harvester="rectifier_bound_915")["wpt"]["harvester"]
        p_in = dbm_to_w(np.arange(-15.0, 0.1, 0.5))
        self.assertTrue(np.all(harvest_w(p_in, bound) > harvest_w(p_in, chain)))
        self.assertLess(harvester_threshold_dbm(bound), harvester_threshold_dbm(chain))
        curve = np.array(efficiency_curve(bound))
        self.assertTrue(np.all((curve[:, 1] > 0) & (curve[:, 1] < 0.75)))


if __name__ == "__main__":
    unittest.main()

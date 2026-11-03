"""Screening of sensor nodes within 1 cm of a surface towards the gateway, on a committed HOUSIONNA batch."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine.screening import MIN_SEGMENT_M, first_hit_m, run_folder, too_close  # noqa: E402

RUN = "batch_1_0_20261030_055729Z.wi001"


def _available() -> bool:
    try:
        run_folder(RUN)
        return True
    except FileNotFoundError:
        return False


@unittest.skipUnless(_available(), f"needs the exported scene of {RUN}")
class ScreeningTests(unittest.TestCase):
    def test_the_two_sensor_nodes_below_a_leaf_are_found(self):
        self.assertEqual(sorted(too_close(RUN)), ["plant_sensor_5", "plant_sensor_7"])

    def test_the_other_sensor_nodes_see_the_gateway_directly(self):
        hits = first_hit_m(run_folder(RUN), "ap_", "plant_sensor_")
        clear = [name for name, distance in hits.items() if distance > 1.0]
        self.assertEqual(len(clear), 7)
        self.assertTrue(all(hits[name] < MIN_SEGMENT_M for name in ("plant_sensor_5", "plant_sensor_7")))


if __name__ == "__main__":
    unittest.main()

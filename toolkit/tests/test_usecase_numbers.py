"""Use-case numbers: runs keyed by parameters and carrier, row labels, and gateway strategies with several gateways."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from engine.application_engine import RunChannels  # noqa: E402
from usecase_numbers import (  # noqa: E402
    at, evaluate, finite_min, fmt, frequency_parameters, group_runs, label, varying,
)

HARVESTER = {"label": "linear", "quadratic_uw": [0.0, 0.5, 0.0], "input_range_dbm": [-60.0, 30.0]}


def run(parameters: dict, frequency_hz: float = 915e6, h=((1e-3,),), run_id: str = "b.wi000") -> RunChannels:
    h = np.asarray(h, dtype=np.complex128)
    return RunChannels(import_id=run_id, run_id=run_id, frequency_hz=frequency_hz,
                       tx_names=[f"ap_{i}" for i in range(h.shape[0])], tx_power_dbm=np.zeros(h.shape[0]),
                       rx_names=[f"plant_sensor_{j}" for j in range(h.shape[1])],
                       rx_positions_m=np.zeros((h.shape[1], 3)), h=h, gain_incoherent=np.abs(h) ** 2,
                       path_counts=np.ones(h.shape, dtype=int), parameters=dict(parameters))


class GroupingTests(unittest.TestCase):
    def test_a_wedged_frequency_is_left_out_of_the_key(self):
        runs = [run({"stage": s, "a": f / 1e6, "tray_copies": 1}, f, run_id=f"b.wi{s}{f:.0f}")
                for s in (0, 1) for f in (868e6, 915e6, 2.437e9)]
        self.assertEqual(frequency_parameters(runs), {"a"})
        grouped, carrier = group_runs(runs)
        self.assertEqual(carrier, {"a"})
        self.assertEqual(len(grouped), 2)                       # one key per stage, three carriers each
        key = (("stage", 1), ("tray_copies", 1))
        self.assertEqual(at(grouped[key], 2.437e9).frequency_hz, 2.437e9)
        self.assertIsNone(at(grouped[key], 5.18e9))

    def test_separate_batches_per_frequency_share_their_keys(self):
        runs = [run({"plant_id": p}, f, run_id=f"b{f:.0f}.wi{p}") for p in (1, 2) for f in (915e6, 2.437e9)]
        self.assertEqual(frequency_parameters(runs), set())  # plant_id takes several values at one carrier
        grouped, _ = group_runs(runs)
        self.assertEqual(sorted(grouped), [(("plant_id", 1),), (("plant_id", 2),)])

    def test_two_runs_with_the_same_parameters_and_carrier_are_refused(self):
        with self.assertRaises(SystemExit):
            group_runs([run({"stage": 0}, run_id="x.wi0"), run({"stage": 0}, run_id="y.wi0")])

    def test_labels_show_only_the_varying_parameters(self):
        keys = [(("species", s), ("stage", g), ("tray_copies", 1)) for s in (0, 1) for g in (0, 4)]
        self.assertEqual(varying(keys), ["species", "stage"])
        self.assertEqual(label(keys[1], varying(keys)), "species=0, stage=4")
        self.assertEqual(label(keys[1], []), "all")


class StrategyTests(unittest.TestCase):
    def test_one_gateway_gives_the_same_power_for_both_strategies(self):
        result = evaluate(run({}, h=[[1e-3, 1e-2]]), [0, 1], 1.0, {"ideal": HARVESTER}, 1e-3)
        single, mrt = (result["strategies"][s] for s in ("single_best", "coherent_mrt"))
        np.testing.assert_allclose(single["p_rf_dbm"], [-30.0, -10.0])  # 30 dBm times |h|^2
        np.testing.assert_allclose(single["p_rf_dbm"], mrt["p_rf_dbm"])

    def test_mrt_adds_the_gateways_and_the_gain_is_from_the_best(self):
        h = [[1e-3, 1e-4], [1e-3, 1e-2]]                       # sensor 0 equal from both, sensor 1 from ap_1
        result = evaluate(run({}, h=h), [0, 1], 1.0, {"ideal": HARVESTER}, 1e-3)
        np.testing.assert_allclose(result["gain_db"], [-60.0, -40.0])
        np.testing.assert_allclose(result["strategies"]["single_best"]["p_rf_dbm"], [-30.0, -10.0])
        np.testing.assert_allclose(result["strategies"]["coherent_mrt"]["p_rf_dbm"],
                                   10 * np.log10([2e-6, 1e-8 + 1e-4]) + 30)

    def test_excluded_sensor_nodes_are_left_out(self):
        result = evaluate(run({}, h=[[1e-3, 1e-2, 1e-1]]), [0, 2], 1.0, {"ideal": HARVESTER}, 1e-3)
        np.testing.assert_allclose(result["gain_db"], [-60.0, -20.0])

    def test_a_node_without_a_path_is_not_powered_and_left_out_of_the_spread(self):
        h = [[1e-3, 0.0], [1e-2, 0.0]]                         # sensor 1 has no path from either gateway
        result = evaluate(run({}, h=h), [0, 1], 1.0, {"ideal": HARVESTER}, 1e-3)
        np.testing.assert_array_equal(result["has_path"], [True, False])
        self.assertEqual(result["gain_db"][1], -np.inf)
        self.assertEqual(finite_min(result["gain_db"]), -40.0)
        self.assertEqual(len(result["below_local_mean_db"]), 1)
        self.assertTrue(np.all(np.isfinite(result["below_local_mean_db"])))
        for strategy in result["strategies"].values():
            self.assertEqual(strategy["p_rf_dbm"][1], -np.inf)
            self.assertEqual(strategy["within_hour"]["ideal"], 1)

    def test_finite_min_and_fmt_without_values(self):
        self.assertIsNone(finite_min([-np.inf, np.nan]))
        self.assertEqual(fmt(None), "--")
        self.assertEqual(fmt(-np.inf), "--")
        self.assertEqual(fmt(-3.04), "$-3.0$")
        self.assertEqual(fmt(-3.04, math=False), "-3.0")


if __name__ == "__main__":
    unittest.main()

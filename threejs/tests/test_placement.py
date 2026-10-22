"""Placement search: exhaustive optimum, greedy as a lower bound, and the objective definitions."""
from __future__ import annotations

from itertools import combinations
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from application_engine import RunChannels, load_config  # noqa: E402
from placement import optimise, subset_scores  # noqa: E402


def random_run(n_tx: int = 6, n_rx: int = 9, seed: int = 3) -> RunChannels:
    rng = np.random.default_rng(seed)
    h = (rng.normal(size=(n_tx, n_rx)) + 1j * rng.normal(size=(n_tx, n_rx))) * 1e-3
    return RunChannels(import_id="toy", run_id="toy", frequency_hz=915e6, tx_names=[f"tx_{i}" for i in range(n_tx)],
                       tx_power_dbm=np.full(n_tx, 30.0), rx_names=[f"rx_{j}" for j in range(n_rx)],
                       rx_positions_m=rng.uniform(size=(n_rx, 3)), h=h, gain_incoherent=np.abs(h) ** 2 * 1.5,
                       path_counts=np.ones((n_tx, n_rx), dtype=int), tx_positions_m=rng.uniform(size=(n_tx, 3)))


class PlacementTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
        self.run = random_run()
        self.result = optimise(self.run, self.config)

    def test_exhaustive_matches_brute_force(self):
        total_w = 10 ** ((self.config["wpt"]["total_power_dbm"] - 30) / 10)
        for row in self.result["sizes"]:
            k = row["k"]
            brute = max(min(total_w * (np.abs(self.run.h[list(subset)]) ** 2).sum(axis=0))
                        for subset in combinations(range(6), k))
            self.assertAlmostEqual(row["objectives"]["wpt_coherent"]["best_value"], 10 * np.log10(brute) + 30, places=9)

    def test_greedy_never_beats_the_optimum_and_coherent_grows_with_k(self):
        coherent = []
        for row in self.result["sizes"]:
            for item in row["objectives"].values():
                self.assertLessEqual(item["greedy_value"], item["best_value"] + 1e-9)
                self.assertLessEqual(item["p10"], item["median"] + 1e-9)
            coherent.append(row["objectives"]["wpt_coherent"]["best_value"])
        self.assertTrue(all(b >= a - 1e-9 for a, b in zip(coherent, coherent[1:])))  # more TX, never less power

    def test_scores_of_one_subset(self):
        scores = subset_scores(self.run, np.array([[0, 2]]), self.config)
        total_w = 10 ** ((self.config["wpt"]["total_power_dbm"] - 30) / 10)
        incoherent = total_w / 2 * self.run.gain_incoherent[[0, 2]].sum(axis=0)
        self.assertAlmostEqual(scores["wpt_incoherent"][0], 10 * np.log10(incoherent.min()) + 30, places=9)
        single = total_w * (np.abs(self.run.h[[0, 2]]) ** 2).max(axis=0)
        self.assertAlmostEqual(scores["wpt_single"][0], 10 * np.log10(single.min()) + 30, places=9)


if __name__ == "__main__":
    unittest.main()

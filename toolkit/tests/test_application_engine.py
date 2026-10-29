"""Application engine: link margins, WPT strategies, harvesting and reporting intervals."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine.application_engine import (  # noqa: E402
    RunChannels, channels_from_payload, communication_summary, evaluate_run, harvested_power_w, link_margins_db,
    load_config, reporting_interval_s, write_outputs, wpt_received_power_w,
)
from server.digital_twin_data import housionna_viewer_payload  # noqa: E402
from housionna.importer import import_run  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "housionna" / "20261019_195611Z"


def toy_run(h: np.ndarray, gain: np.ndarray | None = None, power_dbm: float = 30.0) -> RunChannels:
    h = np.asarray(h, dtype=np.complex128)
    return RunChannels(import_id="toy", run_id="toy", frequency_hz=915e6, tx_names=[f"tx_{i}" for i in range(h.shape[0])],
                       tx_power_dbm=np.full(h.shape[0], power_dbm), rx_names=[f"rx_{j}" for j in range(h.shape[1])],
                       rx_positions_m=np.zeros((h.shape[1], 3)), h=h,
                       gain_incoherent=np.abs(h) ** 2 if gain is None else np.asarray(gain, dtype=float),
                       path_counts=np.ones(h.shape, dtype=int))


class CommunicationTests(unittest.TestCase):
    def test_margin_and_best_server(self):
        run = toy_run([[1e-6, 1e-9], [1e-8, 1e-7]])   # gains -120/-180 dB (tx_0), -160/-140 dB (tx_1)
        profile = {"sensitivity_dbm": -95.0, "implementation_loss_db": 2.0, "reserve_db": 10.0}
        margins = link_margins_db(run, profile)
        self.assertAlmostEqual(margins[0, 0], 30 - 120 + 95 - 2 - 10)
        summary = communication_summary(run, profile)
        self.assertEqual(summary["best_server"], ["tx_0", "tx_1"])
        self.assertAlmostEqual(summary["worst_margin_db"], 30 - 140 + 95 - 12)
        self.assertEqual(summary["coverage"], 0.0)
        self.assertEqual(link_margins_db(toy_run([[0.0]]), profile)[0, 0], -np.inf)  # no path, no link


class WptTests(unittest.TestCase):
    def test_strategies_follow_their_definitions(self):
        h = np.array([[1e-3, 2e-3j], [1e-3, -2e-3j]])  # two TX: in phase at rx_0, opposite at rx_1
        p = wpt_received_power_w(toy_run(h), total_power_w=1.0)
        np.testing.assert_allclose(p["single_best"], [1e-6, 4e-6])
        np.testing.assert_allclose(p["coherent_mrt"], [2e-6, 8e-6])
        np.testing.assert_allclose(p["equal_in_phase"], [2e-6, 0.0], atol=1e-18)  # destructive at rx_1
        np.testing.assert_allclose(p["equal_incoherent"], [1e-6, 4e-6])
        # MRT is the optimum: no unit-power weight vector does better at a receiver.
        rng = np.random.default_rng(1)
        for _ in range(200):
            w = rng.normal(size=2) + 1j * rng.normal(size=2)
            w /= np.linalg.norm(w)
            self.assertLessEqual(abs(h[:, 1] @ w) ** 2, p["coherent_mrt"][1] * (1 + 1e-12))

    def test_harvester_threshold_and_interval(self):
        curve = [[-20.0, 0.1], [0.0, 0.5]]
        p_in = 10 ** ((np.array([-30.0, -20.0, -10.0, 0.0, 10.0]) - 30) / 10)
        np.testing.assert_allclose(harvested_power_w(p_in, curve) / p_in, [0.0, 0.1, 0.3, 0.5, 0.5])
        interval = reporting_interval_s(np.array([0.5e-6, 2e-6, 101e-6]), 2.88e-3, 1e-6)
        self.assertEqual(interval[0], np.inf)
        self.assertAlmostEqual(interval[1], 2880.0)
        self.assertAlmostEqual(interval[2], 28.8)


class RealRunTests(unittest.TestCase):
    def test_channels_and_outputs_from_an_imported_run(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            import_id = import_run(FIXTURE, project).parent.name
            payload = housionna_viewer_payload(project, import_id)
            run = channels_from_payload(payload)
            self.assertEqual(run.h.shape, (2, 20))
            # The incoherent gain equals the exported link value; paths are complete in this fixture.
            for scenario_name in payload["scenario_order"]:
                scenario = payload["scenarios"][scenario_name]
                i = run.tx_names.index(scenario["transmitter"]["name"])
                for link in scenario["links"]:
                    j = run.rx_names.index(link["rx"])
                    if link.get("gain_db_incoherent") is not None and run.gain_incoherent[i, j] > 0:
                        self.assertAlmostEqual(10 * np.log10(run.gain_incoherent[i, j]), link["gain_db_incoherent"], places=3)
                        # Coherent gain needs the carrier phase on Paths.a; it must equal the exporter's value.
                        self.assertAlmostEqual(10 * np.log10(abs(run.h[i, j]) ** 2), link["gain_db_coherent"], places=2)
            config = load_config()
            result = evaluate_run(run, config)
            p = {key: value["p_rf_dbm"] for key, value in result["wpt"]["strategies"].items()}
            self.assertTrue(np.all(p["coherent_mrt"] >= p["single_best"] - 1e-9))
            self.assertTrue(np.all(p["coherent_mrt"] <= p["single_best"] + 10 * np.log10(2) + 1e-9))
            self.assertIsNotNone(result["wpt"]["frequency_warning"])  # fixture runs at 3.5 GHz, curve is for 915 MHz
            written = write_outputs([(run, result)], config, Path(directory) / "out")
            self.assertTrue(all(path.is_file() for path in written))


if __name__ == "__main__":
    unittest.main()

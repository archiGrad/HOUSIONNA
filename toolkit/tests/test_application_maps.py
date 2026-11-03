"""Application maps: surface loading, area weighting and the local-average WPT strategies."""
from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engine.application_engine import load_config  # noqa: E402
from engine.application_maps import (  # noqa: E402
    MapChannels, combine_configurations, evaluate_maps, map_channels_from_payload, select_prefix, select_transmitters,
)
from server.digital_twin_data import housionna_viewer_payload  # noqa: E402
from housionna.importer import import_run  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "housionna" / "20261019_195611Z"


def square_maps(gain: list[list[float]]) -> MapChannels:
    """Two triangles of a 1 m x 2 m rectangle (areas 1 m2 each)."""
    vertices = np.array([[0, 0, 0], [1, 0, 0], [1, 2, 0], [0, 2, 0]], dtype=float)
    gain = np.asarray(gain, dtype=float)
    return MapChannels("toy", "toy", 915e6, [f"tx_{i}" for i in range(gain.shape[0])], np.full(gain.shape[0], 30.0),
                       np.zeros((gain.shape[0], 3)), vertices, np.array([[0, 1, 2], [0, 2, 3]]), gain, "floor")


class BatchMapTests(unittest.TestCase):
    def test_worst_case_per_cell_over_crop_configurations(self):
        config = load_config()
        sparse = square_maps([[1e-5, 1e-9]])           # second triangle shadowed in this configuration
        dense = square_maps([[1e-9, 1e-5]])            # first triangle shadowed in this one
        worst = combine_configurations([(sparse, evaluate_maps(sparse, config)), (dense, evaluate_maps(dense, config))])
        ble = config["communication"]["ble_1m"]
        expected = ble["tx_power_dbm"] - 90 - ble["sensitivity_dbm"] - ble["reserve_db"]
        np.testing.assert_allclose(worst["communication"]["ble_1m"]["margin_db"], [expected, expected])
        self.assertEqual(worst["communication"]["ble_1m"]["coverage_area_share"], 0.0)
        self.assertEqual(worst["wpt"]["single_best"]["feasible_area_share"], 0.0)
        moved = square_maps([[1e-5, 1e-9]])
        moved.vertices_m = moved.vertices_m * 2       # another measurement surface: no worst case per cell
        self.assertIsNone(combine_configurations([(sparse, evaluate_maps(sparse, config)),
                                                  (moved, evaluate_maps(moved, config))]))

    def test_infrastructure_by_prefix(self):
        maps = square_maps([[1e-3, 1e-3], [1e-5, 1e-5]])
        maps.tx_names = ["ap_0", "plant_sensor_0"]
        self.assertEqual(select_prefix(maps, "ap_").tx_names, ["ap_0"])
        self.assertIs(select_prefix(maps, None), maps)
        self.assertIsNone(select_prefix(maps, "gateway_"))  # simulated as a receiver: no map


class MapTests(unittest.TestCase):
    def test_strategies_and_area_shares(self):
        maps = square_maps([[1e-3, 1e-7], [1e-5, 1e-7]])
        np.testing.assert_allclose(maps.areas_m2, [1.0, 1.0])
        result = evaluate_maps(maps, load_config())
        wpt = result["wpt"]
        np.testing.assert_allclose(wpt["coherent_mrt_mean"]["p_rf_dbm"], 10 * np.log10([1.01e-3, 2e-7]) + 30)
        np.testing.assert_allclose(wpt["equal_incoherent"]["p_rf_dbm"], wpt["coherent_mrt_mean"]["p_rf_dbm"] - 10 * np.log10(2))
        np.testing.assert_allclose(wpt["single_best"]["p_rf_dbm"], 10 * np.log10([1e-3, 1e-7]) + 30)
        self.assertEqual(wpt["coherent_mrt_mean"]["feasible_area_share"], 0.5)  # only the strong triangle runs a node
        self.assertEqual(result["communication"]["ble_1m"]["coverage_area_share"], 1.0)

    def test_imported_run_and_transmitter_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            import_id = import_run(FIXTURE, project).parent.name
            maps = map_channels_from_payload(housionna_viewer_payload(project, import_id))
            self.assertEqual(maps.gain.shape[0], 2)
            self.assertEqual(maps.gain.shape[1], len(maps.faces))
            self.assertGreater(maps.areas_m2.sum(), 0)
            one = select_transmitters(maps, [maps.tx_names[1]])
            np.testing.assert_array_equal(one.gain[0], maps.gain[1])
            with self.assertRaises(ValueError):
                select_transmitters(maps, ["no_such_tx"])


if __name__ == "__main__":
    unittest.main()

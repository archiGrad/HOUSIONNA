"""HOUSIONNA multi-sim exports (Oct 2026): NumPy results and binary PLY meshes.

The fixture is a trimmed copy of run 20261019_195611Z (2 TX, 20 RX, one ground object, one
measurement surface), so these tests do not depend on run folders in houdini_files/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from server.digital_twin_data import _import_summary, housionna_viewer_payload  # noqa: E402
from housionna.importer import _load_ply, discover_runs, import_run  # noqa: E402


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "tests" / "fixtures" / "housionna"
RUN = FIXTURE_ROOT / "20261019_195611Z"


def _raw(name: str):
    return np.load(next(RUN.glob(f"*_{name}.npz")), allow_pickle=False)


class HousionnaNpzExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = import_run(RUN, PROJECT_ROOT, dry_run=True)
        cls.devices = json.loads(next(RUN.glob("*_txrx.json")).read_text(encoding="utf-8"))
        cls.scenarios = {row["transmitter"]["name"]: row for row in cls.document["scenarios"].values()}

    def test_devices_and_paths_match_the_raw_arrays(self):
        result = _raw("result")
        tx_names = [str(name) for name in result["tx"]]
        rx_names = [str(name) for name in result["rx"]]
        self.assertEqual(sorted(self.scenarios), sorted(tx_names))
        self.assertEqual(sum(len(row["paths"]) for row in self.scenarios.values()), len(result["path_tx"]))
        source_tx = {row["name"]: row for row in self.devices["tx"]}
        for t, tx_name in enumerate(tx_names):
            scenario = self.scenarios[tx_name]
            self.assertEqual(scenario["transmitter"]["position_m"], source_tx[tx_name]["position"])
            rows = np.flatnonzero(result["path_tx"] == t)
            self.assertEqual(len(scenario["paths"]), len(rows))
            for normalized, k in zip(scenario["paths"], rows):
                used = result["path_interactions"][k] != 0
                self.assertEqual(normalized["receiver"], rx_names[result["path_rx"][k]])
                self.assertEqual(normalized["interaction_type_ids"], result["path_interactions"][k][used].tolist())
                self.assertEqual(normalized["interaction_vertices_m"],
                                 result["path_vertices"][k][used].astype(float).tolist())
                self.assertEqual(normalized["interacted_objects"],
                                 [str(result["object_names"][i]) for i in result["path_objects"][k][used]])
                self.assertEqual(normalized["magnitude_db"], float(result["path_gain_db"][k]))
                self.assertEqual(normalized["delay_s"], float(result["path_tau"][k]))
            # Link arrays are indexed [rx, tx]; one link per receiver.
            self.assertEqual(len(scenario["links"]), len(rx_names))
            for r, link in enumerate(scenario["links"]):
                self.assertEqual(link["rx"], rx_names[r])
                self.assertEqual(link["num_paths"], int(result["link_num_paths"][r, t]))
                self.assertEqual(link["gain_db_coherent"], float(result["link_gain_db_coherent"][r, t]))

    def test_radio_map_matches_the_raw_arrays_and_measurement_mesh(self):
        radio = _raw("radiomap")
        for t, tx_name in enumerate(str(name) for name in radio["tx"]):
            surface = self.scenarios[tx_name]["radio_map"]["surfaces"][0]
            self.assertEqual(surface["name"], str(radio["map_names"][0]))
            expected = [None if value <= -999 else float(value) for value in radio["path_gain_db"][:, t]]
            self.assertEqual(surface["values_db"], expected)
        mesh = self.document["assets"]["meshes"][surface["mesh_ref"]]
        ply_vertices, ply_faces = _load_ply(RUN / "meshes" / "measure_ground.ply")
        self.assertEqual(mesh["faces"], ply_faces)
        self.assertEqual(mesh["faces"], radio["faces"].tolist())
        self.assertEqual(len(mesh["vertices_m"]), len(ply_vertices))

    def test_scene_object_from_binary_ply_is_imported(self):
        geometry = next(iter(self.document["assets"]["geometries"].values()))
        self.assertEqual([row["id"] for row in geometry["objects"]], ["ground"])
        vertices, faces = _load_ply(RUN / "meshes" / "ground.ply")
        self.assertEqual(geometry["objects"][0]["faces"], faces)
        self.assertEqual(len(geometry["objects"][0]["vertices"]), len(vertices))

    def test_discovery_accepts_npz_runs(self):
        with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(FIXTURE_ROOT)}):
            rows = {row["run_id"]: row for row in discover_runs(PROJECT_ROOT)}
        self.assertEqual(rows[RUN.name]["status"], "valid", rows[RUN.name].get("errors"))

    def test_json_and_npz_results_together_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            copy = Path(directory) / RUN.name
            shutil.copytree(RUN, copy)
            (copy / "SIONNA_HOUDINI_pipeline_4_result.json").write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "both"):
                import_run(copy, PROJECT_ROOT, dry_run=True)



class HousionnaOnDemandViewerTests(unittest.TestCase):
    """The scene file carries stubs; the viewer fetches a run's full data when it is selected."""

    def test_stubs_match_the_full_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            output = import_run(RUN, project)
            summary = _import_summary(output)
            payload = housionna_viewer_payload(project, output.parent.name)
            self.assertEqual(summary["scenario_order"], payload["scenario_order"])
            self.assertNotIn("source_run_folder", json.dumps(payload))
            for name in payload["scenario_order"]:
                full, stub = payload["scenarios"][name], summary["stubs"][name]
                self.assertTrue(stub["stub"])
                self.assertNotIn("paths", stub)
                self.assertEqual(stub["transmitter"], full["transmitter"])
                self.assertEqual(stub["import_id"], output.parent.name)
                values = sorted(value for surface in full["radio_map"]["surfaces"]
                                for value in surface["values_db"] if value is not None)
                self.assertEqual(stub["summary"]["median_db"], values[len(values)//2])
                self.assertEqual(stub["summary"]["path_count"], len(full["paths"]))
                self.assertIn(full["geometry_ref"], payload["assets"]["geometries"])

    def test_one_transmitter_at_a_time(self):
        # The viewer loads one scenario (transmitter) per request; it must equal that scenario of the full payload.
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            import_id = import_run(RUN, project).parent.name
            full = housionna_viewer_payload(project, import_id)
            for name in full["scenario_order"]:
                single = housionna_viewer_payload(project, import_id, name)
                self.assertEqual(single["scenario_order"], [name])
                self.assertEqual(single["scenarios"][name], full["scenarios"][name])
                scenario = single["scenarios"][name]
                self.assertEqual(set(single["assets"]["geometries"]), {scenario["geometry_ref"]})
                self.assertEqual(set(single["assets"]["meshes"]),
                                 {row["mesh_ref"] for row in scenario["radio_map"]["surfaces"]})
            with self.assertRaises(FileNotFoundError):
                housionna_viewer_payload(project, import_id, "no_such_tx")
            with self.assertRaises(ValueError):
                housionna_viewer_payload(project, "../outside", full["scenario_order"][0])

    def test_summary_is_cached_until_the_import_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = import_run(RUN, Path(directory) / "project")
            cache = output.with_name("viewer_summary.json")
            summary = _import_summary(output)
            marked = dict(summary, featured_scenario="cache-marker")
            cache.write_text(json.dumps(marked), encoding="utf-8")
            self.assertEqual(_import_summary(output)["featured_scenario"], "cache-marker")
            output.write_text(output.read_text(encoding="utf-8") + " ", encoding="utf-8")  # import changed
            self.assertNotEqual(_import_summary(output)["featured_scenario"], "cache-marker")


if __name__ == "__main__":
    unittest.main()

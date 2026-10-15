from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from digital_twin_data import build_viewer_scene
from integrations.housionna import (
    _RUN_VALIDATION_CACHE,
    compare_imports,
    _load_ascii_ply,
    configured_path_endpoint_tolerance,
    configured_runs_directory,
    discover_runs,
    import_run,
)
from integrations.housionna_api import HousionnaApiError, HousionnaImportManager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RUN_ID = "20261007_200100Z"
SAMPLE_RUN = configured_runs_directory(PROJECT_ROOT) / SAMPLE_RUN_ID
HAS_SAMPLE = SAMPLE_RUN.is_dir()
LARGE_RUN_ID = "20261007_195457Z"
LARGE_RUN = configured_runs_directory(PROJECT_ROOT) / LARGE_RUN_ID
HAS_LARGE_RUN = LARGE_RUN.is_dir()


@unittest.skipUnless(HAS_SAMPLE, "The real HOUSIONNA sample export is not available locally")
class HousionnaRealExportTests(unittest.TestCase):
    def copy_sample(self, parent: Path, run_id: str = SAMPLE_RUN_ID) -> Path:
        target = parent / run_id
        target.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True)
        for source in list(SAMPLE_RUN.glob("*.json")) + list(SAMPLE_RUN.glob("*_scene.xml")):
            shutil.copy2(source, target / source.name)
        source_meshes = SAMPLE_RUN / "meshes"
        target_meshes = target / "meshes"
        target_meshes.mkdir()
        for source in source_meshes.glob("*.ply"):
            shutil.copy2(source, target_meshes / source.name)
        return target

    def import_into_temp_project(self, run_folder: Path, project_root: Path) -> tuple[Path, dict]:
        output = import_run(run_folder, project_root)
        self.assertIsInstance(output, Path)
        return output, json.loads(output.read_text(encoding="utf-8"))

    def test_valid_completed_run_discovery_and_incomplete_exclusion(self):
        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory)
            incomplete = runs_root / "20990101_000000Z"
            incomplete.mkdir()
            (incomplete / "partial_settings.json").write_text("{}", encoding="utf-8")
            self.copy_sample(runs_root)
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(runs_root)}):
                rows = discover_runs(PROJECT_ROOT)
            by_id = {row["run_id"]: row for row in rows}
            self.assertEqual(by_id[incomplete.name]["status"], "incomplete")
            self.assertEqual(by_id[SAMPLE_RUN_ID]["status"], "valid")
            newest_valid = next(row for row in rows if row["status"] == "valid")
            self.assertEqual(newest_valid["run_id"], SAMPLE_RUN_ID)
            self.assertEqual(newest_valid["tx_count"], 15)

    def test_import_latest_and_specific_run_reuse_real_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            exports = root / "exports"
            run_folder = self.copy_sample(exports)
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(exports)}):
                latest = next(row for row in discover_runs(PROJECT_ROOT) if row["status"] == "valid")
            output, document = self.import_into_temp_project(exports / latest["run_id"], root / "project")
            self.assertEqual(document["run_metadata"]["run_id"], SAMPLE_RUN_ID)
            self.assertEqual(document["run_metadata"]["path_count"], 530)
            first_mtime = output.stat().st_mtime_ns
            cached = import_run(run_folder, root / "project")
            self.assertEqual(cached, output)
            self.assertEqual(output.stat().st_mtime_ns, first_mtime)
            self.assertEqual(document["adapter_version"], "2.2.0")

    def test_corrupt_json_is_reported_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_folder = self.copy_sample(root)
            next(run_folder.glob("*_result.json")).write_text("{", encoding="utf-8")
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(root)}):
                row = discover_runs(PROJECT_ROOT)[0]
            self.assertEqual(row["status"], "invalid")

    def test_missing_scene_mesh_is_reported_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_folder = self.copy_sample(root)
            (run_folder / "meshes" / "ground.ply").unlink()
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(root)}):
                row = discover_runs(PROJECT_ROOT)[0]
            self.assertEqual(row["status"], "invalid")
            self.assertIn("Scene mesh", row["errors"][0])

    def test_missing_material_reference_is_reported_invalid(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_folder = self.copy_sample(root)
            scene = next(run_folder.glob("*_scene.xml"))
            xml_root = ET.parse(scene).getroot()
            reference = xml_root.find("shape/ref[@name='bsdf']")
            self.assertIsNotNone(reference)
            reference.set("id", "missing_material")
            ET.ElementTree(xml_root).write(scene, encoding="unicode")
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(root)}):
                row = discover_runs(PROJECT_ROOT)[0]
            self.assertEqual(row["status"], "invalid")
            self.assertIn("missing material", row["errors"][0])

    def test_malformed_path_and_unknown_interaction_object_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_folder = self.copy_sample(root)
            result_file = next(run_folder.glob("*_result.json"))
            result = json.loads(result_file.read_text(encoding="utf-8"))
            row = next(path for path in result["paths"] if path.get("objects"))
            row["objects"][0] = "not_an_exported_object"
            result_file.write_text(json.dumps(result), encoding="utf-8")
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(root)}):
                invalid = discover_runs(PROJECT_ROOT)[0]
            self.assertEqual(invalid["status"], "invalid")
            self.assertIn("unknown scene object", invalid["errors"][0])

            result = json.loads(next(run_folder.glob("*_result.json")).read_text(encoding="utf-8"))
            result["paths"][0]["vertices"] = []
            result_file.write_text(json.dumps(result), encoding="utf-8")
            _RUN_VALIDATION_CACHE.clear()
            with patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(root)}):
                malformed = discover_runs(PROJECT_ROOT)[0]
            self.assertEqual(malformed["status"], "invalid")

    def test_coordinates_missing_map_values_and_multiple_transmitters(self):
        document = import_run(SAMPLE_RUN, PROJECT_ROOT, dry_run=True)
        self.assertIsInstance(document, dict)
        source_devices = json.loads(next(SAMPLE_RUN.glob("*_txrx.json")).read_text(encoding="utf-8"))
        source_results = json.loads(next(SAMPLE_RUN.glob("*_result.json")).read_text(encoding="utf-8"))
        source_maps = json.loads(next(SAMPLE_RUN.glob("*_radiomap.json")).read_text(encoding="utf-8"))
        first_tx = source_devices["tx"][0]
        key = document["featured_scenario"]
        scenario = document["scenarios"][key]
        self.assertEqual(scenario["transmitter"]["position_m"], first_tx["position"])
        geometry = document["assets"]["geometries"][scenario["geometry_ref"]]
        self.assertEqual(geometry["units"], "m")
        self.assertEqual(geometry["up_axis"], "z")
        self.assertEqual(len(document["scenario_order"]), 15)
        self.assertEqual(sum(row["path_count"] for row in document["scenarios"].values()), 530)
        source_tx_paths = [row for row in source_results["paths"] if row["tx"] == first_tx["name"]]
        source_path = source_tx_paths[0]
        normalized_path = scenario["paths"][0]
        source_rx = next(row for row in source_devices["rx"] if row["name"] == source_path["rx"])
        self.assertEqual(source_path["vertices"][0], scenario["transmitter"]["position_m"])
        self.assertEqual(source_path["vertices"][-1], source_rx["position"])
        self.assertEqual(normalized_path["interaction_vertices_m"], source_path["vertices"][1:-1])
        surface = scenario["radio_map"]["surfaces"][0]
        self.assertEqual(len(surface["values_db"]), 19602)
        source_map = source_maps["maps"][0]
        for tx_index, tx in enumerate(source_maps["tx"]):
            tx_scenario = document["scenarios"][document["scenario_order"][tx_index]]
            tx_surface = tx_scenario["radio_map"]["surfaces"][0]
            expected = [None if row[tx_index] == -999 else row[tx_index]
                        for row in source_map["path_gain_db"][:3]]
            self.assertEqual(tx_surface["values_db"][:3], expected)
        measurement_mesh = document["assets"]["meshes"][surface["mesh_ref"]]
        for index, point in enumerate(source_map["vertices"][:4]):
            self.assertEqual(measurement_mesh["vertices_m"][index], point)
        self.assertGreater(sum(value is None for value in surface["values_db"]), 0)
        self.assertTrue(all(value is None or value > -999 for value in surface["values_db"]))

    def test_path_endpoint_tolerance_is_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_folder = self.copy_sample(root / "exports")
            result_file = next(run_folder.glob("*_result.json"))
            result = json.loads(result_file.read_text(encoding="utf-8"))
            result["paths"][0]["vertices"][0][0] += 0.005
            result_file.write_text(json.dumps(result), encoding="utf-8")

            strict_project = root / "strict_project"
            (strict_project / "config").mkdir(parents=True)
            (strict_project / "config" / "housionna.yaml").write_text(
                "housionna:\n  path_endpoint_tolerance_m: 0.001\n", encoding="utf-8")
            self.assertEqual(configured_path_endpoint_tolerance(strict_project), 0.001)
            with self.assertRaisesRegex(ValueError, "TX endpoint differs"):
                import_run(run_folder, strict_project, dry_run=True)

            tolerant_project = root / "tolerant_project"
            (tolerant_project / "config").mkdir(parents=True)
            (tolerant_project / "config" / "housionna.yaml").write_text(
                "housionna:\n  path_endpoint_tolerance_m: 0.01\n", encoding="utf-8")
            accepted = import_run(run_folder, tolerant_project, dry_run=True)
            self.assertAlmostEqual(accepted["provenance"]["max_path_endpoint_error_m"], 0.005)
            self.assertEqual(accepted["provenance"]["path_endpoint_tolerance_m"], 0.01)

    def test_comparison_checks_triangle_alignment_before_cell_deltas(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, document = self.import_into_temp_project(SAMPLE_RUN, root)
            first_id = source.parent.name
            second_id = "second-revision"
            second_dir = root / "outputs" / "integrations" / "housionna" / second_id
            second_dir.mkdir(parents=True)
            altered = json.loads(json.dumps(document))
            scenario = altered["scenarios"][altered["featured_scenario"]]
            mesh = altered["assets"]["meshes"][scenario["radio_map"]["surfaces"][0]["mesh_ref"]]
            face = mesh["faces"][0]
            mesh["faces"][0] = [face[1], face[0], face[2]]
            (second_dir / "viewer_import.json").write_text(json.dumps(altered), encoding="utf-8")
            result = compare_imports(root, first_id, first_id, "tx_0")
            self.assertEqual(result["compatibility"]["status"], "compatible")
            self.assertTrue(result["radio_map"]["compatible"])
            self.assertEqual(result["radio_map"]["delta_statistics"]["mean_absolute_delta_db"], 0.0)
            misaligned = compare_imports(root, first_id, second_id, "tx_0")
            self.assertFalse(misaligned["radio_map"]["compatible"])
            self.assertIsNone(misaligned["radio_map"]["delta_statistics"])

    def test_viewer_rebuild_keeps_builtin_scenarios_with_imported_scenes(self):
        scene_file = build_viewer_scene(PROJECT_ROOT)
        scene = json.loads(scene_file.read_text(encoding="utf-8"))
        self.assertIn("farm_proxy", scene["scenarios"])
        self.assertIn("empty", scene["scenarios"])
        self.assertTrue(any(row.get("source_type") == "housionna" for row in scene["scenarios"].values()))
        self.assertNotIn("source_run_folder", json.dumps(scene))


class HousionnaApiInputTests(unittest.TestCase):
    def test_import_api_rejects_path_traversal(self):
        manager = HousionnaImportManager(PROJECT_ROOT)
        with self.assertRaises(HousionnaApiError) as error:
            manager.start("../outside")
        self.assertEqual(error.exception.status, 400)


@unittest.skipUnless(HAS_LARGE_RUN, "The real 102-transmitter HOUSIONNA run is not available locally")
class HousionnaLargeExportValidationTests(unittest.TestCase):
    def test_meshes_devices_paths_and_all_map_columns_match_source(self):
        document = import_run(LARGE_RUN, PROJECT_ROOT, dry_run=True)
        self.assertIsInstance(document, dict)
        devices = json.loads(next(LARGE_RUN.glob("*_txrx.json")).read_text(encoding="utf-8"))
        result = json.loads(next(LARGE_RUN.glob("*_result.json")).read_text(encoding="utf-8"))
        radio = json.loads(next(LARGE_RUN.glob("*_radiomap.json")).read_text(encoding="utf-8"))
        scenario_by_tx = {
            row["transmitter"]["name"]: row for row in document["scenarios"].values()
        }
        geometry = document["assets"]["geometries"][next(iter(document["assets"]["geometries"]))]
        objects = {row["name"]: row for row in geometry["objects"]}

        self.assertEqual(len(objects), 2)
        self.assertEqual(document["run_metadata"]["mesh_count"], 2)
        self.assertEqual(document["provenance"]["path_endpoint_tolerance_m"], 0.001)
        self.assertEqual(document["provenance"]["max_path_endpoint_error_m"], 0.0)
        self.assertEqual(document["scenarios"][document["featured_scenario"]]["provenance"][
            "max_path_endpoint_error_m"], 0.0)
        self.assertEqual({name: objects[name]["material_key"] for name in objects}, {
            "ground": "medium_dry_ground_t1_s0",
            "box": "concrete_t0p2_s0",
        })
        for name in ("ground", "box"):
            source_vertices, source_faces = _load_ascii_ply(LARGE_RUN / "meshes" / f"{name}.ply")
            imported = objects[name]
            self.assertEqual(imported["vertices"], source_vertices)
            self.assertEqual(imported["faces"], source_faces)
            self.assertEqual(imported["triangle_count"], len(source_faces))

            edge_counts = {}
            degenerate = duplicate = 0
            seen = set()
            vertices = source_vertices
            for face in source_faces:
                canonical = tuple(sorted(face))
                duplicate += canonical in seen
                seen.add(canonical)
                a, b, c = (vertices[index] for index in face)
                ab = [b[i] - a[i] for i in range(3)]
                ac = [c[i] - a[i] for i in range(3)]
                cross = [ab[1] * ac[2] - ab[2] * ac[1],
                         ab[2] * ac[0] - ab[0] * ac[2],
                         ab[0] * ac[1] - ab[1] * ac[0]]
                degenerate += sum(value * value for value in cross) < 1e-24
                for first, second in ((face[0], face[1]), (face[1], face[2]), (face[2], face[0])):
                    edge = tuple(sorted((first, second)))
                    edge_counts[edge] = edge_counts.get(edge, 0) + 1
            self.assertEqual(degenerate, 0)
            self.assertEqual(duplicate, 0)
            self.assertEqual(sum(count > 2 for count in edge_counts.values()), 0)
            if name == "box":
                self.assertEqual(len(source_vertices), 266)
                self.assertEqual(len(source_faces), 528)
                self.assertEqual(sum(count == 1 for count in edge_counts.values()), 0)

        source_tx = {row["name"]: row for row in devices["tx"]}
        for tx_name, scenario in scenario_by_tx.items():
            self.assertEqual(scenario["transmitter"]["position_m"], source_tx[tx_name]["position"])
            self.assertEqual(scenario["transmitter"]["orientation_rad"], source_tx[tx_name]["orientation"])
            self.assertEqual(scenario["receivers"][0]["position_m"], devices["rx"][0]["position"])
            self.assertEqual(scenario["receivers"][0]["orientation_rad"], devices["rx"][0]["orientation"])
            self.assertEqual(scenario["receivers"][0]["velocity_m_s"], devices["rx"][0]["velocity"])
            source_paths = [row for row in result["paths"] if row["tx"] == tx_name]
            self.assertEqual(len(scenario["paths"]), len(source_paths))
            for normalized, raw in zip(scenario["paths"], source_paths):
                self.assertEqual(normalized["interaction_vertices_m"], raw["vertices"][1:-1])
                self.assertEqual(normalized["interaction_type_ids"], raw["interactions"])
                self.assertEqual(normalized["interacted_objects"], raw["objects"])
                self.assertEqual(normalized["interacted_primitives"], raw["primitives"])
                self.assertEqual(normalized["a_real"], raw["a_re"])
                self.assertEqual(normalized["a_imag"], raw["a_im"])
                self.assertEqual(normalized["magnitude_db"], raw["gain_db"])
                self.assertEqual(normalized["delay_s"], raw["tau"])
                self.assertEqual(normalized["source_angles_rad"], {
                    key: raw[key] for key in ("theta_t", "phi_t", "theta_r", "phi_r")
                })
                joined = [scenario["transmitter"]["position_m"], *normalized["interaction_vertices_m"],
                          scenario["receivers"][0]["position_m"]]
                self.assertEqual(joined, raw["vertices"])

            source_links = [row for row in result["links"] if row["tx"] == tx_name]
            self.assertEqual(len(scenario["links"]), len(source_links))
            for normalized, raw in zip(scenario["links"], source_links):
                self.assertEqual(normalized["tx"], raw["tx"])
                self.assertEqual(normalized["rx"], raw["rx"])
                self.assertEqual(normalized["num_paths"], raw["num_paths"])
                self.assertEqual(normalized["gain_db_coherent"], raw.get("gain_db_coherent"))
                self.assertEqual(normalized["gain_db_incoherent"], raw.get("gain_db_incoherent"))
                self.assertEqual(normalized["delay_spread_s"], raw.get("delay_spread"))
                self.assertEqual(normalized["cfr_db"], raw.get("cfr_db", []))
                self.assertEqual(normalized["cfr_frequencies_hz"], result["cfr_frequencies"])
                self.assertEqual(normalized["vertices_m"], raw["vertices"])
            receiver_metric = next(row for row in scenario["receiver_metrics"]
                                   if row["receiver"] == devices["rx"][0]["name"])
            self.assertEqual(receiver_metric["path_count"], len(source_paths))
            self.assertEqual(receiver_metric["link_metrics"]["gain_db_coherent"],
                             source_links[0].get("gain_db_coherent"))
            self.assertEqual(receiver_metric["link_metrics"]["gain_db_incoherent"],
                             source_links[0].get("gain_db_incoherent"))
            if source_links[0].get("delay_spread") is not None:
                self.assertAlmostEqual(receiver_metric["link_metrics"]["delay_spread_ns"],
                                       source_links[0]["delay_spread"] * 1e9)

        source_surface = radio["maps"][0]
        normalized_surface = scenario_by_tx[radio["tx"][0]]["radio_map"]["surfaces"][0]
        map_mesh = document["assets"]["meshes"][normalized_surface["mesh_ref"]]
        measurement_vertices, measurement_faces = _load_ascii_ply(LARGE_RUN / "meshes" / "measure_ground.ply")
        self.assertEqual(map_mesh["faces"], measurement_faces)
        self.assertEqual(map_mesh["vertices_m"], source_surface["vertices"])
        # The PLY mesh is serialized to six decimal places, while the JSON
        # radio map carries higher precision. Compare those independent source
        # representations within the PLY serialization precision.
        coordinate_error = max(
            abs(measurement_vertices[vertex][axis] - source_surface["vertices"][vertex][axis])
            for vertex in range(len(measurement_vertices))
            for axis in range(3)
        )
        self.assertLessEqual(coordinate_error, 5.1e-7)
        self.assertEqual(map_mesh["faces"], source_surface["faces"])
        self.assertEqual(len(source_surface["faces"]), 19602)
        self.assertEqual(sum(value is None for value in normalized_surface["values_db"]),
                         sum(row[0] == -999 for row in source_surface["path_gain_db"]))
        for tx_index, tx_name in enumerate(radio["tx"]):
            normalized_values = scenario_by_tx[tx_name]["radio_map"]["surfaces"][0]["values_db"]
            expected = [None if row[tx_index] == -999 else row[tx_index]
                        for row in source_surface["path_gain_db"]]
            self.assertEqual(normalized_values, expected)


if __name__ == "__main__":
    unittest.main()

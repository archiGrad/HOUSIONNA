"""HOUSIONNA batch exports (Oct 2026): <batches>/<batch>/wiNNN/ work items with wedged TOPS_ parameters.

Each work item is built from the trimmed npz fixture plus a <hip>_meta.json shaped like Joris's exporter
writes it (batch 20261020_095105Z), so the tests do not depend on folders in houdini_files/.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from server.digital_twin_data import _import_summary, housionna_viewer_payload  # noqa: E402
from housionna.importer import discover_runs, import_run, resolve_run_folder  # noqa: E402


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "housionna" / "20261019_195611Z"
BATCH = "20261020_095105Z"
HIP = "/home/joris/Documents/archiGrad/HOUSIONNA/houdini_files/SIONNA_HOUDINI_pipeline_5.hipnc"
WEDGES = [  # (TOPS_radiomap_tx, TOPS_rx_n) per work item; two attributes vary, as in nested wedges
    (-5.0, 5.0), (-5.0, 20.0), (-3.888888888888889, 20.0),
]


def _meta(index: int, radiomap_tx: float, rx_n: float) -> dict:
    return {
        "exported_utc": f"{BATCH}", "hip": HIP, "houdini": "21.0.440",
        "commit": "e593cbe5740b7bf9b5e489b3ff4e79a0dfce285f", "dirty": True,
        "work_item": {"index": index, "id": 499 + index, "name": f"output0_{499 + index}"},
        "wedge": {"wedgetotal": 280, "TOPS_rx_n": rx_n, "wedgenum": 0, "wedgeattribs": "TOPS_radiomap_tx",
                  "wedgecount": 2, "wedgeindex": index, "TOPS_scene_geometry_res": 1, "runs": 0,
                  "TOPS_tx_n": 1, "TOPS_radiomap_tx": radiomap_tx},
    }


class HousionnaBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        base = Path(self.temp.name)
        self.project = base / "project"
        self.runs = base / "sionna" / "data"
        batch = base / "sionna" / "batches" / BATCH
        self.project.mkdir()
        shutil.copytree(FIXTURE, self.runs / "20261019_195611Z")
        items = {}
        for index, (radiomap_tx, rx_n) in enumerate(WEDGES):
            name = f"wi{index:03d}"
            shutil.copytree(FIXTURE, batch / name)
            # Replace the fixture's own provenance-only meta file, as a batch export would write it.
            next((batch / name).glob("*_meta.json")).write_text(
                json.dumps(_meta(index, radiomap_tx, rx_n)), encoding="utf-8")
            items[name] = {"index": index, "id": 499 + index, "name": f"output0_{499 + index}", "status": "exported"}
        (batch / "batch.json").write_text(json.dumps({
            "created_utc": BATCH, "hip": HIP, "top_node": "/obj/procedural_demo/topnet1/output0",
            "range": [0, len(WEDGES) - 1], "frequency": 3.5e9, "items": items}), encoding="utf-8")
        (batch / "status.json").write_text(json.dumps({"total": len(WEDGES), "finished": True}), encoding="utf-8")
        # Batches default to the folder next to the runs directory.
        self.env = patch.dict(os.environ, {"HOUSIONNA_RUNS_DIRECTORY": str(self.runs)})
        self.env.start()
        os.environ.pop("HOUSIONNA_BATCHES_DIRECTORY", None)

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_discovery_lists_each_work_item_as_a_run(self):
        rows = {row["run_id"]: row for row in discover_runs(self.project)}
        expected = {f"{BATCH}.wi{index:03d}" for index in range(len(WEDGES))}
        self.assertTrue(expected <= set(rows))
        self.assertIn("20261019_195611Z", rows)
        for run_id in expected:
            self.assertEqual(rows[run_id]["status"], "valid", rows[run_id])
            self.assertEqual(rows[run_id]["batch_id"], BATCH)
        self.assertNotIn("batch_id", rows["20261019_195611Z"])
        only = discover_runs(self.project, only=f"{BATCH}.wi001")
        self.assertEqual([row["run_id"] for row in only], [f"{BATCH}.wi001"])

    def test_run_ids_resolve_only_to_run_folders(self):
        self.assertEqual(resolve_run_folder(self.project, f"{BATCH}.wi002").name, "wi002")
        self.assertEqual(resolve_run_folder(self.project, "20261019_195611Z").name, "20261019_195611Z")
        for bad in (f"{BATCH}.wi999", "../data", f"{BATCH}/wi000", "..", f"{BATCH}..wi000", "", None):
            with self.subTest(run_id=bad), self.assertRaises((ValueError, FileNotFoundError)):
                resolve_run_folder(self.project, bad)

    def test_import_keeps_parameters_and_batch_without_local_paths(self):
        output = import_run(resolve_run_folder(self.project, f"{BATCH}.wi002"), self.project)
        import_id = output.parent.name
        self.assertTrue(import_id.startswith(f"{BATCH}_wi002-"))
        payload = housionna_viewer_payload(self.project, import_id)
        scenario = next(iter(payload["scenarios"].values()))
        meta = scenario["run_metadata"]
        self.assertEqual(meta["run_id"], f"{BATCH}.wi002")
        self.assertEqual(meta["parameters"], {"TOPS_rx_n": 20.0, "TOPS_scene_geometry_res": 1, "TOPS_tx_n": 1,
                                              "TOPS_radiomap_tx": -3.888888888888889})
        self.assertEqual(meta["batch"]["id"], BATCH)
        self.assertEqual(meta["batch"]["items"], len(WEDGES))
        self.assertEqual(meta["wedge"]["wedgeindex"], 2)
        self.assertEqual(meta["houdini"]["hip_file"], "SIONNA_HOUDINI_pipeline_5.hipnc")
        text = json.dumps(payload)
        self.assertNotIn("/home/joris", text)
        self.assertNotIn(self.temp.name, text)
        # The scene file's stubs carry the same metadata, so the batch chart works before a run is loaded.
        stub = next(iter(_import_summary(output)["stubs"].values()))
        self.assertEqual(stub["run_metadata"]["parameters"], meta["parameters"])
        self.assertEqual(stub["run_metadata"]["batch"]["id"], BATCH)

    def test_wedged_attributes_need_no_prefix(self):
        # From 21 Oct 2026 the exporter writes plain names (a, b, c, ...) next to PDG's bookkeeping fields.
        folder = resolve_run_folder(self.project, f"{BATCH}.wi000")
        meta_file = next(folder.glob("*_meta.json"))
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        meta["wedge"] = {"runs": 0, "wedgeindex": 3, "wedgetotal": 675, "wedgeattribs": "a", "wedgecount": 1,
                         "wedgenum": 0, "a": 1, "b": 1, "c": 1, "d": 2, "e": 1}
        meta_file.write_text(json.dumps(meta), encoding="utf-8")
        document = import_run(folder, self.project, dry_run=True)
        self.assertEqual(document["run_metadata"]["parameters"], {"a": 1, "b": 1, "c": 1, "d": 2, "e": 1})
        self.assertEqual(document["run_metadata"]["wedge"]["wedgeindex"], 3)

    def test_plain_runs_import_as_before(self):
        output = import_run(self.runs / "20261019_195611Z", self.project)
        meta = json.loads(output.read_text(encoding="utf-8"))["run_metadata"]
        self.assertEqual(meta["run_id"], "20261019_195611Z")
        self.assertNotIn("batch", meta)
        self.assertNotIn("parameters", meta)


if __name__ == "__main__":
    unittest.main()

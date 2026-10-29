"""run.py publish: which runs go on the public site, and how their numbers are compacted."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from server.publish_site import LOCAL_PATH, _compact, _select  # noqa: E402


def _run(name: str, batch: str | None) -> dict:
    meta = {"run_id": name, "batch": {"id": batch}} if batch else {"run_id": name}
    return {"source_type": "housionna", "import_id": name, "run_metadata": meta}


SCENE = {
    "scenario_order": ["farm_proxy", "single", "a1", "a2", "b1"],
    "featured_scenario": "b1",
    "scenario_labels": {"farm_proxy": "Farm", "single": "Single", "a1": "A1", "a2": "A2", "b1": "B1"},
    "scenarios": {"farm_proxy": {"source_type": "vertical_farm"}, "single": _run("single", None),
                  "a1": _run("a1", "A"), "a2": _run("a2", "A"), "b1": _run("b1", "B")},
}


class PublishSelectionTests(unittest.TestCase):
    def test_default_keeps_everything(self):
        self.assertEqual(_select(SCENE, None, True)["scenario_order"], SCENE["scenario_order"])

    def test_batch_selection_keeps_built_in_scenes_and_moves_the_featured_run(self):
        selected = _select(SCENE, ["A"], False)
        self.assertEqual(selected["scenario_order"], ["farm_proxy", "a1", "a2"])
        self.assertEqual(set(selected["scenario_labels"]), {"farm_proxy", "a1", "a2"})
        self.assertEqual(selected["featured_scenario"], "a2")  # b1 was featured but is not published
        self.assertEqual(_select(SCENE, ["A"], True)["scenario_order"], ["farm_proxy", "single", "a1", "a2"])
        self.assertEqual(_select(SCENE, None, False)["scenario_order"], ["farm_proxy", "a1", "a2", "b1"])

    def test_unknown_batch_is_an_error(self):
        with self.assertRaises(ValueError):
            _select(SCENE, ["A", "missing"], True)

    def test_compact_keeps_six_significant_digits_and_small_values(self):
        value = {"m": [10.123456789, -2.7777777777777777], "gain": 2.145104986785703e-07, "n": 20, "ok": True, "s": "x"}
        self.assertEqual(_compact(value), {"m": [10.1235, -2.77778], "gain": 2.1451e-07, "n": 20, "ok": True, "s": "x"})

    def test_local_path_check(self):
        for leak in ("/home/joris/Documents/x.hipnc", "C:\\\\Users\\\\beauf\\\\x", "C:/Users/beauf/x"):
            self.assertIsNotNone(LOCAL_PATH.search(leak), leak)
        self.assertIsNone(LOCAL_PATH.search("SIONNA_HOUDINI_pipeline_5.hipnc /obj/procedural_demo/topnet1/output0"))


if __name__ == "__main__":
    unittest.main()

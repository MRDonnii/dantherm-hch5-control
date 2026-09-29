import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "gateway"))

from balancing_store import BalancingError, BalancingStore, clean_project

ROOM = {"name": "Køkken", "type": "kitchen", "area": 14, "height": 2.4, "extract": True, "measured_extract": "21.5"}


class BalancingStoreTests(unittest.TestCase):
    def test_project_is_validated_and_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BalancingStore(Path(tmp) / "b.json")
            store.save_project({"rooms": [ROOM], "meta": {"site": "Hus"}, "measure_level": 3}, "tek")
            project = store.state()["project"]
            self.assertEqual(project["rooms"][0]["measured_extract"], 21.5)
            self.assertFalse(project["rooms"][0]["supply"])
            self.assertEqual(project["measure_level"], 3)
            for bad in ({"rooms": [{**ROOM, "type": "garage"}]}, {"rooms": [{**ROOM, "area": 0}]}, {"measure_level": 9}):
                with self.assertRaises(BalancingError):
                    clean_project(bad)

    def test_reports_are_kept_and_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = BalancingStore(Path(tmp) / "b.json")
            summary = store.add_report({"meta": {"site": "Hus"}, "verdict": "Godkendt", "level": 3}, "tek")
            self.assertEqual(store.state()["reports"][0]["site"], "Hus")
            self.assertEqual(store.get_report(summary["id"])["verdict"], "Godkendt")
            self.assertTrue(store.delete_report(summary["id"]))
            self.assertEqual(store.state()["reports"], [])


if __name__ == "__main__":
    unittest.main()

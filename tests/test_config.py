import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perch import config as C  # noqa: E402


class MigrationTests(unittest.TestCase):
    def test_v1_gpu_watch_becomes_a_gpu_card(self):
        v1 = {"threshold": 60, "hosts": [{"id": "h1"}], "watch": [], "x": 10, "y": 20, "opacity": 0.8,
              "topmost": False, "visible": True}  # fmt: skip
        cfg, changed = C.migrate(v1)
        self.assertTrue(changed)
        self.assertEqual(cfg["version"], C.VERSION)
        (card,) = cfg["cards"]
        self.assertEqual((card["type"], card["title"]), ("gpus", "GPUs"))
        self.assertEqual((card["x"], card["y"], card["opacity"], card["topmost"]), (10, 20, 0.8, False))
        self.assertEqual(card["settings"], {"threshold": 60, "hosts": [{"id": "h1"}], "watch": []})

    def test_empty_config_has_no_cards(self):
        cfg, changed = C.migrate({})
        self.assertEqual(cfg, {"version": C.VERSION, "cards": []})
        self.assertTrue(changed)

    def test_current_config_untouched(self):
        cfg = {"version": C.VERSION, "cards": [C.new_card("sites", "Sites")]}
        self.assertEqual(C.migrate(cfg), (cfg, False))


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gpuwatch.config import DEFAULTS  # noqa: E402
from gpuwatch.status import BUSY, FREE, HELD, UNKNOWN, Tracker  # noqa: E402


def cfg(**kw):
    c = dict(DEFAULTS)
    c.update(kw)
    return c


class StatusTests(unittest.TestCase):
    def test_unknown_without_samples(self):
        self.assertEqual(Tracker().evaluate(cfg()), UNKNOWN)

    def test_vram_threshold(self):
        t = Tracker()
        t.add(30, 0, now=0)
        self.assertEqual(t.evaluate(cfg(), now=0), FREE)
        t.add(60, 0, now=5)
        self.assertEqual(t.evaluate(cfg(), now=5), BUSY)

    def test_hysteresis(self):
        t = Tracker()
        t.add(52, 0, now=0)
        self.assertEqual(t.evaluate(cfg(), now=0), BUSY)
        t.add(48, 0, now=5)  # just under 50 - stays busy inside the 5-point dead zone
        self.assertEqual(t.evaluate(cfg(), now=5), BUSY)
        t.add(44, 0, now=10)
        self.assertEqual(t.evaluate(cfg(), now=10), FREE)
        t.add(48, 0, now=15)  # rising again: needs to reach 50 to flip
        self.assertEqual(t.evaluate(cfg(), now=15), FREE)

    def test_utilization_counts(self):
        t = Tracker()
        for i in range(12):
            t.add(10, 90, now=i * 5)
        self.assertEqual(t.evaluate(cfg(), now=55), BUSY)
        self.assertEqual(t.evaluate(cfg(use_util=False), now=55), FREE)

    def test_util_is_averaged(self):
        t = Tracker()
        for i in range(12):
            t.add(10, 0, now=i * 5)
        t.add(10, 100, now=60)  # one spike shouldn't flip it
        self.assertEqual(t.evaluate(cfg(), now=60), FREE)

    def test_held(self):
        t = Tracker()
        for i in range(0, 11 * 60, 5):
            t.add(80, 0, now=i)
        self.assertEqual(t.evaluate(cfg(held_minutes=10), now=11 * 60 - 5), HELD)
        self.assertEqual(t.evaluate(cfg(detect_held=False), now=11 * 60 - 5), BUSY)

    def test_not_held_without_enough_history(self):
        t = Tracker()
        for i in range(0, 120, 5):
            t.add(80, 0, now=i)
        self.assertEqual(t.evaluate(cfg(held_minutes=10), now=115), BUSY)

    def test_not_held_if_recently_active(self):
        t = Tracker()
        for i in range(0, 11 * 60, 5):
            t.add(80, 50 if i == 500 else 0, now=i)
        self.assertEqual(t.evaluate(cfg(held_minutes=10), now=11 * 60 - 5), BUSY)


if __name__ == "__main__":
    unittest.main()

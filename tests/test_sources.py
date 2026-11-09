import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perch.sources import gkey, parse_gpus, parse_procs, parse_ps  # noqa: E402

GPUS = """0, GPU-aaa, NVIDIA GeForce RTX 4090, 18000, 24564, 97, 71
1, GPU-bbb, NVIDIA A100-SXM4-80GB, [N/A], 81920, [N/A], 40
garbage line
"""
PROCS = """GPU-aaa, 4242, /usr/bin/python3, 17000
GPU-bbb, 99, C:\\Program Files\\Blender\\blender.exe, [N/A]
"""


class ParseTests(unittest.TestCase):
    def test_gpus(self):
        g = parse_gpus(GPUS)
        self.assertEqual(len(g), 2)
        self.assertEqual(
            g[0],
            {
                "index": 0,
                "uuid": "GPU-aaa",
                "name": "NVIDIA GeForce RTX 4090",
                "mem_used": 18000.0,
                "mem_total": 24564.0,
                "util": 97.0,
                "temp": 71.0,
            },
        )
        self.assertIsNone(g[1]["mem_used"])
        self.assertIsNone(g[1]["util"])

    def test_procs(self):
        p = parse_procs(PROCS)
        self.assertEqual([x["name"] for x in p], ["python3", "blender.exe"])
        self.assertEqual(p[0]["pid"], 4242)
        self.assertIsNone(p[1]["mem"])

    def test_ps(self):
        self.assertEqual(parse_ps("  4242 alice\n 99 bob\nnoise\n"), {4242: "alice", 99: "bob"})

    def test_gkey(self):
        self.assertEqual(gkey({"uuid": "GPU-x", "index": 3}), "GPU-x")
        self.assertEqual(gkey({"uuid": "", "index": 3}), "3")


if __name__ == "__main__":
    unittest.main()

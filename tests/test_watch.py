import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from perch import machines as M  # noqa: E402
from perch.watch import BAD, OFF, OK, WARN, condition, duration, is_problem, match, new_job, short_status  # noqa: E402

PS_LINUX = """\
  1234   7300  97.5 3500000 jarrod   /usr/bin/blender -b scene.blend -a
     2      0   0.0     0 root     [kthreadd]
  4321     60   0.4  51200 jarrod   python train.py --epochs 50
garbage
"""


def container(**kw):
    base = {"state": "running", "status": "Up 9 days", "health": None, "exit_code": None}
    return {**base, **kw}


class ProcessParsingTests(unittest.TestCase):
    def test_linux_ps(self):
        procs = M.parse_ps_linux(PS_LINUX, now=10000)
        self.assertEqual([p["name"] for p in procs], ["blender", "python"])
        blender = procs[0]
        self.assertEqual((blender["pid"], blender["cpu"], blender["started"]), (1234, 97.5, 10000 - 7300))
        self.assertAlmostEqual(blender["mem"], 3500000 / 1024)
        self.assertEqual(procs[1]["cmd"], "python train.py --epochs 50")

    def test_windows_cpu_from_two_samples(self):
        first = M.parse_ps_windows(
            '[{"pid": 7, "name": "Blender", "started": 50, "mem": 900, "cpu_time": 10}]', "w", 100
        )
        self.assertIsNone(first[0]["cpu"])  # no previous sample yet
        second = M.parse_ps_windows(
            '{"pid": 7, "name": "Blender", "started": 50, "mem": 900, "cpu_time": 15}', "w", 110
        )
        self.assertAlmostEqual(second[0]["cpu"], 50.0)  # 5 CPU-seconds over 10 s

    def test_encoded_powershell_is_quote_free(self):
        cmd = M.encoded_powershell("Get-Process | ConvertTo-Json")
        self.assertNotIn('"', cmd)
        self.assertNotIn("'", cmd)


class JobTests(unittest.TestCase):
    def test_pid_job_survives_and_ends(self):
        job = new_job("m", {"pid": 1234, "name": "blender", "started": 1000})
        self.assertTrue(match(job, [{"pid": 1234, "name": "blender", "started": 1002}]))
        self.assertFalse(match(job, []))

    def test_reused_pid_is_not_the_same_job(self):
        job = new_job("m", {"pid": 1234, "name": "blender", "started": 1000})
        self.assertFalse(match(job, [{"pid": 1234, "name": "chrome", "started": 5000}]))

    def test_name_job_waits_for_the_last_one(self):
        job = new_job("m", {"pid": 1, "name": "Blender", "started": 0}, mode="name")
        procs = [{"pid": 2, "name": "blender"}, {"pid": 3, "name": "blender"}, {"pid": 4, "name": "other"}]
        self.assertEqual(len(match(job, procs)), 2)
        self.assertFalse(match(job, procs[2:]))

    def test_duration(self):
        self.assertEqual(duration(25), "25s")
        self.assertEqual(duration(65), "1m 05s")
        self.assertEqual(duration(3 * 3600 + 120), "3h 2m")
        self.assertEqual(duration(2 * 86400 + 3600), "2d 1h")


class DockerTests(unittest.TestCase):
    def test_parse(self):
        lines = (
            '{"ID":"abc123def4567890","Names":"web","Image":"nginx:1","State":"running",'
            '"Status":"Up 3 hours (unhealthy)","Ports":"0.0.0.0:80->80/tcp"}\n'
            '{"ID":"x","Names":"job","Image":"busybox","State":"exited","Status":"Exited (137) 2 hours ago"}\n'
            "not json\n"
        )
        web, job = M.parse_containers(lines)
        self.assertEqual((web["id"], web["health"], web["ports"]), ("abc123def456", "unhealthy", "0.0.0.0:80->80/tcp"))
        self.assertEqual((job["state"], job["exit_code"]), ("exited", 137))

    def test_parse_old_docker_without_state(self):
        (c,) = M.parse_containers('{"ID":"x","Names":"a","Image":"i","Status":"Up 2 minutes"}')
        self.assertEqual(c["state"], "running")

    def test_stats(self):
        st = M.parse_stats('{"Name":"web","CPUPerc":"12.50%","MemUsage":"76.2MiB / 31GiB","MemPerc":"0.24%"}')
        self.assertEqual(st["web"], {"cpu": 12.5, "mem": "76.2MiB", "mem_pct": 0.24})

    def test_condition(self):
        self.assertEqual(condition(container()), OK)
        self.assertEqual(condition(container(health="unhealthy")), BAD)
        self.assertEqual(condition(container(health="starting")), WARN)
        self.assertEqual(condition(container(state="restarting")), WARN)
        self.assertEqual(condition(container(state="exited", exit_code=0)), OFF)
        self.assertEqual(condition(container(state="exited", exit_code=1)), BAD)
        self.assertTrue(is_problem(container(state="restarting")))
        self.assertFalse(is_problem(container(state="exited", exit_code=0)))

    def test_short_status(self):
        self.assertEqual(short_status(container(status="Up 9 days (healthy)")), "up 9 days")
        self.assertEqual(short_status(container(state="exited", exit_code=2)), "exited (2)")
        self.assertEqual(short_status(container(health="unhealthy")), "unhealthy")


class MachineListTests(unittest.TestCase):
    def test_seed_from_gpu_cards_once(self):
        host = {"method": "ssh", "address": "10.0.0.5", "user": "me", "port": 22, "name": "box"}
        cfg = {"cards": [{"type": "gpus", "settings": {"hosts": [host, dict(host), {"method": "local"}]}}]}
        self.assertTrue(M.seed_from_gpu_cards(cfg))
        self.assertEqual([(m["name"], m["method"]) for m in cfg["machines"]], [("box", "ssh")])
        self.assertFalse(M.seed_from_gpu_cards(cfg))  # never again once the list exists
        self.assertEqual(M.all_machines(cfg)[0]["id"], "local")


if __name__ == "__main__":
    unittest.main()

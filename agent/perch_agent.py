#!/usr/bin/env python3
"""
Perch agent - run this on each GPU machine you want to watch.

Serves NVIDIA GPU stats (from nvidia-smi) as JSON at:
    http://<this-machine>:9123/gpus

Includes which processes (and users) are on each GPU. Read-only, standard
library only (uses psutil for process owners if it happens to be installed).
Python 3.7+.

    python3 perch_agent.py [--port 9123] [--bind 0.0.0.0]
"""

import argparse
import csv
import io
import json
import os
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VERSION = "0.3.0"
GPU_QUERY = "index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu"
PROC_QUERY = "gpu_uuid,pid,process_name,used_memory"
FMT = "--format=csv,noheader,nounits"
NO_WINDOW = 0x08000000 if os.name == "nt" else 0
CACHE_SECONDS = 1.0

_lock = threading.Lock()
_cache = {"t": 0.0, "data": None, "err": None}


def find_smi():
    found = shutil.which("nvidia-smi")
    if found:
        return found
    for candidate in (
        "/usr/bin/nvidia-smi",
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ):
        if os.path.exists(candidate):
            return candidate
    return "nvidia-smi"


SMI = find_smi()


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _rows(text):
    for row in csv.reader(io.StringIO(text or "")):
        yield [c.strip() for c in row]


def _smi(query):
    r = subprocess.run(
        [SMI, query, FMT], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW
    )
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip() or "nvidia-smi failed")
    return r.stdout


def user_of(pid):
    try:
        import psutil

        return psutil.Process(pid).username().split("\\")[-1]
    except ImportError:
        pass
    except Exception:
        return None
    try:
        import pwd

        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("Uid:"):
                    return pwd.getpwuid(int(line.split()[1])).pw_name
    except Exception:
        pass
    return None


def collect():
    gpus = []
    for row in _rows(_smi("--query-gpu=" + GPU_QUERY)):
        if len(row) >= 7 and row[0].isdigit():
            gpus.append(
                {
                    "index": int(row[0]),
                    "uuid": row[1],
                    "name": row[2],
                    "mem_used": _num(row[3]),
                    "mem_total": _num(row[4]),
                    "util": _num(row[5]),
                    "temp": _num(row[6]),
                }
            )
    procs = []
    try:
        for row in _rows(_smi("--query-compute-apps=" + PROC_QUERY)):
            if len(row) >= 4 and row[1].isdigit():
                pid = int(row[1])
                procs.append(
                    {
                        "gpu_uuid": row[0],
                        "pid": pid,
                        "name": os.path.basename(row[2].replace("\\", "/")) or row[2],
                        "mem": _num(row[3]),
                        "user": user_of(pid),
                    }
                )
    except Exception:
        pass
    return {"gpus": gpus, "procs": procs}


def read():
    with _lock:
        if time.time() - _cache["t"] >= CACHE_SECONDS:
            try:
                _cache.update(data=collect(), err=None)
            except Exception as e:  # noqa: BLE001 - report any failure to the client
                _cache.update(data=None, err=str(e))
            _cache["t"] = time.time()
        if _cache["err"]:
            raise RuntimeError(_cache["err"])
        return _cache["data"]


_procs_lock = threading.Lock()
_proc_objs = {}  # pid -> psutil.Process, so cpu_percent() can compare against the previous request


def processes():
    """Running processes for the Jobs card: [{pid, name, cmd, cpu (% of one core), mem (MB), user, started}]."""
    try:
        import psutil
    except ImportError:
        psutil = None
    if psutil is None:
        if os.name == "nt":
            raise RuntimeError("process list needs psutil on Windows - use perch-agent.exe")
        r = subprocess.run(
            ["ps", "-eo", "pid=,etimes=,pcpu=,rss=,user:32=,args=", "--sort=-pcpu"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        now, out = time.time(), []
        for line in r.stdout.splitlines()[:500]:
            parts = line.split(None, 5)
            if len(parts) < 6 or not parts[0].isdigit() or parts[5].startswith("["):
                continue
            pid, etimes, pcpu, rss, user, args = parts
            exe = args.split()[0]
            out.append(
                {
                    "pid": int(pid),
                    "name": os.path.basename(exe) or exe,
                    "cmd": args,
                    "cpu": float(pcpu),
                    "mem": int(rss) / 1024,
                    "user": user,
                    "started": now - int(etimes),
                }
            )
        return out
    out, seen = [], set()
    with _procs_lock:
        for p in psutil.process_iter(["pid", "name", "username", "create_time", "memory_info", "cmdline"]):
            info = p.info
            if not info["pid"]:
                continue
            seen.add(info["pid"])
            cached = _proc_objs.get(info["pid"])
            if cached is None or cached.info.get("create_time") != info.get("create_time"):
                _proc_objs[info["pid"]] = cached = p
            try:
                cpu = cached.cpu_percent(None)
            except Exception:
                cpu = None
            mem = info.get("memory_info")
            out.append(
                {
                    "pid": info["pid"],
                    "name": info.get("name") or "?",
                    "cmd": " ".join(info.get("cmdline") or []) or info.get("name") or "",
                    "cpu": cpu,
                    "mem": mem.rss / 1048576 if mem else None,
                    "user": (info.get("username") or "").split("\\")[-1] or None,
                    "started": info.get("create_time"),
                }
            )
        for pid in [pid for pid in _proc_objs if pid not in seen]:
            del _proc_objs[pid]
    return out


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        base = {"host": socket.gethostname(), "agent": VERSION, "time": time.time()}
        try:
            if path in ("/", "/gpus"):
                self._send(200, {**base, **read()})
            elif path == "/processes":
                self._send(200, {**base, "processes": processes()})
            else:
                self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            self._send(500, {**base, "error": str(e)})

    def _send(self, code, payload):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    ap = argparse.ArgumentParser(description="Perch agent")
    ap.add_argument("--port", type=int, default=9123)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"Perch agent {VERSION} on http://{args.bind}:{args.port}/gpus (nvidia-smi: {SMI})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
GPU Watch agent - run this on each GPU machine you want to watch.

Serves NVIDIA GPU stats (from nvidia-smi) as JSON at:
    http://<this-machine>:9123/gpus

Includes which processes (and users) are on each GPU. Read-only, standard
library only (uses psutil for process owners if it happens to be installed).
Python 3.7+.

    python3 gpu_agent.py [--port 9123] [--bind 0.0.0.0]
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

VERSION = "1.0.0"
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
    for candidate in ("/usr/bin/nvidia-smi", r"C:\Windows\System32\nvidia-smi.exe",
                      r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe"):
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
    r = subprocess.run([SMI, query, FMT], capture_output=True, text=True, timeout=10,
                       stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
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
            gpus.append({"index": int(row[0]), "uuid": row[1], "name": row[2],
                         "mem_used": _num(row[3]), "mem_total": _num(row[4]),
                         "util": _num(row[5]), "temp": _num(row[6])})
    procs = []
    try:
        for row in _rows(_smi("--query-compute-apps=" + PROC_QUERY)):
            if len(row) >= 4 and row[1].isdigit():
                pid = int(row[1])
                procs.append({"gpu_uuid": row[0], "pid": pid,
                              "name": os.path.basename(row[2].replace("\\", "/")) or row[2],
                              "mem": _num(row[3]), "user": user_of(pid)})
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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] not in ("/", "/gpus"):
            return self._send(404, {"error": "not found"})
        try:
            self._send(200, {"host": socket.gethostname(), "agent": VERSION, "time": time.time(), **read()})
        except Exception as e:  # noqa: BLE001
            self._send(500, {"host": socket.gethostname(), "agent": VERSION, "error": str(e)})

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
    ap = argparse.ArgumentParser(description="GPU Watch agent")
    ap.add_argument("--port", type=int, default=9123)
    ap.add_argument("--bind", default="0.0.0.0")
    args = ap.parse_args()
    server = ThreadingHTTPServer((args.bind, args.port), Handler)
    print(f"GPU Watch agent {VERSION} on http://{args.bind}:{args.port}/gpus (nvidia-smi: {SMI})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()

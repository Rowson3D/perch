"""Reading GPU stats from a machine: the HTTP agent, SSH, or this PC.

Every fetch returns {"host": str|None, "gpus": [...], "procs": [...]} where
  gpu  = {index, uuid, name, mem_used, mem_total (MiB), util (%), temp (C)}
  proc = {gpu_uuid, pid, name, mem (MiB), user}
"""

import csv
import io
import json
import os
import socket
import subprocess
import urllib.error
import urllib.request

from gpuwatch.util import NO_WINDOW

GPU_QUERY = "index,uuid,name,memory.used,memory.total,utilization.gpu,temperature.gpu"
PROC_QUERY = "gpu_uuid,pid,process_name,used_memory"
FMT = "--format=csv,noheader,nounits"
AGENT_PORT, SSH_PORT, TIMEOUT = 9123, 22, 5
SEP = "__GPUWATCH_SEP__"

METHODS = {"agent": "GPU Watch agent (HTTP)", "ssh": "SSH (key login)", "local": "This PC"}
METHOD_KEYS = {v: k for k, v in METHODS.items()}

_HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # LAN: never use a system proxy


class CommandError(RuntimeError):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None  # "[N/A]", "[Not Supported]", ...


def _rows(text):
    for row in csv.reader(io.StringIO(text or "")):
        yield [c.strip() for c in row]


def parse_gpus(text):
    gpus = []
    for row in _rows(text):
        if len(row) < 7 or not row[0].isdigit():
            continue
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
    return gpus


def parse_procs(text):
    procs = []
    for row in _rows(text):
        if len(row) < 4 or not row[1].isdigit():
            continue
        name = os.path.basename(row[2].replace("\\", "/")) or row[2]
        procs.append({"gpu_uuid": row[0], "pid": int(row[1]), "name": name, "mem": _num(row[3]), "user": None})
    return procs


def parse_ps(text):
    """`ps -eo pid=,user=` output -> {pid: user}."""
    users = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit():
            users[int(parts[0])] = parts[1]
    return users


def local_users(pids):
    try:
        import psutil
    except ImportError:
        return {}
    users = {}
    for pid in pids:
        try:
            users[pid] = psutil.Process(pid).username().split("\\")[-1]
        except Exception:
            pass
    return users


def _run(cmd, timeout):
    r = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW
    )
    if r.returncode != 0:
        lines = (r.stderr or r.stdout or "").strip().splitlines()
        raise CommandError(lines[-1] if lines else f"exit code {r.returncode}", r.returncode)
    return r.stdout


def fetch_local():
    gpus = parse_gpus(_run(["nvidia-smi", "--query-gpu=" + GPU_QUERY, FMT], TIMEOUT + 5))
    try:
        procs = parse_procs(_run(["nvidia-smi", "--query-compute-apps=" + PROC_QUERY, FMT], TIMEOUT + 5))
    except Exception:
        procs = []
    users = local_users([p["pid"] for p in procs])
    for p in procs:
        p["user"] = users.get(p["pid"])
    return {"host": socket.gethostname(), "gpus": gpus, "procs": procs}


def fetch_ssh(addr, user="", port=None):
    target = f"{user}@{addr}" if user else addr
    base = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        f"ConnectTimeout={TIMEOUT}",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-p",
        str(port or SSH_PORT),
        target,
    ]
    gpu_cmd = f"nvidia-smi --query-gpu={GPU_QUERY} {FMT}"
    full = (
        f"{gpu_cmd}; echo {SEP}; nvidia-smi --query-compute-apps={PROC_QUERY} {FMT}; "
        f"echo {SEP}; ps -eo pid=,user:32= 2>/dev/null"
    )
    try:
        parts = _run(base + [full], TIMEOUT + 10).split(SEP)
    except CommandError as e:
        if e.code == 255:  # ssh itself failed (connect/auth) - no point retrying
            raise
        parts = [_run(base + [gpu_cmd], TIMEOUT + 10)]  # e.g. a Windows host whose shell is cmd.exe
    gpus = parse_gpus(parts[0])
    procs = parse_procs(parts[1]) if len(parts) > 1 else []
    users = parse_ps(parts[2]) if len(parts) > 2 else {}
    for p in procs:
        p["user"] = users.get(p["pid"])
    return {"host": None, "gpus": gpus, "procs": procs}


def fetch_agent(addr, port=None):
    hostpart = f"[{addr}]" if ":" in addr else addr
    try:
        with _HTTP.open(f"http://{hostpart}:{port or AGENT_PORT}/gpus", timeout=TIMEOUT) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error")
        except Exception:
            msg = None
        raise RuntimeError(msg or f"HTTP {e.code}") from None
    except urllib.error.URLError as e:
        reason = e.reason
        if isinstance(reason, ConnectionRefusedError) or "refused" in str(reason).lower():
            raise RuntimeError("connection refused - is the agent running?") from None
        raise RuntimeError(str(reason)) from None
    except TimeoutError:
        raise RuntimeError("timed out") from None
    return {"host": data.get("host"), "gpus": data.get("gpus") or [], "procs": data.get("procs") or []}


def fetch(host):
    method = host.get("method", "agent")
    addr = (host.get("address") or "").strip()
    if method == "local":
        return fetch_local()
    if method == "ssh":
        return fetch_ssh(addr, host.get("user", ""), host.get("port"))
    return fetch_agent(addr, host.get("port"))


def gkey(gpu):
    """Stable identity for a GPU (UUID survives index re-ordering)."""
    return gpu.get("uuid") or str(gpu.get("index"))

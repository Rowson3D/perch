"""Machines Perch can reach - this PC, over SSH, or through the Perch agent - and what it reads from them:
running processes (for the Jobs card) and Docker containers (for the Docker card).

The machine list lives in config["machines"] and is shared by every card. "This PC" is always available
and isn't stored. Network calls block - run them off the UI thread.
"""

import base64
import json
import os
import re
import threading
import time
import uuid

from perch.sources import SEP, CommandError, _run, agent_get, run_ssh

LOCAL = {"id": "local", "name": "This PC", "method": "local", "address": "localhost", "port": None, "user": ""}
METHOD_LABELS = {"local": "this PC", "ssh": "SSH", "agent": "agent"}


# ------------------------------------------------------------------ the shared list
def all_machines(cfg):
    return [LOCAL, *cfg.get("machines", [])]


def get(cfg, machine_id):
    return next((m for m in all_machines(cfg) if m["id"] == machine_id), None)


def new_machine(method, address, user="", port=None, name=""):
    return {
        "id": uuid.uuid4().hex[:10],
        "name": name or address,
        "method": method,
        "address": address,
        "port": port,
        "user": user,
    }


def describe(m):
    if m["method"] == "local":
        return "this PC"
    who = f"{m['user']}@{m['address']}" if m.get("user") else m["address"]
    return f"{METHOD_LABELS.get(m['method'], m['method'])} · {who}"


def seed_from_gpu_cards(cfg):
    """First run of 0.3: offer the machines already added to GPU cards everywhere. Returns True if it changed cfg."""
    if "machines" in cfg:
        return False
    seen, machines = set(), []
    for card in cfg.get("cards", []):
        if card.get("type") != "gpus":
            continue
        for h in card.get("settings", {}).get("hosts", []):
            key = (h.get("method"), h.get("address"), h.get("user"), h.get("port"))
            if h.get("method") == "local" or key in seen:
                continue
            seen.add(key)
            machines.append(new_machine(h["method"], h["address"], h.get("user", ""), h.get("port"), h.get("name", "")))
    cfg["machines"] = machines
    return True


# ------------------------------------------------------------------ processes
PS_LINUX = "ps -eo pid=,etimes=,pcpu=,rss=,user:32=,args= --sort=-pcpu 2>/dev/null | head -500"
PS_WINDOWS = r"""
$ErrorActionPreference = 'SilentlyContinue'
Get-Process | ForEach-Object {
  $s = 0; if ($_.StartTime) { $s = [DateTimeOffset]::new($_.StartTime).ToUnixTimeSeconds() }
  [pscustomobject]@{ pid = $_.Id; name = $_.ProcessName; started = $s;
                     mem = [math]::Round($_.WorkingSet64 / 1MB); cpu_time = $_.CPU }
} | ConvertTo-Json -Compress
"""

_os_cache = {}  # machine id -> "linux" / "windows"
_cpu_times = {}  # (machine id, pid) -> (sample time, cpu seconds) for Windows-over-SSH CPU %
_local_procs = {}  # pid -> psutil.Process, kept so cpu_percent() has something to compare against
_lock = threading.Lock()


def encoded_powershell(script):
    """A PowerShell command line that survives any remote shell (cmd or PowerShell) without quoting issues."""
    return "powershell -NoProfile -NonInteractive -EncodedCommand " + base64.b64encode(
        script.encode("utf-16-le")
    ).decode("ascii")


def parse_ps_linux(text, now=None):
    now = time.time() if now is None else now
    out = []
    for line in (text or "").splitlines():
        parts = line.split(None, 5)
        if len(parts) < 6 or not parts[0].isdigit():
            continue
        pid, etimes, pcpu, rss, user, args = parts
        if args.startswith("["):  # kernel threads
            continue
        exe = args.split()[0]
        try:
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
        except ValueError:
            continue
    return out


def parse_ps_windows(text, machine_id="", now=None):
    now = time.time() if now is None else now
    data = json.loads(text or "[]")
    if isinstance(data, dict):
        data = [data]
    out = []
    with _lock:
        for p in data:
            pid, cpu_time = p.get("pid"), p.get("cpu_time")
            cpu = None
            prev = _cpu_times.get((machine_id, pid))
            if cpu_time is not None:
                if prev and now > prev[0]:
                    cpu = max(0.0, (cpu_time - prev[1]) / (now - prev[0]) * 100)
                _cpu_times[(machine_id, pid)] = (now, cpu_time)
            out.append(
                {
                    "pid": pid,
                    "name": p.get("name") or "?",
                    "cmd": p.get("name") or "",
                    "cpu": cpu,
                    "mem": p.get("mem"),
                    "user": None,
                    "started": p.get("started") or None,
                }
            )
    return out


def local_processes():
    import psutil

    out, seen = [], set()
    with _lock:
        for p in psutil.process_iter(["pid", "name", "username", "create_time", "memory_info", "cmdline"]):
            info = p.info
            pid = info["pid"]
            if pid == 0:  # "System Idle Process" - reports idle time as CPU use
                continue
            seen.add(pid)
            cached = _local_procs.get(pid)
            if cached is None or cached.info.get("create_time") != info.get("create_time"):
                _local_procs[pid] = cached = p
            try:
                cpu = cached.cpu_percent(None)
            except Exception:
                cpu = None
            mem = info.get("memory_info")
            cmd = " ".join(info.get("cmdline") or []) or info.get("name") or ""
            out.append(
                {
                    "pid": pid,
                    "name": info.get("name") or "?",
                    "cmd": cmd,
                    "cpu": cpu,
                    "mem": mem.rss / 1048576 if mem else None,
                    "user": (info.get("username") or "").split("\\")[-1] or None,
                    "started": info.get("create_time"),
                }
            )
        for pid in [pid for pid in _local_procs if pid not in seen]:
            del _local_procs[pid]
    return out


def remote_os(m):
    """'linux' or 'windows' for an SSH machine (asked once, then remembered)."""
    if m["id"] not in _os_cache:
        try:
            out = run_ssh(m["address"], m.get("user", ""), m.get("port"), "uname -s")
            _os_cache[m["id"]] = "windows" if "windows" in out.lower() else "linux"
        except CommandError as e:
            if e.code == 255:
                raise
            _os_cache[m["id"]] = "windows"  # cmd.exe: 'uname' is not recognized
    return _os_cache[m["id"]]


def list_processes(m):
    """Running processes on a machine: [{pid, name, cmd, cpu (% of one core), mem (MB), user, started}]."""
    if m["method"] == "local":
        return local_processes()
    if m["method"] == "agent":
        return agent_get(m["address"], m.get("port"), "/processes").get("processes", [])
    if remote_os(m) == "linux":
        return parse_ps_linux(run_ssh(m["address"], m.get("user", ""), m.get("port"), PS_LINUX))
    out = run_ssh(m["address"], m.get("user", ""), m.get("port"), encoded_powershell(PS_WINDOWS))
    return parse_ps_windows(out, m["id"])


# ------------------------------------------------------------------ Docker containers
DOCKER_PS = "docker ps -a --no-trunc --format '{{json .}}'"
DOCKER_STATS = "docker stats --no-stream --no-trunc --format '{{json .}}'"


def _health(status):
    s = (status or "").lower()
    if "(unhealthy)" in s:
        return "unhealthy"
    if "(healthy)" in s:
        return "healthy"
    if "health: starting" in s:
        return "starting"
    return None


def parse_containers(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        status = d.get("Status", "")
        state = (d.get("State") or "").lower()
        if not state:  # very old Docker: work it out from the status text
            low = status.lower()
            state = "running" if low.startswith("up") else "restarting" if "restarting" in low else "exited"
        code = re.search(r"Exited \((-?\d+)\)", status)
        out.append(
            {
                "id": (d.get("ID") or "")[:12],
                "name": (d.get("Names") or "?").split(",")[0],
                "image": d.get("Image", ""),
                "state": state,
                "status": status,
                "health": _health(status),
                "exit_code": int(code.group(1)) if code else None,
                "ports": d.get("Ports", ""),
            }
        )
    return out


def _pct(s):
    try:
        return float(str(s).strip().rstrip("%"))
    except ValueError:
        return None


def parse_stats(text):
    stats = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        stats[d.get("Name", "")] = {
            "cpu": _pct(d.get("CPUPerc")),
            "mem": (d.get("MemUsage") or "").split("/")[0].strip(),
            "mem_pct": _pct(d.get("MemPerc")),
        }
    return stats


def _docker_error(e):
    msg = str(e)
    low = msg.lower()
    if "not found" in low or "not recognized" in low:
        return RuntimeError("Docker isn't installed on that machine")
    if "permission denied" in low:
        return RuntimeError("your user can't run docker there (add it to the docker group)")
    if "cannot connect to the docker daemon" in low or "error during connect" in low:
        return RuntimeError("Docker is installed but not running")
    return RuntimeError(msg)


def list_containers(m, stats=True):
    """Containers on a machine: [{id, name, image, state, status, health, exit_code, ports, cpu, mem, mem_pct}]."""
    if m["method"] == "agent":
        raise RuntimeError("Docker needs SSH or This PC - the agent doesn't report containers")
    try:
        if m["method"] == "local":
            ps = _run(["docker", "ps", "-a", "--no-trunc", "--format", "{{json .}}"], 20)
            st = ""
            if stats:
                try:
                    st = _run(["docker", "stats", "--no-stream", "--no-trunc", "--format", "{{json .}}"], 20)
                except CommandError:
                    pass
        else:
            cmd = f"{DOCKER_PS}; echo {SEP}; {DOCKER_STATS} 2>/dev/null" if stats else DOCKER_PS
            out = run_ssh(m["address"], m.get("user", ""), m.get("port"), cmd, timeout=30)
            ps, _, st = out.partition(SEP)
    except CommandError as e:
        if e.code == 255:
            raise
        raise _docker_error(e) from None
    except FileNotFoundError:
        raise RuntimeError("Docker isn't installed on this PC") from None
    containers = parse_containers(ps)
    usage = parse_stats(st)
    for c in containers:
        c.update(usage.get(c["name"], {"cpu": None, "mem": "", "mem_pct": None}))
    return containers

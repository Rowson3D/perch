"""Rules for the Jobs and Docker cards, kept free of any UI so they're easy to test.

Jobs:   new_job(), match() - is a watched job still running?   duration() - "1h 12m"
Docker: condition() - ok / warn / bad / off,   short_status(),   is_problem()
"""

import time
import uuid

RUNNING, DONE = "running", "done"
OK, WARN, BAD, OFF = "ok", "warn", "bad", "off"


# ------------------------------------------------------------------ jobs
def duration(seconds):
    """25s / 4m 05s / 1h 12m / 2d 3h."""
    s = max(0, int(seconds or 0))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60:02d}s"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m"
    return f"{s // 86400}d {s % 86400 // 3600}h"


def match(job, procs):
    """The processes that count as this job still running."""
    if job["mode"] == "name":
        name = job["name"].lower()
        return [p for p in procs if (p.get("name") or "").lower() == name]
    out = []
    for p in procs:
        if p.get("pid") != job["pid"]:
            continue
        # a reused PID belongs to a different program: require the same start time (give or take a few seconds)
        if job.get("started") and p.get("started") and abs(p["started"] - job["started"]) > 10:
            continue
        out.append(p)
    return out


def new_job(machine_id, proc, mode="pid", label=""):
    return {
        "id": uuid.uuid4().hex[:10],
        "machine": machine_id,
        "mode": mode,
        "pid": proc.get("pid"),
        "name": proc.get("name") or "?",
        "cmd": proc.get("cmd") or "",
        "started": proc.get("started") or time.time(),
        "label": label,
        "status": RUNNING,
        "ended": None,
    }


# ------------------------------------------------------------------ docker
def condition(c):
    """How a container is doing: ok / warn / bad / off."""
    state, health = c["state"], c.get("health")
    if state == "running":
        return BAD if health == "unhealthy" else WARN if health == "starting" else OK
    if state == "restarting":
        return WARN
    if state == "dead" or (state == "exited" and c.get("exit_code") not in (0, None)):
        return BAD
    return OFF  # exited cleanly, created, paused


def short_status(c):
    """'up 9 days', 'exited (1)', 'restarting', 'unhealthy'."""
    if c["state"] == "running":
        if c.get("health") == "unhealthy":
            return "unhealthy"
        up = c["status"].split("(")[0].strip()
        return up[0].lower() + up[1:] if up else "running"
    if c["state"] == "exited":
        return f"exited ({c['exit_code']})" if c.get("exit_code") is not None else "exited"
    return c["state"]


def is_problem(c):
    return condition(c) == BAD or c["state"] == "restarting"

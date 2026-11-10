"""Small Windows/OS helpers shared across the app."""

import ctypes
import os
import subprocess

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0  # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200 if IS_WIN else 0  # CREATE_NEW_PROCESS_GROUP
DETACHED = 0x00000008 if IS_WIN else 0  # DETACHED_PROCESS

_mutex = None


def single_instance(name="Local\\PerchWidget"):
    """Return False if another copy of the widget is already running."""
    global _mutex
    if not IS_WIN:
        return True
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def dpi_aware():
    if IS_WIN:
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass


if IS_WIN:
    from ctypes import wintypes

    _user32 = ctypes.windll.user32
    _user32.MonitorFromPoint.restype = ctypes.c_void_p
    _user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]

    class _MONITORINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("rcMonitor", wintypes.RECT),
            ("rcWork", wintypes.RECT),
            ("dwFlags", wintypes.DWORD),
        ]

    _user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]


def point_on_a_monitor(x, y):
    if not IS_WIN:
        return True
    try:
        return bool(_user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 0))
    except Exception:
        return True


def work_area(x, y):
    """(left, top, right, bottom) of the usable area (excluding taskbar) of the monitor nearest (x, y)."""
    if not IS_WIN:
        return None
    try:
        mon = _user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 2)  # MONITOR_DEFAULTTONEAREST
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        _user32.GetMonitorInfoW(mon, ctypes.byref(info))
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom
    except Exception:
        return None


def ago(seconds):
    """Compact human duration: 45s, 12m, 3h, 2d."""
    s = max(0, int(seconds))
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60}m" if s < 36000 else f"{s // 3600}h"
    return f"{s // 86400}d"


BREAKAWAY = 0x01000000 if IS_WIN else 0  # CREATE_BREAKAWAY_FROM_JOB


def launch_detached(args):
    """Start a process that outlives us - and, where Windows allows it, whatever launched us.

    Terminals, IDEs and some launchers run their children inside a job object that closes everything when
    they exit. Breaking away from it keeps a freshly installed Perch running after the installer's parent quits.
    """
    kwargs = {"close_fds": True, "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL}  # fmt: skip
    try:
        subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP | BREAKAWAY, **kwargs)
    except OSError:  # the job doesn't allow breaking away
        subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP, **kwargs)


def mix(a, b, t):
    """Blend two #rrggbb colors: t=0 gives a, t=1 gives b."""
    ca, cb = [int(a[i : i + 2], 16) for i in (1, 3, 5)], [int(b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(ca, cb, strict=True))


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def short_name(name):
    for prefix in ("NVIDIA ", "GeForce "):
        name = name.replace(prefix, "")
    return name


def gb(mib):
    return f"{(mib or 0) / 1024:.1f}"

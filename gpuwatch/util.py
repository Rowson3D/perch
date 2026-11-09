"""Small Windows/OS helpers shared across the app."""
import ctypes
import os
import subprocess

IS_WIN = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW
NEW_GROUP = 0x00000200 if IS_WIN else 0          # CREATE_NEW_PROCESS_GROUP
DETACHED = 0x00000008 if IS_WIN else 0           # DETACHED_PROCESS

_mutex = None


def single_instance(name="Local\\GpuWatchWidget"):
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


def point_on_a_monitor(x, y):
    if not IS_WIN:
        return True
    try:
        from ctypes import wintypes
        return bool(ctypes.windll.user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), 0))
    except Exception:
        return True


def launch_detached(args):
    subprocess.Popen(args, creationflags=DETACHED | NEW_GROUP, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def short_name(name):
    for prefix in ("NVIDIA ", "GeForce "):
        name = name.replace(prefix, "")
    return name


def gb(mib):
    return f"{(mib or 0) / 1024:.1f}"

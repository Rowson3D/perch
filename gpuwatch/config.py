"""Settings file and the 'start with Windows' registry entry."""
import copy
import json
import os
import sys

from gpuwatch import APP_ID
from gpuwatch.util import IS_WIN

CONFIG_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_ID)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

DEFAULTS = {
    # detection
    "threshold": 50,          # VRAM % at or above which a GPU counts as IN USE
    "use_util": True,         # also IN USE when utilization averages >= util_threshold...
    "util_threshold": 40,
    "util_window": 60,        # ...over this many seconds
    "detect_held": True,      # VRAM held but GPU idle for held_minutes -> HELD
    "held_minutes": 10,
    # display
    "show_history": True,
    "history_minutes": 10,
    "refresh": 5,
    "topmost": True,
    "opacity": 0.94,
    "visible": True,
    "x": None,
    "y": None,
    # data
    "hosts": [],
    "watch": [],              # "hostid|gpukey" entries waiting for a 'GPU is free' notification
}


def load_config():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    for k, v in DEFAULTS.items():
        cfg.setdefault(k, copy.deepcopy(v))
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def launch_command():
    """Command line that starts this copy of the app."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    exe = sys.executable
    pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
    if os.path.exists(pyw):
        exe = pyw
    main = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__main__.py")
    return f'"{exe}" "{main}"'


def autostart_enabled():
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_ID)
        return True
    except OSError:
        return False


def set_autostart(on, command=None):
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_ID, 0, winreg.REG_SZ, command or launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_ID)
            except FileNotFoundError:
                pass

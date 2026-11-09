"""Settings file, card definitions and the 'start with Windows' registry entry.

Config v2 layout:
    {"version": 2, "cards": [card, ...]}
    card = {"id", "type", "title", "x", "y", "visible", "topmost", "opacity", "settings": {...type specific}}
"""

import copy
import json
import os
import sys
import uuid

from perch import APP_ID
from perch.util import IS_WIN

APPDATA = os.environ.get("APPDATA") or os.path.expanduser("~")
CONFIG_DIR = os.path.join(APPDATA, APP_ID)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(CONFIG_DIR, "state")  # per-card history (e.g. site uptime)
OLD_CONFIG_PATH = os.path.join(APPDATA, "GpuWatch", "config.json")  # from before the rename
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VERSION = 2

CARD_DEFAULTS = {"visible": True, "topmost": True, "opacity": 0.94, "x": None, "y": None}
WINDOW_KEYS = tuple(CARD_DEFAULTS)


def new_card(card_type, title, settings=None):
    return {
        "id": uuid.uuid4().hex[:8],
        "type": card_type,
        "title": title,
        **copy.deepcopy(CARD_DEFAULTS),
        "settings": settings or {},
    }


def migrate(cfg):
    """Bring any older config up to v2. v1 (GPU Watch) was a single flat GPU widget."""
    if cfg.get("version") == VERSION and isinstance(cfg.get("cards"), list):
        return cfg, False
    if "hosts" in cfg or "threshold" in cfg:
        card = new_card("gpus", "GPUs")
        for k in WINDOW_KEYS:
            if k in cfg:
                card[k] = cfg[k]
        card["settings"] = {k: v for k, v in cfg.items() if k not in WINDOW_KEYS and k != "version"}
        return {"version": VERSION, "cards": [card]}, True
    return {"version": VERSION, "cards": []}, True


def load_config():
    path = CONFIG_PATH
    if not os.path.exists(path) and os.path.exists(OLD_CONFIG_PATH):
        path = OLD_CONFIG_PATH  # first run after the rename: carry machines + settings over
    try:
        with open(path, encoding="utf-8") as f:
            cfg = json.load(f)
        if not isinstance(cfg, dict):
            cfg = {}
    except (OSError, ValueError):
        cfg = {}
    cfg, changed = migrate(cfg)
    for card in cfg["cards"]:
        for k, v in CARD_DEFAULTS.items():
            card.setdefault(k, copy.deepcopy(v))
        card.setdefault("settings", {})
    if changed or path == OLD_CONFIG_PATH:
        try:
            save_config(cfg)  # the new location/format becomes the source of truth
        except OSError:
            pass
    return cfg


def save_config(cfg):
    os.makedirs(CONFIG_DIR, exist_ok=True)
    tmp = CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG_PATH)


def load_state(card_id):
    try:
        with open(os.path.join(STATE_DIR, f"{card_id}.json"), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_state(card_id, data):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, f"{card_id}.json")
    with open(path + ".tmp", "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(path + ".tmp", path)


def delete_state(card_id):
    try:
        os.remove(os.path.join(STATE_DIR, f"{card_id}.json"))
    except OSError:
        pass


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

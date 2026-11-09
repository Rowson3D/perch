"""Per-user install / update / uninstall for the packaged GpuWatch.exe (no admin needed).

Running GpuWatch.exe from anywhere other than its install folder shows a small
setup window. Installing copies the exe to %LOCALAPPDATA%\\Programs\\GPU Watch,
adds Start-menu (and optional desktop) shortcuts, an Add/Remove Programs entry,
and the 'start with Windows' entry. `GpuWatch.exe --uninstall` reverses it.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from tkinter import ttk

from gpuwatch import APP_ID, APP_NAME, PUBLISHER, REPO_URL, __version__, icons
from gpuwatch import config as C
from gpuwatch import theme as T
from gpuwatch.components import Dialog, alert, confirm
from gpuwatch.util import IS_WIN, NEW_GROUP, NO_WINDOW, launch_detached

LOCAL = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
INSTALL_DIR = os.path.join(LOCAL, "Programs", APP_NAME)
EXE = os.path.join(INSTALL_DIR, "GpuWatch.exe")
UNINSTALL_KEY = "Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\" + APP_ID
START_MENU_LNK = os.path.join(
    os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", APP_NAME + ".lnk"
)
LEGACY_DIR = os.path.join(LOCAL, APP_ID)  # the original script-based install


def frozen():
    return bool(getattr(sys, "frozen", False))


def running_installed():
    return frozen() and os.path.normcase(os.path.abspath(sys.executable)) == os.path.normcase(EXE)


def should_offer_setup(args):
    return IS_WIN and frozen() and not running_installed() and "--portable" not in args


def installed_version():
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
            return winreg.QueryValueEx(k, "DisplayVersion")[0]
    except OSError:
        return None


def desktop_dir():
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
    return buf.value


def desktop_lnk():
    return os.path.join(desktop_dir(), APP_NAME + ".lnk")


def make_shortcut(lnk, target):
    def q(s):
        return "'" + s.replace("'", "''") + "'"

    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({q(lnk)});"
        f"$s.TargetPath={q(target)};$s.WorkingDirectory={q(os.path.dirname(target))};"
        f"$s.IconLocation={q(target + ',0')};$s.Description={q(APP_NAME)};$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        creationflags=NO_WINDOW,
        capture_output=True,
        timeout=60,
        check=True,
    )


def stop_running():
    """Close other running copies (including the old script version)."""
    import psutil

    skip = {os.getpid(), os.getppid()}  # PyInstaller one-file = bootloader parent + child
    victims = []
    for p in psutil.process_iter(["pid", "name", "cmdline"]):
        if p.pid in skip:
            continue
        try:
            name = (p.info["name"] or "").lower()
            cmd = " ".join(p.info["cmdline"] or []).lower()
        except Exception:
            continue
        dev_copy = name.startswith("python") and ("-m gpuwatch" in cmd or "gpuwatch\\__main__.py" in cmd)
        if name == "gpuwatch.exe" or "gpu_watch.pyw" in cmd or dev_copy:
            try:
                p.kill()
                victims.append(p)
            except Exception:
                pass
    psutil.wait_procs(victims, timeout=5)


def register_uninstall():
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as k:
        for name, val in {
            "DisplayName": APP_NAME,
            "DisplayVersion": __version__,
            "Publisher": PUBLISHER,
            "DisplayIcon": EXE,
            "InstallLocation": INSTALL_DIR,
            "URLInfoAbout": REPO_URL,
            "UninstallString": f'"{EXE}" --uninstall',
            "QuietUninstallString": f'"{EXE}" --uninstall --quiet',
        }.items():
            winreg.SetValueEx(k, name, 0, winreg.REG_SZ, val)
        winreg.SetValueEx(k, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "NoRepair", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "EstimatedSize", 0, winreg.REG_DWORD, os.path.getsize(EXE) // 1024)


def install(autostart=True, desktop=False):
    stop_running()
    os.makedirs(INSTALL_DIR, exist_ok=True)
    for attempt in range(40):
        try:
            shutil.copy2(sys.executable, EXE)
            break
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.25)
    make_shortcut(START_MENU_LNK, EXE)
    if desktop:
        make_shortcut(desktop_lnk(), EXE)
    register_uninstall()
    C.set_autostart(autostart, f'"{EXE}"')
    if os.path.exists(os.path.join(LEGACY_DIR, "gpu_watch.pyw")):
        shutil.rmtree(LEGACY_DIR, ignore_errors=True)


def uninstall(purge=False):
    import winreg

    stop_running()
    C.set_autostart(False)
    for lnk in (START_MENU_LNK, desktop_lnk()):
        try:
            os.remove(lnk)
        except OSError:
            pass
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    if purge:
        shutil.rmtree(C.CONFIG_DIR, ignore_errors=True)
    if running_installed():  # can't delete our own exe while running: let cmd do it after we exit
        subprocess.Popen(
            ["cmd", "/c", f'ping -n 3 127.0.0.1 >nul & rmdir /s /q "{INSTALL_DIR}"'],
            creationflags=NO_WINDOW | NEW_GROUP,
            close_fds=True,
        )
    else:
        shutil.rmtree(INSTALL_DIR, ignore_errors=True)


def _hidden_root():
    from gpuwatch import style

    root = tk.Tk()
    root.withdraw()
    style.apply(root)
    try:
        root._icon = icons.photo(64)
        root.iconphoto(True, root._icon)
    except Exception:
        pass
    return root


def run_uninstall(quiet=False):
    if quiet:
        uninstall()
        return
    root = _hidden_root()
    title = f"Uninstall {APP_NAME}"
    if confirm(root, title, f"Remove {APP_NAME} from this PC?", ok="Uninstall", danger=True):
        purge = confirm(
            root,
            title,
            "Also delete your saved machines and settings?",
            ok="Delete them",
            cancel="Keep them",
            danger=True,
        )
        uninstall(purge)
        alert(root, APP_NAME, f"{APP_NAME} has been removed.")
    root.destroy()


def _install_label(current):
    if not current:
        return "Install"
    return "Reinstall" if current == __version__ else "Update"


def run_setup_dialog():
    """Returns 'installed', 'portable' or 'cancel'."""
    result = {"v": "cancel"}
    d = Dialog(None, f"{APP_NAME} Setup", width=380)
    w = d.win
    try:
        logo = icons.photo(64)
        w.iconphoto(True, logo)
    except Exception:
        logo = None

    f = d.content
    head = ttk.Frame(f)
    head.pack(fill="x")
    if logo:
        ttk.Label(head, image=logo).pack(side="left", padx=(0, T.SECTION))
    titles = ttk.Frame(head)
    titles.pack(side="left", fill="x")
    ttk.Label(titles, text=APP_NAME, style="Display.TLabel").pack(anchor="w")
    ttk.Label(titles, text=f"Version {__version__}", style="Muted.TLabel").pack(anchor="w")
    ttk.Label(
        f,
        text="A small desktop widget that shows which GPUs on your machines are free or in use.",
        wraplength=380,
        justify="left",
    ).pack(anchor="w", pady=(T.SECTION, T.GAP))
    current = installed_version()
    if current:
        msg = (
            f"Version {current} is installed - this will update it."
            if current != __version__
            else "This version is already installed - this will reinstall it."
        )
        ttk.Label(f, text=msg, style="Info.TLabel").pack(anchor="w", pady=(0, T.GAP))

    v_auto = tk.BooleanVar(value=True)
    v_desk = tk.BooleanVar(value=os.path.exists(desktop_lnk()))
    ttk.Checkbutton(f, text="Start automatically when I sign in to Windows", variable=v_auto).pack(anchor="w")
    ttk.Checkbutton(f, text="Create a desktop shortcut", variable=v_desk).pack(anchor="w")
    ttk.Label(
        f, text=f"Installs to {INSTALL_DIR}  (just for you, no admin needed)", style="Hint.TLabel", wraplength=380
    ).pack(anchor="w", pady=(T.GAP, 0))
    status = d.footer_note("")

    def do_install():
        for b in buttons.values():
            b.state(["disabled"])
        status.config(text="Installing…")
        w.update()
        try:
            install(v_auto.get(), v_desk.get())
        except Exception as e:  # noqa: BLE001
            alert(w, "Install failed", str(e), "error")
            for b in buttons.values():
                b.state(["!disabled"])
            status.config(text="")
            return
        launch_detached([EXE, "--first-run"])
        result["v"] = "installed"
        d.close()

    def do_portable():
        result["v"] = "portable"
        d.close()

    buttons = d.buttons(("Just run it", do_portable, "secondary"), (_install_label(current), do_install, "primary"))
    w.bind("<Return>", lambda e: do_install())
    d.show(topmost=False)
    w.attributes("-topmost", True)
    w.after(300, lambda: w.attributes("-topmost", False))
    w.mainloop()
    return result["v"]

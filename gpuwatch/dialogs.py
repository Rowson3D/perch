"""Add/edit machine, manage machines, and settings windows."""
import tkinter as tk
import uuid
from tkinter import messagebox, ttk

from gpuwatch import APP_NAME, __version__
from gpuwatch.sources import AGENT_PORT, METHOD_KEYS, METHODS, SSH_PORT, fetch, gkey
from gpuwatch.util import clip, point_on_a_monitor

HINT = "#777777"


def toplevel(app, title):
    w = tk.Toplevel(app.root)
    w.title(title)
    w.resizable(False, False)
    w.attributes("-topmost", True)
    w.withdraw()

    def place():  # beside the widget, on whichever side has room
        w.update_idletasks()
        dw = w.winfo_reqwidth()
        rx, ry, rw = app.root.winfo_x(), app.root.winfo_y(), app.root.winfo_width()
        if app.root.state() == "withdrawn":
            rx, ry, rw = app.root.winfo_screenwidth() // 2 - dw // 2, 120, 0
        x = rx - dw - 12
        if not point_on_a_monitor(x + 10, ry + 10):
            x = rx + rw + 12
        if not point_on_a_monitor(x + dw - 10, ry + 10):
            x, ry = rx, ry + 40
        w.geometry(f"+{x}+{ry}")
        w.deiconify()
        w.focus_force()
    w.after_idle(place)
    return w


class HostDialog:
    def __init__(self, app, host=None):
        self.app, self.host = app, host
        self.found, self.vars = [], {}
        h = host or {}
        w = self.win = toplevel(app, "Edit machine" if host else "Add machine")
        f = ttk.Frame(w, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        self.v_addr = tk.StringVar(value=h.get("address", ""))
        self.v_method = tk.StringVar(value=METHODS[h.get("method", "agent")])
        self.v_port = tk.StringVar(value=str(h.get("port") or ""))
        self.v_user = tk.StringVar(value=h.get("user", ""))
        self.v_name = tk.StringVar(value=h.get("name", ""))

        def row(r, label, widget, hint=None):
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="ew", pady=3)
            if hint is not None:
                hint.grid(row=r, column=2, sticky="w", padx=(6, 0))

        cb = ttk.Combobox(f, textvariable=self.v_method, values=list(METHODS.values()), state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_method())
        row(0, "Connect via", cb)
        self.e_addr = ttk.Entry(f, textvariable=self.v_addr, width=26)
        row(1, "IP / hostname", self.e_addr)
        self.e_port = ttk.Entry(f, textvariable=self.v_port, width=8)
        self.port_hint = ttk.Label(f, foreground=HINT)
        row(2, "Port", self.e_port, self.port_hint)
        self.e_user = ttk.Entry(f, textvariable=self.v_user)
        row(3, "SSH user", self.e_user)
        row(4, "Display name", ttk.Entry(f, textvariable=self.v_name), ttk.Label(f, text="optional", foreground=HINT))
        self.help = ttk.Label(f, foreground=HINT, wraplength=330, justify="left")
        self.help.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        bar = ttk.Frame(f)
        bar.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        self.btn_find = ttk.Button(bar, text="Find GPUs", command=self.find)
        self.btn_find.pack(side="left")
        self.status = ttk.Label(bar, text="", wraplength=250)
        self.status.pack(side="left", padx=10)

        self.box = ttk.LabelFrame(f, text="GPUs to show", padding=8)
        self.box.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 8))
        ttk.Label(self.box, text="Click “Find GPUs” to list this machine's GPUs.", foreground=HINT).pack(anchor="w")

        btns = ttk.Frame(f)
        btns.grid(row=8, column=0, columnspan=3, sticky="e")
        ttk.Button(btns, text="Cancel", command=w.destroy).pack(side="right")
        ttk.Button(btns, text="Save" if host else "Add", command=self.save).pack(side="right", padx=6)

        if host:  # show the saved selection without needing to reconnect
            info = host.get("gpu_info", {})
            self.show_gpus([{"uuid": k, **info.get(k, {})} for k in host.get("gpus", [])])
        self.on_method()
        w.bind("<Return>", lambda e: self.find())
        w.bind("<Escape>", lambda e: w.destroy())

    def method(self):
        return METHOD_KEYS[self.v_method.get()]

    def on_method(self):
        m = self.method()
        self.e_addr.state(["disabled"] if m == "local" else ["!disabled"])
        self.e_port.state(["disabled"] if m == "local" else ["!disabled"])
        self.e_user.state(["!disabled"] if m == "ssh" else ["disabled"])
        self.port_hint.config(text={"agent": f"default {AGENT_PORT}", "ssh": f"default {SSH_PORT}"}.get(m, ""))
        self.help.config(text={
            "agent": "The machine must be running the GPU Watch agent (gpu-agent / gpu_agent.py).",
            "ssh": "Uses your SSH key - `ssh user@host` must work without a password prompt.",
            "local": "Reads the GPUs in this PC directly. Nothing else to install.",
        }[m])
        if m != "local":
            self.e_addr.focus_set()

    def collect(self):
        m = self.method()
        addr, port = self.v_addr.get().strip(), self.v_port.get().strip()
        if m == "local":
            addr, port = "localhost", ""
        elif not addr:
            messagebox.showwarning(APP_NAME, "Enter an IP address or hostname.", parent=self.win)
            return None
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            messagebox.showwarning(APP_NAME, "Port must be a number.", parent=self.win)
            return None
        return {"method": m, "address": addr, "port": int(port) if port else None,
                "user": self.v_user.get().strip() if m == "ssh" else ""}

    def find(self):
        conn = self.collect()
        if not conn:
            return
        self.btn_find.state(["disabled"])
        self.status.config(text="Connecting…", foreground="")

        def done(out):
            ok, val = out
            self.btn_find.state(["!disabled"])
            if not ok:
                hint = " Try “This PC” for your own computer." if conn["address"] in ("localhost", "127.0.0.1") else ""
                self.status.config(text="Couldn't connect: " + clip(val, 120) + hint, foreground="#c0392b")
                return
            if not val["gpus"]:
                self.status.config(text="Connected, but no NVIDIA GPUs were reported.", foreground="#c0392b")
                return
            self.status.config(text=f"Found {len(val['gpus'])} GPU(s).", foreground="#1e8449")
            if val.get("host") and not self.v_name.get().strip():
                self.v_name.set(val["host"])
            self.show_gpus(val["gpus"])

        self.app.run_bg(lambda: fetch(conn), done)

    def show_gpus(self, gpus):
        for c in self.box.winfo_children():
            c.destroy()
        prev = set(self.host["gpus"]) if self.host else None
        self.found, self.vars = gpus, {}
        for g in gpus:
            k = gkey(g)
            v = tk.BooleanVar(value=(k in prev) if prev is not None else True)
            size = f"  ·  {g['mem_total'] / 1024:.0f} GB" if g.get("mem_total") else ""
            ttk.Checkbutton(self.box, text=f"GPU {g.get('index', '?')}: {g.get('name', '?')}{size}",
                            variable=v).pack(anchor="w", pady=1)
            self.vars[k] = v

    def save(self):
        conn = self.collect()
        if not conn:
            return
        chosen = [g for g in self.found if self.vars[gkey(g)].get()]
        if not chosen:
            messagebox.showwarning(APP_NAME, "Click “Find GPUs”, then tick at least one GPU.", parent=self.win)
            return
        host = {
            "id": self.host["id"] if self.host else uuid.uuid4().hex[:10],
            "name": self.v_name.get().strip() or conn["address"],
            **conn,
            "gpus": [gkey(g) for g in chosen],
            "gpu_info": {gkey(g): {"index": g.get("index"), "name": g.get("name", ""),
                                   "mem_total": g.get("mem_total")} for g in chosen},
        }
        self.win.destroy()
        self.app.upsert_host(host)


class ManageDialog:
    def __init__(self, app):
        self.app = app
        w = self.win = toplevel(app, "Machines")
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        self.lb = tk.Listbox(f, width=54, height=9, activestyle="none", exportselection=False)
        self.lb.grid(row=0, column=0, rowspan=7, sticky="nsew", padx=(0, 10))
        self.lb.bind("<Double-1>", lambda e: self.edit())
        for i, (label, cmd) in enumerate([("Add…", app.open_host_dialog), ("Edit…", self.edit),
                                          ("Remove", self.remove), ("Move up", lambda: self.move(-1)),
                                          ("Move down", lambda: self.move(1)), ("Close", w.destroy)]):
            ttk.Button(f, text=label, command=cmd, width=12).grid(row=i, column=1, sticky="ew", pady=2)
        w.bind("<Escape>", lambda e: w.destroy())
        self.refresh()

    def refresh(self):
        self.lb.delete(0, "end")
        for h in self.app.cfg["hosts"]:
            n = len(h.get("gpus", []))
            self.lb.insert("end", f"{h['name']}   —   {h['address']}  ({h['method']}, {n} GPU{'s' * (n != 1)})")

    def sel(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def edit(self):
        i = self.sel()
        if i is not None:
            self.app.open_host_dialog(self.app.cfg["hosts"][i])

    def remove(self):
        i = self.sel()
        if i is None:
            return
        h = self.app.cfg["hosts"][i]
        if messagebox.askyesno(APP_NAME, f"Remove {h['name']}?", parent=self.win):
            del self.app.cfg["hosts"][i]
            self.app.results.pop(h["id"], None)
            self.app.hosts_changed()

    def move(self, d):
        i = self.sel()
        hosts = self.app.cfg["hosts"]
        if i is None or not 0 <= i + d < len(hosts):
            return
        hosts[i], hosts[i + d] = hosts[i + d], hosts[i]
        self.app.hosts_changed()
        self.lb.selection_set(i + d)


class SettingsDialog:
    def __init__(self, app):
        self.app = app
        c = app.cfg
        w = self.win = toplevel(app, f"{APP_NAME} settings")
        f = ttk.Frame(w, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(0, weight=1)

        self.v_thr = tk.IntVar(value=int(c["threshold"]))
        self.v_use_util = tk.BooleanVar(value=bool(c["use_util"]))
        self.v_util_thr = tk.StringVar(value=str(c["util_threshold"]))
        self.v_util_win = tk.StringVar(value=str(c["util_window"]))
        self.v_held = tk.BooleanVar(value=bool(c["detect_held"]))
        self.v_held_min = tk.StringVar(value=str(c["held_minutes"]))
        self.v_hist = tk.BooleanVar(value=bool(c["show_history"]))
        self.v_hist_min = tk.StringVar(value=str(c["history_minutes"]))
        self.v_op = tk.IntVar(value=int(round(float(c["opacity"]) * 100)))
        self.v_ref = tk.StringVar(value=str(c["refresh"]))

        def heading(r, text):
            ttk.Label(f, text=text, font=("Segoe UI Semibold", 10)).grid(row=r, column=0, columnspan=2,
                                                                         sticky="w", pady=(10, 4))

        def spin(parent, var, lo, hi, width=5):
            return ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=width)

        heading(0, "When is a GPU in use?")
        ttk.Label(f, text="VRAM used is at or above").grid(row=1, column=0, sticky="w")
        self.l_thr = ttk.Label(f, width=5, anchor="e")
        self.l_thr.grid(row=1, column=1, sticky="e")
        ttk.Scale(f, from_=1, to=100, variable=self.v_thr, length=330,
                  command=lambda v: self.live()).grid(row=2, column=0, columnspan=2, sticky="ew", pady=(2, 6))

        r3 = ttk.Frame(f)
        r3.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(r3, text="or GPU utilization averages ≥", variable=self.v_use_util).pack(side="left")
        spin(r3, self.v_util_thr, 1, 100, 4).pack(side="left", padx=4)
        ttk.Label(r3, text="% over").pack(side="left")
        spin(r3, self.v_util_win, 10, 900, 4).pack(side="left", padx=4)
        ttk.Label(r3, text="s").pack(side="left")

        r4 = ttk.Frame(f)
        r4.grid(row=4, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(r4, text="Mark HELD when VRAM is held but the GPU is idle for", variable=self.v_held).pack(side="left")
        spin(r4, self.v_held_min, 1, 240, 4).pack(side="left", padx=4)
        ttk.Label(r4, text="min").pack(side="left")
        ttk.Label(f, text="A small dead zone stops GPUs flickering between states near a threshold.",
                  foreground=HINT).grid(row=5, column=0, columnspan=2, sticky="w", pady=(2, 0))

        heading(6, "Display")
        r7 = ttk.Frame(f)
        r7.grid(row=7, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Checkbutton(r7, text="Show history graph of the last", variable=self.v_hist).pack(side="left")
        spin(r7, self.v_hist_min, 2, 240, 4).pack(side="left", padx=4)
        ttk.Label(r7, text="min").pack(side="left")
        r8 = ttk.Frame(f)
        r8.grid(row=8, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(r8, text="Refresh every").pack(side="left")
        spin(r8, self.v_ref, 2, 600, 4).pack(side="left", padx=4)
        ttk.Label(r8, text="seconds").pack(side="left")
        ttk.Label(f, text="Opacity").grid(row=9, column=0, sticky="w", pady=(6, 0))
        self.l_op = ttk.Label(f, width=5, anchor="e")
        self.l_op.grid(row=9, column=1, sticky="e", pady=(6, 0))
        ttk.Scale(f, from_=30, to=100, variable=self.v_op, length=330,
                  command=lambda v: self.live()).grid(row=10, column=0, columnspan=2, sticky="ew", pady=(2, 6))

        foot = ttk.Frame(f)
        foot.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        ttk.Label(foot, text=f"{APP_NAME} {__version__}", foreground=HINT).pack(side="left")
        ttk.Button(foot, text="Done", command=self.close).pack(side="right")
        w.protocol("WM_DELETE_WINDOW", self.close)
        w.bind("<Return>", lambda e: self.close())
        self.live()

    def live(self):
        thr, op = int(float(self.v_thr.get())), int(float(self.v_op.get()))
        self.l_thr.config(text=f"{thr}%")
        self.l_op.config(text=f"{op}%")
        self.app.cfg["threshold"] = thr
        self.app.cfg["opacity"] = op / 100
        self.app.root.attributes("-alpha", op / 100)
        self.app.reevaluate()
        self.app.update_view()

    @staticmethod
    def _int(var, lo, hi, default):
        try:
            return max(lo, min(hi, int(float(var.get()))))
        except (ValueError, tk.TclError):
            return default

    def close(self):
        c = self.app.cfg
        before = (c["show_history"],)
        c["use_util"] = bool(self.v_use_util.get())
        c["util_threshold"] = self._int(self.v_util_thr, 1, 100, c["util_threshold"])
        c["util_window"] = self._int(self.v_util_win, 10, 900, c["util_window"])
        c["detect_held"] = bool(self.v_held.get())
        c["held_minutes"] = self._int(self.v_held_min, 1, 240, c["held_minutes"])
        c["show_history"] = bool(self.v_hist.get())
        c["history_minutes"] = self._int(self.v_hist_min, 2, 240, c["history_minutes"])
        c["refresh"] = self._int(self.v_ref, 2, 600, c["refresh"])
        self.win.destroy()
        self.app.settings_changed(rerender=before != (c["show_history"],))
        self.app.refresh_now()

"""Add/edit machine, manage machines, and settings windows - all built on components.Dialog."""

import tkinter as tk
import uuid
from tkinter import ttk

from perch import APP_NAME, __version__
from perch import theme as T
from perch.components import Dialog, alert, confirm
from perch.sources import AGENT_PORT, METHOD_KEYS, METHODS, SSH_PORT, fetch, gkey
from perch.util import clip

METHOD_HELP = {
    "agent": "The machine must be running the Perch agent (perch-agent / perch_agent.py).",
    "ssh": "Uses your SSH key - `ssh user@host` must already work without a password prompt.",
    "local": "Reads the GPUs in this PC directly. Nothing else to install.",
}


def form_row(parent, row, label, widget, hint=None):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
    widget.grid(row=row, column=1, sticky="ew", pady=4)
    if hint is not None:
        hint.grid(row=row, column=2, sticky="w", padx=(T.GAP, 0))


def spin(parent, var, lo, hi, width=4):
    return ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=width)


class HostDialog(Dialog):
    def __init__(self, app, host=None):
        title = "Edit machine" if host else "Add machine"
        super().__init__(
            app.root,
            title,
            heading="Edit machine" if host else "Add a machine",
            subtitle="Choose how to reach it, find its GPUs, then pick the ones to show.",
        )
        self.app, self.host = app, host
        self.found, self.vars = [], {}
        h = host or {}
        f = self.content
        f.columnconfigure(1, weight=1)

        self.v_addr = tk.StringVar(value=h.get("address", ""))
        self.v_method = tk.StringVar(value=METHODS[h.get("method", "agent")])
        self.v_port = tk.StringVar(value=str(h.get("port") or ""))
        self.v_user = tk.StringVar(value=h.get("user", ""))
        self.v_name = tk.StringVar(value=h.get("name", ""))

        cb = ttk.Combobox(f, textvariable=self.v_method, values=list(METHODS.values()), state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_method())
        form_row(f, 0, "Connect via", cb)
        self.e_addr = ttk.Entry(f, textvariable=self.v_addr, width=28)
        form_row(f, 1, "IP / hostname", self.e_addr)
        self.e_port = ttk.Entry(f, textvariable=self.v_port, width=8)
        self.port_hint = ttk.Label(f, style="Hint.TLabel")
        form_row(f, 2, "Port", self.e_port, self.port_hint)
        self.e_user = ttk.Entry(f, textvariable=self.v_user)
        form_row(f, 3, "SSH user", self.e_user)
        form_row(
            f,
            4,
            "Display name",
            ttk.Entry(f, textvariable=self.v_name),
            ttk.Label(f, text="optional", style="Hint.TLabel"),
        )
        self.help = ttk.Label(f, style="Hint.TLabel", wraplength=360, justify="left")
        self.help.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        find = ttk.Frame(f)
        find.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(T.SECTION, 0))
        self.btn_find = ttk.Button(find, text="Find GPUs", command=self.find)
        self.btn_find.pack(side="left")
        self.status = ttk.Label(find, text="", style="Muted.TLabel", wraplength=260, justify="left")
        self.status.pack(side="left", padx=(12, 0))

        ttk.Label(f, text="GPUs to show", style="Section.TLabel").grid(
            row=7, column=0, columnspan=3, sticky="w", pady=(T.SECTION, 4)
        )
        self.box = ttk.Frame(f, style="Card.TFrame", padding=10)
        self.box.grid(row=8, column=0, columnspan=3, sticky="ew")
        ttk.Label(
            self.box, text="Click “Find GPUs” to list this machine's GPUs.", style="Card.TLabel", foreground=T.MUTED
        ).pack(anchor="w")

        self.buttons(("Cancel", self.close, "secondary"), ("Save" if host else "Add", self.save, "primary"))
        if host:  # show the saved selection without needing to reconnect
            info = host.get("gpu_info", {})
            self.show_gpus([{"uuid": k, **info.get(k, {})} for k in host.get("gpus", [])])
        self.on_method()
        self.win.bind("<Return>", lambda e: self.find())
        self.show(near=app.root)

    def method(self):
        return METHOD_KEYS[self.v_method.get()]

    def on_method(self):
        m = self.method()
        self.e_addr.state(["disabled"] if m == "local" else ["!disabled"])
        self.e_port.state(["disabled"] if m == "local" else ["!disabled"])
        self.e_user.state(["!disabled"] if m == "ssh" else ["disabled"])
        self.port_hint.config(text={"agent": f"default {AGENT_PORT}", "ssh": f"default {SSH_PORT}"}.get(m, ""))
        self.help.config(text=METHOD_HELP[m])
        if m != "local":
            self.e_addr.focus_set()

    def set_status(self, text, kind="Muted"):
        self.status.config(text=text, style=f"{kind}.TLabel")

    def collect(self):
        m = self.method()
        addr, port = self.v_addr.get().strip(), self.v_port.get().strip()
        if m == "local":
            addr, port = "localhost", ""
        elif not addr:
            alert(self.win, "Missing address", "Enter an IP address or hostname.", "warning")
            return None
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            alert(self.win, "Invalid port", "The port must be a number between 1 and 65535.", "warning")
            return None
        return {
            "method": m,
            "address": addr,
            "port": int(port) if port else None,
            "user": self.v_user.get().strip() if m == "ssh" else "",
        }

    def find(self):
        conn = self.collect()
        if not conn:
            return
        self.btn_find.state(["disabled"])
        self.set_status("Connecting…")

        def done(out):
            ok, val = out
            self.btn_find.state(["!disabled"])
            if not ok:
                local = conn["address"] in ("localhost", "127.0.0.1")
                hint = " Try “This PC” for your own computer." if local else ""
                self.set_status("Couldn't connect: " + clip(val, 120) + hint, "Error")
                return
            if not val["gpus"]:
                self.set_status("Connected, but no NVIDIA GPUs were reported.", "Error")
                return
            self.set_status(f"Found {len(val['gpus'])} GPU(s).", "Success")
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
            ttk.Checkbutton(
                self.box,
                text=f"GPU {g.get('index', '?')}: {g.get('name', '?')}{size}",
                variable=v,
                style="Card.TCheckbutton",
            ).pack(anchor="w", pady=1)
            self.vars[k] = v

    def save(self):
        conn = self.collect()
        if not conn:
            return
        chosen = [g for g in self.found if self.vars[gkey(g)].get()]
        if not chosen:
            alert(self.win, "No GPUs selected", "Click “Find GPUs”, then tick at least one GPU.", "warning")
            return
        host = {
            "id": self.host["id"] if self.host else uuid.uuid4().hex[:10],
            "name": self.v_name.get().strip() or conn["address"],
            **conn,
            "gpus": [gkey(g) for g in chosen],
            "gpu_info": {
                gkey(g): {"index": g.get("index"), "name": g.get("name", ""), "mem_total": g.get("mem_total")}
                for g in chosen
            },
        }
        self.close()
        self.app.upsert_host(host)


class ManageDialog(Dialog):
    def __init__(self, app):
        super().__init__(
            app.root,
            "Machines",
            heading="Machines",
            subtitle="Double-click a machine to edit it. Order here is the order on the widget.",
        )
        self.app = app
        f = self.content
        self.lb = tk.Listbox(f, width=52, height=9, activestyle="none", exportselection=False)
        self.lb.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(0, 12))
        self.lb.bind("<Double-1>", lambda e: self.edit())
        actions = [
            ("Add…", app.open_host_dialog),
            ("Edit…", self.edit),
            ("Remove", self.remove),
            ("Move up", lambda: self.move(-1)),
            ("Move down", lambda: self.move(1)),
        ]
        for i, (label, cmd) in enumerate(actions):
            ttk.Button(f, text=label, command=cmd, width=11).grid(row=i, column=1, sticky="ew", pady=(0, 6))
        self.buttons(("Done", self.close, "primary"))
        self.refresh()
        self.show(near=app.root)

    def refresh(self):
        self.lb.delete(0, "end")
        for h in self.app.cfg["hosts"]:
            n = len(h.get("gpus", []))
            self.lb.insert("end", f"  {h['name']}   —   {h['address']}  ({h['method']}, {n} GPU{'s' * (n != 1)})")

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
        if confirm(self.win, "Remove machine", f"Remove {h['name']} from the widget?", ok="Remove", danger=True):
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


class SettingsDialog(Dialog):
    def __init__(self, app):
        super().__init__(app.root, f"{APP_NAME} settings", heading="Settings")
        self.app = app
        c = app.cfg
        f = self.content
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

        def section(r, text, first=False):
            ttk.Label(f, text=text, style="Section.TLabel").grid(
                row=r, column=0, columnspan=2, sticky="w", pady=(0 if first else T.SECTION, 6)
            )

        def line(r):
            fr = ttk.Frame(f)
            fr.grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
            return fr

        section(0, "WHEN IS A GPU IN USE?", first=True)
        ttk.Label(f, text="VRAM used is at or above").grid(row=1, column=0, sticky="w")
        self.l_thr = ttk.Label(f, width=5, anchor="e", style="Info.TLabel")
        self.l_thr.grid(row=1, column=1, sticky="e")
        ttk.Scale(f, from_=1, to=100, variable=self.v_thr, length=360, command=lambda v: self.live()).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(4, 8)
        )
        r = line(3)
        ttk.Checkbutton(r, text="or GPU utilization averages ≥", variable=self.v_use_util).pack(side="left")
        spin(r, self.v_util_thr, 1, 100).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="% over").pack(side="left")
        spin(r, self.v_util_win, 10, 900).pack(side="left", padx=4)
        ttk.Label(r, text="s").pack(side="left")
        r = line(4)
        ttk.Checkbutton(r, text="Mark HELD when VRAM is held but idle for", variable=self.v_held).pack(side="left")
        spin(r, self.v_held_min, 1, 240).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="min").pack(side="left")
        ttk.Label(
            f, text="A small dead zone keeps GPUs from flickering between states near a threshold.", style="Hint.TLabel"
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(4, 0))

        section(6, "DISPLAY")
        r = line(7)
        ttk.Checkbutton(r, text="Show a history graph of the last", variable=self.v_hist).pack(side="left")
        spin(r, self.v_hist_min, 2, 240).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="min").pack(side="left")
        r = line(8)
        ttk.Label(r, text="Refresh every").pack(side="left")
        spin(r, self.v_ref, 2, 600).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="seconds").pack(side="left")
        ttk.Label(f, text="Opacity").grid(row=9, column=0, sticky="w", pady=(8, 0))
        self.l_op = ttk.Label(f, width=5, anchor="e", style="Info.TLabel")
        self.l_op.grid(row=9, column=1, sticky="e", pady=(8, 0))
        ttk.Scale(f, from_=30, to=100, variable=self.v_op, length=360, command=lambda v: self.live()).grid(
            row=10, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )

        self.footer_note(f"{APP_NAME} {__version__}")
        self.buttons(("Done", self.done, "primary"))
        self.win.protocol("WM_DELETE_WINDOW", self.done)
        self.win.bind("<Escape>", lambda e: self.done())
        self.win.bind("<Return>", lambda e: self.done())
        self.live()
        self.show(near=app.root)

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

    def done(self):
        c = self.app.cfg
        history_was = c["show_history"]
        c["use_util"] = bool(self.v_use_util.get())
        c["util_threshold"] = self._int(self.v_util_thr, 1, 100, c["util_threshold"])
        c["util_window"] = self._int(self.v_util_win, 10, 900, c["util_window"])
        c["detect_held"] = bool(self.v_held.get())
        c["held_minutes"] = self._int(self.v_held_min, 1, 240, c["held_minutes"])
        c["show_history"] = bool(self.v_hist.get())
        c["history_minutes"] = self._int(self.v_hist_min, 2, 240, c["history_minutes"])
        c["refresh"] = self._int(self.v_ref, 2, 600, c["refresh"])
        self.close()
        self.app.settings_changed(rerender=history_was != c["show_history"])
        self.app.refresh_now()

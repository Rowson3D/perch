"""Windows for the shared machine list: add/edit a machine, the Machines list, and a machine picker."""

import tkinter as tk
from tkinter import ttk

from perch import machines as M
from perch.components import Dialog, ListManager, alert, confirm, form_row
from perch.sources import AGENT_PORT, SSH_PORT
from perch.util import clip

REMOTE_METHODS = {"ssh": "SSH (key login)", "agent": "Perch agent (HTTP)"}
REMOTE_KEYS = {v: k for k, v in REMOTE_METHODS.items()}
HELP = {
    "ssh": "Uses your SSH key. `ssh user@host` must already work without a password prompt.",
    "agent": "The machine must be running the Perch agent (perch-agent.exe or perch_agent.py).",
}


class MachineDialog(Dialog):
    """Add or edit a machine in the shared list. on_saved(machine) is called after saving."""

    def __init__(self, app, machine=None, on_saved=None, near=None):
        super().__init__(
            app.root,
            "Edit machine" if machine else "Add machine",
            heading="Edit machine" if machine else "Add a machine",
            subtitle="Machines you add here can be used by any card.",
        )
        self.app, self.machine, self.on_saved = app, machine, on_saved
        m = machine or {}
        f = self.content
        f.columnconfigure(1, weight=1)
        self.v_method = tk.StringVar(value=REMOTE_METHODS.get(m.get("method", "ssh"), REMOTE_METHODS["ssh"]))
        self.v_addr = tk.StringVar(value=m.get("address", ""))
        self.v_port = tk.StringVar(value=str(m.get("port") or ""))
        self.v_user = tk.StringVar(value=m.get("user", ""))
        self.v_name = tk.StringVar(value=m.get("name", ""))

        cb = ttk.Combobox(f, textvariable=self.v_method, values=list(REMOTE_METHODS.values()), state="readonly")
        cb.bind("<<ComboboxSelected>>", lambda e: self.on_method())
        form_row(f, 0, "Connect via", cb)
        self.e_addr = ttk.Entry(f, textvariable=self.v_addr, width=28)
        form_row(f, 1, "IP / hostname", self.e_addr)
        self.port_hint = ttk.Label(f, style="Hint.TLabel")
        form_row(f, 2, "Port", ttk.Entry(f, textvariable=self.v_port, width=8), self.port_hint)
        self.e_user = ttk.Entry(f, textvariable=self.v_user)
        form_row(f, 3, "SSH user", self.e_user)
        form_row(
            f, 4, "Name", ttk.Entry(f, textvariable=self.v_name), ttk.Label(f, text="optional", style="Hint.TLabel")
        )
        self.help = ttk.Label(f, style="Hint.TLabel", wraplength=360, justify="left")
        self.help.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        test = ttk.Frame(f)
        test.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self.btn_test = ttk.Button(test, text="Test connection", command=self.test)
        self.btn_test.pack(side="left")
        self.status = ttk.Label(test, text="", style="Muted.TLabel", wraplength=240, justify="left")
        self.status.pack(side="left", padx=(12, 0))

        self.buttons(("Cancel", self.close, "secondary"), ("Save" if machine else "Add", self.save, "primary"))
        self.win.bind("<Return>", lambda e: self.save())
        self.on_method()
        self.show(near=near)
        self.e_addr.focus_set()

    def method(self):
        return REMOTE_KEYS[self.v_method.get()]

    def on_method(self):
        m = self.method()
        self.e_user.state(["!disabled"] if m == "ssh" else ["disabled"])
        self.port_hint.config(text=f"default {SSH_PORT if m == 'ssh' else AGENT_PORT}")
        self.help.config(text=HELP[m])

    def collect(self):
        addr, port = self.v_addr.get().strip(), self.v_port.get().strip()
        if not addr:
            alert(self.win, "Missing address", "Enter an IP address or hostname.", "warning")
            return None
        if port and not (port.isdigit() and 0 < int(port) < 65536):
            alert(self.win, "Invalid port", "The port must be a number between 1 and 65535.", "warning")
            return None
        m = self.method()
        return {
            "method": m,
            "address": addr,
            "port": int(port) if port else None,
            "user": self.v_user.get().strip() if m == "ssh" else "",
            "name": self.v_name.get().strip() or addr,
        }

    def test(self):
        data = self.collect()
        if not data:
            return
        probe = {"id": "test", **data}
        M._os_cache.pop("test", None)
        self.btn_test.state(["disabled"])
        self.status.config(text="Connecting…", style="Muted.TLabel")

        def done(out):
            self.btn_test.state(["!disabled"])
            ok, val = out
            if ok:
                self.status.config(text=f"Connected · {len(val)} processes running", style="Success.TLabel")
            else:
                self.status.config(text="Couldn't connect: " + clip(val, 110), style="Error.TLabel")

        self.app.run_bg(lambda: M.list_processes(probe), done)

    def save(self):
        data = self.collect()
        if not data:
            return
        machines = self.app.cfg.setdefault("machines", [])
        if self.machine:
            self.machine.update(data)
            saved = self.machine
            M._os_cache.pop(saved["id"], None)
        else:
            saved = M.new_machine(**data)
            machines.append(saved)
        self.app.save()
        self.close()
        self.app.machines_changed()
        if self.on_saved:
            self.on_saved(saved)


def open_machines(app):
    def remove(i, parent):
        m = app.cfg["machines"][i]
        if confirm(
            parent,
            "Remove machine",
            f"Remove {m['name']}? Cards that use it will show it as missing.",
            ok="Remove",
            danger=True,
        ):
            del app.cfg["machines"][i]
            app.save()
            app.machines_changed()

    def move(i, d):
        ms = app.cfg["machines"]
        ms[i], ms[i + d] = ms[i + d], ms[i]
        app.save()
        app.machines_changed()

    app.open_dialog(
        "machines",
        lambda: ListManager(
            app.root,
            "Machines",
            "Machines any card can use. This PC is always available and isn't listed.",
            lambda: app.cfg.setdefault("machines", []),
            lambda m: f"{m['name']}   —   {M.describe(m)}",
            lambda: MachineDialog(app),
            lambda i: MachineDialog(app, app.cfg["machines"][i]),
            remove,
            move,
        ),
    )


class MachinePicker(ttk.Frame):
    """A machine dropdown plus an 'Add machine…' button. .value() is the chosen machine id (or None)."""

    def __init__(self, parent, app, allow=("local", "ssh", "agent"), on_change=None, near=None):
        super().__init__(parent)
        self.app, self.allow, self.on_change, self.near = app, allow, on_change, near
        self.var = tk.StringVar()
        self.cb = ttk.Combobox(self, textvariable=self.var, state="readonly", width=30)
        self.cb.pack(side="left", fill="x", expand=True)
        self.cb.bind("<<ComboboxSelected>>", lambda e: self.on_change and self.on_change(self.value()))
        ttk.Button(self, text="Add machine…", command=self.add).pack(side="left", padx=(8, 0))
        self.reload()

    def reload(self, select=None):
        self.options = [m for m in M.all_machines(self.app.cfg) if m["method"] in self.allow]
        self.labels = [f"{m['name']}  ({M.describe(m)})" for m in self.options]
        self.cb.config(values=self.labels)
        current = select or self.value()
        idx = next((i for i, m in enumerate(self.options) if m["id"] == current), 0 if self.options else None)
        self.var.set(self.labels[idx] if idx is not None else "")

    def value(self):
        label = self.var.get()
        return next((m["id"] for m, lab in zip(self.options, self.labels, strict=True) if lab == label), None)

    def add(self):
        def saved(m):
            self.reload(select=m["id"])
            if self.on_change:
                self.on_change(m["id"])

        MachineDialog(self.app, on_saved=saved, near=self.near)

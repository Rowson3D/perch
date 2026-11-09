"""Docker card: your containers on each machine - running or not, healthy or not, and what they're using."""

import tkinter as tk
from tkinter import ttk

from perch import machines as M
from perch import theme as T
from perch.cards.base import Card
from perch.components import Dialog, PopupMenu, confirm, int_of, section, spin
from perch.machines_ui import MachinePicker, open_machines
from perch.util import clip
from perch.watch import BAD, OFF, OK, WARN, condition, is_problem, short_status

COLOR = {OK: T.GREEN, WARN: T.AMBER, BAD: T.RED, OFF: T.GREY}


def descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += descendants(c)
    return out


class DockerCard(Card):
    TYPE = "docker"
    NAME = "Docker"
    DESCRIPTION = "Shows the containers on your machines, whether they're up and healthy, and warns you when one stops."
    ADD_LABEL = "Add a Docker machine"
    DEFAULTS = {"hosts": [], "interval": 30, "show_stopped": True, "hidden": [], "compact": False}

    def __init__(self, app, conf, animate=False):
        self.results, self.inflight, self.rows, self.headers, self.prev = {}, set(), {}, {}, {}
        self.poll_job = None
        super().__init__(app, conf, animate)

    @property
    def hosts(self):
        return self.s["hosts"]

    def machine(self, mid):
        return M.get(self.app.cfg, mid)

    # ------------------------------------------------------------ polling
    def start(self):
        self.poll()

    def poll(self):
        for mid in self.hosts:
            m = self.machine(mid)
            if m is None:
                self.results[mid] = {"ok": False, "error": "machine was removed"}
            elif mid not in self.inflight:
                self.inflight.add(mid)
                self.app.pool.submit(self._fetch, dict(m))
        self.poll_job = self.after(max(10, int(self.s["interval"])) * 1000, self.poll)

    def refresh_now(self):
        if self.poll_job:
            self.cancel(self.poll_job)
        self.poll()

    def _fetch(self, m):
        try:
            out = {"ok": True, "containers": M.list_containers(m)}
        except Exception as e:  # noqa: BLE001
            out = {"ok": False, "error": str(e) or type(e).__name__}
        self.app.call_soon(self.on_result, m["id"], out)

    def on_result(self, mid, out):
        if self.dead:
            return
        self.inflight.discard(mid)
        old_names = {c["name"] for c in self.results.get(mid, {}).get("containers", [])}
        self.results[mid] = out
        if out["ok"]:
            self._notify_changes(mid, out["containers"])
            if {c["name"] for c in out["containers"]} != old_names:
                self.render()
                return
        self.update_view()

    def _notify_changes(self, mid, containers):
        m = self.machine(mid)
        where = m["name"] if m else "a machine"
        first = mid not in self.prev
        before = self.prev.get(mid, {})
        self.prev[mid] = {c["name"]: c for c in containers}
        if first:
            return  # don't alert about how things already were when Perch started
        for c in containers:
            if f"{mid}|{c['name']}" in self.s["hidden"]:
                continue
            was = before.get(c["name"])
            if not was:
                continue
            if was["state"] == "running" and c["state"] in ("exited", "dead"):
                self.notify(f"Container stopped: {c['name']}", f"On {where}: {c['status']}")
            elif c["state"] == "restarting" and was["state"] != "restarting":
                self.notify(f"Container restarting: {c['name']}", f"On {where}. It may be crashing on start.")
            elif c.get("health") == "unhealthy" and was.get("health") != "unhealthy":
                self.notify(f"Container unhealthy: {c['name']}", f"On {where}. Its health check is failing.")
            elif is_problem(was) and condition(c) == OK:
                self.notify(f"Container back up: {c['name']}", f"On {where}.")

    # ------------------------------------------------------------ rendering
    def visible_containers(self, mid):
        res = self.results.get(mid)
        if not res or not res["ok"]:
            return []
        out = []
        for c in res["containers"]:
            if f"{mid}|{c['name']}" in self.s["hidden"]:
                continue
            if not self.s["show_stopped"] and c["state"] not in ("running", "restarting"):
                continue
            out.append(c)
        return sorted(out, key=lambda c: (c["state"] != "running", c["name"].lower()))

    def render(self):
        self.app.tip.hide()
        for w in self.body.winfo_children():
            w.destroy()
        self.rows, self.headers = {}, {}
        if not self.hosts:
            tk.Label(
                self.body,
                text="No machines yet.\nClick  +  to add one that runs Docker.",
                bg=T.BG,
                fg=T.MUTED,
                font=T.F,
                justify="left",
                width=38,
                anchor="w",
            ).pack(anchor="w", pady=6)
        for mid in self.hosts:
            m = self.machine(mid)
            hf = tk.Frame(self.body, bg=T.BG)
            hf.pack(fill="x", pady=(6, 1))
            tk.Label(hf, text=clip(m["name"] if m else "missing machine", 30), bg=T.BG, fg=T.FG, font=T.FB).pack(
                side="left"
            )
            st = tk.Label(hf, text="connecting…", bg=T.BG, fg=T.MUTED, font=T.FS)
            st.pack(side="right")
            self.headers[mid] = st
            for c in self.visible_containers(mid):
                self.rows[(mid, c["name"])] = self._make_row(mid, c["name"])
        self.update_view()

    def _make_row(self, mid, name):
        compact = self.s.get("compact")
        card = tk.Frame(self.body, bg=T.ROW, padx=8, pady=4 if compact else 5)
        card.pack(fill="x", pady=2)
        top = tk.Frame(card, bg=T.ROW)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=10, height=10, bg=T.ROW, highlightthickness=0)
        dot_id = dot.create_oval(1, 1, 9, 9, fill=T.GREY, outline="")
        dot.pack(side="left", pady=(2, 0))
        tk.Label(top, text=clip(name, 26), bg=T.ROW, fg=T.FG, font=T.F).pack(side="left", padx=(6, 0))
        right = tk.Label(top, text="", bg=T.ROW, fg=T.MUTED, font=T.FB)
        right.pack(side="right")
        detail = None
        if not compact:
            detail = tk.Label(card, text="", bg=T.ROW, fg=T.MUTED, font=T.FS, anchor="w")
            detail.pack(fill="x", pady=(2, 0))
        key = (mid, name)
        for w in descendants(card):
            w.bind("<Enter>", lambda e, key=key, card=card: self._hover(key, card), add="+")
            w.bind("<Leave>", lambda e: self.app.tip.hide_soon(), add="+")
            w.bind("<Button-3>", lambda e, key=key: self.row_menu(e, key))
        return {"card": card, "dot": dot, "dot_id": dot_id, "right": right, "detail": detail}

    def container(self, mid, name):
        res = self.results.get(mid)
        if res and res["ok"]:
            return next((c for c in res["containers"] if c["name"] == name), None)
        return None

    def update_view(self):
        for mid in self.hosts:
            res = self.results.get(mid)
            st = self.headers.get(mid)
            if st:
                if res is None:
                    st.config(text="connecting…", fg=T.MUTED)
                elif not res["ok"]:
                    st.config(text=clip(res["error"], 40), fg=T.RED)
                else:
                    running = sum(c["state"] == "running" for c in res["containers"])
                    st.config(text=f"{running}/{len(res['containers'])} running", fg=T.GREY)
        for (mid, name), row in self.rows.items():
            c = self.container(mid, name)
            if not c:
                continue
            color = COLOR[condition(c)]
            row["dot"].itemconfig(row["dot_id"], fill=color)
            row["right"].config(text=short_status(c), fg=color if condition(c) != OK else T.MUTED)
            if row["detail"] is not None:
                bits = [clip(c["image"].split("@")[0], 30)]
                if c.get("cpu") is not None and c["state"] == "running":
                    bits.append(f"{c['cpu']:.1f}% CPU")
                if c.get("mem") and c["state"] == "running":
                    bits.append(c["mem"])
                row["detail"].config(text=clip("  ·  ".join(bits), 56))
        level, text = self.status()
        self.summary.config(text=text)
        self.app.cards_changed()
        if self.app.tip.key and self.app.tip.key[0] == self.id:
            self.app.tip.refresh()

    def status(self):
        if not self.hosts:
            return None, ""
        shown, unreachable = [], False
        for mid in self.hosts:
            res = self.results.get(mid)
            if res and not res["ok"]:
                unreachable = True
            shown += self.visible_containers(mid)
        if not shown:
            return ("bad" if unreachable else None), ""
        running = sum(c["state"] == "running" for c in shown)
        conds = {condition(c) for c in shown}
        level = "bad" if BAD in conds or unreachable else "warn" if WARN in conds else "ok"
        return level, f"{running}/{len(shown)} running"

    def _hover(self, key, row_widget):
        self.app.tip.show((self.id, key), self.win, row_widget, lambda add: self._describe(key, add))

    def _describe(self, key, add):
        c = self.container(*key)
        if not c:
            return False
        m = self.machine(key[0])
        cond = condition(c)
        add(c["name"], font=T.FT)
        add(c["image"], T.MUTED, T.FS)
        add(f"{short_status(c).upper()}  ·  {c['status']}", COLOR[cond] if cond != OFF else T.MUTED, T.FB, (8, 0))
        lines = [f"Machine  {m['name'] if m else 'missing'}"]
        if c["state"] == "running":
            if c.get("cpu") is not None:
                lines.append(f"CPU      {c['cpu']:.1f}%")
            if c.get("mem"):
                pct = f" ({c['mem_pct']:.1f}%)" if c.get("mem_pct") is not None else ""
                lines.append(f"Memory   {c['mem']}{pct}")
        if c.get("health"):
            lines.append(f"Health   {c['health']}")
        if c.get("ports"):
            lines.append(f"Ports    {clip(c['ports'], 60)}")
        lines.append(f"ID       {c['id']}")
        add("\n".join(lines), T.FG, T.MONO, (6, 0))
        add("Right-click: hide this container", T.GREY, T.FS, (8, 0))

    # ------------------------------------------------------------ actions
    def menu_items(self, m):
        m.command("Add a Docker machine…", self.add_item)
        m.check("Show stopped containers", self.s["show_stopped"], self.toggle_stopped)
        m.command("Show hidden containers", self.unhide_all if self.s["hidden"] else None)
        m.command("Machines…", lambda: open_machines(self.app))
        m.command("Check now", self.refresh_now)

    def row_menu(self, e, key):
        self.app.tip.hide()
        m = PopupMenu(self.app.root)
        m.command("Hide this container", lambda: self.hide_container(key))
        m.command("Remove this machine from the card…", lambda: self.remove_host(key[0]))
        m.separator()
        self.menu_items(m)
        self.common_menu(m)
        m.popup(e.x_root, e.y_root)
        return "break"

    def hide_container(self, key):
        self.s["hidden"].append(f"{key[0]}|{key[1]}")
        self.app.save()
        self.render()

    def unhide_all(self):
        self.s["hidden"] = []
        self.app.save()
        self.render()

    def toggle_stopped(self):
        self.s["show_stopped"] = not self.s["show_stopped"]
        self.app.save()
        self.render()

    def remove_host(self, mid):
        m = self.machine(mid)
        name = m["name"] if m else "this machine"
        if confirm(
            self.win, "Remove machine", f"Stop showing {name}'s containers on this card?", ok="Remove", danger=True
        ):
            self.s["hosts"] = [h for h in self.hosts if h != mid]
            self.results.pop(mid, None)
            self.prev.pop(mid, None)
            self.app.save()
            self.render()

    def add_item(self):
        self.app.open_dialog(("docker", self.id), lambda: DockerHostDialog(self), replace=True)

    def add_host(self, mid, containers):
        if mid not in self.hosts:
            self.hosts.append(mid)
        self.results[mid] = {"ok": True, "containers": containers}
        self.prev[mid] = {c["name"]: c for c in containers}
        self.app.save()
        self.render()

    def settings_rows(self, f, row):
        v = tk.StringVar(value=str(self.s["interval"]))
        v_stopped = tk.BooleanVar(value=bool(self.s["show_stopped"]))
        v_compact = tk.BooleanVar(value=bool(self.s["compact"]))
        section(f, row, "Checks", first=True)
        fr = ttk.Frame(f)
        fr.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(fr, text="Check containers every").pack(side="left")
        spin(fr, v, 10, 600).pack(side="left", padx=6)
        ttk.Label(fr, text="seconds").pack(side="left")
        section(f, row + 2, "Display")
        ttk.Checkbutton(f, text="Show stopped containers", variable=v_stopped).grid(
            row=row + 3, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Checkbutton(f, text="Compact rows (one line per container)", variable=v_compact).grid(
            row=row + 4, column=0, columnspan=3, sticky="w", pady=2
        )

        def commit():
            self.s["interval"] = int_of(v, 10, 600, self.s["interval"])
            changed = (self.s["show_stopped"], self.s["compact"]) != (v_stopped.get(), v_compact.get())
            self.s["show_stopped"], self.s["compact"] = bool(v_stopped.get()), bool(v_compact.get())
            if changed:
                self.render()

        return row + 5, commit


class DockerHostDialog(Dialog):
    def __init__(self, card):
        super().__init__(
            card.app.root,
            "Add a Docker machine",
            heading="Add a Docker machine",
            subtitle="Pick a machine that runs Docker. It needs SSH or to be this PC.",
        )
        self.card, self.found = card, None
        f = self.content
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Machine").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self.picker = MachinePicker(
            f, card.app, allow=("local", "ssh"), on_change=lambda mid: self.test(), near=self.win
        )
        self.picker.grid(row=0, column=1, sticky="ew", pady=4)
        prefer = next(
            (m["id"] for m in M.all_machines(card.app.cfg) if m["method"] == "ssh" and m["id"] not in card.hosts), None
        )
        if prefer:
            self.picker.reload(select=prefer)
        test = ttk.Frame(f)
        test.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        self.btn_test = ttk.Button(test, text="Check", command=self.test)
        self.btn_test.pack(side="left")
        self.status = ttk.Label(test, text="", style="Muted.TLabel", wraplength=300, justify="left")
        self.status.pack(side="left", padx=(12, 0))
        self.buttons(("Cancel", self.close, "secondary"), ("Add", self.save, "primary"))
        self.show(near=card.win)
        self.test()

    def test(self):
        m = M.get(self.card.app.cfg, self.picker.value())
        if not m:
            return
        self.found = None
        self.btn_test.state(["disabled"])
        self.status.config(text=f"Looking for containers on {m['name']}…", style="Muted.TLabel")

        def done(out):
            self.btn_test.state(["!disabled"])
            ok, val = out
            if not ok:
                self.status.config(text=clip(val, 120), style="Error.TLabel")
                return
            self.found = (m["id"], val)
            running = sum(c["state"] == "running" for c in val)
            self.status.config(text=f"Found {len(val)} containers, {running} running.", style="Success.TLabel")

        self.card.app.run_bg(lambda: M.list_containers(m, stats=False), done)

    def save(self):
        if not self.found:
            self.status.config(
                text="Check the machine first - it needs to answer before it can be added.", style="Error.TLabel"
            )
            return
        self.close()
        self.card.add_host(*self.found)
        self.card.refresh_now()

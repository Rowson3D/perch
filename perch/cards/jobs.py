"""Jobs card: watch long-running work (renders, training, exports, downloads) on any of your machines,
and get told when it finishes."""

import datetime as dt
import time
import tkinter as tk
from tkinter import ttk

from perch import machines as M
from perch import theme as T
from perch.cards.base import Card
from perch.components import Dialog, PopupMenu, alert, int_of, section, spin
from perch.machines_ui import MachinePicker, open_machines
from perch.util import ago, clip
from perch.watch import DONE, RUNNING, duration, match, new_job


def descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += descendants(c)
    return out


class JobsCard(Card):
    TYPE = "jobs"
    NAME = "Jobs"
    DESCRIPTION = "Watches renders, training runs and other long jobs on your machines, and tells you when they finish."
    ADD_LABEL = "Watch a job"
    DEFAULTS = {"jobs": [], "interval": 10}

    def __init__(self, app, conf, animate=False):
        self.live, self.errors, self.inflight, self.rows = {}, {}, set(), {}
        self.poll_job = None
        super().__init__(app, conf, animate)

    @property
    def jobs(self):
        return self.s["jobs"]

    def job(self, jid):
        return next((j for j in self.jobs if j["id"] == jid), None)

    def machine(self, mid):
        return M.get(self.app.cfg, mid)

    # ------------------------------------------------------------ polling
    def start(self):
        self.poll()

    def poll(self):
        for mid in {j["machine"] for j in self.jobs if j["status"] == RUNNING}:
            m = self.machine(mid)
            if m is None:
                self.errors[mid] = "machine was removed"
                continue
            if mid not in self.inflight:
                self.inflight.add(mid)
                self.app.pool.submit(self._fetch, dict(m))
        self.update_view()
        self.poll_job = self.after(max(3, int(self.s["interval"])) * 1000, self.poll)

    def refresh_now(self):
        if self.poll_job:
            self.cancel(self.poll_job)
        self.poll()

    def _fetch(self, m):
        try:
            out = (True, M.list_processes(m))
        except Exception as e:  # noqa: BLE001
            out = (False, str(e) or type(e).__name__)
        self.app.call_soon(self.on_result, m["id"], out)

    def on_result(self, mid, out):
        if self.dead:
            return
        self.inflight.discard(mid)
        ok, val = out
        if not ok:
            self.errors[mid] = val
            self.update_view()
            return
        self.errors.pop(mid, None)
        now, changed = time.time(), False
        for j in self.jobs:
            if j["machine"] != mid or j["status"] != RUNNING:
                continue
            procs = match(j, val)
            if procs:
                self.live[j["id"]] = {
                    "cpu": sum(p.get("cpu") or 0 for p in procs)
                    if any(p.get("cpu") is not None for p in procs)
                    else None,
                    "mem": sum(p.get("mem") or 0 for p in procs),
                    "count": len(procs),
                }
                continue
            j["status"], j["ended"] = DONE, now
            self.live.pop(j["id"], None)
            changed = True
            m = self.machine(mid)
            self.notify(
                f"Finished: {self.title_of(j)}",
                f"On {m['name'] if m else 'a machine'}, after {duration(now - j['started'])}.",
            )
        if changed:
            self.app.save()
        self.update_view()

    # ------------------------------------------------------------ rendering
    def title_of(self, j):
        return j.get("label") or j["name"]

    def render(self):
        self.app.tip.hide()
        for w in self.body.winfo_children():
            w.destroy()
        self.rows = {}
        if not self.jobs:
            tk.Label(
                self.body,
                text="Nothing watched yet.\nClick  +  to pick a running job.",
                bg=T.BG,
                fg=T.MUTED,
                font=T.F,
                justify="left",
                width=38,
                anchor="w",
            ).pack(anchor="w", pady=6)
        for j in self.jobs:
            self.rows[j["id"]] = self._make_row(j)
        self.update_view()

    def _make_row(self, j):
        card = tk.Frame(self.body, bg=T.ROW, padx=8, pady=5)
        card.pack(fill="x", pady=2)
        top = tk.Frame(card, bg=T.ROW)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=10, height=10, bg=T.ROW, highlightthickness=0)
        dot_id = dot.create_oval(1, 1, 9, 9, fill=T.GREY, outline="")
        dot.pack(side="left", pady=(2, 0))
        tk.Label(top, text=clip(self.title_of(j), 28), bg=T.ROW, fg=T.FG, font=T.F).pack(side="left", padx=(6, 0))
        right = tk.Label(top, text="", bg=T.ROW, fg=T.MUTED, font=T.FB)
        right.pack(side="right")
        detail = tk.Label(card, text="", bg=T.ROW, fg=T.MUTED, font=T.FS, anchor="w")
        detail.pack(fill="x", pady=(2, 0))
        jid = j["id"]
        for w in descendants(card):
            w.bind("<Enter>", lambda e, jid=jid, card=card: self._hover(jid, card), add="+")
            w.bind("<Leave>", lambda e: self.app.tip.hide_soon(), add="+")
            w.bind("<Button-3>", lambda e, jid=jid: self.row_menu(e, jid))
        return {"card": card, "dot": dot, "dot_id": dot_id, "right": right, "detail": detail}

    def update_view(self):
        now = time.time()
        for j in self.jobs:
            row = self.rows.get(j["id"])
            if not row:
                continue
            m = self.machine(j["machine"])
            where = m["name"] if m else "missing machine"
            err = self.errors.get(j["machine"])
            if j["status"] == DONE:
                color, right = T.GREEN, "done"
                detail = f"{where}  ·  finished {ago(now - j['ended'])} ago after {duration(j['ended'] - j['started'])}"
            elif err:
                color, right = T.GREY, duration(now - j["started"])
                detail = f"{where}  ·  can't reach: {err}"
            else:
                color, right = T.ACCENT, duration(now - j["started"])
                live = self.live.get(j["id"])
                bits = [where]
                if live:
                    if live["cpu"] is not None:
                        bits.append(f"{live['cpu']:.0f}% CPU")
                    if live["mem"]:
                        bits.append(f"{live['mem'] / 1024:.1f} GB" if live["mem"] >= 1024 else f"{live['mem']:.0f} MB")
                    if j["mode"] == "name" and live["count"] > 1:
                        bits.append(f"{live['count']} processes")
                else:
                    bits.append("checking…")
                detail = "  ·  ".join(bits)
            row["dot"].itemconfig(row["dot_id"], fill=color)
            row["right"].config(text=right, fg=color)
            row["detail"].config(text=clip(detail, 56))
        level, text = self.status()
        self.summary.config(text=text)
        self.app.cards_changed()
        if self.app.tip.key and self.app.tip.key[0] == self.id:
            self.app.tip.refresh()

    def status(self):
        if not self.jobs:
            return None, ""
        running = sum(j["status"] == RUNNING for j in self.jobs)
        done = len(self.jobs) - running
        parts = ([f"{running} running"] if running else []) + ([f"{done} done"] if done else [])
        return None, ", ".join(parts)

    def _hover(self, jid, row_widget):
        self.app.tip.show((self.id, jid), self.win, row_widget, lambda add: self._describe(jid, add))

    def _describe(self, jid, add):
        j = self.job(jid)
        if not j:
            return False
        m, now = self.machine(j["machine"]), time.time()
        add(self.title_of(j), font=T.FT)
        add(clip(j["cmd"] or j["name"], 90), T.MUTED, T.FS)
        if j["status"] == DONE:
            add(f"DONE  ·  ran for {duration(j['ended'] - j['started'])}", T.GREEN, T.FB, (8, 0))
        elif self.errors.get(j["machine"]):
            add(f"CAN'T REACH  ·  {clip(self.errors[j['machine']], 60)}", T.GREY, T.FB, (8, 0))
        else:
            add(f"RUNNING  ·  {duration(now - j['started'])} so far", T.ACCENT, T.FB, (8, 0))
        started = dt.datetime.fromtimestamp(j["started"]).strftime("%d %b, %H:%M").lstrip("0")
        lines = [f"Machine   {m['name'] if m else 'missing'}", f"Started   {started}"]
        if j["status"] == DONE:
            lines.append(f"Finished  {dt.datetime.fromtimestamp(j['ended']).strftime('%d %b, %H:%M').lstrip('0')}")
        watch = f"every process named {j['name']}" if j["mode"] == "name" else f"process {j['pid']}"
        lines.append(f"Watching  {watch}")
        add("\n".join(lines), T.FG, T.MONO, (6, 0))
        add("Right-click: stop watching or clear finished", T.GREY, T.FS, (8, 0))

    # ------------------------------------------------------------ actions
    def menu_items(self, m):
        m.command("Watch a job…", self.add_item)
        m.command("Clear finished", self.clear_done if any(j["status"] == DONE for j in self.jobs) else None)
        m.command("Machines…", lambda: open_machines(self.app))
        m.command("Check now", self.refresh_now)

    def row_menu(self, e, jid):
        self.app.tip.hide()
        j = self.job(jid)
        m = PopupMenu(self.app.root)
        m.command("Dismiss" if j["status"] == DONE else "Stop watching", lambda: self.remove_job(jid))
        m.separator()
        self.menu_items(m)
        self.common_menu(m)
        m.popup(e.x_root, e.y_root)
        return "break"

    def remove_job(self, jid):
        self.s["jobs"] = [j for j in self.jobs if j["id"] != jid]
        self.live.pop(jid, None)
        self.app.save()
        self.render()

    def clear_done(self):
        self.s["jobs"] = [j for j in self.jobs if j["status"] != DONE]
        self.app.save()
        self.render()

    def add_item(self):
        self.app.open_dialog(("job", self.id), lambda: JobDialog(self), replace=True)

    def add_job(self, job):
        self.jobs.append(job)
        self.app.save()
        self.render()
        self.refresh_now()

    def settings_rows(self, f, row):
        v = tk.StringVar(value=str(self.s["interval"]))
        section(f, row, "Checks", first=True)
        fr = ttk.Frame(f)
        fr.grid(row=row + 1, column=0, columnspan=3, sticky="w", pady=2)
        ttk.Label(fr, text="Check running jobs every").pack(side="left")
        spin(fr, v, 3, 300).pack(side="left", padx=6)
        ttk.Label(fr, text="seconds").pack(side="left")

        def commit():
            self.s["interval"] = int_of(v, 3, 300, self.s["interval"])

        return row + 2, commit


class JobDialog(Dialog):
    """Pick a machine, pick a running process from it, choose how to watch it."""

    def __init__(self, card):
        super().__init__(
            card.app.root,
            "Watch a job",
            heading="Watch a job",
            subtitle="Pick something that's running. Perch tells you when it finishes.",
            width=440,
        )
        self.card, self.procs, self.shown, self._gen = card, [], [], 0
        f = self.content
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Machine").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        self.picker = MachinePicker(f, card.app, on_change=lambda mid: self.load(), near=self.win)
        self.picker.grid(row=0, column=1, sticky="ew", pady=4)

        self.v_filter = tk.StringVar()
        self.v_filter.trace_add("write", lambda *a: self.fill())
        top = ttk.Frame(f)
        top.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        ttk.Label(top, text="Search").pack(side="left")
        ttk.Entry(top, textvariable=self.v_filter, width=24).pack(side="left", padx=(12, 8), fill="x", expand=True)
        ttk.Button(top, text="Refresh", command=self.load).pack(side="left")
        header = f" {'Name':<26} {'CPU':>5} {'Memory':>7}  {'Running':>9}  PID"
        ttk.Label(f, text=header, style="Hint.TLabel", font=T.MONO).grid(row=2, column=0, columnspan=2, sticky="w")
        self.lb = tk.Listbox(f, height=12, width=64, activestyle="none", exportselection=False, font=T.MONO)
        self.lb.grid(row=3, column=0, columnspan=2, sticky="nsew")
        self.lb.bind("<<ListboxSelect>>", lambda e: self.on_pick())
        self.lb.bind("<Double-1>", lambda e: self.save())
        self.status = ttk.Label(f, text="", style="Hint.TLabel")
        self.status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        section(f, 5, "Finished when", columns=2)
        self.v_mode = tk.StringVar(value="pid")
        self.rb_pid = ttk.Radiobutton(f, text="this process exits", variable=self.v_mode, value="pid")
        self.rb_pid.grid(row=6, column=0, columnspan=2, sticky="w")
        self.rb_name = ttk.Radiobutton(
            f, text="every process with this name has exited", variable=self.v_mode, value="name"
        )
        self.rb_name.grid(row=7, column=0, columnspan=2, sticky="w")
        self.v_label = tk.StringVar()
        ttk.Label(f, text="Label").grid(row=8, column=0, sticky="w", padx=(0, 12), pady=(10, 4))
        ttk.Entry(f, textvariable=self.v_label).grid(row=8, column=1, sticky="ew", pady=(10, 4))
        ttk.Label(f, text="optional, e.g. “Hero shot render”", style="Hint.TLabel").grid(row=9, column=1, sticky="w")

        self.buttons(("Cancel", self.close, "secondary"), ("Watch", self.save, "primary"))
        self.show(near=card.win)
        self.load()

    def load(self):
        mid = self.picker.value()
        m = M.get(self.card.app.cfg, mid)
        if not m:
            return
        self._gen += 1
        gen = self._gen  # results from a machine you've since switched away from are ignored
        self.procs = []
        self.status.config(text=f"Loading what's running on {m['name']}…")
        self.lb.delete(0, "end")

        def done(out):
            if gen != self._gen:
                return
            ok, val = out
            if not ok:
                self.status.config(text=f"Couldn't connect: {clip(val, 90)}")
                return
            if m["method"] == "local":  # CPU % needs two samples on this PC: take the second one shortly
                self.card.app.root.after(900, lambda: self.card.app.run_bg(lambda: M.list_processes(m), shown))
            shown((True, val))

        def shown(out):
            ok, val = out
            if ok and gen == self._gen:
                self.procs = sorted(val, key=lambda p: (-(p.get("cpu") or 0), -(p.get("mem") or 0)))
                self.status.config(text=f"{len(val)} processes on {m['name']}, busiest first. Double-click to watch.")
                self.fill()

        self.card.app.run_bg(lambda: M.list_processes(m), done)

    def fill(self):
        if not self.lb.winfo_exists():
            return
        q = self.v_filter.get().strip().lower()
        self.shown = [
            p for p in self.procs if not q or q in (p.get("name") or "").lower() or q in (p.get("cmd") or "").lower()
        ]
        self.lb.delete(0, "end")
        now = time.time()
        for p in self.shown[:300]:
            cpu = f"{p['cpu']:.0f}%" if p.get("cpu") is not None else "—"
            mem = f"{(p.get('mem') or 0) / 1024:.1f}G" if (p.get("mem") or 0) >= 1024 else f"{p.get('mem') or 0:.0f}M"
            age = duration(now - p["started"]) if p.get("started") else ""
            self.lb.insert("end", f" {clip(p.get('name') or '?', 26):<26} {cpu:>5} {mem:>7}  {age:>9}  {p.get('pid')}")

    def on_pick(self):
        sel = self.lb.curselection()
        if sel:
            name = self.shown[sel[0]].get("name") or "?"
            self.rb_name.config(text=f"every process named “{clip(name, 30)}” has exited")

    def save(self):
        sel = self.lb.curselection()
        if not sel:
            alert(self.win, "Pick a process", "Choose something from the list first.", "warning")
            return
        job = new_job(self.picker.value(), self.shown[sel[0]], self.v_mode.get(), self.v_label.get().strip())
        self.close()
        self.card.add_job(job)

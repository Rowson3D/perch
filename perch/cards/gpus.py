"""GPUs card: which GPUs on your machines are free, in use or held - and who's using them."""

import time
import tkinter as tk
import uuid
from tkinter import ttk

from perch import theme as T
from perch.cards.base import Card
from perch.components import Dialog, ListManager, PopupMenu, alert, confirm, form_row, int_of, section, spin
from perch.sources import AGENT_PORT, METHOD_KEYS, METHODS, SSH_PORT, fetch, gkey
from perch.status import BUSY, DETECTION_DEFAULTS, FREE, HELD, UNKNOWN, Tracker
from perch.util import clip, gb, short_name

STYLE = {
    FREE: (T.GREEN, T.GREEN_DIM, "FREE"),
    BUSY: (T.RED, T.RED_DIM, "IN USE"),
    HELD: (T.AMBER, T.AMBER_DIM, "HELD"),
    UNKNOWN: (T.GREY, T.GREY_DIM, ""),
}
METHOD_HELP = {
    "agent": "The machine must be running the Perch agent (perch-agent / perch_agent.py).",
    "ssh": "Uses your SSH key - `ssh user@host` must already work without a password prompt.",
    "local": "Reads the GPUs in this PC directly. Nothing else to install.",
}


def local_host(data):
    """A 'This PC' machine entry with every GPU from a fetch_local() result."""
    gpus = data["gpus"]
    return {
        "id": uuid.uuid4().hex[:10],
        "name": data.get("host") or "This PC",
        "method": "local",
        "address": "localhost",
        "port": None,
        "user": "",
        "gpus": [gkey(g) for g in gpus],
        "gpu_info": {
            gkey(g): {"index": g.get("index"), "name": g.get("name", ""), "mem_total": g.get("mem_total")} for g in gpus
        },
    }


def descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += descendants(c)
    return out


def flat(points):
    return [v for p in points for v in p]


class GpuCard(Card):
    TYPE = "gpus"
    NAME = "GPUs"
    DESCRIPTION = "Shows which GPUs on your machines are free, in use or held, and who is using them."
    ADD_LABEL = "Add machine"
    DEFAULTS = {
        **DETECTION_DEFAULTS,
        "show_history": True,
        "history_minutes": 10,
        "refresh": 5,
        "hosts": [],
        "watch": [],
    }

    def __init__(self, app, conf, animate=False):
        self.results, self.trackers, self.states = {}, {}, {}
        self.inflight, self.rows, self.host_status = set(), {}, {}
        self.poll_job = None
        super().__init__(app, conf, animate)

    # ------------------------------------------------------------ data
    @property
    def hosts(self):
        return self.s["hosts"]

    def host(self, hid):
        return next((h for h in self.hosts if h["id"] == hid), None)

    def live(self, hid, k):
        res = self.results.get(hid)
        if not res or not res["ok"]:
            return None, []
        g = next((g for g in res["data"]["gpus"] if gkey(g) == k), None)
        if not g:
            return None, []
        procs = [p for p in res["data"].get("procs", []) if p.get("gpu_uuid") == g.get("uuid")]
        return g, procs

    def start(self):
        self.poll()

    def poll(self):
        for h in self.hosts:
            if h["id"] not in self.inflight:
                self.inflight.add(h["id"])
                self.app.pool.submit(self._job, dict(h))
        self.poll_job = self.after(max(2000, int(float(self.s["refresh"]) * 1000)), self.poll)

    def _job(self, h):
        try:
            res = {"ok": True, "data": fetch(h)}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": str(e) or type(e).__name__}
        self.app.call_soon(self.on_result, h["id"], res)

    def refresh_now(self):
        if self.poll_job:
            self.cancel(self.poll_job)
        self.poll()

    def on_result(self, hid, res):
        if self.dead:
            return
        self.inflight.discard(hid)
        h = self.host(hid)
        if not h:
            return
        self.results[hid] = res
        for k in h.get("gpus", []):
            key = (hid, k)
            tr = self.trackers.setdefault(key, Tracker())
            g, _ = self.live(hid, k)
            if g and g.get("mem_total"):
                tr.add(100.0 * (g.get("mem_used") or 0) / g["mem_total"], g.get("util"))
                self.states[key] = tr.evaluate(self.s)
            else:
                self.states[key] = UNKNOWN
            self.check_watch(h, key, g)
        self.update_view()

    def reevaluate(self):
        for key, tr in self.trackers.items():
            if self.states.get(key, UNKNOWN) != UNKNOWN:
                self.states[key] = tr.evaluate(self.s)

    # ------------------------------------------------------------ rendering
    def render(self):
        self.app.tip.hide()
        for w in self.body.winfo_children():
            w.destroy()
        self.rows, self.host_status = {}, {}
        if not self.hosts:
            tk.Label(
                self.body,
                text="No GPUs yet.\nClick  +  to add a machine.",
                bg=T.BG,
                fg=T.MUTED,
                font=T.F,
                justify="left",
                width=38,
                anchor="w",
            ).pack(anchor="w", pady=6)
        for h in self.hosts:
            hf = tk.Frame(self.body, bg=T.BG)
            hf.pack(fill="x", pady=(6, 1))
            tk.Label(hf, text=clip(h.get("name") or h.get("address"), 32), bg=T.BG, fg=T.FG, font=T.FB).pack(
                side="left"
            )
            st = tk.Label(hf, text="connecting…", bg=T.BG, fg=T.MUTED, font=T.FS)
            st.pack(side="right")
            self.host_status[h["id"]] = st
            for k in h.get("gpus", []):
                self.rows[(h["id"], k)] = self._make_row(h, k)
        self.update_view()

    def _make_row(self, h, k):
        info = h.get("gpu_info", {}).get(k, {})
        card = tk.Frame(self.body, bg=T.ROW, padx=8, pady=5)
        card.pack(fill="x", pady=2)
        top = tk.Frame(card, bg=T.ROW)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=10, height=10, bg=T.ROW, highlightthickness=0)
        dot_id = dot.create_oval(1, 1, 9, 9, fill=T.GREY, outline="")
        dot.pack(side="left", pady=(2, 0))
        tk.Label(
            top,
            text=clip(f"GPU {info.get('index', '?')}  {short_name(info.get('name', ''))}", 26),
            bg=T.ROW,
            fg=T.FG,
            font=T.F,
        ).pack(side="left", padx=(6, 0))
        pct = tk.Label(top, text="—", bg=T.ROW, fg=T.MUTED, font=T.FB)
        pct.pack(side="right")
        state = tk.Label(top, text="", bg=T.ROW, fg=T.MUTED, font=T.FS)
        state.pack(side="right", padx=(0, 6))
        bell = tk.Label(top, text="", bg=T.ROW, fg=T.ACCENT, font=T.FS)
        bell.pack(side="right", padx=(0, 4))
        bar = tk.Canvas(card, width=T.BAR_W, height=T.BAR_H, bg=T.ROW, highlightthickness=0)
        bar.pack(anchor="w", pady=(4, 2))
        bar.create_rectangle(0, 0, T.BAR_W, T.BAR_H, fill=T.TRACK, outline="")
        fill = bar.create_rectangle(0, 0, 0, T.BAR_H, fill=T.GREY, outline="")
        mark = bar.create_line(0, 0, 0, T.BAR_H, fill=T.MARK, width=2)
        hist = None
        if self.s.get("show_history", True):
            hist = tk.Canvas(card, width=T.BAR_W, height=T.HIST_H, bg=T.HIST_BG, highlightthickness=0)
            hist.pack(anchor="w", pady=(2, 2))
        detail = tk.Label(card, text="", bg=T.ROW, fg=T.MUTED, font=T.FS, anchor="w")
        detail.pack(fill="x")
        key = (h["id"], k)
        for w in descendants(card):
            w.bind("<Enter>", lambda e, key=key, card=card: self._hover(key, card), add="+")
            w.bind("<Leave>", lambda e: self.app.tip.hide_soon(), add="+")
            w.bind("<Button-3>", lambda e, key=key: self.row_menu(e, key))
        return dict(
            card=card,
            dot=dot,
            dot_id=dot_id,
            pct=pct,
            state=state,
            bell=bell,
            bar=bar,
            fill=fill,
            mark=mark,
            hist=hist,
            detail=detail,
        )

    def update_view(self):
        thr = float(self.s["threshold"])
        for h in self.hosts:
            res = self.results.get(h["id"])
            st = self.host_status.get(h["id"])
            if st:
                if res is None:
                    st.config(text="connecting…", fg=T.MUTED)
                elif not res["ok"]:
                    st.config(text="offline", fg=T.RED)
                else:
                    st.config(text=h.get("method", ""), fg=T.GREY)
            for k in h.get("gpus", []):
                key = (h["id"], k)
                row = self.rows.get(key)
                if not row:
                    continue
                state = self.states.get(key, UNKNOWN)
                color, dim, label = STYLE[state]
                g, procs = self.live(h["id"], k)
                if g and g.get("mem_total") and state != UNKNOWN:
                    used = g.get("mem_used") or 0
                    p = 100.0 * used / g["mem_total"]
                    frac = min(p / 100, 1)
                    row["pct"].config(text=f"{p:.0f}%", fg=color)
                    row["state"].config(text=label, fg=color)
                    bits = [f"{gb(used)} / {gb(g['mem_total'])} GB"]
                    if g.get("util") is not None:
                        bits.append(f"util {g['util']:.0f}%")
                    if g.get("temp") is not None:
                        bits.append(f"{g['temp']:.0f}°C")
                    users = sorted({p["user"] for p in procs if p.get("user")})
                    if users:
                        bits.append(users[0] + (f" +{len(users) - 1}" if len(users) > 1 else ""))
                    elif procs:
                        bits.append(f"{len(procs)} proc{'s' * (len(procs) > 1)}")
                    detail = "  ·  ".join(bits)
                else:
                    frac = 0
                    row["pct"].config(text="—", fg=T.MUTED)
                    row["state"].config(text="", fg=T.MUTED)
                    if res is None:
                        detail = "waiting…"
                    elif not res["ok"]:
                        detail = res["error"]
                    else:
                        detail = "GPU not reported by machine"
                row["bell"].config(text="notify" if self.watch_key(key) in self.s["watch"] else "")
                row["dot"].itemconfig(row["dot_id"], fill=color)
                row["bar"].coords(row["fill"], 0, 0, T.BAR_W * frac, T.BAR_H)
                row["bar"].itemconfig(row["fill"], fill=color)
                tx = max(1, min(T.BAR_W - 1, T.BAR_W * thr / 100))
                row["bar"].coords(row["mark"], tx, 0, tx, T.BAR_H)
                row["detail"].config(text=clip(detail, 54))
                if row["hist"] is not None:
                    self.draw_history(row["hist"], self.trackers.get(key), color, dim)
        level, text = self.status()
        self.summary.config(text=text.replace(" GPUs", "") if text else "")
        self.app.cards_changed()
        if self.app.tip.key and self.app.tip.key[0] == self.id:
            self.app.tip.refresh()

    def draw_history(self, c, tracker, color, dim):
        c.delete("all")
        W, H = T.BAR_W, T.HIST_H
        ty = H - (H - 2) * float(self.s["threshold"]) / 100
        c.create_line(0, ty, W, ty, fill=T.TIP_BORDER, dash=(2, 3))
        if not tracker:
            return
        now = time.time()
        span = float(self.s.get("history_minutes", 10)) * 60
        pts = [s for s in tracker.samples if s[0] >= now - span]
        if len(pts) < 2:
            return

        def xy(t, v):
            return W * (1 - (now - t) / span), H - 1 - (H - 3) * min(max(v, 0), 100) / 100

        mem = [xy(t, m) for t, m, _ in pts]
        c.create_polygon(flat([(mem[0][0], H), *mem, (mem[-1][0], H)]), fill=dim, outline="")
        c.create_line(flat(mem), fill=color, width=1.5)
        util = [xy(t, u) for t, _, u in pts if u is not None]
        if len(util) >= 2:
            c.create_line(flat(util), fill=T.UTIL_LINE, width=1)

    def status(self):
        keys = [(h["id"], k) for h in self.hosts for k in h.get("gpus", [])]
        if not keys:
            return None, ""
        states = [self.states.get(k, UNKNOWN) for k in keys]
        free, known = states.count(FREE), sum(s != UNKNOWN for s in states)
        level = "ok" if free else ("warn" if known == len(keys) else None)
        return level, f"{free}/{len(keys)} GPUs free"

    # ------------------------------------------------------------ hover details
    def _hover(self, key, row_widget):
        self.app.tip.show((self.id, key), self.win, row_widget, lambda add: self._describe(key, add))

    def _describe(self, key, add):
        h = self.host(key[0])
        if not h:
            return False
        info = h.get("gpu_info", {}).get(key[1], {})
        g, procs = self.live(*key)
        res = self.results.get(key[0])
        add((g or info).get("name", "GPU"), font=T.FT)
        add(f"GPU {info.get('index', '?')} on {h.get('name') or h.get('address')}  ({h.get('method')})", T.MUTED, T.FS)
        state = self.states.get(key, UNKNOWN)
        color, _, label = STYLE[state]
        tr = self.trackers.get(key)
        if res and not res["ok"]:
            add(f"OFFLINE  ·  {clip(res['error'], 70)}", T.RED, T.FB, (8, 0))
        elif state != UNKNOWN and tr:
            add(f"{label}  ·  {tr.reason}", color, T.FB, (8, 0))
        if g and g.get("mem_total"):
            used = g.get("mem_used") or 0
            stats = [f"VRAM   {gb(used)} / {gb(g['mem_total'])} GB  ({100 * used / g['mem_total']:.0f}%)"]
            if g.get("util") is not None:
                win = int(self.s.get("util_window", 60))
                avg = tr.util_avg(win) if tr else None
                stats.append(
                    f"Util   {g['util']:.0f}%" + (f"   (avg {avg:.0f}% over {win} s)" if avg is not None else "")
                )
            if g.get("temp") is not None:
                stats.append(f"Temp   {g['temp']:.0f}°C")
            add("\n".join(stats), T.FG, T.MONO, (6, 0))
            add("Processes", T.MUTED, T.FB, (8, 2))
            if procs:
                rows = [
                    f"{clip(p.get('user') or '?', 12):<12} {clip(p['name'], 22):<22} "
                    f"{(gb(p['mem']) + ' GB') if p.get('mem') is not None else '':>8}"
                    for p in sorted(procs, key=lambda p: -(p.get("mem") or 0))[:12]
                ]
                if len(procs) > 12:
                    rows.append(f"… and {len(procs) - 12} more")
                add("\n".join(rows), T.FG, T.MONO)
            else:
                add("No compute processes reported", T.MUTED, T.FS)
        watching = self.watch_key(key) in self.s["watch"]
        add(
            "Right-click: cancel notification" if watching else "Right-click: notify me when it's free",
            T.GREY,
            T.FS,
            (8, 0),
        )

    # ------------------------------------------------------------ notifications
    @staticmethod
    def watch_key(key):
        return f"{key[0]}|{key[1]}"

    def set_watch(self, key, on):
        wk = self.watch_key(key)
        if on and wk not in self.s["watch"]:
            self.s["watch"].append(wk)
        elif not on and wk in self.s["watch"]:
            self.s["watch"].remove(wk)
        self.app.save()
        self.update_view()

    def check_watch(self, h, key, g):
        wk = self.watch_key(key)
        if wk in self.s["watch"] and self.states.get(key) == FREE:
            self.s["watch"].remove(wk)
            self.app.save()
            info = h.get("gpu_info", {}).get(key[1], {})
            name = short_name((g or {}).get("name") or info.get("name", "GPU"))
            self.notify(
                f"GPU free: {name}", f"GPU {info.get('index', '?')} on {h.get('name') or h.get('address')} is free now."
            )

    # ------------------------------------------------------------ menus
    def menu_items(self, m):
        m.command("Add machine…", self.add_item)
        m.command("Manage machines…", self.open_manage)
        m.command("Refresh now", self.refresh_now)

    def row_menu(self, e, key):
        self.app.tip.hide()
        h = self.host(key[0])
        m = PopupMenu(self.app.root)
        state = self.states.get(key, UNKNOWN)
        if self.watch_key(key) in self.s["watch"]:
            m.command("Cancel 'notify when free'", lambda: self.set_watch(key, False))
        elif state == FREE:
            m.command("Notify me when free (it's free now)", None)
        else:
            m.command("Notify me when free", lambda: self.set_watch(key, True))
        if h:
            m.command("Edit this machine…", lambda: self.edit_host(h))
        m.separator()
        self.menu_items(m)
        self.common_menu(m)
        m.popup(e.x_root, e.y_root)
        return "break"

    # ------------------------------------------------------------ machines
    def add_item(self):
        self.edit_host(None)

    def edit_host(self, host):
        self.app.open_dialog(("host", self.id), lambda: HostDialog(self, host), replace=True)

    def upsert_host(self, host):
        for i, h in enumerate(self.hosts):
            if h["id"] == host["id"]:
                self.hosts[i] = host
                break
        else:
            self.hosts.append(host)
        self.results.pop(host["id"], None)
        for key in [k for k in self.trackers if k[0] == host["id"]]:
            self.trackers.pop(key, None)
            self.states.pop(key, None)
        self.hosts_changed()
        self.refresh_now()

    def hosts_changed(self):
        ids = {h["id"] for h in self.hosts}
        self.s["watch"] = [w for w in self.s["watch"] if w.split("|", 1)[0] in ids]
        for key in [k for k in self.trackers if k[0] not in ids]:
            self.trackers.pop(key, None)
            self.states.pop(key, None)
        self.app.save()
        self.render()
        d = self.app.dialogs.get(("manage", self.id))
        if d:
            d.refresh()

    def open_manage(self):
        def label(h):
            n = len(h.get("gpus", []))
            return f"{h['name']}   —   {h['address']}  ({h['method']}, {n} GPU{'s' * (n != 1)})"

        def remove(i, parent):
            h = self.hosts[i]
            if confirm(parent, "Remove machine", f"Remove {h['name']} from this card?", ok="Remove", danger=True):
                del self.hosts[i]
                self.results.pop(h["id"], None)
                self.hosts_changed()

        def move(i, d):
            self.hosts[i], self.hosts[i + d] = self.hosts[i + d], self.hosts[i]
            self.hosts_changed()

        self.app.open_dialog(
            ("manage", self.id),
            lambda: ListManager(
                self.app.root,
                "Machines",
                "Double-click a machine to edit it. The order here is the order on the card.",
                lambda: self.hosts,
                label,
                self.add_item,
                lambda i: self.edit_host(self.hosts[i]),
                remove,
                move,
                near=self.win,
            ),
        )

    # ------------------------------------------------------------ settings (inside CardSettings)
    def settings_rows(self, f, row):
        s = self.s
        v = {
            "thr": tk.IntVar(value=int(s["threshold"])),
            "use_util": tk.BooleanVar(value=bool(s["use_util"])),
            "util_thr": tk.StringVar(value=str(s["util_threshold"])),
            "util_win": tk.StringVar(value=str(s["util_window"])),
            "held": tk.BooleanVar(value=bool(s["detect_held"])),
            "held_min": tk.StringVar(value=str(s["held_minutes"])),
            "hist": tk.BooleanVar(value=bool(s["show_history"])),
            "hist_min": tk.StringVar(value=str(s["history_minutes"])),
            "ref": tk.StringVar(value=str(s["refresh"])),
        }

        def line(r):
            fr = ttk.Frame(f)
            fr.grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
            return fr

        section(f, row, "When is a GPU in use?", first=True)
        ttk.Label(f, text="VRAM used is at or above").grid(row=row + 1, column=0, columnspan=2, sticky="w")
        l_thr = ttk.Label(f, width=5, anchor="e", style="Info.TLabel")
        l_thr.grid(row=row + 1, column=2, sticky="e")

        def live_thr(_=None):
            s["threshold"] = int(float(v["thr"].get()))
            l_thr.config(text=f"{s['threshold']}%")
            self.reevaluate()
            self.update_view()

        ttk.Scale(f, from_=1, to=100, variable=v["thr"], length=360, command=live_thr).grid(
            row=row + 2, column=0, columnspan=3, sticky="ew", pady=(4, 8)
        )
        r = line(row + 3)
        ttk.Checkbutton(r, text="or GPU utilization averages ≥", variable=v["use_util"]).pack(side="left")
        spin(r, v["util_thr"], 1, 100).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="% over").pack(side="left")
        spin(r, v["util_win"], 10, 900).pack(side="left", padx=4)
        ttk.Label(r, text="s").pack(side="left")
        r = line(row + 4)
        ttk.Checkbutton(r, text="Mark HELD when VRAM is held but idle for", variable=v["held"]).pack(side="left")
        spin(r, v["held_min"], 1, 240).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="min").pack(side="left")
        ttk.Label(
            f, text="A small buffer stops GPUs from switching back and forth near a threshold.", style="Hint.TLabel"
        ).grid(row=row + 5, column=0, columnspan=3, sticky="w", pady=(4, 0))

        section(f, row + 6, "Display")
        r = line(row + 7)
        ttk.Checkbutton(r, text="Show a history graph of the last", variable=v["hist"]).pack(side="left")
        spin(r, v["hist_min"], 2, 240).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="min").pack(side="left")
        r = line(row + 8)
        ttk.Label(r, text="Refresh every").pack(side="left")
        spin(r, v["ref"], 2, 600).pack(side="left", padx=(6, 4))
        ttk.Label(r, text="seconds").pack(side="left")
        live_thr()

        def commit():
            history_was = s["show_history"]
            s["use_util"] = bool(v["use_util"].get())
            s["util_threshold"] = int_of(v["util_thr"], 1, 100, s["util_threshold"])
            s["util_window"] = int_of(v["util_win"], 10, 900, s["util_window"])
            s["detect_held"] = bool(v["held"].get())
            s["held_minutes"] = int_of(v["held_min"], 1, 240, s["held_minutes"])
            s["show_history"] = bool(v["hist"].get())
            s["history_minutes"] = int_of(v["hist_min"], 2, 240, s["history_minutes"])
            s["refresh"] = int_of(v["ref"], 2, 600, s["refresh"])
            self.reevaluate()
            if history_was != s["show_history"]:
                self.render()
            else:
                self.update_view()

        return row + 9, commit


class HostDialog(Dialog):
    def __init__(self, card, host=None):
        title = "Edit machine" if host else "Add machine"
        super().__init__(
            card.app.root,
            title,
            heading="Edit machine" if host else "Add a machine",
            subtitle="Choose how to reach it, find its GPUs, then pick the ones to show.",
        )
        self.card, self.host = card, host
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

        section(f, 7, "GPUs to show")
        self.box = ttk.Frame(f, style="Card.TFrame", padding=10)
        self.box.grid(row=8, column=0, columnspan=3, sticky="ew")
        ttk.Label(self.box, text="Click “Find GPUs” to list this machine's GPUs.", style="CardMuted.TLabel").pack(
            anchor="w"
        )

        self.buttons(("Cancel", self.close, "secondary"), ("Save" if host else "Add", self.save, "primary"))
        if host:  # show the saved selection without needing to reconnect
            info = host.get("gpu_info", {})
            self.show_gpus([{"uuid": k, **info.get(k, {})} for k in host.get("gpus", [])])
        self.on_method()
        self.win.bind("<Return>", lambda e: self.find())
        self.show(near=card.win)

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

        self.card.app.run_bg(lambda: fetch(conn), done)

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
        self.card.upsert_host(host)

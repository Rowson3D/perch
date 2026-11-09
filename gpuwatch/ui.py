"""The desktop widget window."""
import os
import queue
import threading
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

from gpuwatch import APP_NAME, icons
from gpuwatch import config as C
from gpuwatch.sources import fetch, gkey
from gpuwatch.status import BUSY, FREE, HELD, UNKNOWN, Tracker
from gpuwatch.theme import (ACCENT, AMBER, AMBER_DIM, BAR_H, BAR_W, BG, BORDER, F, FB, FG, FS, FT,
                            GREEN, GREEN_DIM, GREY, GREY_DIM, HIST_BG, HIST_H, MARK, MONO, MUTED,
                            RED, RED_DIM, ROW, TIP_BG, TIP_BORDER, TRACK, UTIL_LINE)
from gpuwatch.tray import Tray
from gpuwatch.util import clip, gb, point_on_a_monitor, short_name

STYLE = {FREE: (GREEN, GREEN_DIM, "FREE"), BUSY: (RED, RED_DIM, "IN USE"),
         HELD: (AMBER, AMBER_DIM, "HELD"), UNKNOWN: (GREY, GREY_DIM, "")}


def descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += descendants(c)
    return out


def flat(points):
    return [v for p in points for v in p]


class App:
    def __init__(self, first_run=False):
        self.cfg = C.load_config()
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.results = {}       # host id -> {"ok", "data" | "error"}
        self.trackers = {}      # (host id, gpu key) -> Tracker
        self.states = {}        # (host id, gpu key) -> FREE/BUSY/HELD/UNKNOWN
        self.inflight, self.rows, self.host_status, self.dialogs = set(), {}, {}, {}
        self.poll_job, self._off = None, None
        self.autostart_on = C.autostart_enabled()

        r = self.root = tk.Tk()
        r.title(APP_NAME)
        r.overrideredirect(True)
        r.configure(bg=BG)
        r.attributes("-topmost", bool(self.cfg["topmost"]))
        r.attributes("-alpha", float(self.cfg["opacity"]))
        try:
            self._icon = icons.photo(64)
            r.iconphoto(True, self._icon)
        except Exception:
            pass
        self.topmost_var = tk.BooleanVar(value=bool(self.cfg["topmost"]))
        self.autostart_var = tk.BooleanVar(value=self.autostart_on)

        self.tray = Tray(self)

        outer = tk.Frame(r, bg=BG, padx=10, pady=8, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=BORDER)
        outer.pack(fill="both", expand=True)
        hdr = tk.Frame(outer, bg=BG)
        hdr.pack(fill="x")
        tk.Label(hdr, text=APP_NAME, bg=BG, fg=FG, font=FT).pack(side="left")
        self.summary = tk.Label(hdr, text="", bg=BG, fg=MUTED, font=FS)
        self.summary.pack(side="left", padx=(8, 0), pady=(2, 0))
        if self.tray.available:
            self._hbtn(hdr, "–", lambda e: self.toggle_visible(), "Hide to tray")
        self._hbtn(hdr, "⋯", lambda e: self.menu.tk_popup(e.x_root, e.y_root), "Menu")
        self._hbtn(hdr, "+", lambda e: self.open_host_dialog(), "Add machine")
        self.body = tk.Frame(outer, bg=BG)
        self.body.pack(fill="both", expand=True, pady=(4, 0))

        m = self.menu = tk.Menu(r, tearoff=0)
        m.add_command(label="Add machine…", command=self.open_host_dialog)
        m.add_command(label="Manage machines…", command=self.open_manage)
        m.add_command(label="Settings…", command=self.open_settings)
        m.add_command(label="Refresh now", command=self.refresh_now)
        m.add_separator()
        m.add_checkbutton(label="Always on top", variable=self.topmost_var,
                          command=lambda: self.set_topmost(self.topmost_var.get()))
        if os.name == "nt":
            m.add_checkbutton(label="Start with Windows", variable=self.autostart_var,
                              command=lambda: self.set_autostart(self.autostart_var.get()))
        if self.tray.available:
            m.add_command(label="Hide to tray", command=self.toggle_visible)
        m.add_separator()
        m.add_command(label=f"Quit {APP_NAME}", command=self.quit)

        # Bound on the root's bindtag, so these apply to every widget inside the widget window.
        r.bind("<ButtonPress-1>", self._press)
        r.bind("<B1-Motion>", self._drag)
        r.bind("<ButtonRelease-1>", self._release)
        r.bind("<Button-3>", lambda e: self.menu.tk_popup(e.x_root, e.y_root))

        self.tip = Tip(self)
        self.render()
        self.place()
        if not self.cfg.get("visible", True) and self.tray.available:
            r.withdraw()
        r.after(150, self.drain)
        self.poll()
        if first_run:
            r.after(2500, lambda: self.notify(
                f"{APP_NAME} is running",
                "Drag the widget anywhere. Right-click it, or the tray icon, for options."))

    # ------------------------------------------------------------ window chrome
    def _hbtn(self, parent, text, cmd, tip):
        b = tk.Label(parent, text=text, bg=BG, fg=MUTED, font=("Segoe UI Semibold", 11),
                     cursor="hand2", padx=5)
        b.pack(side="right")
        b.bind("<Enter>", lambda e: b.config(fg=FG))
        b.bind("<Leave>", lambda e: b.config(fg=MUTED))

        def click(e):
            cmd(e)
            return "break"  # don't start a drag
        b.bind("<Button-1>", click)

    def _press(self, e):
        self._off = (e.x_root - self.root.winfo_x(), e.y_root - self.root.winfo_y())

    def _drag(self, e):
        if self._off:
            self.tip.hide()
            self.root.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _release(self, e):
        if self._off:
            self._off = None
            self.cfg["x"], self.cfg["y"] = self.root.winfo_x(), self.root.winfo_y()
            self.save()

    def place(self):
        self.root.update_idletasks()
        w = self.root.winfo_reqwidth()
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None or y is None or not point_on_a_monitor(x + 20, y + 10):
            x, y = self.root.winfo_screenwidth() - w - 40, 80
        self.root.geometry(f"+{int(x)}+{int(y)}")

    # ------------------------------------------------------------ rendering
    def render(self):
        self.tip.hide()
        for w in self.body.winfo_children():
            w.destroy()
        self.rows, self.host_status = {}, {}
        if not self.cfg["hosts"]:
            tk.Label(self.body, text="No GPUs yet.\nClick  +  to add a machine.", bg=BG, fg=MUTED,
                     font=F, justify="left", width=38, anchor="w").pack(anchor="w", pady=6)
        for h in self.cfg["hosts"]:
            hf = tk.Frame(self.body, bg=BG)
            hf.pack(fill="x", pady=(6, 1))
            tk.Label(hf, text=clip(h.get("name") or h.get("address"), 32), bg=BG, fg=FG,
                     font=FB).pack(side="left")
            st = tk.Label(hf, text="connecting…", bg=BG, fg=MUTED, font=FS)
            st.pack(side="right")
            self.host_status[h["id"]] = st
            for k in h.get("gpus", []):
                self.rows[(h["id"], k)] = self._make_row(h, k)
        self.update_view()
        self.root.update_idletasks()

    def _make_row(self, h, k):
        info = h.get("gpu_info", {}).get(k, {})
        card = tk.Frame(self.body, bg=ROW, padx=8, pady=5)
        card.pack(fill="x", pady=2)
        top = tk.Frame(card, bg=ROW)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=10, height=10, bg=ROW, highlightthickness=0)
        dot_id = dot.create_oval(1, 1, 9, 9, fill=GREY, outline="")
        dot.pack(side="left", pady=(2, 0))
        tk.Label(top, text=clip(f"GPU {info.get('index', '?')}  {short_name(info.get('name', ''))}", 26),
                 bg=ROW, fg=FG, font=F).pack(side="left", padx=(6, 0))
        pct = tk.Label(top, text="—", bg=ROW, fg=MUTED, font=FB)
        pct.pack(side="right")
        state = tk.Label(top, text="", bg=ROW, fg=MUTED, font=FS)
        state.pack(side="right", padx=(0, 6))
        bell = tk.Label(top, text="", bg=ROW, fg=ACCENT, font=FS)
        bell.pack(side="right", padx=(0, 4))
        bar = tk.Canvas(card, width=BAR_W, height=BAR_H, bg=ROW, highlightthickness=0)
        bar.pack(anchor="w", pady=(4, 2))
        bar.create_rectangle(0, 0, BAR_W, BAR_H, fill=TRACK, outline="")
        fill = bar.create_rectangle(0, 0, 0, BAR_H, fill=GREY, outline="")
        mark = bar.create_line(0, 0, 0, BAR_H, fill=MARK, width=2)
        hist = None
        if self.cfg.get("show_history", True):
            hist = tk.Canvas(card, width=BAR_W, height=HIST_H, bg=HIST_BG, highlightthickness=0)
            hist.pack(anchor="w", pady=(2, 2))
        detail = tk.Label(card, text="", bg=ROW, fg=MUTED, font=FS, anchor="w")
        detail.pack(fill="x")
        key = (h["id"], k)
        for w in descendants(card):
            w.bind("<Enter>", lambda e, key=key: self.tip.show(key), add="+")
            w.bind("<Leave>", lambda e: self.tip.hide_soon(), add="+")
            w.bind("<Button-3>", lambda e, key=key: self.row_menu(e, key))
        return dict(card=card, dot=dot, dot_id=dot_id, pct=pct, state=state, bell=bell, bar=bar,
                    fill=fill, mark=mark, hist=hist, detail=detail)

    def host(self, hid):
        return next((h for h in self.cfg["hosts"] if h["id"] == hid), None)

    def live(self, hid, k):
        """(gpu dict or None, [procs on it]) from the latest successful fetch."""
        res = self.results.get(hid)
        if not res or not res["ok"]:
            return None, []
        g = next((g for g in res["data"]["gpus"] if gkey(g) == k), None)
        if not g:
            return None, []
        procs = [p for p in res["data"].get("procs", []) if p.get("gpu_uuid") == g.get("uuid")]
        return g, procs

    def update_view(self):
        thr = float(self.cfg["threshold"])
        free = total = known = 0
        for h in self.cfg["hosts"]:
            res = self.results.get(h["id"])
            st = self.host_status.get(h["id"])
            if st:
                if res is None:
                    st.config(text="connecting…", fg=MUTED)
                elif not res["ok"]:
                    st.config(text="offline", fg=RED)
                else:
                    st.config(text=h.get("method", ""), fg=GREY)
            for k in h.get("gpus", []):
                key = (h["id"], k)
                row = self.rows.get(key)
                if not row:
                    continue
                total += 1
                state = self.states.get(key, UNKNOWN)
                color, dim, label = STYLE[state]
                g, procs = self.live(h["id"], k)
                if g and g.get("mem_total") and state != UNKNOWN:
                    known += 1
                    free += state == FREE
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
                    row["pct"].config(text="—", fg=MUTED)
                    row["state"].config(text="", fg=MUTED)
                    if res is None:
                        detail = "waiting…"
                    elif not res["ok"]:
                        detail = res["error"]
                    else:
                        detail = "GPU not reported by machine"
                row["bell"].config(text="notify" if self.watch_key(key) in self.cfg["watch"] else "")
                row["dot"].itemconfig(row["dot_id"], fill=color)
                row["bar"].coords(row["fill"], 0, 0, BAR_W * frac, BAR_H)
                row["bar"].itemconfig(row["fill"], fill=color)
                tx = max(1, min(BAR_W - 1, BAR_W * thr / 100))
                row["bar"].coords(row["mark"], tx, 0, tx, BAR_H)
                row["detail"].config(text=clip(detail, 54))
                if row["hist"] is not None:
                    self.draw_history(row["hist"], self.trackers.get(key), color, dim)
        self.summary.config(text=f"{free}/{total} free" if total else "")
        self.tray.update(free, total, known)
        if self.tip.key:
            self.tip.refresh()

    def draw_history(self, c, tracker, color, dim):
        c.delete("all")
        W, H = BAR_W, HIST_H
        ty = H - (H - 2) * float(self.cfg["threshold"]) / 100
        c.create_line(0, ty, W, ty, fill="#3a3f4b", dash=(2, 3))
        if not tracker:
            return
        now = time.time()
        span = float(self.cfg.get("history_minutes", 10)) * 60
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
            c.create_line(flat(util), fill=UTIL_LINE, width=1)

    # ------------------------------------------------------------ data
    def poll(self):
        for h in self.cfg["hosts"]:
            if h["id"] not in self.inflight:
                self.inflight.add(h["id"])
                self.pool.submit(self._job, dict(h))
        self.poll_job = self.root.after(max(1000, int(float(self.cfg["refresh"]) * 1000)), self.poll)

    def _job(self, h):
        try:
            res = {"ok": True, "data": fetch(h)}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "error": str(e) or type(e).__name__}
        self.q.put((self.on_result, (h["id"], res)))

    def on_result(self, hid, res):
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
                self.states[key] = tr.evaluate(self.cfg)
            else:
                self.states[key] = UNKNOWN
            self.check_watch(h, key, g)
        self.update_view()

    def reevaluate(self):
        for key, tr in self.trackers.items():
            if self.states.get(key, UNKNOWN) != UNKNOWN:
                self.states[key] = tr.evaluate(self.cfg)

    def refresh_now(self):
        if self.poll_job:
            self.root.after_cancel(self.poll_job)
        self.poll()

    def call_soon(self, fn, *args):
        """Thread-safe: run fn(*args) on the Tk thread."""
        self.q.put((fn, args))

    def run_bg(self, fn, done):
        """Run fn() off the UI thread, then done((ok, value_or_error)) on the UI thread."""
        def job():
            try:
                out = (True, fn())
            except Exception as e:  # noqa: BLE001
                out = (False, str(e) or type(e).__name__)
            self.call_soon(done, out)
        threading.Thread(target=job, daemon=True).start()

    def drain(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                try:
                    fn(*args)
                except tk.TclError:
                    pass  # a dialog was closed meanwhile
        except queue.Empty:
            pass
        self.root.after(150, self.drain)

    # ------------------------------------------------------------ notifications
    @staticmethod
    def watch_key(key):
        return f"{key[0]}|{key[1]}"

    def set_watch(self, key, on):
        wk = self.watch_key(key)
        if on and wk not in self.cfg["watch"]:
            self.cfg["watch"].append(wk)
        elif not on and wk in self.cfg["watch"]:
            self.cfg["watch"].remove(wk)
        self.save()
        self.update_view()

    def check_watch(self, h, key, g):
        wk = self.watch_key(key)
        if wk in self.cfg["watch"] and self.states.get(key) == FREE:
            self.cfg["watch"].remove(wk)
            self.save()
            info = h.get("gpu_info", {}).get(key[1], {})
            name = short_name((g or {}).get("name") or info.get("name", "GPU"))
            self.notify(f"GPU free: {name}",
                        f"GPU {info.get('index', '?')} on {h.get('name') or h.get('address')} is free now.")

    def notify(self, title, message):
        if not self.tray.notify(title, message):
            Toast(self.root, title, message)

    def row_menu(self, e, key):
        h = self.host(key[0])
        m = tk.Menu(self.root, tearoff=0)
        state = self.states.get(key, UNKNOWN)
        if self.watch_key(key) in self.cfg["watch"]:
            m.add_command(label="Cancel 'notify when free'", command=lambda: self.set_watch(key, False))
        elif state == FREE:
            m.add_command(label="Notify me when free (it's free now)", state="disabled")
        else:
            m.add_command(label="Notify me when free", command=lambda: self.set_watch(key, True))
        m.add_separator()
        if h:
            m.add_command(label="Edit machine…", command=lambda: self.open_host_dialog(h))
        m.add_command(label="Refresh now", command=self.refresh_now)
        m.add_separator()
        m.add_command(label="Add machine…", command=self.open_host_dialog)
        m.add_command(label="Manage machines…", command=self.open_manage)
        m.add_command(label="Settings…", command=self.open_settings)
        m.tk_popup(e.x_root, e.y_root)
        return "break"

    # ------------------------------------------------------------ actions
    def save(self):
        try:
            C.save_config(self.cfg)
        except OSError:
            pass

    def hosts_changed(self):
        ids = {h["id"] for h in self.cfg["hosts"]}
        self.cfg["watch"] = [w for w in self.cfg["watch"] if w.split("|", 1)[0] in ids]
        for key in [k for k in self.trackers if k[0] not in ids]:
            self.trackers.pop(key, None)
            self.states.pop(key, None)
        self.save()
        self.render()
        d = self.dialogs.get("manage")
        if d and d.win.winfo_exists():
            d.refresh()

    def upsert_host(self, host):
        hosts = self.cfg["hosts"]
        for i, h in enumerate(hosts):
            if h["id"] == host["id"]:
                hosts[i] = host
                break
        else:
            hosts.append(host)
        self.results.pop(host["id"], None)
        for key in [k for k in self.trackers if k[0] == host["id"]]:
            self.trackers.pop(key, None)
            self.states.pop(key, None)
        self.hosts_changed()
        self.refresh_now()

    def settings_changed(self, rerender):
        self.reevaluate()
        self.save()
        if rerender:
            self.render()
        else:
            self.update_view()

    def _dialog(self, name, factory):
        d = self.dialogs.get(name)
        if d and d.win.winfo_exists():
            d.win.deiconify()
            d.win.lift()
            d.win.focus_force()
            return d
        d = self.dialogs[name] = factory()
        return d

    def open_host_dialog(self, host=None):
        from gpuwatch.dialogs import HostDialog
        d = self.dialogs.get("host")
        if d and d.win.winfo_exists():
            d.win.destroy()
        self.dialogs["host"] = HostDialog(self, host)

    def open_manage(self):
        from gpuwatch.dialogs import ManageDialog
        self._dialog("manage", lambda: ManageDialog(self))

    def open_settings(self):
        from gpuwatch.dialogs import SettingsDialog
        self._dialog("settings", lambda: SettingsDialog(self))

    def toggle_visible(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
            self.root.attributes("-topmost", bool(self.cfg["topmost"]))
            self.root.lift()
            self.cfg["visible"] = True
        else:
            self.tip.hide()
            self.root.withdraw()
            self.cfg["visible"] = False
        self.save()

    def set_topmost(self, on):
        self.cfg["topmost"] = bool(on)
        self.topmost_var.set(self.cfg["topmost"])
        self.root.attributes("-topmost", self.cfg["topmost"])
        self.save()

    def set_autostart(self, on):
        try:
            C.set_autostart(on)
        except OSError as e:
            self.notify(APP_NAME, f"Couldn't change the startup setting: {e}")
        self.autostart_on = C.autostart_enabled()
        self.autostart_var.set(self.autostart_on)

    def quit(self):
        self.save()
        self.tray.stop()
        self.root.destroy()
        os._exit(0)  # don't wait on in-flight ssh/http calls


class Tip:
    """Hover card with full details and the processes using a GPU."""

    def __init__(self, app):
        self.app, self.win, self.key, self._job = app, None, None, None

    def show(self, key):
        if self._job:
            self.app.root.after_cancel(self._job)
            self._job = None
        if self.app._off or (self.key == key and self.win):
            return
        self.key = key
        self.refresh()

    def hide_soon(self):
        if self._job:
            self.app.root.after_cancel(self._job)
        self._job = self.app.root.after(150, self.hide)

    def hide(self):
        self._job = None
        self.key = None
        if self.win:
            self.win.destroy()
            self.win = None

    def refresh(self):
        app, key = self.app, self.key
        row, h = app.rows.get(key), app.host(key[0]) if key else None
        if not row or not h:
            return self.hide()
        if not self.win:
            self.win = tk.Toplevel(app.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.win.configure(bg=TIP_BORDER)
        for c in self.win.winfo_children():
            c.destroy()
        f = tk.Frame(self.win, bg=TIP_BG, padx=12, pady=10)
        f.pack(padx=1, pady=1)

        def line(text, fg=FG, font=F, pady=0):
            tk.Label(f, text=text, bg=TIP_BG, fg=fg, font=font, justify="left", anchor="w").pack(
                anchor="w", pady=pady)

        info = h.get("gpu_info", {}).get(key[1], {})
        g, procs = app.live(*key)
        res = app.results.get(key[0])
        line((g or info).get("name", "GPU"), font=FT)
        line(f"GPU {info.get('index', '?')} on {h.get('name') or h.get('address')}  ({h.get('method')})", MUTED, FS)
        state = app.states.get(key, UNKNOWN)
        color, _, label = STYLE[state]
        tr = app.trackers.get(key)
        if res and not res["ok"]:
            line(f"OFFLINE  ·  {clip(res['error'], 70)}", RED, FB, (8, 0))
        elif state != UNKNOWN and tr:
            line(f"{label}  ·  {tr.reason}", color, FB, (8, 0))
        if g and g.get("mem_total"):
            used = g.get("mem_used") or 0
            stats = [f"VRAM   {gb(used)} / {gb(g['mem_total'])} GB  ({100 * used / g['mem_total']:.0f}%)"]
            if g.get("util") is not None:
                avg = tr.util_avg(float(app.cfg.get("util_window", 60))) if tr else None
                stats.append(f"Util   {g['util']:.0f}%" + (f"   (avg {avg:.0f}% over "
                             f"{int(app.cfg.get('util_window', 60))} s)" if avg is not None else ""))
            if g.get("temp") is not None:
                stats.append(f"Temp   {g['temp']:.0f}°C")
            line("\n".join(stats), FG, MONO, (6, 0))
            line("Processes", MUTED, FB, (8, 2))
            if procs:
                rows = [f"{clip(p.get('user') or '?', 12):<12} {clip(p['name'], 22):<22} "
                        f"{(gb(p['mem']) + ' GB') if p.get('mem') is not None else '':>8}"
                        for p in sorted(procs, key=lambda p: -(p.get("mem") or 0))[:12]]
                if len(procs) > 12:
                    rows.append(f"… and {len(procs) - 12} more")
                line("\n".join(rows), FG, MONO)
            else:
                line("No compute processes reported", MUTED, FS)
        hint = ("Right-click: cancel notification" if app.watch_key(key) in app.cfg["watch"]
                else "Right-click: notify me when it's free")
        line(hint, GREY, FS, (8, 0))

        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        y = row["card"].winfo_rooty()
        x = app.root.winfo_x() - w - 8
        if not point_on_a_monitor(x + 5, y + 5):
            x = app.root.winfo_x() + app.root.winfo_width() + 8
        self.win.geometry(f"+{x}+{y}")


class Toast:
    """Fallback notification when the tray icon isn't available."""

    def __init__(self, root, title, message):
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=TIP_BORDER)
        f = tk.Frame(w, bg=TIP_BG, padx=14, pady=10)
        f.pack(padx=1, pady=1)
        tk.Label(f, text=title, bg=TIP_BG, fg=FG, font=FT).pack(anchor="w")
        tk.Label(f, text=message, bg=TIP_BG, fg=MUTED, font=F, wraplength=300, justify="left").pack(anchor="w")
        w.update_idletasks()
        x = root.winfo_screenwidth() - w.winfo_reqwidth() - 24
        y = root.winfo_screenheight() - w.winfo_reqheight() - 72
        w.geometry(f"+{x}+{y}")
        w.bind("<Button-1>", lambda e: w.destroy())
        w.after(8000, w.destroy)

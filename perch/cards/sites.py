"""Sites card: whether your websites are up, how fast they respond, and when their SSL and domain expire."""

import datetime as dt
import time
import tkinter as tk
import webbrowser
from tkinter import ttk

from perch import config as C
from perch import sitecheck as S
from perch import theme as T
from perch.cards.base import Card
from perch.components import Dialog, ListManager, PopupMenu, alert, confirm, form_row, int_of, section, spin
from perch.sitecheck import fmt_pct, new_site, sites_from_text  # noqa: F401 - re-exported
from perch.util import ago, clip, mix

SSL_EVERY = 6 * 3600
DOMAIN_EVERY = 12 * 3600
RETRY_ON_ERROR = 30 * 60
TRAFFIC_EVERY = 15 * 60
TRAFFIC_RETRY = 5 * 60
GRAPH_H = 20
STATUS_COLOR = {S.UP: T.GREEN, S.DOWN: T.RED, S.UNKNOWN: T.GREY, S.PAUSED: T.GREY}
STATUS_DIM = {S.UP: T.GREEN_DIM, S.DOWN: T.RED_DIM, S.UNKNOWN: T.GREY_DIM, S.PAUSED: T.GREY_DIM}


def fmt_date(epoch):
    return dt.datetime.fromtimestamp(epoch).strftime("%d %b %Y").lstrip("0")


def flat(points):
    return [v for p in points for v in p]


def descendants(w):
    out = [w]
    for c in w.winfo_children():
        out += descendants(c)
    return out


class SitesCard(Card):
    TYPE = "sites"
    NAME = "Sites"
    DESCRIPTION = (
        "Checks your websites: whether they're up, how fast they respond, and when their SSL and domain expire."
    )
    ADD_LABEL = "Add site"
    DEFAULTS = {
        "sites": [],
        "interval": 60,
        "fail_after": 2,
        "ssl_warn_days": 14,
        "domain_warn_days": 30,
        "show_graph": True,
        "graph_minutes": 60,
        "compact": False,
        "show_traffic": True,
        "visitors_every": 2,  # minutes between the light "today" checks
        "new_visitor_badge": True,
        "badge_minutes": 60,
        "notify_visitors": False,
    }

    def __init__(self, app, conf, animate=False):
        saved = C.load_state(conf["id"])
        self.monitors = {s["id"]: S.SiteMonitor(saved.get(s["id"])) for s in conf.get("settings", {}).get("sites", [])}
        self.inflight, self.last_check, self.rows, self.traffic_inflight = set(), {}, {}, set()
        super().__init__(app, conf, animate)

    # ------------------------------------------------------------ data
    @property
    def sites(self):
        return self.s["sites"]

    def site(self, sid):
        return next((s for s in self.sites if s["id"] == sid), None)

    def monitor(self, sid):
        return self.monitors.setdefault(sid, S.SiteMonitor())

    def start(self):
        self.tick()
        self.after(5 * 60 * 1000, self._persist_loop)

    def stop(self):
        self.persist()

    def _persist_loop(self):
        self.persist()
        self.after(5 * 60 * 1000, self._persist_loop)

    def persist(self):
        try:
            C.save_state(self.id, {sid: m.to_json() for sid, m in self.monitors.items() if self.site(sid)})
        except OSError:
            pass

    def tick(self):
        now = time.time()
        interval = max(15, int(self.s["interval"]))
        for site in self.sites:
            sid = site["id"]
            if site.get("paused") or sid in self.inflight or now - self.last_check.get(sid, 0) < interval:
                continue
            mon = self.monitor(sid)
            https = site["url"].startswith("https://")
            need_ssl = (
                https
                and site.get("check_ssl", True)
                and (now - mon.ssl_checked >= (SSL_EVERY if mon.ssl and not mon.ssl_error else RETRY_ON_ERROR))
            )
            need_domain = site.get("check_domain", True) and (
                now - mon.domain_checked >= (DOMAIN_EVERY if mon.domain else RETRY_ON_ERROR)
            )
            self.inflight.add(sid)
            self.last_check[sid] = now
            self.app.pool.submit(self._job, dict(site), need_ssl, need_domain)
        self._tick_traffic(now)
        self.after(2000, self.tick)

    # ------------------------------------------------------------ visitor numbers
    def _tick_traffic(self, now):
        from perch import traffic as TR

        accounts = {a["id"]: a for a in self.app.cfg.get("accounts", [])}
        for site in self.sites:
            sid = site["id"]
            if "traffic" not in site:  # new site: link it to a connected account by its domain, once
                found = next(
                    ((a, s) for a in accounts.values() if (s := TR.match_source(site["url"], a.get("sources", [])))),
                    None,
                )
                site["traffic"] = TR.link(found[1], found[0]["id"]) if found else None
                self.app.save()
            link = site.get("traffic")
            if not link or sid in self.traffic_inflight:
                continue
            mon = self.monitor(sid)
            full = now - mon.traffic_checked >= (TRAFFIC_RETRY if mon.traffic_error else TRAFFIC_EVERY)
            light = now - mon.today_checked >= max(1, int(self.s.get("visitors_every", 2))) * 60
            if not (full or light):
                continue
            account = accounts.get(link.get("account"))
            mon.today_checked = now
            if full:
                mon.traffic_checked = now
            if not account:
                mon.traffic_error = "its account was disconnected"
                continue
            self.traffic_inflight.add(sid)
            self.app.pool.submit(self._traffic_job, sid, dict(account), dict(link), full)

    def _traffic_job(self, sid, account, link, full=True):
        from perch import traffic as TR

        try:
            out = (True, TR.fetch(account, link) if full else {"light": TR.fetch_today(account, link)})
        except Exception as e:  # noqa: BLE001
            out = (False, str(e) or type(e).__name__)
        self.app.call_soon(self.on_traffic, sid, out)

    def on_traffic(self, sid, out):
        if self.dead:
            return
        self.traffic_inflight.discard(sid)
        mon = self.monitor(sid)
        ok, val = out
        if not ok:
            mon.traffic_error = val
            self.update_view()
            return
        mon.traffic_error = None
        if "light" in val:
            light = val["light"]
            day, count = light["day"], light["visitors"]
            if mon.traffic:  # keep the 7-day numbers, update today's
                mon.traffic["today"] = {"visitors": count, "pageviews": light["pageviews"]}
        else:
            mon.traffic = val
            day, count = val.get("day"), val["today"]["visitors"]
        self._count_new(sid, mon, count, day)
        self.update_view()

    def _count_new(self, sid, mon, count, day):
        from perch.traffic import new_visitors

        n = new_visitors(mon.seen_count, mon.seen_day, count, day)
        mon.seen_count, mon.seen_day = count, day
        if not n or not self.s.get("new_visitor_badge", True):
            return
        mon.fresh += n
        mon.fresh_at = time.time()
        self.persist()
        self.after(50, self.celebrate, sid)
        if self.s.get("notify_visitors"):
            site = self.site(sid)
            self.notify(f"+{n} visitor{'s' * (n != 1)} on {site['name']}", f"{count} today so far.")

    def clear_fresh(self, sid):
        mon = self.monitor(sid)
        if mon.fresh:
            mon.fresh = 0
            self.persist()
            self.update_view()

    def celebrate(self, sid):
        """Make a new visitor noticeable: the +N badge pops, and the row glows green and fades back."""
        from perch.components import animate

        row = self.rows.get(sid)
        if not row or not row["card"].winfo_exists():
            return
        badge, tinted = row["fresh"], row["tinted"]
        sizes = (14, 13, 12, 11, 10, 9)

        def step(t):
            glow = mix(T.ROW, T.GREEN_DIM, 1 - t if t > 0.25 else 1)
            for w in tinted:
                if w.winfo_exists():
                    w.configure(bg=glow)
            if badge.winfo_exists():
                badge.configure(font=(T.FONT_SEMI, sizes[min(len(sizes) - 1, int(t * len(sizes) * 1.6))]))

        animate(row["card"], 1600, step, frames=32)

    def traffic_changed(self):
        """An account was connected or removed, or a site's source changed: fetch again."""
        for mon in self.monitors.values():
            mon.traffic_checked = 0
        self.update_view()

    def _job(self, site, need_ssl, need_domain):
        out = {"http": S.check_http(site["url"], site.get("keyword", ""))}
        host = S.hostname(site["url"])
        reached = out["http"]["status"] is not None or out["http"]["error"].startswith("certificate")
        if need_ssl and reached:  # no point checking the certificate of a server we can't reach
            try:
                out["ssl"] = S.check_ssl(host)
            except Exception as e:  # noqa: BLE001
                out["ssl_error"] = S.short_error(e)
        if need_domain:
            domain = S.registrable_domain(host)
            if domain:
                try:
                    out["domain"] = S.check_domain(domain)
                except Exception as e:  # noqa: BLE001
                    out["domain_error"] = str(e) or type(e).__name__
            else:
                out["domain_error"] = "not a registered domain name"
        self.app.call_soon(self.on_result, site["id"], out)

    def on_result(self, sid, out):
        if self.dead:
            return
        self.inflight.discard(sid)
        site = self.site(sid)
        if not site:
            return
        mon = self.monitor(sid)
        now = time.time()
        event = mon.record(out["http"], int(self.s["fail_after"]), now)
        if "ssl" in out or "ssl_error" in out:
            mon.ssl_checked = now
            mon.ssl = out.get("ssl", mon.ssl)
            mon.ssl_error = out.get("ssl_error")
        if "domain" in out or "domain_error" in out:
            mon.domain_checked = now
            mon.domain = out.get("domain", mon.domain)
            mon.domain_error = out.get("domain_error")
        name = site["name"]
        if event == "down":
            self.notify(f"{name} is down", f"{out['http']['error'] or 'Not responding'}  ·  {site['url']}")
        elif event == "up":
            inc = mon.last_incident()
            took = f" after {ago(now - inc['start'])}" if inc else ""
            self.notify(f"{name} is back up", f"It's responding again{took}.")
        self._expiry_warnings(site, mon, now)
        if event:
            self.persist()
        self.update_view()

    def _warn_once(self, mon, key, title, message):
        today = dt.date.today().isoformat()
        if mon.notified.get(key) != today:
            mon.notified[key] = today
            self.notify(title, message)

    def _expiry_warnings(self, site, mon, now):
        name = site["name"]
        if site.get("check_ssl", True) and site["url"].startswith("https://"):
            if mon.ssl_error:
                self._warn_once(mon, "ssl_error", f"SSL problem: {name}", mon.ssl_error)
            elif mon.ssl:
                d = S.SiteMonitor.days_left(mon.ssl["expires"], now)
                if d is not None and d <= int(self.s["ssl_warn_days"]):
                    when = "has expired" if d < 0 else f"expires in {int(d)} day{'s' * (int(d) != 1)}"
                    self._warn_once(mon, "ssl", f"SSL certificate: {name}", f"The certificate {when}.")
        if site.get("check_domain", True) and mon.domain and mon.domain.get("expires"):
            d = S.SiteMonitor.days_left(mon.domain["expires"], now)
            if d is not None and d <= int(self.s["domain_warn_days"]):
                when = "has expired" if d < 0 else f"expires in {int(d)} day{'s' * (int(d) != 1)}"
                self._warn_once(
                    mon, "domain", f"Domain renewal: {name}", f"{S.registrable_domain(S.hostname(site['url']))} {when}."
                )

    def warnings(self, site, mon, now=None):
        """Short warning badges for a row, plus the worst level ('warn' or 'bad')."""
        out, level = [], None
        if site.get("check_ssl", True) and site["url"].startswith("https://"):
            if mon.ssl_error:
                out.append("SSL error")
                level = "bad"
            elif mon.ssl:
                d = S.SiteMonitor.days_left(mon.ssl["expires"], now)
                if d is not None and d <= int(self.s["ssl_warn_days"]):
                    out.append("SSL expired" if d < 0 else f"SSL {int(d)}d")
                    level = "bad" if d < 3 else (level or "warn")
        if site.get("check_domain", True) and mon.domain and mon.domain.get("expires"):
            d = S.SiteMonitor.days_left(mon.domain["expires"], now)
            if d is not None and d <= int(self.s["domain_warn_days"]):
                out.append("domain expired" if d < 0 else f"domain {int(d)}d")
                level = "bad" if d < 7 else (level or "warn")
        return out, level

    def site_status(self, site):
        return S.PAUSED if site.get("paused") else self.monitor(site["id"]).status

    def refresh_now(self):
        self.last_check.clear()
        self.update_view()

    def check_now(self, sid):
        self.last_check.pop(sid, None)

    # ------------------------------------------------------------ rendering
    def render(self):
        self.app.tip.hide()
        for w in self.body.winfo_children():
            w.destroy()
        self.rows = {}
        if not self.sites:
            tk.Label(
                self.body,
                text="No sites yet.\nClick  +  to add your first website.",
                bg=T.BG,
                fg=T.MUTED,
                font=T.F,
                justify="left",
                width=38,
                anchor="w",
            ).pack(anchor="w", pady=6)
        for site in self.sites:
            self.rows[site["id"]] = self._make_row(site)
        self.update_view()

    def _make_row(self, site):
        compact = self.s.get("compact")
        card = tk.Frame(self.body, bg=T.ROW, padx=8, pady=4 if compact else 5)
        card.pack(fill="x", pady=2)
        top = tk.Frame(card, bg=T.ROW)
        top.pack(fill="x")
        dot = tk.Canvas(top, width=10, height=10, bg=T.ROW, highlightthickness=0)
        dot_id = dot.create_oval(1, 1, 9, 9, fill=T.GREY, outline="")
        dot.pack(side="left", pady=(2, 0))
        name = tk.Label(top, text=clip(site["name"], 26), bg=T.ROW, fg=T.FG, font=T.F)
        name.pack(side="left", padx=(6, 0))
        fresh = tk.Label(top, text="", bg=T.GREEN, fg=T.ON_ACCENT, font=T.FB, padx=5)
        ms = tk.Label(top, text="…", bg=T.ROW, fg=T.MUTED, font=T.FB)
        ms.pack(side="right")
        warn = tk.Label(top, text="", bg=T.ROW, fg=T.AMBER, font=T.FS)
        warn.pack(side="right", padx=(0, 6))
        graph = detail = None
        if not compact:
            if self.s.get("show_graph", True):
                graph = tk.Canvas(card, width=T.BAR_W, height=GRAPH_H, bg=T.HIST_BG, highlightthickness=0)
                graph.pack(anchor="w", pady=(4, 2))
            detail = tk.Label(card, text="", bg=T.ROW, fg=T.MUTED, font=T.FS, anchor="w")
            detail.pack(fill="x")
        sid = site["id"]
        tinted = [w for w in descendants(card) if w is not fresh and w.cget("bg") == T.ROW]
        for w in descendants(card):
            w.bind("<Enter>", lambda e, sid=sid, card=card: self._hover(sid, card), add="+")
            w.bind("<Leave>", lambda e: self.app.tip.hide_soon(), add="+")
            w.bind("<Button-3>", lambda e, sid=sid: self.row_menu(e, sid))
            w.bind("<Double-Button-1>", lambda e, sid=sid: self.open_url(sid, "url"))
        return dict(
            card=card,
            dot=dot,
            dot_id=dot_id,
            name=name,
            ms=ms,
            warn=warn,
            graph=graph,
            detail=detail,
            fresh=fresh,
            tinted=tinted,
        )

    def update_view(self):
        now = time.time()
        for site in self.sites:
            row = self.rows.get(site["id"])
            if not row:
                continue
            mon = self.monitor(site["id"])
            status = self.site_status(site)
            color = STATUS_COLOR[status]
            row["dot"].itemconfig(row["dot_id"], fill=color)
            last = mon.last
            if status == S.UP and last and last.get("ms") is not None:
                row["ms"].config(text=f"{last['ms']:.0f} ms", fg=color)
            else:
                row["ms"].config(text={S.DOWN: "DOWN", S.PAUSED: "paused"}.get(status, "…"), fg=color)
            if mon.fresh and now - mon.fresh_at > int(self.s.get("badge_minutes", 60)) * 60:
                mon.fresh = 0  # nobody looked for a while: let it go
            if mon.fresh and self.s.get("new_visitor_badge", True):
                row["fresh"].config(text=f"+{mon.fresh}")
                if not row["fresh"].winfo_ismapped():
                    row["fresh"].pack(side="left", padx=(6, 0), after=row["name"])
            elif row["fresh"].winfo_ismapped():
                row["fresh"].pack_forget()
            badges, level = self.warnings(site, mon, now)
            row["warn"].config(text="  ·  ".join(badges), fg=T.RED if level == "bad" else T.AMBER)
            if row["detail"] is not None:
                row["detail"].config(text=clip(self._detail(site, mon, status, now), 54))
            if row["graph"] is not None:
                self._draw_graph(row["graph"], mon, color, STATUS_DIM[status], now)
        level, text = self.status()
        fresh = self.fresh_total()
        self.summary.config(text=text.replace(" sites", "") if text else "", fg=T.GREEN if fresh else T.MUTED)
        self.app.cards_changed()
        if self.app.tip.key and self.app.tip.key[0] == self.id:
            self.app.tip.refresh()

    def _detail(self, site, mon, status, now):
        if status == S.PAUSED:
            return "checks paused"
        last = mon.last or {}
        if status == S.DOWN:
            return f"down {ago(now - (mon.since or now))}  ·  {last.get('error') or 'not responding'}"
        if status == S.UNKNOWN:
            if mon.fails:
                return f"failing ({mon.fails}/{self.s['fail_after']})  ·  {last.get('error', '')}"
            return "checking…"
        bits = [f"{fmt_pct(mon.uptime(24, now))} 24h"]
        if self.s.get("show_traffic", True) and mon.traffic and site.get("traffic"):
            bits.append(f"{mon.traffic['today']['visitors']} today")
        if mon.ssl and not mon.ssl_error:
            bits.append(f"SSL {int(S.SiteMonitor.days_left(mon.ssl['expires'], now))}d")
        if mon.domain and mon.domain.get("expires"):
            bits.append(f"domain {int(S.SiteMonitor.days_left(mon.domain['expires'], now))}d")
        return "  ·  ".join(bits)

    def _draw_graph(self, c, mon, color, dim, now):
        c.delete("all")
        W, H = T.BAR_W, GRAPH_H
        span = float(self.s.get("graph_minutes", 60)) * 60
        pts = [(t, ms) for t, ms in mon.samples if t >= now - span]
        ok = [ms for _, ms in pts if ms is not None]
        top = max(max(ok, default=0) * 1.15, 300)

        def x(t):
            return W * (1 - (now - t) / span)

        for t, ms in pts:  # failed checks: red ticks along the bottom
            if ms is None:
                c.create_line(x(t), H - 6, x(t), H, fill=T.RED, width=2)
        line = [(x(t), H - 2 - (H - 5) * min(ms, top) / top) for t, ms in pts if ms is not None]
        if len(line) >= 2:
            c.create_polygon(flat([(line[0][0], H), *line, (line[-1][0], H)]), fill=dim, outline="")
            c.create_line(flat(line), fill=color, width=1.5)
        elif len(line) == 1:
            px, py = line[0]
            c.create_oval(px - 2, py - 2, px + 2, py + 2, fill=color, outline="")

    def status(self):
        if not self.sites:
            return None, ""
        now = time.time()
        active = [s for s in self.sites if not s.get("paused")]
        statuses = [self.site_status(s) for s in active]
        up = statuses.count(S.UP)
        level = None
        if S.DOWN in statuses:
            level = "bad"
        else:
            levels = {self.warnings(s, self.monitor(s["id"]), now)[1] for s in active}
            if "bad" in levels:
                level = "bad"
            elif "warn" in levels:
                level = "warn"
            elif active and up == len(active):
                level = "ok"
        fresh = self.fresh_total()
        return level, f"{up}/{len(active)} sites up" + (f" · +{fresh} new" if fresh else "")

    # ------------------------------------------------------------ hover details
    def fresh_total(self):
        if not self.s.get("new_visitor_badge", True):
            return 0
        return sum(self.monitor(s["id"]).fresh for s in self.sites)

    def _hover(self, sid, row_widget):
        if self.monitor(sid).fresh:  # you've seen it: clear the badge shortly
            self.after(2500, self.clear_fresh, sid)
        self.app.tip.show((self.id, sid), self.win, row_widget, lambda add: self._describe(sid, add))

    def _describe(self, sid, add):
        site = self.site(sid)
        if not site:
            return False
        mon, now = self.monitor(sid), time.time()
        status = self.site_status(site)
        last = mon.last or {}
        add(site["name"], font=T.FT)
        add(site["url"], T.MUTED, T.FS)
        if status == S.UP:
            code = f"HTTP {last.get('status')}" if last.get("status") else "responding"
            add(f"UP  ·  {code} in {last.get('ms', 0):.0f} ms", T.GREEN, T.FB, (8, 0))
        elif status == S.DOWN:
            add(
                f"DOWN for {ago(now - (mon.since or now))}  ·  {last.get('error') or 'not responding'}",
                T.RED,
                T.FB,
                (8, 0),
            )
        elif status == S.PAUSED:
            add("PAUSED  ·  checks are off for this site", T.GREY, T.FB, (8, 0))
        else:
            add("CHECKING…", T.GREY, T.FB, (8, 0))

        lines = [
            f"Uptime    24h {fmt_pct(mon.uptime(24, now)):>7}   7d {fmt_pct(mon.uptime(168, now)):>7}"
            f"   30d {fmt_pct(mon.uptime(720, now)):>7}"
        ]
        avg = mon.response_avg(3600, now)
        if avg is not None:
            lines.append(f"Response  avg {avg:.0f} ms over the last hour")
        if site["url"].startswith("https://") and site.get("check_ssl", True):
            if mon.ssl_error:
                lines.append(f"SSL       {clip(mon.ssl_error, 48)}")
            elif mon.ssl:
                d = int(S.SiteMonitor.days_left(mon.ssl["expires"], now))
                issuer = f" · {clip(mon.ssl['issuer'], 22)}" if mon.ssl.get("issuer") else ""
                lines.append(f"SSL       expires {fmt_date(mon.ssl['expires'])} ({d} days){issuer}")
        if site.get("check_domain", True):
            if mon.domain and mon.domain.get("expires"):
                d = int(S.SiteMonitor.days_left(mon.domain["expires"], now))
                reg = f" · {clip(mon.domain['registrar'], 22)}" if mon.domain.get("registrar") else ""
                lines.append(f"Domain    expires {fmt_date(mon.domain['expires'])} ({d} days){reg}")
            elif mon.domain_error:
                lines.append(f"Domain    {clip(mon.domain_error, 48)}")
        link = site.get("traffic")
        if link and mon.traffic:
            t = mon.traffic
            lines.append(f"Visitors  today {t['today']['visitors']:<6}  7 days {t['week']['visitors']}")
            lines.append(f"Views     today {t['today']['pageviews']:<6}  7 days {t['week']['pageviews']}")
        elif link and mon.traffic_error:
            lines.append(f"Visitors  {clip(mon.traffic_error, 48)}")
        if last.get("t"):
            lines.append(f"Checked   {ago(now - last['t'])} ago")
        add("\n".join(lines), T.FG, T.MONO, (6, 0))
        inc = mon.last_incident()
        if inc:
            start = dt.datetime.fromtimestamp(inc["start"]).strftime("%d %b, %H:%M").lstrip("0")
            took = ago((inc.get("end") or now) - inc["start"])
            still = "" if inc.get("end") else " (ongoing)"
            add(f"Last outage  {start} · {took}{still} · {clip(inc.get('reason', ''), 30)}", T.MUTED, T.FS, (8, 0))
        if link:
            from perch.traffic import PROVIDERS

            add(
                f"Visitor numbers from {PROVIDERS.get(link.get('provider'), '')} ({link.get('name', '')})",
                T.MUTED,
                T.FS,
                (8, 0),
            )
        add("Double-click: open site  ·  Right-click: admin, repo, check now", T.GREY, T.FS, (8, 0))

    # ------------------------------------------------------------ actions
    def open_url(self, sid, field):
        site = self.site(sid)
        if site and site.get(field):
            webbrowser.open(site[field])
        return "break"

    def toggle_pause(self, sid):
        site = self.site(sid)
        site["paused"] = not site.get("paused")
        if not site["paused"]:
            self.check_now(sid)
        self.app.save()
        self.update_view()

    def menu_items(self, m):
        m.command("Add site…", self.add_item)
        m.command("Manage sites…", self.open_manage)
        m.command("Traffic accounts…", self.open_accounts)
        m.command("Check all now", self.refresh_now)

    def open_accounts(self):
        from perch.traffic_ui import open_accounts

        open_accounts(self.app)

    def row_menu(self, e, sid):
        self.app.tip.hide()
        site = self.site(sid)
        m = PopupMenu(self.app.root)
        m.command("Open site", lambda: self.open_url(sid, "url"))
        m.command("Open admin", (lambda: self.open_url(sid, "admin_url")) if site.get("admin_url") else None)
        m.command("Open repo", (lambda: self.open_url(sid, "repo_url")) if site.get("repo_url") else None)
        m.separator()
        m.command("Check now", lambda: self.check_now(sid))
        m.command("Resume checks" if site.get("paused") else "Pause checks", lambda: self.toggle_pause(sid))
        m.command("Edit site…", lambda: self.edit_site(site))
        m.command("Remove site…", lambda: self.remove_site(sid, self.win))
        m.separator()
        self.menu_items(m)
        self.common_menu(m)
        m.popup(e.x_root, e.y_root)
        return "break"

    def add_item(self):
        self.edit_site(None)

    def edit_site(self, site):
        self.app.open_dialog(("site", self.id), lambda: SiteDialog(self, site), replace=True)

    def upsert_site(self, site):
        for i, s in enumerate(self.sites):
            if s["id"] == site["id"]:
                if s["url"] != site["url"]:
                    self.monitors[site["id"]] = S.SiteMonitor()  # new address = fresh history
                self.sites[i] = site
                break
        else:
            self.sites.append(site)
        self.check_now(site["id"])
        self.monitor(site["id"]).traffic_checked = 0
        self.sites_changed()

    def remove_site(self, sid, parent):
        site = self.site(sid)
        if site and confirm(parent, "Remove site", f"Stop watching {site['name']}?", ok="Remove", danger=True):
            self.sites.remove(site)
            self.monitors.pop(sid, None)
            self.sites_changed()

    def sites_changed(self):
        self.app.save()
        self.persist()
        self.render()
        d = self.app.dialogs.get(("manage", self.id))
        if d:
            d.refresh()

    def open_manage(self):
        def label(s):
            return f"{s['name']}   —   {s['url']}" + ("   (paused)" if s.get("paused") else "")

        def move(i, d):
            self.sites[i], self.sites[i + d] = self.sites[i + d], self.sites[i]
            self.sites_changed()

        self.app.open_dialog(
            ("manage", self.id),
            lambda: ListManager(
                self.app.root,
                "Sites",
                "Double-click a site to edit it. The order here is the order on the card.",
                lambda: self.sites,
                label,
                self.add_item,
                lambda i: self.edit_site(self.sites[i]),
                lambda i, parent: self.remove_site(self.sites[i]["id"], parent),
                move,
                near=self.win,
            ),
        )

    # ------------------------------------------------------------ settings (inside CardSettings)
    def settings_rows(self, f, row):
        s = self.s
        v = {
            k: tk.StringVar(value=str(s[k]))
            for k in ("interval", "fail_after", "ssl_warn_days", "domain_warn_days", "graph_minutes")
        }
        v["show_graph"] = tk.BooleanVar(value=bool(s["show_graph"]))
        v["compact"] = tk.BooleanVar(value=bool(s["compact"]))
        v["show_traffic"] = tk.BooleanVar(value=bool(s.get("show_traffic", True)))
        v["visitors_every"] = tk.StringVar(value=str(s.get("visitors_every", 2)))
        v["badge_minutes"] = tk.StringVar(value=str(s.get("badge_minutes", 60)))
        v["new_visitor_badge"] = tk.BooleanVar(value=bool(s.get("new_visitor_badge", True)))
        v["notify_visitors"] = tk.BooleanVar(value=bool(s.get("notify_visitors", False)))

        def line(r, *parts):
            fr = ttk.Frame(f)
            fr.grid(row=r, column=0, columnspan=3, sticky="w", pady=2)
            for p in parts:
                if isinstance(p, str):
                    ttk.Label(fr, text=p).pack(side="left")
                elif isinstance(p, tuple):
                    spin(fr, v[p[0]], p[1], p[2]).pack(side="left", padx=6)
                else:
                    p(fr).pack(side="left")
            return fr

        section(f, row, "Checks", first=True)
        line(row + 1, "Check every", ("interval", 15, 3600), "seconds")
        line(row + 2, "Mark a site down after", ("fail_after", 1, 10), "failed checks in a row")
        line(row + 3, "Warn", ("ssl_warn_days", 1, 90), "days before an SSL certificate expires")
        line(row + 4, "Warn", ("domain_warn_days", 1, 180), "days before a domain registration expires")
        line(row + 5, "Check for new visitors every", ("visitors_every", 1, 60), "minutes")
        section(f, row + 6, "New visitors")
        line(
            row + 7,
            lambda fr: ttk.Checkbutton(
                fr, text="Show +1 on the site when someone new visits, for up to", variable=v["new_visitor_badge"]
            ),
            ("badge_minutes", 5, 1440),
            "min",
        )
        line(
            row + 8,
            lambda fr: ttk.Checkbutton(fr, text="Also send a Windows notification", variable=v["notify_visitors"]),
        )
        ttk.Label(
            f,
            text="The badge clears when you hover over the site. Visits can take a few minutes to show up.",
            style="Hint.TLabel",
        ).grid(row=row + 9, column=0, columnspan=3, sticky="w", pady=(2, 0))
        row += 5
        section(f, row + 5, "Display")
        line(
            row + 6,
            lambda fr: ttk.Checkbutton(fr, text="Show a response-time graph of the last", variable=v["show_graph"]),
            ("graph_minutes", 10, 1440),
            "min",
        )
        line(row + 7, lambda fr: ttk.Checkbutton(fr, text="Compact rows (one line per site)", variable=v["compact"]))
        line(
            row + 8,
            lambda fr: ttk.Checkbutton(fr, text="Show today's visitors on each row", variable=v["show_traffic"]),
        )

        def commit():
            before = (s["show_graph"], s["compact"])
            s["interval"] = int_of(v["interval"], 15, 3600, s["interval"])
            s["fail_after"] = int_of(v["fail_after"], 1, 10, s["fail_after"])
            s["ssl_warn_days"] = int_of(v["ssl_warn_days"], 1, 90, s["ssl_warn_days"])
            s["domain_warn_days"] = int_of(v["domain_warn_days"], 1, 180, s["domain_warn_days"])
            s["graph_minutes"] = int_of(v["graph_minutes"], 10, 1440, s["graph_minutes"])
            s["show_graph"] = bool(v["show_graph"].get())
            s["compact"] = bool(v["compact"].get())
            s["show_traffic"] = bool(v["show_traffic"].get())
            s["visitors_every"] = int_of(v["visitors_every"], 1, 60, s.get("visitors_every", 2))
            s["badge_minutes"] = int_of(v["badge_minutes"], 5, 1440, s.get("badge_minutes", 60))
            s["new_visitor_badge"] = bool(v["new_visitor_badge"].get())
            s["notify_visitors"] = bool(v["notify_visitors"].get())
            if before != (s["show_graph"], s["compact"]):
                self.render()
            else:
                self.update_view()

        return row + 9, commit


class SiteDialog(Dialog):
    def __init__(self, card, site=None):
        super().__init__(
            card.app.root,
            "Edit site" if site else "Add site",
            heading="Edit site" if site else "Add a site",
            subtitle="Perch checks this site from your PC and warns you before its certificate or domain expires.",
        )
        self.card, self.site = card, site
        s = site or {}
        f = self.content
        f.columnconfigure(1, weight=1)
        self.v = {k: tk.StringVar(value=s.get(k, "")) for k in ("url", "name", "keyword", "admin_url", "repo_url")}
        self.v_ssl = tk.BooleanVar(value=s.get("check_ssl", True))
        self.v_domain = tk.BooleanVar(value=s.get("check_domain", True))

        def hint(text):
            return ttk.Label(f, text=text, style="Hint.TLabel")

        self.e_url = ttk.Entry(f, textvariable=self.v["url"], width=34)
        form_row(f, 0, "Address", self.e_url)
        form_row(f, 1, "Name", ttk.Entry(f, textvariable=self.v["name"]), hint("optional"))
        form_row(f, 2, "Must contain", ttk.Entry(f, textvariable=self.v["keyword"]), hint("optional"))
        ttk.Label(
            f, text="Counts as down if this text is missing from the page, e.g. your site's name.", style="Hint.TLabel"
        ).grid(row=3, column=1, columnspan=2, sticky="w")

        section(f, 4, "Shortcuts")
        form_row(f, 5, "Admin page", ttk.Entry(f, textvariable=self.v["admin_url"]), hint("optional"))
        form_row(f, 6, "Repository", ttk.Entry(f, textvariable=self.v["repo_url"]), hint("optional"))

        section(f, 7, "Warnings")
        ttk.Checkbutton(f, text="Warn before the SSL certificate expires", variable=self.v_ssl).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=2
        )
        ttk.Checkbutton(f, text="Warn before the domain registration expires", variable=self.v_domain).grid(
            row=9, column=0, columnspan=3, sticky="w", pady=2
        )

        section(f, 10, "Visitors")
        from perch import traffic as TR
        from perch.traffic_ui import source_label, sources_of

        self.sources = sources_of(card.app)
        labels = ["None"] + [source_label(a, src) for a, src in self.sources]
        current = s.get("traffic")  # a new site gets one picked as its address is typed (see _auto_source)
        pick = "None"
        for (a, src), lab in zip(self.sources, labels[1:], strict=True):
            if (
                current
                and a["id"] == current.get("account")
                and src.get("project", src.get("zone")) == current.get("project", current.get("zone"))
            ):
                pick = lab
        self.v_traffic = tk.StringVar(value=pick)
        self.cb_traffic = ttk.Combobox(f, textvariable=self.v_traffic, values=labels, state="readonly")
        form_row(f, 11, "From", self.cb_traffic)
        if not self.sources:
            ttk.Label(
                f,
                text="Connect Vercel or Cloudflare from the card menu (Traffic accounts…) to see visitors.",
                style="Hint.TLabel",
                wraplength=360,
            ).grid(row=12, column=0, columnspan=3, sticky="w")
        self._labels, self._TR = labels, TR
        self.v["url"].trace_add("write", lambda *a: self._auto_source())

        test = ttk.Frame(f)
        test.grid(row=13, column=0, columnspan=3, sticky="ew", pady=(T.SECTION, 0))
        self.btn_test = ttk.Button(test, text="Test now", command=self.test)
        self.btn_test.pack(side="left")
        self.status = ttk.Label(test, text="", style="Muted.TLabel", wraplength=280, justify="left")
        self.status.pack(side="left", padx=(12, 0))

        self.buttons(("Cancel", self.close, "secondary"), ("Save" if site else "Add", self.save, "primary"))
        self.win.bind("<Return>", lambda e: self.save())
        self.show(near=card.win)
        self.e_url.focus_set()

    def set_status(self, text, kind="Muted"):
        self.status.config(text=text, style=f"{kind}.TLabel")

    def _auto_source(self):
        """While typing a new site's address, pick the matching project/zone if nothing was chosen yet."""
        if self.site or self.v_traffic.get() != "None":
            return
        url = S.normalize_url(self.v["url"].get())
        for (_account, src), lab in zip(self.sources, self._labels[1:], strict=True):
            if url and self._TR.match_source(url, [src]):
                self.v_traffic.set(lab)
                return

    def collect(self):
        url = S.normalize_url(self.v["url"].get())
        if not url:
            alert(self.win, "Missing address", "Enter the site's address, e.g. example.com.", "warning")
            return None
        return {
            k: S.normalize_url(self.v[k].get())
            if k.endswith("_url") and self.v[k].get().strip()
            else self.v[k].get().strip()
            for k in ("name", "keyword", "admin_url", "repo_url")
        } | {"url": url}

    def test(self):
        data = self.collect()
        if not data:
            return
        self.btn_test.state(["disabled"])
        self.set_status("Checking…")
        check_ssl = self.v_ssl.get() and data["url"].startswith("https://")

        def work():
            http = S.check_http(data["url"], data["keyword"])
            cert = None
            if check_ssl and http["ok"]:
                try:
                    cert = S.check_ssl(S.hostname(data["url"]))
                except Exception as e:  # noqa: BLE001
                    cert = {"error": S.short_error(e)}
            return http, cert

        def done(out):
            self.btn_test.state(["!disabled"])
            ok, val = out
            if not ok:
                return self.set_status(val, "Error")
            http, cert = val
            if not http["ok"]:
                return self.set_status(f"Down: {http['error']}", "Error")
            bits = [f"Up · HTTP {http['status']} · {http['ms']:.0f} ms"]
            if cert and cert.get("error"):
                return self.set_status(bits[0] + f" · SSL problem: {cert['error']}", "Error")
            if cert:
                bits.append(f"SSL valid {int(S.SiteMonitor.days_left(cert['expires']))} days")
            self.set_status(" · ".join(bits), "Success")

        self.card.app.run_bg(work, done)

    def save(self):
        data = self.collect()
        if not data:
            return
        base = dict(self.site) if self.site else new_site(data["url"])
        base.update(data)
        base["name"] = data["name"] or S.hostname(data["url"])
        base["check_ssl"] = bool(self.v_ssl.get())
        base["check_domain"] = bool(self.v_domain.get())
        choice = self.v_traffic.get()
        base["traffic"] = None
        for (a, src), lab in zip(self.sources, self._labels[1:], strict=True):
            if lab == choice:
                base["traffic"] = self._TR.link(src, a["id"])
        self.close()
        self.card.upsert_site(base)

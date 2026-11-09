"""Card base class: the floating window, header, dragging/snapping, menus and common settings.

A card type subclasses Card and implements:
    render()          build rows inside self.body
    update_view()     refresh rows from current data
    start()           begin polling (use self.every / self.after)
    status()          (level, text) for the tray: level in ok / warn / bad / None
    menu_items(m)     card-specific PopupMenu entries
    settings_rows(f, row) -> (next_row, commit)   card-specific settings fields
Optional: ADD_LABEL + add_item() for the header "+" button, stop() for cleanup.
"""

import copy
import tkinter as tk
from tkinter import ttk

from perch import theme as T
from perch.components import Dialog, PopupMenu, fade_in, fade_out, icon_button, int_of, section
from perch.util import point_on_a_monitor, work_area

SNAP = 14  # px within which a dragged card snaps to an edge
GAP = 8  # space kept between snapped cards


class Card:
    TYPE = ""
    NAME = ""
    DESCRIPTION = ""
    DEFAULTS: dict = {}
    ADD_LABEL = None

    def __init__(self, app, conf, animate=False):
        self.app, self.conf = app, conf
        s = conf.setdefault("settings", {})
        for k, v in self.DEFAULTS.items():
            s.setdefault(k, copy.deepcopy(v))
        self.s = s
        self.dead = False
        self._jobs = set()
        self._off = None

        w = self.win = tk.Toplevel(app.root)
        w.withdraw()
        w.title(self.title)
        w.overrideredirect(True)
        w.configure(bg=T.BG)
        w.attributes("-topmost", bool(conf.get("topmost", True)))
        w.attributes("-alpha", float(conf.get("opacity", 0.94)))

        outer = tk.Frame(
            w, bg=T.BG, padx=10, pady=8, highlightthickness=1, highlightbackground=T.BORDER, highlightcolor=T.BORDER
        )
        outer.pack(fill="both", expand=True)
        hdr = tk.Frame(outer, bg=T.BG)
        hdr.pack(fill="x")
        self.title_lbl = tk.Label(hdr, text=self.title, bg=T.BG, fg=T.FG, font=T.FT)
        self.title_lbl.pack(side="left")
        self.summary = tk.Label(hdr, text="", bg=T.BG, fg=T.MUTED, font=T.FS)
        self.summary.pack(side="left", padx=(8, 0), pady=(2, 0))
        icon_button(hdr, "–", lambda e: self.hide())
        icon_button(hdr, "⋯", self.show_menu)
        if self.ADD_LABEL:
            icon_button(hdr, "+", lambda e: self.add_item())
        self.body = tk.Frame(outer, bg=T.BG)
        self.body.pack(fill="both", expand=True, pady=(4, 0))

        # Bound on the card window's bindtag, so they apply to every widget inside it.
        w.bind("<ButtonPress-1>", self._press)
        w.bind("<B1-Motion>", self._drag)
        w.bind("<ButtonRelease-1>", self._release)
        w.bind("<Button-3>", self.show_menu)

        self.render()
        self._place(animate)
        self.start()

    # ------------------------------------------------------------ identity
    @property
    def id(self):
        return self.conf["id"]

    @property
    def title(self):
        return self.conf.get("title") or self.NAME

    @property
    def visible(self):
        return bool(self.conf.get("visible", True))

    # ------------------------------------------------------------ hooks for subclasses
    def render(self):
        pass

    def update_view(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def status(self):
        return None, ""

    def menu_items(self, m):
        pass

    def settings_rows(self, f, row):
        return row, lambda: None

    def add_item(self):
        pass

    def refresh_now(self):
        pass

    # ------------------------------------------------------------ timers (cancelled when the card goes away)
    def after(self, ms, fn, *args):
        def run():
            self._jobs.discard(job)
            if not self.dead:
                fn(*args)

        job = self.win.after(int(ms), run)
        self._jobs.add(job)
        return job

    def cancel(self, job):
        if job in self._jobs:
            self._jobs.discard(job)
            self.win.after_cancel(job)

    # ------------------------------------------------------------ window placement
    def _place(self, animate):
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        x, y = self.conf.get("x"), self.conf.get("y")
        if x is None or y is None or not point_on_a_monitor(x + 20, y + 10):
            x, y = self.app.free_spot(w, h, exclude=self)
            self.conf["x"], self.conf["y"] = x, y
        if not self.visible:
            self.win.geometry(f"+{int(x)}+{int(y)}")
            return
        if animate:
            fade_in(self.win, int(x), int(y), float(self.conf.get("opacity", 0.94)))
        else:
            self.win.geometry(f"+{int(x)}+{int(y)}")
            self.win.deiconify()

    def rect(self):
        return self.win.winfo_x(), self.win.winfo_y(), self.win.winfo_width(), self.win.winfo_height()

    def _press(self, e):
        self._off = (e.x_root - self.win.winfo_x(), e.y_root - self.win.winfo_y())

    def _drag(self, e):
        if self._off:
            self.app.tip.hide()
            self.win.geometry(f"+{e.x_root - self._off[0]}+{e.y_root - self._off[1]}")

    def _release(self, e):
        if not self._off:
            return
        self._off = None
        x, y = self._snap(*self.rect())
        self.win.geometry(f"+{x}+{y}")
        self.conf["x"], self.conf["y"] = x, y
        self.app.save()

    def _snap(self, x, y, w, h):
        xs, ys = [], []
        area = work_area(x + w // 2, y + h // 2)
        if area:
            left, top, right, bottom = area
            xs += [left, right - w]
            ys += [top, bottom - h]
        for other in self.app.cards.values():
            if other is self or not other.visible:
                continue
            ox, oy, ow, oh = other.rect()
            xs += [ox, ox + ow + GAP, ox - w - GAP, ox + ow - w]
            ys += [oy, oy + oh + GAP, oy - h - GAP, oy + oh - h]

        def nearest(v, cands):
            best = min(cands, key=lambda c: abs(c - v), default=v)
            return best if abs(best - v) <= SNAP else v

        return nearest(x, xs), nearest(y, ys)

    # ------------------------------------------------------------ show / hide / remove
    def show(self):
        self.conf["visible"] = True
        self.win.deiconify()
        self.win.attributes("-topmost", bool(self.conf.get("topmost", True)))
        self.win.lift()
        self.app.save()
        self.app.cards_changed()

    def hide(self):
        self.app.tip.hide()
        self.conf["visible"] = False
        self.win.withdraw()
        self.app.save()
        self.app.cards_changed()

    def set_topmost(self, on):
        self.conf["topmost"] = bool(on)
        self.win.attributes("-topmost", self.conf["topmost"])
        self.app.save()

    def set_title(self, title):
        self.conf["title"] = title.strip() or self.NAME
        self.title_lbl.config(text=self.title)
        self.app.cards_changed()

    def destroy(self, animate=False, done=None):
        self.dead = True
        self.stop()
        for job in list(self._jobs):
            self.win.after_cancel(job)
        self._jobs.clear()

        def finish():
            self.win.destroy()
            if done:
                done()

        if animate and self.win.state() != "withdrawn":
            fade_out(self.win, finish)
        else:
            finish()

    # ------------------------------------------------------------ menus
    def show_menu(self, e=None):
        self.app.tip.hide()
        m = PopupMenu(self.app.root)
        self.menu_items(m)
        self.common_menu(m)
        x, y = (e.x_root, e.y_root) if e else (self.win.winfo_rootx(), self.win.winfo_rooty())
        m.popup(x, y)
        return "break"

    def common_menu(self, m):
        if m.items:
            m.separator()
        m.command("Card settings…", self.open_settings)
        m.check("Always on top", self.conf.get("topmost", True), lambda: self.set_topmost(not self.conf["topmost"]))
        m.command("Hide this card", self.hide)
        m.separator()
        m.command("All cards…", self.app.open_cards)
        m.command("Add a card…", self.app.open_add_card)
        m.separator()
        m.command("Quit Perch", self.app.quit)

    # ------------------------------------------------------------ settings window
    def open_settings(self):
        self.app.open_dialog(("settings", self.id), lambda: CardSettings(self))

    def notify(self, title, message):
        self.app.notify(title, message)


class CardSettings(Dialog):
    """Settings window for any card: the card's own fields, then the common CARD section."""

    def __init__(self, card):
        super().__init__(card.app.root, f"{card.title} settings", heading=f"{card.title} settings")
        self.card = card
        f = self.content
        f.columnconfigure(1, weight=1)
        row, commit_specific = card.settings_rows(f, 0)

        section(f, row, "Card", first=row == 0)
        self.v_title = tk.StringVar(value=card.title)
        ttk.Label(f, text="Title").grid(row=row + 1, column=0, sticky="w", pady=4, padx=(0, 12))
        ttk.Entry(f, textvariable=self.v_title).grid(row=row + 1, column=1, columnspan=2, sticky="ew", pady=4)
        self.v_top = tk.BooleanVar(value=bool(card.conf.get("topmost", True)))
        ttk.Checkbutton(f, text="Always on top of other windows", variable=self.v_top).grid(
            row=row + 2, column=0, columnspan=3, sticky="w", pady=2
        )
        self.v_op = tk.IntVar(value=int(round(float(card.conf.get("opacity", 0.94)) * 100)))
        ttk.Label(f, text="Opacity").grid(row=row + 3, column=0, sticky="w", pady=(6, 0))
        self.l_op = ttk.Label(f, width=5, anchor="e", style="Info.TLabel")
        self.l_op.grid(row=row + 3, column=2, sticky="e", pady=(6, 0))
        ttk.Scale(f, from_=30, to=100, variable=self.v_op, length=360, command=lambda v: self._live()).grid(
            row=row + 4, column=0, columnspan=3, sticky="ew", pady=(4, 0)
        )
        self._commit_specific = commit_specific

        from perch import APP_NAME, __version__

        self.footer_note(f"{APP_NAME} {__version__}")
        self.buttons(("Done", self.done, "primary"))
        self.win.protocol("WM_DELETE_WINDOW", self.done)
        self.win.bind("<Escape>", lambda e: self.done())
        self.win.bind("<Return>", lambda e: self.done())
        self._live()
        self.show(near=card.win)

    def _live(self):
        op = int(float(self.v_op.get()))
        self.l_op.config(text=f"{op}%")
        self.card.conf["opacity"] = op / 100
        self.card.win.attributes("-alpha", op / 100)

    def done(self):
        card = self.card
        card.set_title(self.v_title.get())
        card.set_topmost(self.v_top.get())
        self._commit_specific()
        self.close()
        card.app.save()
        card.refresh_now()


__all__ = ["Card", "CardSettings", "int_of"]

"""The Perch app: a hidden Tk root that hosts every card window, the tray icon and shared workers."""

import os
import queue
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor

from perch import APP_NAME, icons, style
from perch import config as C
from perch.cards import CARD_TYPES
from perch.components import HoverCard, Toast
from perch.tray import Tray
from perch.util import work_area

LEVEL_RANK = {"bad": 3, "warn": 2, "ok": 1, None: 0}


class App:
    def __init__(self, first_run=False):
        self.cfg = C.load_config()
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.cards, self.dialogs = {}, {}
        self.autostart_on = C.autostart_enabled()

        r = self.root = tk.Tk()
        r.withdraw()
        r.title(APP_NAME)
        style.apply(r)
        try:
            self._icon = icons.photo(64, master=r)
            r.iconphoto(True, self._icon)
        except Exception:
            pass
        self.tip = HoverCard(r)
        self.tray = Tray(self)

        for conf in list(self.cfg["cards"]):
            self._spawn(conf)
        r.after(150, self.drain)
        if not self.cards:
            r.after(500, self.open_cards)  # first run: show the empty card list with its "Add a card" tile
        elif first_run:
            r.after(
                2500,
                lambda: self.notify(
                    f"{APP_NAME} is running", "Drag cards anywhere. Right-click a card, or the tray icon, for options."
                ),
            )
        self.cards_changed(structure=True)

    # ------------------------------------------------------------ cards
    def _spawn(self, conf, animate=False):
        cls = CARD_TYPES.get(conf.get("type"))
        if cls is None:
            return None  # a card type from a newer version: leave its config untouched
        card = cls(self, conf, animate=animate)
        self.cards[card.id] = card
        return card

    def add_card(self, card_type, title, settings=None):
        conf = C.new_card(card_type, title, settings)
        self.cfg["cards"].append(conf)
        card = self._spawn(conf, animate=True)
        self.save()
        self.cards_changed(structure=True)
        return card

    def remove_card(self, card_id):
        card = self.cards.pop(card_id, None)
        self.cfg["cards"] = [c for c in self.cfg["cards"] if c["id"] != card_id]
        for key in [k for k in self.dialogs if isinstance(k, tuple) and k[-1] == card_id]:
            d = self.dialogs.pop(key)
            if d.win.winfo_exists():
                d.win.destroy()
        self.tip.hide()
        if card:
            card.destroy(animate=True)  # stops the card (which saves its state) before we delete it
        C.delete_state(card_id)
        self.save()
        self.cards_changed(structure=True)

    def free_spot(self, w, h, exclude=None):
        """Somewhere on the main screen that doesn't cover another card: right side, moving left, then down."""
        area = work_area(self.root.winfo_screenwidth() // 2, 10) or (
            0,
            0,
            self.root.winfo_screenwidth(),
            self.root.winfo_screenheight(),
        )
        left, top, right, bottom = area
        rects = [c.rect() for c in self.cards.values() if c is not exclude and c.visible]

        def clear(x, y):
            return all(
                x + w + 8 <= ox or x >= ox + ow + 8 or y + h + 8 <= oy or y >= oy + oh + 8 for ox, oy, ow, oh in rects
            )

        y = top + 60
        while y + 80 < bottom:
            x = right - w - 32
            while x > left:
                if clear(x, y):
                    return x, y
                x -= 40
            y += 60
        return right - w - 32, top + 60

    def toggle_all(self):
        if any(c.visible for c in self.cards.values()):
            for c in self.cards.values():
                if c.visible:
                    c.hide()
        else:
            for c in self.cards.values():
                c.show()
        self.cards_changed(structure=True)

    def refresh_all(self):
        for c in self.cards.values():
            c.refresh_now()

    def cards_changed(self, structure=False):
        """Called whenever a card's status, title or visibility changes."""
        worst, texts = None, []
        for c in self.cards.values():
            level, text = c.status()
            if LEVEL_RANK[level] > LEVEL_RANK[worst]:
                worst = level
            if text:
                texts.append(text)
        self.tray.update(worst, f"{APP_NAME} - " + " · ".join(texts) if texts else APP_NAME)
        home = self.dialogs.get("cards")
        if home and home.win.winfo_exists():
            home.rebuild() if structure else home.refresh_status()

    # ------------------------------------------------------------ windows
    def open_dialog(self, key, factory, replace=False):
        d = self.dialogs.get(key)
        if d and d.win.winfo_exists():
            if not replace:
                d.win.deiconify()
                d.win.lift()
                d.win.focus_force()
                return d
            d.win.destroy()
        d = self.dialogs[key] = factory()
        return d

    def open_cards(self):
        from perch.home import CardsWindow

        self.open_dialog("cards", lambda: CardsWindow(self))

    def open_add_card(self):
        from perch.home import AddCardDialog

        self.open_dialog("add", lambda: AddCardDialog(self), replace=True)

    # ------------------------------------------------------------ plumbing
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
                    pass  # a window was closed meanwhile
        except queue.Empty:
            pass
        self.root.after(150, self.drain)

    def save(self):
        try:
            C.save_config(self.cfg)
        except OSError:
            pass

    def notify(self, title, message):
        if not self.tray.notify(title, message):
            Toast(self.root, title, message)

    def set_autostart(self, on):
        try:
            C.set_autostart(on)
        except OSError as e:
            self.notify(APP_NAME, f"Couldn't change the startup setting: {e}")
        self.autostart_on = C.autostart_enabled()

    def quit(self):
        for c in self.cards.values():
            c.stop()
        self.save()
        self.tray.stop()
        self.root.destroy()
        os._exit(0)  # don't wait on in-flight network checks

    def run(self):
        self.root.mainloop()

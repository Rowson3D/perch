"""Shared UI building blocks, so every window has the same structure and look.

- Dialog       base for all windows: heading, content area, footer button bar
- confirm()    themed yes/no box (replaces tkinter.messagebox)
- alert()      themed message box
- PopupMenu    themed right-click / overflow menu (Tk's native menus can't be styled on Windows)
"""

import tkinter as tk
from tkinter import ttk

from perch import style
from perch import theme as T
from perch.util import point_on_a_monitor

BUTTON_STYLES = {"primary": "Accent.TButton", "secondary": "TButton", "danger": "Danger.TButton"}


class Dialog:
    """A styled window. Fill `self.content`, call `buttons(...)`, then `show()`.

    master=None creates a standalone root window (used by setup / uninstall).
    """

    def __init__(self, master, title, heading=None, subtitle=None, width=360):
        self.standalone = master is None
        self.win = w = tk.Tk() if self.standalone else tk.Toplevel(master)
        if self.standalone:
            style.apply(w)
        self.master = master
        self.width = width
        w.title(title)
        w.resizable(False, False)
        w.withdraw()
        w.configure(bg=T.SURFACE)

        body = ttk.Frame(w, padding=(T.PAD, T.PAD, T.PAD, 0))
        body.pack(fill="both", expand=True)
        if heading:
            ttk.Label(body, text=heading, style="Heading.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(body, text=subtitle, style="Muted.TLabel", wraplength=width, justify="left").pack(
                anchor="w", pady=(2, 0)
            )
        self.content = ttk.Frame(body)
        self.content.pack(fill="both", expand=True, pady=(T.SECTION if heading else 0, 0))
        ttk.Separator(w).pack(fill="x", pady=(T.PAD, 0))
        self.footer = ttk.Frame(w, padding=(T.PAD, 10))
        self.footer.pack(fill="x")
        w.bind("<Escape>", lambda e: self.close())
        w.protocol("WM_DELETE_WINDOW", self.close)

    def buttons(self, *specs):
        """specs: (label, command, kind) with kind in primary/secondary/danger. Primary goes rightmost."""
        made = {}
        for label, command, kind in reversed(specs):
            b = ttk.Button(self.footer, text=label, command=command, style=BUTTON_STYLES[kind])
            b.pack(side="right", padx=(T.GAP, 0))
            made[label] = b
        return made

    def footer_note(self, text, style_name="Hint.TLabel"):
        lbl = ttk.Label(self.footer, text=text, style=style_name)
        lbl.pack(side="left")
        return lbl

    def show(self, near=None, topmost=True):
        """near: a widget whose window we open beside; None centers on screen."""
        w = self.win
        w.update_idletasks()
        dw, dh = w.winfo_reqwidth(), w.winfo_reqheight()
        if near is not None and near.winfo_viewable():
            rx, ry, rw = near.winfo_rootx(), near.winfo_rooty(), near.winfo_width()
            x, y = rx - dw - 12, ry
            if not point_on_a_monitor(x + 10, y + 10):
                x = rx + rw + 12
            if not point_on_a_monitor(x + dw - 10, y + 10):
                x, y = rx, ry + 40
        else:
            x = (w.winfo_screenwidth() - dw) // 2
            y = (w.winfo_screenheight() - dh) // 3
        w.geometry(f"+{x}+{y}")
        style.dark_titlebar(w)
        w.deiconify()
        if topmost:
            w.attributes("-topmost", True)
        w.lift()
        w.focus_force()
        return self

    def close(self):
        if self.win.winfo_exists():
            self.win.destroy()


def _modal(d, master):
    d.show(near=None)
    d.win.grab_set()
    d.win.wait_window()


def confirm(master, title, message, ok="OK", cancel="Cancel", danger=False):
    d = Dialog(master, title, heading=title)
    ttk.Label(d.content, text=message, wraplength=340, justify="left").pack(anchor="w")
    result = {"ok": False}

    def yes():
        result["ok"] = True
        d.close()

    d.buttons((cancel, d.close, "secondary"), (ok, yes, "danger" if danger else "primary"))
    d.win.bind("<Return>", lambda e: yes())
    _modal(d, master)
    return result["ok"]


def alert(master, title, message, kind="info"):
    d = Dialog(master, title, heading=title)
    style_name = {"error": "Error.TLabel", "warning": "TLabel", "info": "TLabel"}[kind]
    ttk.Label(d.content, text=message, style=style_name, wraplength=340, justify="left").pack(anchor="w")
    d.buttons(("OK", d.close, "primary"))
    d.win.bind("<Return>", lambda e: d.close())
    _modal(d, master)


class PopupMenu:
    """Dark popup menu. Build with command()/check()/separator(), then popup(x, y)."""

    _open = None

    def __init__(self, root):
        self.root = root
        self.items = []

    def command(self, label, fn=None, enabled=True):
        self.items.append(("cmd", label, fn, enabled and fn is not None, None))
        return self

    def check(self, label, checked, fn):
        self.items.append(("check", label, fn, True, bool(checked)))
        return self

    def separator(self):
        self.items.append(("sep", None, None, False, None))
        return self

    def popup(self, x, y):
        if PopupMenu._open is not None:
            PopupMenu._open.close()
        PopupMenu._open = self
        w = self.win = tk.Toplevel(self.root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=T.TIP_BORDER)
        f = tk.Frame(w, bg=T.TIP_BG, padx=4, pady=4)
        f.pack(padx=1, pady=1)
        for kind, label, fn, enabled, checked in self.items:
            if kind == "sep":
                tk.Frame(f, height=1, bg=T.BORDER).pack(fill="x", padx=6, pady=4)
                continue
            mark = "✓" if checked else ""
            row = tk.Frame(f, bg=T.TIP_BG)
            row.pack(fill="x")
            parts = [
                tk.Label(row, text=mark, width=2, bg=T.TIP_BG, fg=T.ACCENT, font=T.FB),
                tk.Label(
                    row, text=label, anchor="w", bg=T.TIP_BG, fg=T.FG if enabled else T.GREY, font=T.F, padx=4, pady=4
                ),
            ]
            parts[0].pack(side="left", padx=(4, 0))
            parts[1].pack(side="left", fill="x", expand=True, padx=(0, 18))
            if enabled:
                widgets = (row, *parts)

                def hover(on, ws=widgets):
                    for x_ in ws:
                        x_.configure(bg=T.HOVER if on else T.TIP_BG)

                def run(e, fn=fn):
                    self.close()
                    fn()

                for x_ in widgets:
                    x_.bind("<Enter>", lambda e, h=hover: h(True))
                    x_.bind("<Leave>", lambda e, h=hover: h(False))
                    x_.bind("<ButtonRelease-1>", run)
                    x_.configure(cursor="hand2")
        w.update_idletasks()
        mw, mh = w.winfo_reqwidth(), w.winfo_reqheight()
        if not point_on_a_monitor(x + mw, y):
            x -= mw
        if not point_on_a_monitor(x, y + mh):
            y -= mh
        w.geometry(f"+{x}+{y}")
        w.bind("<Escape>", lambda e: self.close())
        self._had_focus = False
        w.bind("<FocusIn>", lambda e: setattr(self, "_had_focus", True))
        w.bind("<FocusOut>", self._focus_out)
        w.bind("<ButtonPress-1>", self._maybe_outside, add="+")
        w.focus_force()
        w.grab_set()

    def _focus_out(self, e):
        # Windows can send a stray FocusOut while the menu maps; only close once focus really left the app.
        if self._had_focus:
            self.win.after(60, self._check_focus)

    def _check_focus(self):
        try:
            focused = self.win.focus_get()
        except (KeyError, tk.TclError):
            focused = None
        if focused is None:
            self.close()

    def _maybe_outside(self, e):
        w = self.win
        inside = (
            w.winfo_rootx() <= e.x_root < w.winfo_rootx() + w.winfo_width()
            and w.winfo_rooty() <= e.y_root < w.winfo_rooty() + w.winfo_height()
        )
        if not inside:
            self.close()

    def close(self):
        if PopupMenu._open is self:
            PopupMenu._open = None
        w = getattr(self, "win", None)
        if w is not None and w.winfo_exists():
            try:
                w.grab_release()
            except tk.TclError:
                pass
            w.destroy()

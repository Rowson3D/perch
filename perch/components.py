"""Shared UI building blocks, so every window has the same structure and look.

- Dialog       base for all windows: heading, content area, footer button bar
- confirm()    themed yes/no box (replaces tkinter.messagebox)
- alert()      themed message box
- PopupMenu    themed right-click / overflow menu (Tk's native menus can't be styled on Windows)
- ListManager  the standard "list of things + Add/Edit/Remove/Move" window
- HoverCard    the floating details card shown when hovering a row
- Toast        fallback notification when the tray is unavailable
- icon_button, form_row, spin, fade_in / fade_out
"""

import tkinter as tk
from tkinter import ttk

from perch import style
from perch import theme as T
from perch.util import point_on_a_monitor


# ------------------------------------------------------------------ small helpers
def icon_button(parent, text, command, bg=T.BG):
    """Borderless glyph button used in card headers (+, ⋯, –)."""
    b = tk.Label(parent, text=text, bg=bg, fg=T.MUTED, font=(T.FONT_SEMI, 11), cursor="hand2", padx=5)
    b.pack(side="right")
    b.bind("<Enter>", lambda e: b.config(fg=T.FG))
    b.bind("<Leave>", lambda e: b.config(fg=T.MUTED))

    def click(e):
        command(e)
        return "break"  # don't start a drag

    b.bind("<Button-1>", click)
    return b


def form_row(parent, row, label, widget, hint=None):
    ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4, padx=(0, 12))
    widget.grid(row=row, column=1, sticky="ew", pady=4)
    if hint is not None:
        hint.grid(row=row, column=2, sticky="w", padx=(T.GAP, 0))


def spin(parent, var, lo, hi, width=4):
    return ttk.Spinbox(parent, from_=lo, to=hi, textvariable=var, width=width)


def section(parent, row, text, first=False, columns=3):
    ttk.Label(parent, text=text.upper(), style="Section.TLabel").grid(
        row=row, column=0, columnspan=columns, sticky="w", pady=(0 if first else T.SECTION, 6)
    )


def int_of(var, lo, hi, default):
    try:
        return max(lo, min(hi, int(float(var.get()))))
    except (ValueError, tk.TclError):
        return default


def ease_out(t):
    return 1 - (1 - t) ** 3


def animate(win, ms, step, done=None, frames=14):
    """Call step(t) for t in (0, 1] over `ms`, then done()."""
    delay = max(10, ms // frames)

    def tick(i=1):
        if not win.winfo_exists():
            return
        step(i / frames)
        if i < frames:
            win.after(delay, tick, i + 1)
        elif done:
            done()

    tick()


def fade_in(win, x, y, alpha):
    """Show a new card by fading it in."""
    win.attributes("-alpha", 0.0)
    win.geometry(f"+{x}+{y}")
    win.deiconify()
    animate(win, 220, lambda t: win.attributes("-alpha", alpha * ease_out(t)))


def fade_out(win, done):
    """Hide a removed card by fading it out."""
    a0 = float(win.attributes("-alpha"))
    animate(win, 220, lambda t: win.attributes("-alpha", max(0.0, a0 * (1 - t))), done)


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
        self.heading_lbl = self.subtitle_lbl = None
        if heading:
            self.heading_lbl = ttk.Label(body, text=heading, style="Heading.TLabel")
            self.heading_lbl.pack(anchor="w")
        if subtitle:
            self.subtitle_lbl = ttk.Label(body, text=subtitle, style="Muted.TLabel", wraplength=width, justify="left")
            self.subtitle_lbl.pack(anchor="w", pady=(2, 0))
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


class ListManager(Dialog):
    """Standard list window: a list on the left, Add / Edit / Remove / Move on the right.

    The owner supplies callbacks; the dialog never touches data itself.
    """

    def __init__(self, master, title, subtitle, items, label, on_add, on_edit, on_remove, on_move, near=None):
        super().__init__(master, title, heading=title, subtitle=subtitle)
        self.items, self.label = items, label
        self.on_edit, self.on_remove, self.on_move = on_edit, on_remove, on_move
        f = self.content
        self.lb = tk.Listbox(f, width=56, height=9, activestyle="none", exportselection=False)
        self.lb.grid(row=0, column=0, rowspan=6, sticky="nsew", padx=(0, 12))
        self.lb.bind("<Double-1>", lambda e: self._edit())
        actions = [
            ("Add…", on_add),
            ("Edit…", self._edit),
            ("Remove", self._remove),
            ("Move up", lambda: self._move(-1)),
            ("Move down", lambda: self._move(1)),
        ]
        for i, (text, cmd) in enumerate(actions):
            ttk.Button(f, text=text, command=cmd, width=11).grid(row=i, column=1, sticky="ew", pady=(0, 6))
        self.buttons(("Done", self.close, "primary"))
        self.refresh()
        self.show(near=near)

    def refresh(self):
        if not self.win.winfo_exists():
            return
        self.lb.delete(0, "end")
        for item in self.items():
            self.lb.insert("end", "  " + self.label(item))

    def _sel(self):
        s = self.lb.curselection()
        return s[0] if s else None

    def _edit(self):
        i = self._sel()
        if i is not None:
            self.on_edit(i)

    def _remove(self):
        i = self._sel()
        if i is not None:
            self.on_remove(i, self.win)

    def _move(self, d):
        i = self._sel()
        if i is None or not 0 <= i + d < len(self.items()):
            return
        self.on_move(i, d)
        self.refresh()
        self.lb.selection_set(i + d)


class HoverCard:
    """Floating details panel shown beside a card while a row is hovered."""

    def __init__(self, root):
        self.root, self.win, self.key, self._job = root, None, None, None
        self._anchor = self._build = None

    def show(self, key, card_win, row_widget, build):
        """build(add_line) fills the panel; add_line(text, fg=, font=, pady=)."""
        if self._job:
            self.root.after_cancel(self._job)
            self._job = None
        if self.key == key and self.win:
            return
        self.key, self._anchor, self._build = key, (card_win, row_widget), build
        self.refresh()

    def refresh(self):
        if not self.key:
            return
        card_win, row = self._anchor
        if not (card_win.winfo_exists() and row.winfo_exists()):
            return self.hide()
        if not self.win:
            self.win = tk.Toplevel(self.root)
            self.win.overrideredirect(True)
            self.win.attributes("-topmost", True)
            self.win.configure(bg=T.TIP_BORDER)
        for c in self.win.winfo_children():
            c.destroy()
        f = tk.Frame(self.win, bg=T.TIP_BG, padx=12, pady=10)
        f.pack(padx=1, pady=1)

        def add_line(text, fg=T.FG, font=T.F, pady=0):
            tk.Label(f, text=text, bg=T.TIP_BG, fg=fg, font=font, justify="left", anchor="w").pack(
                anchor="w", pady=pady
            )

        if self._build(add_line) is False:
            return self.hide()
        self.win.update_idletasks()
        w = self.win.winfo_reqwidth()
        y = row.winfo_rooty()
        x = card_win.winfo_x() - w - 8
        if not point_on_a_monitor(x + 5, y + 5):
            x = card_win.winfo_x() + card_win.winfo_width() + 8
        self.win.geometry(f"+{x}+{y}")

    def is_showing(self, key):
        return self.key == key and self.win is not None

    def hide_soon(self):
        if self._job:
            self.root.after_cancel(self._job)
        self._job = self.root.after(150, self.hide)

    def hide(self):
        self._job = None
        self.key = None
        if self.win:
            self.win.destroy()
            self.win = None


class Toast:
    """Fallback notification when the tray icon isn't available."""

    def __init__(self, root, title, message):
        w = tk.Toplevel(root)
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.configure(bg=T.TIP_BORDER)
        f = tk.Frame(w, bg=T.TIP_BG, padx=14, pady=10)
        f.pack(padx=1, pady=1)
        tk.Label(f, text=title, bg=T.TIP_BG, fg=T.FG, font=T.FT).pack(anchor="w")
        tk.Label(f, text=message, bg=T.TIP_BG, fg=T.MUTED, font=T.F, wraplength=300, justify="left").pack(anchor="w")
        w.update_idletasks()
        x = root.winfo_screenwidth() - w.winfo_reqwidth() - 24
        y = root.winfo_screenheight() - w.winfo_reqheight() - 72
        w.geometry(f"+{x}+{y}")
        w.bind("<Button-1>", lambda e: w.destroy())
        w.after(8000, w.destroy)


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

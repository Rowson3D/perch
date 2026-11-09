"""The one ttk theme used by every window, built from the tokens in theme.py."""

import ctypes
import tkinter as tk
from tkinter import ttk

from perch import theme as T

THEME_NAME = "perch-dark"


def dark_titlebar(win: tk.Misc) -> None:
    """Ask Windows to draw this window's title bar dark (Windows 10 20H1+ / 11)."""
    try:
        win.update_idletasks()
        hwnd = int(win.wm_frame(), 16)
        on = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new id, then pre-20H1 id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
                break
    except Exception:
        pass


def _make_images(root):
    """Checkbox and slider artwork drawn from the tokens (ttk's stock ones can't be recolored well)."""
    from PIL import Image, ImageDraw, ImageTk

    scale = max(1.0, root.winfo_fpixels("1i") / 96)
    n = round(16 * scale)  # indicator / knob size in pixels
    k = 4  # supersampling factor

    def finish(img, w, h):
        return ImageTk.PhotoImage(img.resize((w, h), Image.LANCZOS), master=root)

    def checkbox(fill, outline, tick):
        gap = round(8 * scale)  # space between box and label
        img = Image.new("RGBA", ((n + gap) * k, n * k), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        s = n * k
        d.rounded_rectangle([k, k, s - k - 1, s - k - 1], radius=4 * k * scale, fill=fill, outline=outline, width=k)
        if tick:
            pts = [(s * 0.27, s * 0.52), (s * 0.44, s * 0.69), (s * 0.75, s * 0.33)]
            d.line(pts, fill=T.ON_ACCENT, width=round(2.2 * k * scale), joint="curve")
        return finish(img, n + gap, n)

    def knob(fill):
        img = Image.new("RGBA", (n * k, n * k), (0, 0, 0, 0))
        ImageDraw.Draw(img).ellipse([k, k, n * k - k - 1, n * k - k - 1], fill=fill)
        return finish(img, n, n)

    def trough():
        w = n * 2
        img = Image.new("RGBA", (w * k, n * k), (0, 0, 0, 0))
        bar = 2 * k * scale
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, n * k / 2 - bar, w * k - 1, n * k / 2 + bar], radius=bar, fill=T.TRACK)
        return finish(img, w, n)

    return {
        "cb_off": checkbox(T.FIELD, T.TIP_BORDER, False),
        "cb_hover": checkbox(T.HOVER, T.MUTED, False),
        "cb_on": checkbox(T.ACCENT, T.ACCENT, True),
        "cb_on_hover": checkbox(T.ACCENT_HOVER, T.ACCENT_HOVER, True),
        "cb_disabled": checkbox(T.SURFACE, T.BORDER, False),
        "knob": knob(T.ACCENT),
        "knob_hover": knob(T.ACCENT_HOVER),
        "trough": trough(),
        "border": n,
    }


def apply(root: tk.Misc) -> ttk.Style:
    s = ttk.Style(root)
    if THEME_NAME not in s.theme_names():
        s.theme_create(THEME_NAME, parent="clam")
    s.theme_use(THEME_NAME)

    s.configure(
        ".",
        background=T.SURFACE,
        foreground=T.FG,
        font=T.F,
        bordercolor=T.BORDER,
        lightcolor=T.SURFACE,
        darkcolor=T.SURFACE,
        troughcolor=T.TRACK,
        fieldbackground=T.FIELD,
        selectbackground=T.ACCENT_DIM,
        selectforeground=T.FG,
        insertcolor=T.FG,
        focuscolor=T.SURFACE,
    )
    s.map(".", foreground=[("disabled", T.GREY)])

    # Labels
    s.configure("TLabel", background=T.SURFACE, foreground=T.FG)
    for name, opts in {
        "Muted": {"foreground": T.MUTED},
        "Hint": {"foreground": T.MUTED, "font": T.FS},
        "Section": {"foreground": T.MUTED, "font": T.FB},
        "Heading": {"font": T.FH},
        "Display": {"font": T.FD},
        "Error": {"foreground": T.RED},
        "Success": {"foreground": T.GREEN},
        "Info": {"foreground": T.ACCENT},
    }.items():
        s.configure(f"{name}.TLabel", **opts)
    s.configure("Card.TFrame", background=T.ROW)
    s.configure("Card.TLabel", background=T.ROW)
    s.configure("TSeparator", background=T.BORDER)

    # Buttons: secondary (default) and primary (Accent)
    flat = {"relief": "flat", "borderwidth": 1, "padding": (14, 5), "focusthickness": 0}
    s.configure(
        "TButton",
        background=T.RAISED,
        foreground=T.FG,
        bordercolor=T.BORDER,
        lightcolor=T.RAISED,
        darkcolor=T.RAISED,
        **flat,
    )
    s.map(
        "TButton",
        background=[("disabled", T.SURFACE), ("pressed", T.PRESSED), ("active", T.HOVER)],
        lightcolor=[("disabled", T.SURFACE), ("pressed", T.PRESSED), ("active", T.HOVER)],
        darkcolor=[("disabled", T.SURFACE), ("pressed", T.PRESSED), ("active", T.HOVER)],
        bordercolor=[("focus", T.ACCENT)],
    )
    s.configure(
        "Accent.TButton",
        background=T.ACCENT,
        foreground=T.ON_ACCENT,
        bordercolor=T.ACCENT,
        lightcolor=T.ACCENT,
        darkcolor=T.ACCENT,
        font=T.FB,
        **flat,
    )
    s.map(
        "Accent.TButton",
        background=[("disabled", T.RAISED), ("pressed", T.ACCENT), ("active", T.ACCENT_HOVER)],
        lightcolor=[("disabled", T.RAISED), ("active", T.ACCENT_HOVER)],
        darkcolor=[("disabled", T.RAISED), ("active", T.ACCENT_HOVER)],
        bordercolor=[("disabled", T.RAISED), ("active", T.ACCENT_HOVER)],
        foreground=[("disabled", T.GREY)],
    )

    s.configure(
        "Danger.TButton",
        background=T.RED,
        foreground=T.ON_ACCENT,
        bordercolor=T.RED,
        lightcolor=T.RED,
        darkcolor=T.RED,
        font=T.FB,
        **flat,
    )
    s.map(
        "Danger.TButton",
        background=[("active", "#f37477")],
        lightcolor=[("active", "#f37477")],
        darkcolor=[("active", "#f37477")],
        bordercolor=[("active", "#f37477")],
    )

    # Text inputs
    field = {
        "fieldbackground": T.FIELD,
        "foreground": T.FG,
        "bordercolor": T.BORDER,
        "lightcolor": T.FIELD,
        "darkcolor": T.FIELD,
        "insertcolor": T.FG,
        "padding": 5,
    }
    field_map = {
        "bordercolor": [("focus", T.ACCENT)],
        "lightcolor": [("focus", T.FIELD)],
        "fieldbackground": [("disabled", T.SURFACE), ("readonly", T.FIELD)],
        "foreground": [("disabled", T.GREY)],
    }
    s.configure("TEntry", **field)
    s.map("TEntry", **field_map)
    s.configure("TSpinbox", background=T.FIELD, arrowcolor=T.MUTED, arrowsize=11, **field)
    s.map("TSpinbox", **field_map)
    s.configure("TCombobox", background=T.FIELD, arrowcolor=T.MUTED, arrowsize=12, **field)
    s.map(
        "TCombobox",
        **field_map,
        selectbackground=[("readonly", T.FIELD)],
        selectforeground=[("readonly", T.FG)],
        background=[("active", T.HOVER)],
    )
    root.option_add("*TCombobox*Listbox.background", T.FIELD)
    root.option_add("*TCombobox*Listbox.foreground", T.FG)
    root.option_add("*TCombobox*Listbox.selectBackground", T.ACCENT_DIM)
    root.option_add("*TCombobox*Listbox.selectForeground", T.FG)
    root.option_add("*TCombobox*Listbox.font", f"{{{T.FONT}}} {T.F[1]}")
    root.option_add("*TCombobox*Listbox.borderWidth", 0)

    img = root._gw_images = _make_images(root)  # keep references alive
    s.element_create(
        "gw.Checkbutton.indicator",
        "image",
        img["cb_off"],
        ("disabled", img["cb_disabled"]),
        ("selected", "active", img["cb_on_hover"]),
        ("selected", img["cb_on"]),
        ("active", img["cb_hover"]),
        sticky="",
    )
    s.layout(
        "TCheckbutton",
        [
            (
                "Checkbutton.padding",
                {
                    "sticky": "nswe",
                    "children": [
                        ("gw.Checkbutton.indicator", {"side": "left", "sticky": ""}),
                        ("Checkbutton.label", {"side": "left", "sticky": "w"}),
                    ],
                },
            )
        ],
    )
    s.element_create("gw.Horizontal.Scale.trough", "image", img["trough"], border=(img["border"] // 2, 0), sticky="ew")
    s.element_create("gw.Horizontal.Scale.slider", "image", img["knob"], ("active", img["knob_hover"]), sticky="")
    s.layout(
        "Horizontal.TScale",
        [
            (
                "gw.Horizontal.Scale.trough",
                {
                    "sticky": "ew",
                    "children": [
                        ("gw.Horizontal.Scale.slider", {"side": "left", "sticky": ""}),
                    ],
                },
            )
        ],
    )

    # Checkboxes
    s.configure(
        "TCheckbutton",
        background=T.SURFACE,
        foreground=T.FG,
        indicatorbackground=T.FIELD,
        indicatorforeground=T.ON_ACCENT,
        upperbordercolor=T.TIP_BORDER,
        lowerbordercolor=T.TIP_BORDER,
        indicatormargin=(0, 0, 8, 0),
        padding=(0, 2),
    )
    s.map(
        "TCheckbutton",
        background=[("active", T.SURFACE)],
        indicatorbackground=[("disabled", T.SURFACE), ("selected", T.ACCENT), ("active", T.HOVER)],
        upperbordercolor=[("selected", T.ACCENT)],
        lowerbordercolor=[("selected", T.ACCENT)],
    )
    s.configure("Card.TCheckbutton", background=T.ROW)
    s.map("Card.TCheckbutton", background=[("active", T.ROW)])

    # Sliders (artwork comes from the image elements above; transparent parts show this background)
    s.configure("Horizontal.TScale", background=T.SURFACE)

    # Classic tk widgets used in dialogs
    root.option_add("*Listbox.background", T.FIELD)
    root.option_add("*Listbox.foreground", T.FG)
    root.option_add("*Listbox.selectBackground", T.ACCENT_DIM)
    root.option_add("*Listbox.selectForeground", T.FG)
    root.option_add("*Listbox.highlightThickness", 1)
    root.option_add("*Listbox.highlightBackground", T.BORDER)
    root.option_add("*Listbox.highlightColor", T.ACCENT)
    root.option_add("*Listbox.borderWidth", 0)
    root.option_add("*Listbox.font", f"{{{T.FONT}}} {T.F[1]}")
    root.option_add("*Toplevel.background", T.SURFACE)
    return s

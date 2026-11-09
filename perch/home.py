"""The card list (every card with its status, settings, show/hide and remove) and the "Add a card" window."""

import tkinter as tk
from tkinter import ttk

from perch import icons
from perch import theme as T
from perch.cards import CARD_TYPES, COMING_SOON
from perch.components import Dialog, confirm
from perch.util import clip

LEVEL_COLOR = {"ok": T.GREEN, "warn": T.AMBER, "bad": T.RED, None: T.MUTED}
TILE_W = 236
COLUMNS = 2


def text_area(parent, height=4, width=40):
    """Multi-line input styled like ttk.Entry."""
    return tk.Text(
        parent,
        height=height,
        width=width,
        bg=T.FIELD,
        fg=T.FG,
        insertbackground=T.FG,
        relief="flat",
        font=T.F,
        padx=8,
        pady=6,
        highlightthickness=1,
        highlightbackground=T.BORDER,
        highlightcolor=T.ACCENT,
        selectbackground=T.ACCENT_DIM,
        selectforeground=T.FG,
        wrap="none",
        undo=True,
    )


def dashed_tile(parent, text, command, height):
    """The "Add a card" tile: a dashed outline you can click."""
    c = tk.Canvas(parent, width=TILE_W, height=height, bg=T.SURFACE, highlightthickness=0, cursor="hand2")
    rect = c.create_rectangle(2, 2, TILE_W - 2, height - 2, outline=T.TIP_BORDER, dash=(4, 4), width=2)
    plus = c.create_text(TILE_W / 2, height / 2 - 12, text="+", fill=T.MUTED, font=(T.FONT, 22))
    label = c.create_text(TILE_W / 2, height / 2 + 18, text=text, fill=T.MUTED, font=T.FB)

    def hover(on):
        color = T.ACCENT if on else T.MUTED
        c.itemconfig(rect, outline=T.ACCENT if on else T.TIP_BORDER)
        c.itemconfig(plus, fill=color)
        c.itemconfig(label, fill=color)

    c.bind("<Enter>", lambda e: hover(True))
    c.bind("<Leave>", lambda e: hover(False))
    c.bind("<Button-1>", lambda e: command())
    return c


class CardsWindow(Dialog):
    """Every card on your desktop as a tile (status, settings, show/hide, remove), plus a tile to add one."""

    def __init__(self, app):
        super().__init__(app.root, "Your cards", heading="Your cards", subtitle=" ", width=TILE_W * COLUMNS)
        self.app = app
        self.subtitle = self.subtitle_lbl
        self.tiles = ttk.Frame(self.content)
        self.tiles.pack(fill="both", expand=True)
        self.tiles.columnconfigure(tuple(range(COLUMNS)), uniform="tile", minsize=TILE_W)
        self._images = []
        self.status_labels = {}
        self.footer_note("You can drag cards anywhere. They snap to the screen edges and to each other.")
        self.buttons(("Done", self.close, "primary"))
        self.rebuild()
        self.show()

    def rebuild(self):
        if not self.win.winfo_exists():
            return
        for w in self.tiles.winfo_children():
            w.destroy()
        self._images, self.status_labels = [], {}
        cards = list(self.app.cards.values())
        n = len(cards)
        if n:
            self.subtitle.config(text=f"{n} card{'s' * (n != 1)} on your desktop.")
        else:
            self.subtitle.config(text="No cards yet. Add one and it will appear on your desktop.")
        for i, card in enumerate(cards):
            self._tile(card).grid(row=i // COLUMNS, column=i % COLUMNS, padx=(0, T.GAP), pady=(0, T.GAP), sticky="nsew")
        tile = dashed_tile(self.tiles, "Add a card", self.app.open_add_card, 132 if n else 150)
        tile.grid(row=n // COLUMNS, column=n % COLUMNS, padx=(0, T.GAP), pady=(0, T.GAP), sticky="nw")
        self.refresh_status()

    def _tile(self, card):
        f = ttk.Frame(self.tiles, style="Card.TFrame", padding=12)
        head = ttk.Frame(f, style="Card.TFrame")
        head.pack(fill="x")
        img = icons.card_photo(card.TYPE, 36, master=self.win)
        self._images.append(img)
        ttk.Label(head, image=img, style="Card.TLabel").pack(side="left", padx=(0, 10))
        names = ttk.Frame(head, style="Card.TFrame")
        names.pack(side="left", fill="x")
        ttk.Label(names, text=clip(card.title, 22), style="CardTitle.TLabel").pack(anchor="w")
        kind = f"{card.NAME} card"
        hidden = "" if card.visible else "  ·  hidden"
        ttk.Label(names, text=kind + hidden, style="CardMuted.TLabel").pack(anchor="w")
        status = ttk.Label(f, text="", style="Card.TLabel", font=T.FB)
        status.pack(anchor="w", pady=(10, 10))
        self.status_labels[card.id] = status
        btns = ttk.Frame(f, style="Card.TFrame")
        btns.pack(fill="x")
        ttk.Button(btns, text="Settings", style="Small.TButton", command=card.open_settings).pack(side="left")
        ttk.Button(
            btns, text="Hide" if card.visible else "Show", style="Small.TButton", command=lambda: self._toggle(card)
        ).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Remove", style="SmallDanger.TButton", command=lambda: self._remove(card)).pack(
            side="right"
        )
        return f

    def refresh_status(self):
        if not self.win.winfo_exists():
            return
        for cid, lbl in self.status_labels.items():
            card = self.app.cards.get(cid)
            if card and lbl.winfo_exists():
                level, text = card.status()
                lbl.config(text=text or "Nothing added yet", foreground=LEVEL_COLOR[level])

    def _toggle(self, card):
        card.hide() if card.visible else card.show()
        self.rebuild()

    def _remove(self, card):
        extra = " and its uptime history" if card.TYPE == "sites" else ""
        if confirm(
            self.win,
            "Remove card?",
            f"“{card.title}” and its settings{extra} will be deleted. This can't be undone.",
            ok="Remove",
            danger=True,
        ):
            self.app.remove_card(card.id)


class AddCardDialog(Dialog):
    """Pick a card type, name it, do a quick setup, and add it to the desktop."""

    def __init__(self, app):
        super().__init__(
            app.root,
            "Add a card",
            heading="Add a card",
            subtitle="Choose a card type. You can add as many cards as you like.",
            width=TILE_W * COLUMNS,
        )
        self.app = app
        self.heading, self.subtitle = self.heading_lbl, self.subtitle_lbl
        self._images = []
        self.page = ttk.Frame(self.content)
        self.page.pack(fill="both", expand=True)
        self.page.columnconfigure(tuple(range(COLUMNS)), uniform="tile", minsize=TILE_W)
        self.btns = {}
        self.pick()
        self.show()

    def _clear(self):
        for w in self.page.winfo_children():
            w.destroy()
        for w in self.footer.winfo_children():
            w.destroy()
        self._images = []

    # ------------------------------------------------------------ step 1: choose a type
    def pick(self):
        self._clear()
        self.heading.config(text="Add a card")
        self.subtitle.config(text="Choose a card type. You can add as many cards as you like.")
        types = [(cls.TYPE, cls.NAME, cls.DESCRIPTION, cls) for cls in CARD_TYPES.values()]
        types += [(t, n, d, None) for t, n, d in COMING_SOON]
        for i, (t, name, desc, cls) in enumerate(types):
            self._type_tile(t, name, desc, cls).grid(
                row=i // COLUMNS, column=i % COLUMNS, padx=(0, T.GAP), pady=(0, T.GAP), sticky="nsew"
            )
        self.footer_note("More card types are coming.")
        self.buttons(("Cancel", self.close, "secondary"))

    def _type_tile(self, t, name, desc, cls):
        f = ttk.Frame(self.page, style="Card.TFrame", padding=12)
        head = ttk.Frame(f, style="Card.TFrame")
        head.pack(fill="x")
        img = icons.card_photo(t, 36, master=self.win)
        self._images.append(img)
        ttk.Label(head, image=img, style="Card.TLabel").pack(side="left", padx=(0, 10))
        ttk.Label(head, text=name, style="CardTitle.TLabel", foreground=T.FG if cls else T.MUTED).pack(side="left")
        if not cls:
            ttk.Label(head, text="SOON", style="CardBadge.TLabel").pack(side="right")
        ttk.Label(f, text=desc, style="CardMuted.TLabel", wraplength=TILE_W - 24, justify="left").pack(
            anchor="w", pady=(8, 10)
        )
        if cls:
            ttk.Button(f, text="Add", style="SmallAccent.TButton", command=lambda: self.setup(cls)).pack(anchor="w")
        return f

    # ------------------------------------------------------------ step 2: name + quick setup
    def setup(self, cls):
        self._clear()
        self.heading.config(text=f"Add a {cls.NAME} card")
        self.subtitle.config(text=cls.DESCRIPTION)
        f = ttk.Frame(self.page)
        f.grid(row=0, column=0, columnspan=COLUMNS, sticky="ew")
        f.columnconfigure(1, weight=1)
        taken = {c.title for c in self.app.cards.values()}
        title = cls.NAME
        n = 2
        while title in taken:
            title, n = f"{cls.NAME} {n}", n + 1
        self.v_title = tk.StringVar(value=title)
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w", padx=(0, 12), pady=4)
        ttk.Entry(f, textvariable=self.v_title).grid(row=0, column=1, sticky="ew", pady=4)
        self.collect = lambda: {}
        if cls.TYPE == "sites":
            ttk.Label(f, text="WHICH SITES?", style="Section.TLabel").grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(T.SECTION, 4)
            )
            ttk.Label(
                f,
                text="Paste one address per line. You can add more and set admin and repo links later.",
                style="Hint.TLabel",
                wraplength=TILE_W * 2 - 20,
            ).grid(row=2, column=0, columnspan=2, sticky="w")
            box = text_area(f, height=5)
            box.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            box.focus_set()

            def collect_sites():
                from perch.cards.sites import sites_from_text

                return {"sites": sites_from_text(box.get("1.0", "end"))}

            self.collect = collect_sites
        elif cls.TYPE == "gpus":
            self.v_local = tk.BooleanVar(value=True)
            ttk.Checkbutton(f, text="Start with this PC's GPUs", variable=self.v_local).grid(
                row=1, column=0, columnspan=2, sticky="w", pady=(T.SECTION, 0)
            )
            ttk.Label(f, text="Add other machines afterwards with the card's  +  button.", style="Hint.TLabel").grid(
                row=2, column=0, columnspan=2, sticky="w", pady=(2, 0)
            )
        self.status = self.footer_note("")
        self.btns = self.buttons(("Back", self.pick, "secondary"), ("Add card", lambda: self.create(cls), "primary"))
        self.win.bind("<Return>", lambda e: self.create(cls) if cls.TYPE != "sites" else None)

    def create(self, cls):
        title = self.v_title.get().strip() or cls.NAME
        settings = self.collect()
        if cls.TYPE == "gpus" and self.v_local.get():
            for b in self.btns.values():
                b.state(["disabled"])
            self.status.config(text="Looking for this PC's GPUs…")

            def find():
                from perch.sources import fetch_local

                return fetch_local()

            def done(out):
                ok, data = out
                hosts = []
                if ok and data["gpus"]:
                    from perch.cards.gpus import local_host

                    hosts = [local_host(data)]
                self._finish(cls, title, {"hosts": hosts})

            self.app.run_bg(find, done)
            return
        self._finish(cls, title, settings)

    def _finish(self, cls, title, settings):
        self.close()
        self.app.add_card(cls.TYPE, title, settings)

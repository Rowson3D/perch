"""Windows for connecting Vercel and Cloudflare accounts, so the Sites card can show visitor numbers."""

import tkinter as tk
import webbrowser
from tkinter import ttk

from perch import traffic as TR
from perch import vault
from perch.components import Dialog, ListManager, alert, confirm, form_row
from perch.util import clip


def sources_of(app):
    """Every project/zone across connected accounts, as (account, source) pairs."""
    return [(a, s) for a in app.cfg.get("accounts", []) for s in a.get("sources", [])]


def source_label(account, source):
    return f"{TR.PROVIDERS[source['provider']]}: {source['name']}"


def match_all_sites(app, account):
    """Link every site (in every Sites card) that has no traffic source yet to this account, by domain.
    Returns (matched, total)."""
    matched = total = 0
    for card in app.cards.values():
        if card.TYPE != "sites":
            continue
        for site in card.sites:
            total += 1
            if site.get("traffic"):
                continue
            src = TR.match_source(site["url"], account.get("sources", []))
            if src:
                site["traffic"] = TR.link(src, account["id"])
                matched += 1
        card.traffic_changed()
    return matched, total


class ConnectDialog(Dialog):
    def __init__(self, app, account=None):
        super().__init__(
            app.root,
            "Connect traffic",
            heading="Reconnect account" if account else "Connect a traffic account",
            subtitle="Perch reads visitor numbers for your sites from the service that hosts them.",
            width=400,
        )
        self.app, self.account, self.sources = app, account, None
        f = self.content
        f.columnconfigure(1, weight=1)
        self.v_provider = tk.StringVar(value=(account or {}).get("provider", "vercel"))
        row = ttk.Frame(f)
        row.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))
        for key, name in TR.PROVIDERS.items():
            rb = ttk.Radiobutton(row, text=name, variable=self.v_provider, value=key, command=self.on_provider)
            rb.pack(side="left", padx=(0, 16))
            if account:
                rb.state(["disabled"])
        self.help = ttk.Label(f, style="Hint.TLabel", wraplength=400, justify="left")
        self.help.grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Button(f, text="Open the token page", command=self.open_page).grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 12)
        )
        self.v_token = tk.StringVar()
        self.e_token = ttk.Entry(f, textvariable=self.v_token, show="•")
        form_row(f, 3, "Token", self.e_token)
        self.v_name = tk.StringVar(value=(account or {}).get("name", ""))
        form_row(
            f, 4, "Name", ttk.Entry(f, textvariable=self.v_name), ttk.Label(f, text="optional", style="Hint.TLabel")
        )
        ttk.Label(
            f,
            text="The token is kept in Windows Credential Manager, not in Perch's settings file.",
            style="Hint.TLabel",
        ).grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 0))
        test = ttk.Frame(f)
        test.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        self.btn_test = ttk.Button(test, text="Check token", command=self.check)
        self.btn_test.pack(side="left")
        self.status = ttk.Label(test, text="", style="Muted.TLabel", wraplength=260, justify="left")
        self.status.pack(side="left", padx=(12, 0))
        self.buttons(("Cancel", self.close, "secondary"), ("Save", self.save, "primary"))
        self.win.bind("<Return>", lambda e: self.check())
        self.on_provider()
        self.show()
        self.e_token.focus_set()

    def provider(self):
        return self.v_provider.get()

    def on_provider(self):
        self.help.config(text=TR.TOKEN_HELP[self.provider()])
        self.sources = None
        self.status.config(text="")

    def open_page(self):
        webbrowser.open(TR.TOKEN_PAGES[self.provider()])

    def check(self):
        token = self.v_token.get().strip()
        if not token:
            alert(self.win, "Missing token", "Paste the token you created first.", "warning")
            return
        provider = self.provider()
        self.btn_test.state(["disabled"])
        self.status.config(text="Checking…", style="Muted.TLabel")

        def done(out):
            self.btn_test.state(["!disabled"])
            ok, val = out
            if not ok:
                self.sources = None
                self.status.config(text=clip(val, 120), style="Error.TLabel")
                return
            self.sources = val
            sites = [s for c in self.app.cards.values() if c.TYPE == "sites" for s in c.sites]
            hits = sum(1 for s in sites if TR.match_source(s["url"], val))
            kind = "project" if provider == "vercel" else "site"
            self.status.config(
                text=f"Connected. {len(val)} {kind}{'s' * (len(val) != 1)}, "
                f"matching {hits} of your {len(sites)} sites.",
                style="Success.TLabel",
            )

        self.app.run_bg(lambda: TR.connect(provider, token), done)

    def save(self):
        if self.sources is None:
            self.status.config(text="Check the token first.", style="Error.TLabel")
            return
        accounts = self.app.cfg.setdefault("accounts", [])
        name = self.v_name.get().strip() or TR.PROVIDERS[self.provider()]
        account = self.account or TR.new_account(self.provider(), name)
        try:
            vault.set_secret(f"account/{account['id']}", self.v_token.get().strip())
        except OSError as e:
            alert(self.win, "Couldn't save the token", str(e), "error")
            return
        account["name"] = name
        account["sources"] = [{k: v for k, v in s.items()} for s in self.sources]
        if not self.account:
            accounts.append(account)
        matched, total = match_all_sites(self.app, account)
        self.app.save()
        self.close()
        d = self.app.dialogs.get("accounts")
        if d and d.win.winfo_exists():
            d.refresh()
        self.app.notify("Traffic connected", f"{name}: matched {matched} of your {total} sites.")


def open_accounts(app):
    def label(a):
        n = len(a.get("sources", []))
        kind = "project" if a["provider"] == "vercel" else "site"
        return f"{a['name']}   —   {TR.PROVIDERS[a['provider']]}, {n} {kind}{'s' * (n != 1)}"

    def remove(i, parent):
        a = app.cfg["accounts"][i]
        if not confirm(
            parent,
            "Remove account",
            f"Disconnect {a['name']}? Sites using it stop showing visitors.",
            ok="Remove",
            danger=True,
        ):
            return
        vault.delete_secret(f"account/{a['id']}")
        del app.cfg["accounts"][i]
        for card in app.cards.values():
            if card.TYPE == "sites":
                for site in card.sites:
                    if (site.get("traffic") or {}).get("account") == a["id"]:
                        site["traffic"] = None
                card.traffic_changed()
        app.save()
        app.dialogs["accounts"].refresh()

    def move(i, d):
        accts = app.cfg["accounts"]
        accts[i], accts[i + d] = accts[i + d], accts[i]
        app.save()

    app.open_dialog(
        "accounts",
        lambda: ListManager(
            app.root,
            "Traffic accounts",
            "Vercel and Cloudflare accounts Perch reads visitor numbers from.",
            lambda: app.cfg.setdefault("accounts", []),
            label,
            lambda: ConnectDialog(app),
            lambda i: ConnectDialog(app, app.cfg["accounts"][i]),
            remove,
            move,
        ),
    )

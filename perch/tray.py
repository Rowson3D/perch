"""System tray icon (pystray). Its callbacks run on pystray's thread, so they
hand work to the Tk thread through app.call_soon()."""

from perch import APP_ID, APP_NAME, icons

try:
    import pystray
except Exception:  # pragma: no cover - tray is optional
    pystray = None


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None
        self._status = self._title = None
        if pystray is None:
            return
        Item, SEP = pystray.MenuItem, pystray.Menu.SEPARATOR
        call = app.call_soon
        menu = pystray.Menu(
            Item("Show / hide widget", lambda: call(app.toggle_visible), default=True),
            SEP,
            Item("Add machineâ€¦", lambda: call(app.open_host_dialog)),
            Item("Manage machinesâ€¦", lambda: call(app.open_manage)),
            Item("Settingsâ€¦", lambda: call(app.open_settings)),
            Item("Refresh now", lambda: call(app.refresh_now)),
            SEP,
            Item(
                "Always on top",
                lambda: call(app.set_topmost, not app.cfg["topmost"]),
                checked=lambda item: bool(app.cfg["topmost"]),
            ),
            Item(
                "Start with Windows",
                lambda: call(app.set_autostart, not app.autostart_on),
                checked=lambda item: app.autostart_on,
            ),
            SEP,
            Item(f"Quit {APP_NAME}", lambda: call(app.quit)),
        )
        try:
            self.icon = pystray.Icon(APP_ID, icons.tray_image("unknown"), APP_NAME, menu)
            self.icon.run_detached()
        except Exception:
            self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def update(self, free, total, known):
        if not self.icon:
            return
        status = "free" if free else ("busy" if total and known == total else "unknown")
        if status != self._status:
            self._status = status
            self.icon.icon = icons.tray_image(status)
        title = f"{APP_NAME} - {free}/{total} GPUs free" if total else APP_NAME
        if title != self._title:
            self._title = title
            self.icon.title = title

    def notify(self, title, message):
        if not self.icon:
            return False
        try:
            self.icon.notify(message, title)
            return True
        except Exception:
            return False

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass

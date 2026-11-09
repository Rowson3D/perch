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
        self._level = self._title = object()
        if pystray is None:
            return
        Item, SEP = pystray.MenuItem, pystray.Menu.SEPARATOR
        call = app.call_soon
        menu = pystray.Menu(
            Item("Show / hide cards", lambda: call(app.toggle_all), default=True),
            SEP,
            Item("All cards…", lambda: call(app.open_cards)),
            Item("Add a card…", lambda: call(app.open_add_card)),
            Item("Refresh all", lambda: call(app.refresh_all)),
            SEP,
            Item(
                "Start with Windows",
                lambda: call(app.set_autostart, not app.autostart_on),
                checked=lambda item: app.autostart_on,
            ),
            SEP,
            Item(f"Quit {APP_NAME}", lambda: call(app.quit)),
        )
        try:
            self.icon = pystray.Icon(APP_ID, icons.tray_image(None), APP_NAME, menu)
            self.icon.run_detached()
        except Exception:
            self.icon = None

    @property
    def available(self):
        return self.icon is not None

    def update(self, level, title):
        if not self.icon:
            return
        if level != self._level:
            self._level = level
            self.icon.icon = icons.tray_image(level)
        title = title[:127]  # Windows tray tooltips are limited to 128 characters
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

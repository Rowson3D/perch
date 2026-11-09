# Perch

**Discreet, customizable desktop cards for your machines and websites.** Perch sits quietly on your Windows desktop and keeps watch. Each card is its own small floating window: put it anywhere, style it, hide it, or hatch another.

![GPU and Sites cards on the desktop](docs/cards.png)

## Cards

### Sites

Your websites at a glance.

- **Up or down.** Each site is checked every minute (adjustable). It only counts as **down** after 2 failed checks in a row, so a single blip won't alert you.
- **Response time** with a graph, plus **uptime %** for 24 hours, 7 days and 30 days.
- **SSL certificate and domain expiry.** Perch shows the days left and warns you before either lapses. Domain dates come from the registry (RDAP).
- **"Must contain" check.** A site also counts as down if a phrase you choose is missing from the page, e.g. when a broken deploy serves an error page with status 200.
- **Notifications:** when a site goes down, when it comes back (with how long it was out), and when its certificate or domain is about to expire.
- **Shortcuts:**
  - Double-click a site to open it.
  - Right-click it to open its **admin page** or **repository**, check it now, or pause checks.
- **Hover a site** to see the full picture: status code, uptime, response time, SSL issuer and expiry, domain registrar and expiry, and the last outage.

### GPUs

Which NVIDIA GPUs across your machines are **free**, **in use**, or **held**.

- **Any number of machines.** Add a machine by IP or hostname and pick which of its GPUs to show.
- **Three ways to connect:**
  - **Agent:** a tiny read-only HTTP service on the GPU machine (Linux or Windows).
  - **SSH:** nothing to install on the remote machine; it uses your existing SSH key.
  - **This PC:** your local GPUs.
- **Smart "in use" detection:**
  - **VRAM threshold** (default 50%).
  - **GPU utilization**, averaged over a time window so a single spike doesn't flip the state.
  - **HELD state:** VRAM is reserved but the GPU has been idle for a while, e.g. a forgotten notebook or a PyTorch cache.
  - **Dead zone** so a GPU sitting right at a threshold doesn't flicker between states.
- **Who's using it.** Hover a GPU to see its processes, their users, and how much memory each holds.
- **History graphs** of VRAM use (filled) and utilization (line).
- **"Notify me when free."** Right-click a busy GPU to get a Windows notification when it frees up.

![GPU hover details](docs/widget_tip.png)

## Your perch: hatching and managing cards

Open **Your perch** from the tray icon or any card's **⋯** menu. Every card on your desktop is shown as a tile with its live status, and from there you can open its **Settings**, **Hide** or **Show** it, or let it **Fly away** (remove it; it floats off your desktop).

The dashed **Hatch a new card** tile opens the gallery:

1. Pick a card type.
2. Name it.
3. Do the quick setup, e.g. paste your site addresses, one per line.
4. Click **Hatch**. The card drops onto your desktop.

You can have as many cards as you like, e.g. one Sites card for clients and another for your own projects. **This PC**, **GitHub** and a **build-your-own card** builder are coming next.

## Everywhere in Perch

- **Discreet:**
  - Borderless cards that snap to screen edges and to each other.
  - Per-card opacity and always-on-top.
  - Hide any card in one click.
- **Tray icon:**
  - It shows the worst status across all your cards: **green** when all is well, **amber** for warnings (e.g. an SSL certificate expiring soon, or every GPU busy), **red** when something is down.
  - Its tooltip summarises every card.
- **One consistent look.** Every window, menu and dialog uses the same dark [design system](docs/design-system.md).
- **Proper install.** A single exe that installs per-user with no admin rights. It adds a Start-menu entry, an Add/Remove Programs entry and optional start-with-Windows, and updates in place.

## Install

1. Download **`Perch.exe`** from the [latest release](https://github.com/Rowson3D/perch/releases/latest).
2. Run it and click **Install**.

> Windows SmartScreen may warn about an unrecognized app because the exe isn't code-signed. Click **More info → Run anyway**.

Other options:

- **Without installing:** click **Just run it**, or start it with `Perch.exe --portable`.
- **Silent install:** `Perch.exe --install [--no-autostart] [--desktop] [--no-launch]`.
- **Upgrading from GPU Watch:** Perch removes the old install automatically and keeps your machines and settings.

## Adding machines

Click **+** on a GPU card (or right-click it → *Add machine…*). Then:

1. Choose how to connect.
2. Enter the IP or hostname.
3. Click **Find GPUs**.
4. Tick the GPUs you want, then click **Add**.

| Connect via | Use it for | Needs |
|---|---|---|
| **This PC** | the GPUs in the computer running Perch | nothing |
| **SSH** | Linux boxes, cloud VMs (AWS, GCP, Azure, RunPod, Lambda…), anything you can already `ssh` into | key-based login, so `ssh user@host` works without a password prompt |
| **Agent** | machines where you'd rather not use SSH, including Windows GPU boxes | the Perch agent running on that machine (port 9123) |

### Installing the agent

**Linux** (installs a systemd service that starts on boot):

```bash
sudo ./install_agent_linux.sh          # optional: port number, default 9123
curl http://localhost:9123/gpus         # check it
```

**Windows**: put `perch-agent.exe` and `install_agent_windows.ps1` in one folder, then run this from an **Administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_agent_windows.ps1
```

This adds a startup task and a firewall rule for private and domain networks.

The agent is read-only. It only reports GPU stats and process names, and it can't change anything. It has no authentication, so run it on a trusted network, or use **SSH** for machines reachable over the internet.

## How a GPU's state is decided

| State | Meaning |
|---|---|
| 🟢 **FREE** | VRAM is below the threshold *and* average utilization is low |
| 🔴 **IN USE** | VRAM is at or above the threshold, *or* average utilization is high |
| 🟡 **HELD** | VRAM is at or above the threshold, but utilization has been ~0% for the "held" period |
| ⚪ offline | the machine couldn't be reached (the reason is shown on the card) |

All thresholds and time windows are in the card's **Settings** (right-click the card).

## Using it

- **Drag** anywhere on a card to move it. It snaps to screen edges and to other cards.
- **Hover** a row for its full details.
- **Right-click** a row for its actions (notify when free, open site, check now…).
- **Right-click** anywhere else on a card, or click **⋯**, for the card menu.
- **+** adds a machine or site to that card. **–** hides the card.
- **Click the tray icon** to show or hide all cards.

Settings are stored in `%APPDATA%\Perch\config.json`, and site history in `%APPDATA%\Perch\state\`.

## Uninstall

Use **Settings → Apps → Installed apps → Perch → Uninstall**, or run `Perch.exe --uninstall`. It asks whether to keep your saved machines.

## Roadmap

- **More cards:** This PC (CPU, RAM, disk, network), GitHub (builds and pull requests), Docker.
- **Build your own card:** make a card from a website, a JSON API or a script, either visually or in a few lines of Python.
- **More customization:** desktop-layer mode, click-through, auto-hide while a fullscreen app or game is running, and saved layouts.

## Adding a card type

A card is one class in `perch/cards/`:

1. Subclass `Card` from `perch/cards/base.py`.
2. Implement `render`, `update_view`, `start`, `status`, `menu_items` and `settings_rows`.
3. Register the class in `perch/cards/__init__.py`.

The window, dragging and snapping, menus, settings window, hover details and animations all come from the base class and the shared components, so a new card automatically looks and behaves like the others.

## Building from source

Requires Windows and Python 3.10+.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

The script:

1. creates `.venv` and installs the project with its build and dev extras;
2. lints with ruff and runs the tests;
3. builds `dist\Perch.exe` and `dist\perch-agent.exe` with PyInstaller.

To run from source without building:

```powershell
pip install -e ".[dev]"
python -m perch
```

The code follows ruff's lint and format rules (`ruff check .`, `ruff format .`). Pushing a tag like `v0.2.0` makes GitHub Actions build both executables and attach them to a release.

## License

[MIT](LICENSE)

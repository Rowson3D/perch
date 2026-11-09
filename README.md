# Perch

**Discreet, customizable desktop cards for your machines.** Perch sits quietly on your Windows desktop and keeps watch. Its first card shows which NVIDIA GPUs across your machines are **free**, **in use**, or **held**. A **Sites** card (uptime, response time, SSL and domain expiry for your websites) is next.

![Perch GPU card with hover details](docs/widget_tip.png)

## GPU card

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

## Everywhere in Perch

- **Discreet:**
  - Borderless and draggable, and it remembers its position.
  - Adjustable opacity.
  - Optionally always on top.
  - Hides to the tray in one click.
- **Tray icon:** it goes green when anything is free and red when everything is busy. Every option is a right-click away.
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

Click **+** on the GPU card (or use the tray menu → *Add machine…*). Then:

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

All thresholds and time windows are in **Settings** (right-click the card).

## Using it

- **Drag** anywhere on a card to move it.
- **Hover** a GPU for its details and processes.
- **Right-click** a GPU to get notified when it's free, or to edit its machine.
- **Right-click** anywhere else, or click **⋯**, for the menu.
- **–** hides Perch to the tray. Click the tray icon to bring it back.

Settings are stored in `%APPDATA%\Perch\config.json`.

## Uninstall

Use **Settings → Apps → Installed apps → Perch → Uninstall**, or run `Perch.exe --uninstall`. It asks whether to keep your saved machines.

## Roadmap

- **Sites card:** up/down status, response time, SSL certificate and domain expiry, and alerts for your websites.
- **Card builder:** make your own card from a website, a JSON API or a script, either visually or in a few lines of Python.
- **More cards:** This PC (CPU, RAM, disk, network), GitHub builds, Docker.
- **More customization:** desktop-layer mode, click-through, auto-hide while a fullscreen app or game is running, snapping, and saved layouts.

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

The code follows ruff's lint and format rules (`ruff check .`, `ruff format .`). Pushing a tag like `v0.1.0` makes GitHub Actions build both executables and attach them to a release.

## License

[MIT](LICENSE)

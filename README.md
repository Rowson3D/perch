# GPU Watch

A small, always-there desktop widget for Windows that shows which NVIDIA GPUs on your machines are **free**, **in use**, or **held**, so you can tell at a glance where to run your next job.

![GPU Watch widget with hover details](docs/widget_tip.png)

## Features

- **Floating widget.** Borderless, draggable, remembers its position, and can stay always on top. Opacity is adjustable.
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
- **History graphs** of VRAM use (filled) and utilization (line) over the last N minutes.
- **"Notify me when free."** Right-click a busy GPU to get a Windows notification when it frees up.
- **Tray icon.** It goes green when anything is free and red when everything is busy. Use it to show or hide the widget and reach every option.
- **Proper install.** A single exe that installs per-user with no admin rights. It adds a Start-menu entry, an Add/Remove Programs entry and optional start-with-Windows.

## Install

1. Download **`GpuWatch.exe`** from the [latest release](https://github.com/Rowson3D/gpu-watch/releases/latest).
2. Run it and click **Install**.

It installs to `%LOCALAPPDATA%\Programs\GPU Watch` and starts with Windows (you can untick that). Running a newer `GpuWatch.exe` later updates it in place, and your machines and settings are kept.

> Windows SmartScreen may warn about an unrecognized app because the exe isn't code-signed. Click **More info → Run anyway**.

Prefer not to install? Click **Just run it**, or start it with `GpuWatch.exe --portable`.

Silent install for scripts: `GpuWatch.exe --install [--no-autostart] [--desktop] [--no-launch]`.

## Adding machines

Click **+** on the widget (or use the tray menu → *Add machine…*). Then:

1. Choose how to connect.
2. Enter the IP or hostname.
3. Click **Find GPUs**.
4. Tick the GPUs you want, then click **Add**.

| Connect via | Use it for | Needs |
|---|---|---|
| **This PC** | the GPUs in the computer running the widget | nothing |
| **SSH** | Linux boxes, cloud VMs (AWS, GCP, Azure, RunPod, Lambda…), anything you can already `ssh` into | key-based login, so `ssh user@host` works without a password prompt |
| **Agent** | machines where you'd rather not use SSH, including Windows GPU boxes | the GPU Watch agent running on that machine (port 9123) |

### Installing the agent

**Linux** (installs a systemd service that starts on boot):

```bash
sudo ./install_agent_linux.sh          # optional: port number, default 9123
curl http://localhost:9123/gpus         # check it
```

**Windows**: put `gpu-agent.exe` and `install_agent_windows.ps1` in one folder, then run this from an **Administrator** PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install_agent_windows.ps1
```

This adds a startup task and a firewall rule for private and domain networks.

The agent is read-only. It only reports GPU stats and process names, and it can't change anything. It has no authentication, so run it on a trusted network, or use **SSH** for machines reachable over the internet.

## How the state is decided

| State | Meaning |
|---|---|
| 🟢 **FREE** | VRAM is below the threshold *and* average utilization is low |
| 🔴 **IN USE** | VRAM is at or above the threshold, *or* average utilization is high |
| 🟡 **HELD** | VRAM is at or above the threshold, but utilization has been ~0% for the "held" period |
| ⚪ offline | the machine couldn't be reached (the reason is shown on the card) |

All thresholds and time windows are in **Settings** (right-click the widget).

## Using it

- **Drag** anywhere on the widget to move it.
- **Hover** a GPU for its details and processes.
- **Right-click** a GPU to get notified when it's free, or to edit its machine.
- **Right-click** anywhere else, or click **⋯**, for the menu.
- **–** hides the widget to the tray. Click the tray icon to bring it back.

Settings are stored in `%APPDATA%\GpuWatch\config.json`.

## Uninstall

Use **Settings → Apps → Installed apps → GPU Watch → Uninstall**, or run `GpuWatch.exe --uninstall`. It asks whether to keep your saved machines.

## Building from source

Requires Windows and Python 3.10+.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
```

The script:

1. creates `.venv` and installs the project with its build and dev extras;
2. lints with ruff and runs the tests;
3. builds `dist\GpuWatch.exe` and `dist\gpu-agent.exe` with PyInstaller.

To run from source without building:

```powershell
pip install -e ".[dev]"
python -m gpuwatch
```

The code follows ruff's lint and format rules (`ruff check .`, `ruff format .`). The UI follows the [design system](docs/design-system.md): one set of colors, type and spacing tokens, plus shared dialog and menu components, so every window looks the same.

Pushing a tag like `v1.0.1` makes GitHub Actions build both executables and attach them to a release.

## License

[MIT](LICENSE)

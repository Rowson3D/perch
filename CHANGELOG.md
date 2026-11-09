# Changelog

Changes to Perch, newest first. Versions follow [Semantic Versioning](https://semver.org/). Each section here is also used as the notes for that version's GitHub release.

## [0.2.0] - 2026-11-09

First public release. Perch puts small cards on your Windows desktop that show whether your GPUs are free and whether your websites are up.

![GPU and Sites cards on the desktop](https://raw.githubusercontent.com/Rowson3D/perch/main/docs/cards.png)

### New: Sites card

- Checks each of your sites every minute. A site is marked down after 2 failed checks in a row.
- Shows response time with a graph of the last hour, and uptime over 24 hours, 7 days and 30 days.
- Shows days left on the SSL certificate and the domain registration, and warns you before either runs out.
- Optional text to look for on the page, so a broken page that still returns a 200 counts as down.
- Notifies you when a site goes down, when it comes back, and when a certificate or domain is close to expiring.
- Double-click a site to open it. Right-click it for its admin page, its repo, check now, or pause.

### GPU card

- Shows which NVIDIA GPUs on your machines are free, in use or held.
- Connects through the Perch agent, over SSH, or directly for this PC.
- A GPU is in use when its VRAM is over a threshold or its utilization has been high. It's held when the VRAM is taken but the GPU has been idle for a while.
- Hover over a GPU to see its processes and users. Right-click a busy one to get notified when it frees up.

### Cards

- Every card is its own window, with its own title, opacity and always-on-top setting. Cards snap to the screen edges and to each other.
- **Your perch** lists your cards. From there you can add new ones, change their settings, hide them, or remove them.
- The tray icon turns green, amber or red depending on the worst status across your cards.

### Install

Download `Perch.exe` below, run it and click **Install**. It installs for your user only, so no admin rights are needed.

The exe isn't code-signed yet, so SmartScreen may warn you the first time. Click **More info**, then **Run anyway**.

If you have GPU Watch installed, Perch replaces it and keeps your machines and settings.

### Agent for GPU machines

You only need the agent for machines you don't want to reach over SSH.

| Machine | Files | How to install |
|---|---|---|
| Windows | `perch-agent.exe`, `install_agent_windows.ps1` | run the script from an Administrator PowerShell |
| Linux | `perch_agent.py`, `install_agent_linux.sh` | `sudo ./install_agent_linux.sh` |

The agent only reports GPU stats and has no password, so keep it on a network you trust.

### Requirements

- Windows 10 or 11, 64-bit.
- GPU machines need the NVIDIA driver, which includes `nvidia-smi`.

"""Entry point:  python -m gpuwatch   (or the packaged GpuWatch.exe)

Options:
  --portable    run without offering to install (packaged exe only)
  --install     install silently (packaged exe only); add --no-autostart, --desktop, --no-launch
  --uninstall   remove an installed copy (add --quiet for no prompts)
"""

import os
import sys

if __package__ in (None, ""):  # run as a plain script / by PyInstaller
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from gpuwatch import util

    args = sys.argv[1:]
    util.dpi_aware()
    if util.IS_WIN and "--uninstall" in args:
        from gpuwatch import installer

        installer.run_uninstall(quiet="--quiet" in args)
        return
    if util.IS_WIN and "--install" in args:
        from gpuwatch import installer

        if not installer.frozen():
            print("--install only works from the packaged GpuWatch.exe")
            return
        installer.install(autostart="--no-autostart" not in args, desktop="--desktop" in args)
        if "--no-launch" not in args:
            util.launch_detached([installer.EXE, "--first-run"])
        return
    if util.IS_WIN:
        from gpuwatch import installer

        if installer.should_offer_setup(args) and installer.run_setup_dialog() != "portable":
            return
    if not util.single_instance():
        return
    from gpuwatch.ui import App

    App(first_run="--first-run" in args).root.mainloop()


if __name__ == "__main__":
    main()

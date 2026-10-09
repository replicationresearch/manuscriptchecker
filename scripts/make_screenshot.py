"""Capture a screenshot of the running MüCOS Manuscript Checker GUI.

Launches ``metacheck_gui.py``, waits for its main window, brings it to the
front and saves a PNG of the window to ``site/assets/screenshot.png`` (used by
the GitHub Pages landing page). Run this after changing the UI to refresh the
screenshot:

    python scripts/make_screenshot.py
"""

import subprocess
import sys
import time
from pathlib import Path

import win32con
import win32gui
from PIL import ImageGrab

ROOT = Path(__file__).resolve().parent.parent
TITLE = "MüCOS Manuscript Checker"
OUT = ROOT / "site" / "assets" / "mmc.png"


def find_window():
    for _ in range(40):
        hwnd = win32gui.FindWindow(None, TITLE)
        if hwnd:
            return hwnd
        time.sleep(0.5)
    return None


def main():
    proc = subprocess.Popen(
        [sys.executable, "metacheck_gui.py"],
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    try:
        hwnd = find_window()
        if not hwnd:
            raise SystemExit("Could not find the MüCOS Manuscript Checker window.")
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        time.sleep(1.5)
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        img = ImageGrab.grab(bbox=(left, top, right, bottom))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        img.save(OUT)
        print(f"Saved screenshot to {OUT} ({img.size[0]}x{img.size[1]})")
    finally:
        try:
            win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                                  win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
        except Exception:  # noqa: BLE001
            pass
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()

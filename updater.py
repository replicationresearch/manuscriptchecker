"""Self-update: check the GitLab repo for a newer build and install it.

The app publishes a ``update/latest_version.json`` manifest in the repo::

    {"version": "0.6.0", "exe": "ManuscriptChecker.exe",
     "exe_url": "https://.../ManuscriptChecker.exe", "notes": "..."}

On startup (and via the "Check for updates" button) we compare the remote
version against the local ``config.DESKTOP_APP_VERSION``. When a newer version
exists we download the new exe to ``<exe>.new`` and launch a small batch file
that waits for the running app to exit, swaps the new exe in and relaunches it.
"""

import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

import config

USER_AGENT = "MueCOS-ManuscriptChecker/" + config.DESKTOP_APP_VERSION


def _parse_version(v):
    """Parse ``1.2.3`` into a comparable tuple, ignoring non-numeric suffixes."""
    parts = []
    for p in str(v).split("."):
        digits = ""
        for ch in p:
            if ch.isdigit():
                digits += ch
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def current_version():
    return config.DESKTOP_APP_VERSION


def _app_dir():
    """Directory the running app (exe or script) lives in."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def exe_path():
    """The frozen executable path, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def check_for_update(timeout=15):
    """Return a dict describing an available update, or None.

    Returns ``{"available": False, ...}`` when up to date and
    ``{"available": True, "latest_version", "exe_url", "exe", "notes"}`` when a
    newer build is published. Returns None if the manifest can't be reached.
    """
    try:
        req = urllib.request.Request(
            config.UPDATE_MANIFEST_URL,
            headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        latest = str(data.get("version", ""))
        if not latest:
            return None
        if _parse_version(latest) > _parse_version(current_version()):
            return {"available": True,
                    "latest_version": latest,
                    "exe": data.get("exe", "ManuscriptChecker.exe"),
                    "exe_url": data.get("exe_url", ""),
                    "notes": data.get("notes", "")}
        return {"available": False, "latest_version": latest}
    except Exception:  # noqa: BLE001
        return None


def _download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(data)
    return tmp


def install_update(url, on_log=None):
    """Download the new exe and stage it for install on the next launch.

    The running executable can't be replaced on Windows, so we download to
    ``<exe>.new`` and launch a batch file that waits for this process to exit,
    swaps the file over, deletes the temp files and relaunches the app.

    Returns the path to the staged ``.new`` file.
    """
    exe = exe_path()
    if not exe:
        raise RuntimeError("Cannot self-update: not running as a frozen exe.")
    if not url:
        raise RuntimeError("Update manifest did not provide an exe URL.")
    if on_log:
        on_log(f"Downloading update from {url} ...")
    new = exe.with_name(exe.name + ".new")
    _download(url, new)
    if on_log:
        on_log(f"Update downloaded ({new.stat().st_size // 1024} KB).")

    bat = Path(tempfile.gettempdir()) / "_muecos_apply_update.bat"
    bat.write_text(_apply_script(exe, new), encoding="utf-8")
    # CREATE_NO_WINDOW so the batch doesn't flash a console window.
    subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000)
    return new


def _apply_script(exe, new):
    """Batch that waits for the running app, swaps the new exe and relaunches."""
    name = exe.name
    # The bat is self-contained (absolute paths) and deletes itself at the end.
    return (
        "@echo off\r\n"
        "setlocal\r\n"
        ":wait\r\n"
        f'tasklist /FI "IMAGENAME eq {name}" 2>nul | findstr /i "{name}" >nul\r\n'
        "if not errorlevel 1 (\r\n"
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto wait\r\n"
        ")\r\n"
        f'copy /y "{new}" "{exe}" >nul\r\n'
        f'del "{new}" >nul 2>nul\r\n'
        'start "" "' + str(exe) + '"\r\n'
        'del "%~f0" >nul 2>nul\r\n'
        "endlocal\r\n"
    )

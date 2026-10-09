"""Configuration and environment/tool discovery for the metacheck app.

Everything here is read once at import time. Override via environment
variables (GROBID_URL, RSCRIPT, SOFFICE, METACHECK_MODULES) or by editing
the values below.
"""

import os
import shutil
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller: data files are extracted here (read-only).
    BASE_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
else:
    BASE_DIR = Path(__file__).resolve().parent

# Writable location for job output. When frozen, _MEIPASS is read-only, so use
# the user's Documents/Home folder instead.
if getattr(sys, "frozen", False):
    UPLOAD_DIR = Path(os.environ.get("USERPROFILE", ".")) / "Documents" / "metacheck"
else:
    UPLOAD_DIR = BASE_DIR / "uploads"

SCRIPTS_DIR = BASE_DIR / "scripts"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


def default_output_dir():
    """A stable, user-writable folder for metacheck reports."""
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("USERPROFILE", ".")) / "Documents" / "metacheck"
    else:
        base = BASE_DIR / "reports"
    base.mkdir(parents=True, exist_ok=True)
    return base

# ---------------------------------------------------------------------------
# GROBID
# ---------------------------------------------------------------------------
# Default is the TUE GROBID instance (reliable and reachable). A local Docker
# GROBID is offered as an option in the UI.
DEFAULT_GROBID_URL = os.environ.get("GROBID_URL", "https://grobid.hti.ieis.tue.nl")

PUBLIC_GROBID_SERVERS = [
    {"id": "TUE GROBID 0.8.2", "url": "https://grobid.hti.ieis.tue.nl"},
    {"id": "HF GROBID FULL 0.9.0", "url": "https://grobidOrg-grobid.hf.space"},
    {"id": "HF GROBID CRF 0.9.0", "url": "https://grobidOrg-grobid-crf.hf.space"},
    {"id": "Local Docker (localhost:8070)", "url": "http://localhost:8070"},
    {"id": "Metacheck GROBID 0.9.0", "url": "https://grobid.metacheck.app"},
]

# Timeout for the GROBID full-text conversion call (seconds).
GROBID_TIMEOUT = int(os.environ.get("GROBID_TIMEOUT", "300"))

# ---------------------------------------------------------------------------
# Uploads
# ---------------------------------------------------------------------------
# Reject a web-app upload larger than this before it ever reaches LibreOffice
# or GROBID. Override with the MAX_UPLOAD_MB env var.
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "50")) * 1024 * 1024

# ---------------------------------------------------------------------------
# metacheck modules
# ---------------------------------------------------------------------------
# Module names the R `metacheck` package provides. Split below into
# FAST_MODULES (text-only, no network) / ONLINE_MODULES (contact CrossRef,
# OSF/GitHub, RetractionWatch, PubPeer, ...) using chetameck's catalog as the
# single source of truth for which modules are online, instead of a hand-kept
# copy - the previous copy miscategorized "prereg_check" (which resolves
# every OSF link via the OSF API) as offline, so unticking "include online
# checks" did not actually stop it from calling out to OSF.
_R_SUPPORTED_MODULES = [
    "prereg_check", "funding_check", "coi_check", "power", "stat_check",
    "stat_p_exact", "stat_p_nonsig", "stat_effect_size", "marginal",
    "ref_consistency", "ref_summary",
    "ref_accuracy", "repo_check", "code_check", "ref_replication",
    "ref_retraction", "ref_pubpeer",
]
try:
    from chetameck.catalog import ONLINE_MODULE_NAMES as _ONLINE_MODULE_NAMES
except Exception:  # noqa: BLE001  (chetameck unavailable -> static fallback)
    _ONLINE_MODULE_NAMES = {"ref_accuracy", "repo_check", "code_check",
                            "ref_replication", "ref_retraction", "ref_pubpeer",
                            "prereg_check"}

FAST_MODULES = [m for m in _R_SUPPORTED_MODULES if m not in _ONLINE_MODULE_NAMES]
ONLINE_MODULES = [m for m in _R_SUPPORTED_MODULES if m in _ONLINE_MODULE_NAMES]

DEFAULT_MODULES = FAST_MODULES + ONLINE_MODULES


def module_list(include_online: bool = True):
    """Return the module vector to run, optionally excluding online checks."""
    if include_online:
        return DEFAULT_MODULES
    return FAST_MODULES


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------
def _find_candidate(name, candidates):
    """Return the first existing candidate path, or None."""
    for cand in candidates:
        if cand and Path(cand).exists():
            return str(cand)
    return None


def find_rscript():
    """Locate the Rscript executable."""
    env = os.environ.get("RSCRIPT")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("Rscript")
    if on_path:
        return on_path
    r_dir = Path(r"C:\Program Files\R")
    if r_dir.exists():
        matches = sorted(r_dir.glob("R-*/bin/Rscript.exe"))
        if matches:
            return str(matches[-1])
    return None


def find_soffice():
    """Locate the LibreOffice `soffice` executable."""
    env = os.environ.get("SOFFICE")
    if env and Path(env).exists():
        return env
    on_path = shutil.which("soffice") or shutil.which("soffice.exe")
    if on_path:
        return on_path
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    return _find_candidate("soffice", candidates)


RSCRIPT = find_rscript()
SOFFICE = find_soffice()

# ---------------------------------------------------------------------------
# App version + self-update (checks the GitHub repo for a newer release).
# ---------------------------------------------------------------------------
# Single source of truth for the app's version. Bump the third number for
# bugfix releases; bump the first/second for feature releases.
DESKTOP_APP_VERSION = "0.6.1"

# GitHub repo that hosts the app releases. The app queries the GitHub Releases
# API for the latest release; when a newer version exists, the new exe is
# downloaded from the release asset and installed on the next launch.
GITHUB_REPO = os.environ.get(
    "GITHUB_REPO",
    "replicationresearch/manuscriptchecker",
)
# GitHub Releases API endpoint that returns the latest release.
RELEASES_API_URL = os.environ.get(
    "RELEASES_API_URL",
    f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest",
)
# Optional personal access token: used to avoid API rate limits and to allow
# the app to read releases from a private repo. Leave empty for public repos.
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

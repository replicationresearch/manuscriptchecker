"""Load the bundled reference databases (RetractionWatch, FLoRA, miscite).

These databases ship with the metacheck R package as .Rds files. We locate them
either next to this package (when bundled by PyInstaller) or in the user's R
library. Falls back to empty DataFrames if unavailable.
"""

import sys
from pathlib import Path

import pandas as pd

try:
    import pyreadr
except Exception:  # noqa: BLE001
    pyreadr = None


def _find_db_dir():
    """Locate the directory containing the .Rds databases."""
    # 1. bundled next to this module (PyInstaller --add-data)
    here = Path(__file__).resolve().parent
    candidates = [
        here / "databases",
        here.parent / "databases",
    ]
    for c in candidates:
        if (c / "retractionwatch.Rds").exists():
            return c
    # 2. try the metacheck R library
    import subprocess
    try:
        out = subprocess.run(
            [sys.executable and "Rscript" or "Rscript"],
            capture_output=True, text=True) if False else None
    except Exception:  # noqa: BLE001
        pass
    # Try common R library paths
    for lib in [Path.home() / "AppData/Local/R/win-library",
                Path("C:/Program Files/R")]:
        if lib.exists():
            versions = sorted(lib.glob("4.*"), reverse=True)
            for ver in versions:
                db = ver / "metacheck/databases"
                if (db / "retractionwatch.Rds").exists():
                    return db
    return None


def _read(name):
    d = _find_db_dir()
    if d is None or pyreadr is None:
        return None
    p = d / f"{name}.Rds"
    if not p.exists():
        return None
    try:
        r = pyreadr.read_r(str(p))
        for v in r.values():
            return v
    except Exception:  # noqa: BLE001
        return None
    return None


def retractionwatch():
    df = _read("retractionwatch")
    if df is None:
        return pd.DataFrame(columns=["doi", "retractionwatch"])
    df["doi"] = df["doi"].astype(str).str.strip().str.lower()
    return df


def flora():
    df = _read("FLoRA")
    if df is None:
        return pd.DataFrame(columns=["doi_o", "apa_ref_o", "doi_r", "apa_ref_r",
                                     "url_r", "outcome", "outcome_quote", "type"])
    df["doi_o"] = df["doi_o"].astype(str).str.strip().str.lower()
    df["doi_r"] = df["doi_r"].astype(str).str.strip().str.lower()
    return df


def flora_online():
    """Best-effort download of the latest FLoRA CSV from OSF (file id ``t4j8f``).

    Used as a fallback when the bundled FLoRA database is unavailable. Returns a
    DataFrame with the 8 standard FLoRA columns, or None on failure.
    """
    cols = ["doi_o", "apa_ref_o", "doi_r", "apa_ref_r", "url_r", "outcome",
            "outcome_quote", "type"]
    try:
        import io
        import requests
        headers = {"Accept": "application/vnd.api+json", "User-Agent": "metacheck"}
        # resolve the 24-char waterbutler id from the 5-char guid
        r = requests.get("https://api.osf.io/v2/guids/t4j8f/",
                         headers=headers, timeout=20)
        if r.status_code != 200:
            return None
        data = r.json().get("data", {})
        dl_url = data.get("links", {}).get("download") or "https://osf.io/download/t4j8f/"
        dl = requests.get(dl_url, headers={"User-Agent": "metacheck"}, timeout=120)
        if dl.status_code != 200:
            return None
        df = pd.read_csv(io.BytesIO(dl.content))
        for c in cols:
            if c not in df.columns:
                df[c] = ""
        df = df[cols].copy()
        df["doi_o"] = df["doi_o"].astype(str).str.strip().str.lower()
        df["doi_r"] = df["doi_r"].astype(str).str.strip().str.lower()
        return df.drop_duplicates()
    except Exception:  # noqa: BLE001
        return None


def miscite():
    df = _read("miscite")
    if df is None:
        return pd.DataFrame(columns=["doi", "reftext", "warning"])
    df["doi"] = df["doi"].astype(str).str.strip().str.lower()
    return df

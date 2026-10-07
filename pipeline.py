"""Shared, standalone pipeline for converting a manuscript and running metacheck.

This module has no FastAPI/web dependency so it can be reused by both the web
app (app.py) and the desktop GUI (metacheck_gui.py), and packaged into a
standalone executable.
"""

import json
import subprocess
from pathlib import Path

import requests

import config

ALLOWED_EXT = {".pdf", ".html", ".htm", ".docx", ".doc"}

# Supported check engines.
ENGINES = ("metacheck", "chetameck", "plagiarism")

# Keep generated filenames short so the full output path stays under Windows'
# 260-char MAX_PATH. Browsers refuse to open file:// URLs whose path is longer,
# reporting ERR_FILE_NOT_FOUND even though the file exists.
# scripts/metacheck_report.R's `title_slug(title, maxlen = 50)` mirrors this
# same constraint independently for the R engine's report filenames - if this
# value changes, update that one too.
MAX_STEM_LEN = 60

# Module names the R `metacheck` package provides (the inherited module set).
# Split into FAST_MODULES / ONLINE_MODULES below, using chetameck's catalog as
# the single source of truth for which of these actually contact an external
# service - previously this list was hand-kept and miscategorized
# "prereg_check" (which resolves every OSF link via the OSF API) as fast/
# offline, so it kept running even when "include online checks" was off.
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


def module_list(include_online=True):
    return FAST_MODULES + ONLINE_MODULES if include_online else FAST_MODULES


# ChetaMeck-only categories (not available in the R metacheck engine).
CHETAMECK_ONLY_CATS = {"forensic", "r2", "esci"}


def filter_modules(modules, engine, include_online=True):
    """Filter a list of ChetaMeck module names for a given engine.

    * ``chetameck``: any registered ChetaMeck module.
    * ``metacheck`` (R): only modules the R package provides (the inherited set).

    Online modules are dropped when ``include_online`` is False.
    """
    if engine == "plagiarism":
        # single built-in algorithm, no selectable modules
        return ["plagiarism"]
    modules = list(modules or [])
    try:
        from chetameck.catalog import all_modules, module_category
        catalog_names = set(all_modules(include_online=True))
    except Exception:  # noqa: BLE001  (chetameck unavailable -> static lists)
        catalog_names = set(FAST_MODULES + ONLINE_MODULES)
        module_category = None
    if engine == "chetameck":
        valid = catalog_names
    else:
        # The R metacheck package only knows the inherited module set.
        valid = set(FAST_MODULES + ONLINE_MODULES)
    modules = [m for m in modules if m in valid]
    if not include_online:
        online = set(ONLINE_MODULES)
        modules = [m for m in modules if m not in online]
    return modules


def safe_stem(filename):
    name = Path(filename).name
    stem = Path(name).stem
    stem = "".join(c if c.isalnum() or c in "-_." else "_" for c in stem)
    stem = stem or "manuscript"
    if len(stem) > MAX_STEM_LEN:
        stem = stem[:MAX_STEM_LEN].rstrip("._-") or "manuscript"
    return stem


# Magic-byte signatures for the file types we accept, used to sniff an
# upload's *actual* type rather than trusting its extension (a mismatch is
# rejected before it ever reaches LibreOffice/GROBID). HTML has no reliable
# magic bytes, so it isn't sniffed.
_MAGIC_SIGNATURES = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK\x03\x04",),
    # classic binary .doc (OLE2), or a Word-2007-format file saved with a
    # .doc extension (zip-based, same signature as .docx).
    ".doc": (b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1", b"PK\x03\x04"),
}


def sniff_file_type(data, ext):
    """Return True if ``data``'s magic bytes match what ``ext`` claims to be.

    Extensions with no reliable magic bytes (HTML) always pass.
    """
    sigs = _MAGIC_SIGNATURES.get(ext.lower())
    if not sigs:
        return True
    return any(data.startswith(sig) for sig in sigs)


def _timestamp():
    import datetime
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")


def check_grobid(url, timeout=10):
    """Return (ok, detail)."""
    try:
        r = requests.get(f"{url}/api/isalive", timeout=timeout)
        ok = r.status_code == 200 and r.text.strip() == "true"
        return ok, (r.text.strip() if ok else f"HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def check_metacheck():
    """Return True if Rscript is available and the metacheck package loads."""
    if not config.RSCRIPT:
        return False
    try:
        r = subprocess.run(
            [config.RSCRIPT, "-e", 'cat(requireNamespace("metacheck", quietly=TRUE))'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return r.returncode == 0 and r.stdout.strip() == "TRUE"
    except Exception:  # noqa: BLE001
        return False


def get_metacheck_version():
    """Return the installed metacheck package version, or None."""
    if not config.RSCRIPT:
        return None
    try:
        r = subprocess.run(
            [config.RSCRIPT, "-e",
             'cat(as.character(packageVersion("metacheck")))'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        return None
    except Exception:  # noqa: BLE001
        return None


def update_metacheck(on_log=None):
    """Upgrade the metacheck R package to the latest version. Returns version."""
    if not config.RSCRIPT:
        raise RuntimeError("Rscript not found. Install R first.")
    script = config.SCRIPTS_DIR / "setup_r.R"
    cmd = [config.RSCRIPT, str(script), "update"]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if on_log:
        if proc.stdout.strip():
            on_log(proc.stdout.strip())
        if proc.stderr.strip():
            on_log(proc.stderr.strip())
    if proc.returncode != 0:
        raise RuntimeError(
            "metacheck update failed:\n" + (proc.stderr or proc.stdout)[-1500:]
        )
    return get_metacheck_version()


def convert_to_pdf(soffice, src, outdir):
    """Convert DOCX/HTML to PDF with LibreOffice. Returns the PDF path."""
    cmd = [soffice, "--headless", "--convert-to", "pdf",
           "--outdir", str(outdir), str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"LibreOffice failed: {proc.stderr.strip()}")
    pdf = outdir / (src.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError(
            f"LibreOffice did not produce a PDF. Output: {proc.stdout.strip()}"
        )
    return pdf


def grobid_to_xml(url, pdf_path, outdir, stem):
    """POST a PDF to GROBID /api/processFulltextDocument and save the TEI XML."""
    data = {
        "start": "-1",
        "end": "-1",
        "consolidateCitations": "0",
        "consolidateHeader": "0",
        "consolidateFunders": "0",
        "includeRawCitations": "1",
    }
    with open(pdf_path, "rb") as fh:
        files = {"input": (pdf_path.name, fh, "application/pdf")}
        resp = requests.post(
            f"{url}/api/processFulltextDocument",
            data=data,
            files=files,
            timeout=config.GROBID_TIMEOUT,
        )

    if resp.status_code >= 400:
        raise RuntimeError(
            f"GROBID returned HTTP {resp.status_code}: {resp.text[:500]}"
        )
    if resp.status_code == 204 or not resp.text.strip():
        raise RuntimeError(
            "GROBID returned no content (the PDF may be scanned/image-only "
            "without selectable text)."
        )
    if "<" not in resp.text[:200]:
        raise RuntimeError(f"GROBID response was not XML: {resp.text[:500]}")

    xml_path = outdir / f"{stem}.xml"
    xml_path.write_text(resp.text, encoding="utf-8")
    return xml_path


def run_chetameck(xml_path, outdir, stem, modules, on_log=None, pdf_path=None):
    """Run the Python ChetaMeck engine and write an HTML report + JSON meta.

    Mirrors the output contract of :func:`run_metacheck` so the pipeline can
    dispatch to either engine. ``pdf_path``, when given, is exposed to
    modules that need the original PDF (e.g. ``image_forensic_check``).
    Returns a dict with ``status``, ``format``, ``report_file`` and ``meta``.
    """
    from chetameck import run_chetameck as _run
    from chetameck.catalog import ONLINE_MODULE_NAMES

    def log(msg):
        if on_log:
            on_log(msg)

    include_online = bool(set(modules) & ONLINE_MODULE_NAMES)
    res = _run(str(xml_path), modules=list(modules), include_online=include_online,
               on_log=log, pdf_path=pdf_path)

    # Title-based slug for the report filename (kept under MAX_PATH).
    title = ""
    if not res["paper"].info.empty:
        title = res["paper"].info.iloc[0].get("title") or ""
    title = title[:50]
    slug = "".join(c if c.isalnum() else "-" for c in title).strip("-")
    slug = slug or stem
    if len(slug) > MAX_STEM_LEN:
        slug = slug[:MAX_STEM_LEN].rstrip("-")
    report_name = f"chetameck_report_{slug}.html"
    report_path = Path(outdir) / report_name
    report_path.write_text(res["report_html"], encoding="utf-8")

    # Build a JSON meta file compatible with the metacheck contract.
    meta = {
        "status": "done",
        "format": "html",
        "engine": "chetameck",
        "report_file": report_name,
        "paper_id": res["paper"].paper_id,
        "title": title,
        "modules": list(modules),
        "summary": [
            {"module": o["module"], "traffic_light": o["traffic_light"],
             "summary_text": o["summary_text"]}
            for o in res["outputs"]
        ],
    }
    meta_path = Path(outdir) / f"{stem}_report.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    log(f"ChetaMeck report written to {report_name}")
    return meta


def run_plagiarism_engine(xml_path, outdir, stem, options=None, on_log=None,
                          pdf_path=None):
    """Run the licence-free Plagiarism Check engine (see ``plagcheck``)."""
    from plagcheck import run_plagiarism
    return run_plagiarism(xml_path, outdir, stem, options=options,
                          on_log=on_log, pdf_path=pdf_path)


def run_metacheck(xml_path, outdir, stem, modules, on_log=None):
    """Run the R script that reads the XML and generates a report."""
    if not config.RSCRIPT:
        raise RuntimeError(
            "Rscript not found. Install R and the metacheck package to "
            "generate the report."
        )
    script = config.SCRIPTS_DIR / "metacheck_report.R"
    cmd = [
        config.RSCRIPT,
        str(script),
        "--xml", str(xml_path),
        "--outdir", str(outdir),
        "--name", stem,
        "--modules", ",".join(modules),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    if on_log:
        if proc.stdout.strip():
            on_log(proc.stdout.strip())
        if proc.stderr.strip():
            on_log(proc.stderr.strip())
    report_json = outdir / f"{stem}_report.json"
    if report_json.exists():
        try:
            meta = json.loads(report_json.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            meta = None
    else:
        meta = None
    if meta is not None:
        return meta
    if proc.returncode != 0:
        raise RuntimeError(
            "metacheck failed:\n" + (proc.stderr or proc.stdout)[-2000:]
        )
    raise RuntimeError("metacheck finished but produced no report JSON.")


def run_pipeline(manuscript, grobid_url=None, modules=None, outdir=None,
                 engines=None, engine="metacheck", on_step=None, on_log=None,
                 plag_options=None, include_online=True):
    """Run the full manuscript -> PDF -> GROBID XML -> check engine pipeline.

    `manuscript` is a path to a PDF/DOCX/DOC/HTML file.
    `engines` is a list of engines to run, each one of ``"metacheck"`` (R),
    ``"chetameck"`` (Python) or ``"plagiarism"`` (licence-free overlap check;
    options in ``plag_options``). ``engine`` is a single-engine shorthand kept
    for backwards compatibility.
    `modules` is the full list of ChetaMeck module names selected by the user
    (it is filtered per engine internally); ``include_online`` controls whether
    modules that contact external services are included.
    `on_step(name, status, message)` and `on_log(text)` are optional callbacks.
    Returns a dict whose ``reports`` list holds one entry per engine.
    """
    if engines is None:
        engines = [engine]
    elif isinstance(engines, str):
        engines = [engines]
    engines = [e for e in engines if e in ENGINES]
    if not engines:
        raise ValueError(f"No valid engine selected. Must be one of {ENGINES}.")

    result = {
        "status": "running",
        "steps": [],
        "error": None,
        "xml_path": None,
        "report_path": None,
        "report_format": None,
        "report_json": None,
        "pdf_path": None,
        "outdir": None,
        "engine": engines[0] if len(engines) == 1 else ",".join(engines),
        "engines": engines,
        "reports": [],
    }

    def step(name, status, message=""):
        result["steps"].append({"name": name, "status": status, "message": message})
        if on_step:
            on_step(name, status, message)

    try:
        manuscript = Path(manuscript)
        if not manuscript.exists():
            raise FileNotFoundError(f"File not found: {manuscript}")
        ext = manuscript.suffix.lower()
        if ext not in ALLOWED_EXT:
            raise ValueError(
                f"Unsupported file type '{ext}'. Allowed: PDF, HTML, DOCX, DOC."
            )
        stem = safe_stem(manuscript.name)
        grobid_url = (grobid_url or config.DEFAULT_GROBID_URL).strip()

        if outdir is None:
            outdir = config.default_output_dir() / f"{stem}_{_timestamp()}"
            outdir.mkdir(parents=True, exist_ok=True)
        else:
            outdir = Path(outdir)
            outdir.mkdir(parents=True, exist_ok=True)
        result["outdir"] = str(outdir)

        # --- step 1: ensure a PDF -------------------------------------------------
        if ext == ".pdf":
            step("pdf", "done", "Input was already a PDF.")
            pdf_path = outdir / f"{stem}.pdf"
            pdf_path.write_bytes(manuscript.read_bytes())
        else:
            step("pdf", "running", f"Converting {ext} to PDF with LibreOffice...")
            if not config.SOFFICE:
                raise RuntimeError(
                    "LibreOffice not found. Install it (or set the SOFFICE env "
                    "var) to convert DOCX/HTML, or upload a PDF directly."
                )
            pdf_path = convert_to_pdf(config.SOFFICE, manuscript, outdir)
            step("pdf", "done", f"Converted to {pdf_path.name}.")
        result["pdf_path"] = str(pdf_path)

        # --- step 2: GROBID -> TEI XML -------------------------------------------
        ok, detail = check_grobid(grobid_url)
        if not ok:
            raise RuntimeError(
                f"GROBID server {grobid_url} is not reachable ({detail})."
            )
        step("grobid", "running", f"Converting PDF to XML via {grobid_url}...")
        xml_path = grobid_to_xml(grobid_url, pdf_path, outdir, stem)
        result["xml_path"] = str(xml_path)
        step("grobid", "done", f"Produced {xml_path.name}.")

        # --- step 3: run each selected engine ------------------------------------
        for eng in engines:
            label = {"chetameck": "ChetaMeck",
                     "plagiarism": "Plagiarism Check"}.get(eng, "metacheck")
            step("metacheck", "running", f"Running {label}...")
            try:
                if eng == "plagiarism":
                    meta = run_plagiarism_engine(xml_path, outdir, stem,
                                                 options=plag_options,
                                                 on_log=on_log, pdf_path=pdf_path)
                else:
                    base = modules if modules is not None else module_list(include_online)
                    eng_modules = filter_modules(base, eng, include_online)
                    if not eng_modules:
                        raise RuntimeError(
                            f"No modules selected for {label}.")
                    if eng == "chetameck":
                        meta = run_chetameck(xml_path, outdir, stem, eng_modules,
                                             on_log=on_log, pdf_path=pdf_path)
                    else:
                        meta = run_metacheck(xml_path, outdir, stem, eng_modules,
                                             on_log=on_log)
                fmt = meta.get("format")
                report_name = meta.get("report_file")
                if report_name:
                    report_path = outdir / report_name
                elif fmt == "html":
                    report_path = outdir / f"{stem}_report.html"
                elif fmt == "qmd":
                    report_path = outdir / f"{stem}_report.qmd"
                else:
                    report_path = None
                rep = {
                    "engine": eng, "status": "done",
                    "report_json": meta, "report_file": report_name,
                    "report_path": str(report_path) if report_path else None,
                    "report_format": fmt,
                }
                result["reports"].append(rep)
                step("metacheck", "done", f"{label}: report generated ({fmt}).")
            except Exception as e:  # noqa: BLE001
                rep = {"engine": eng, "status": "error", "error": str(e),
                       "report_json": None, "report_file": None,
                       "report_path": None, "report_format": None}
                result["reports"].append(rep)
                step("metacheck", "error", f"{label}: {e}")

        # --- top-level fields for backwards compatibility ------------------------
        done = [r for r in result["reports"] if r["status"] == "done"]
        if done:
            first = done[0]
            result["report_path"] = first["report_path"]
            result["report_json"] = first["report_json"]
            result["report_format"] = first["report_format"]
            result["status"] = "done"
        else:
            errs = [f"{r['engine']}: {r.get('error')}" for r in result["reports"]]
            result["status"] = "error"
            result["error"] = "; ".join(errs)

    except Exception as e:  # noqa: BLE001
        result["status"] = "error"
        result["error"] = str(e)
        step("error", "error", str(e))

    return result

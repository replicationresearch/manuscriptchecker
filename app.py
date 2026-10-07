"""metacheck app - upload a manuscript, convert to XML with GROBID, run metacheck.

Run with:
    uvicorn app:app --host 127.0.0.1 --port 8000
or use run.bat.

This is a thin FastAPI wrapper around ``pipeline.py``: all conversion/GROBID/
check-engine logic lives there (shared with the desktop GUI) so it is only
implemented once.
"""

import shutil
import threading
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import config
import pipeline

app = FastAPI(title="metacheck app", version="0.5.2")

app.mount("/static", StaticFiles(directory=str(config.STATIC_DIR)), name="static")

ALLOWED_EXT = pipeline.ALLOWED_EXT
JOBS = {}
JOBS_LOCK = threading.Lock()


def _chetameck_ok():
    try:
        import chetameck  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _new_job():
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",           # queued | running | done | error
        "steps": [],
        "error": None,
        "original_name": None,
        "pdf_path": None,
        "xml_path": None,
        "report_path": None,
        "report_format": None,
        "report_json": None,
    }
    with JOBS_LOCK:
        JOBS[job_id] = job
    return job


def _set_step(job, name, status, message=""):
    job["steps"].append({"name": name, "status": status, "message": message})


def _saved_dir(job_id):
    d = config.UPLOAD_DIR / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Pipeline (runs in a background thread)
# ---------------------------------------------------------------------------
def _run_pipeline(job_id, file_bytes, filename, grobid_url, modules,
                  engines=None, engine="metacheck", include_online=True):
    """Write the upload to disk and delegate everything else to pipeline.py.

    Keeping the actual conversion/GROBID/check-engine logic in one place
    (``pipeline.py``) means the web app and the desktop GUI can't drift out
    of sync with each other.
    """
    job = JOBS.get(job_id)
    job["status"] = "running"
    job["original_name"] = Path(filename).name
    engines = engines or [engine]
    job["engines"] = engines
    try:
        outdir = _saved_dir(job_id)
        src_path = outdir / (Path(filename).name or "manuscript")
        src_path.write_bytes(file_bytes)

        def on_step(name, status, message):
            _set_step(job, name, status, message)

        result = pipeline.run_pipeline(
            src_path, grobid_url=grobid_url, modules=modules, outdir=outdir,
            engines=engines, include_online=include_online, on_step=on_step,
        )
        # on_step already appended every step into job["steps"] live; don't
        # let the final result overwrite that with its own (identical) copy.
        result.pop("steps", None)
        job.update(result)
    except Exception as e:  # noqa: BLE001
        job["status"] = "error"
        job["error"] = str(e)
        _set_step(job, "error", "error", str(e))


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index():
    return (config.TEMPLATES_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def api_config():
    return {
        "default_grobid_url": config.DEFAULT_GROBID_URL,
        "grobid_servers": config.PUBLIC_GROBID_SERVERS,
    }


@app.get("/api/modules")
def api_modules():
    """Return the ChetaMeck module catalog grouped by category.

    Drives the check-selection UI. ``engine`` tells us which category the
    module belongs to and whether it is available for a given engine.
    """
    from chetameck.catalog import CATEGORIES, module_category
    r_supported = set(pipeline.FAST_MODULES + pipeline.ONLINE_MODULES)
    cats = []
    for cat_name, cat in CATEGORIES.items():
        modules = []
        for mname, label, desc in cat["modules"]:
            modules.append({
                "name": mname,
                "label": label,
                "description": desc,
                "category": cat_name,
                "online": mname in pipeline.ONLINE_MODULES,
                "chetameck_only": cat_name in pipeline.CHETAMECK_ONLY_CATS,
                "metacheck_supported": mname in r_supported,
            })
        cats.append({"id": cat_name, "label": cat["label"], "modules": modules})
    return {"categories": cats, "engines": list(pipeline.ENGINES)}


@app.get("/api/status")
def api_status():
    grobid_ok, grobid_detail = pipeline.check_grobid(config.DEFAULT_GROBID_URL)
    servers = []
    for s in config.PUBLIC_GROBID_SERVERS:
        ok, detail = pipeline.check_grobid(s["url"])
        servers.append({**s, "reachable": ok, "detail": detail})
    return {
        "rscript": bool(config.RSCRIPT),
        "rscript_path": config.RSCRIPT,
        "libreoffice": bool(config.SOFFICE),
        "libreoffice_path": config.SOFFICE,
        "chetameck": _chetameck_ok(),
        "grobid": grobid_ok,
        "grobid_url": config.DEFAULT_GROBID_URL,
        "grobid_detail": grobid_detail,
        "grobid_servers": servers,
    }


async def _read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks, aborting as soon as it exceeds ``max_bytes``.

    ``UploadFile.read()`` with no size limit buffers the whole body in memory
    regardless of size; this stops a large/malicious upload before that
    happens instead of after.
    """
    chunks = bytearray()
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        chunks.extend(chunk)
        if len(chunks) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=f"File too large (max {max_bytes // (1024 * 1024)} MB).",
            )
    return bytes(chunks)


@app.post("/api/process")
async def api_process(
    file: UploadFile = File(...),
    grobid_url: str = Form(""),
    include_online: bool = Form(True),
    engines: str = Form(""),
    modules: str = Form(""),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file supplied.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Allowed: PDF, HTML, DOCX, DOC.",
        )
    if engines.strip():
        engine_list = [e.strip() for e in engines.split(",") if e.strip()]
    else:
        engine_list = ["metacheck"]
    for e in engine_list:
        if e not in pipeline.ENGINES:
            raise HTTPException(status_code=400, detail=f"Unknown engine '{e}'.")

    grobid_url = grobid_url.strip() or config.DEFAULT_GROBID_URL
    if modules.strip():
        module_names = [m for m in modules.split(",") if m.strip()]
    else:
        module_names = config.module_list(include_online)

    job = _new_job()
    file_bytes = await _read_upload(file, config.MAX_UPLOAD_BYTES)
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if not pipeline.sniff_file_type(file_bytes, ext):
        raise HTTPException(
            status_code=400,
            detail=f"The file's content does not look like a valid '{ext}' file.",
        )

    t = threading.Thread(
        target=_run_pipeline,
        args=(job["id"], file_bytes, file.filename, grobid_url, module_names,
              engine_list, "metacheck", include_online),
        daemon=True,
    )
    t.start()

    return {"job_id": job["id"]}


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


def _job_file(job_id, key):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    path = job.get(key)
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail=f"{key} not available yet.")
    return Path(path)


@app.get("/api/job/{job_id}/xml")
def api_xml(job_id: str):
    p = _job_file(job_id, "xml_path")
    return PlainTextResponse(p.read_text(encoding="utf-8"), media_type="application/xml")


@app.get("/api/job/{job_id}/pdf")
def api_pdf(job_id: str):
    p = _job_file(job_id, "pdf_path")
    return FileResponse(p, media_type="application/pdf")


@app.get("/api/job/{job_id}/report")
def api_report(job_id: str, engine: str = ""):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    if engine:
        rep = next((r for r in (job.get("reports") or [])
                    if r.get("engine") == engine and r.get("report_path")), None)
        if not rep:
            raise HTTPException(status_code=404,
                                detail=f"Report for engine '{engine}' not available.")
        path = rep["report_path"]
    else:
        path = job.get("report_path")
    if not path or not Path(path).exists():
        raise HTTPException(status_code=404, detail="Report not available yet.")
    media = "text/html" if Path(path).suffix == ".html" else "text/plain"
    return FileResponse(path, media_type=media)


@app.get("/api/job/{job_id}/download")
def api_download(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")
    d = config.UPLOAD_DIR / job_id
    if not d.exists():
        raise HTTPException(status_code=404, detail="Job files not found.")
    zip_path = config.UPLOAD_DIR / f"{job_id}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", str(d))
    return FileResponse(zip_path, media_type="application/zip",
                        filename=f"{job_id}.zip")

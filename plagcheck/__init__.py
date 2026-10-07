"""Plagiarism Check engine (third engine next to metacheck and ChetaMeck).

Licence-free text-overlap detection: exact-phrase retrieval in open scholarly
full texts (Europe PMC, OpenAlex) plus shingle-based verification against the
downloaded full texts and any local comparison files. See ``core`` for the
algorithm and its limits.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import core

PLAG_APP_VERSION = "0.2.0"
SKIP_SECTIONS = {"references", "figure", "table"}


def _manuscript_rows(paper):
    text = paper.table("text")
    sec = paper.table("section")
    stype = {}
    if not sec.empty:
        stype = dict(zip(sec["section_id"], sec["section_type"]))
    rows = []
    for _, r in text.iterrows():
        if stype.get(r.get("section_id")) in SKIP_SECTIONS:
            continue
        t = str(r.get("text") or "").strip()
        if t:
            sid = r.get("section_id")
            header = ""
            if not sec.empty:
                m = sec[sec["section_id"] == sid]
                if not m.empty:
                    header = str(m.iloc[0].get("header") or "")
            rows.append({"text": t, "header": core._strip_html(header)})
    return rows


def _ref_context(paper):
    """DOIs and normalised reference text of the manuscript's own references."""
    dois, blob = set(), ""
    try:
        from chetameck.modules._refs import ref_table
        rt = ref_table(paper)
        if not rt.empty:
            dois = {str(d).strip().lower() for d in rt["doi"].dropna()
                    if str(d).strip()}
            blob = " ".join(core.tokenize_words(" ".join(rt["text"].dropna())))
    except Exception:  # noqa: BLE001
        pass
    return dois, blob


def _analyse(doc, name, meta, text, kind):
    words = [w for w, _, _ in core.tokenize(text)]
    toks = core.tokenize(text)
    covered, runs = core.match_doc(doc, words)
    n_cov = sum(1 for c in covered if c)
    passages = []
    for a, b, p in runs[:25]:
        ms, me = doc.spans[a][0], doc.spans[b - 1][1]
        q = min(p + (b - a), len(toks)) - 1
        src_txt = text[toks[p][1]:toks[q][2]] if toks else ""
        passages.append({"manuscript": doc.text[ms:me], "source": src_txt,
                         "words": b - a, "row": doc.row_of_char(ms)})
    return dict(meta, kind=kind, name=name, covered=covered,
                matched_words=n_cov, n_runs=len(runs), passages=passages,
                coverage=(n_cov / doc.n_scored) if doc.n_scored else 0.0)


def _phrase_log_path(doc):
    import hashlib
    import os
    key = hashlib.sha1(doc.text.encode("utf-8", "ignore")).hexdigest()[:16]
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "MuCOS_PlagCheck" / "phrase_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _load_phrase_log(path):
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"runs": []}


def run_plagiarism(xml_path, outdir, stem, options=None, on_log=None,
                   pdf_path=None):
    """Run the check and write the HTML report. Returns a meta dict."""
    from chetameck.paper import read_paper
    from .report import build_report

    opts = {"max_passages": 120, "max_sources": 15, "online": True,
            "extra_files": [], "library_dir": None, "seed": None,
            "skip_used": False, "mailto": None}
    opts.update(options or {})

    def log(msg):
        if on_log:
            on_log(msg)

    paper = read_paper(str(xml_path))
    title = ""
    doi = ""
    if not paper.info.empty:
        title = str(paper.info.iloc[0].get("title") or "")
        doi = str(paper.info.iloc[0].get("doi") or "").lower()
    rows = _manuscript_rows(paper)
    doc = core.Doc(rows)
    log(f"Plagiarism check: {len(doc.words)} words "
        f"({doc.n_scored} scored; {doc.quote_words} quoted words excluded).")
    ref_dois, ref_blob = _ref_context(paper)

    sources, unverified, notes = [], [], []

    # --- local comparison files ------------------------------------------------
    for f in opts["extra_files"]:
        try:
            p = Path(f)
            text = core.bytes_to_text(p.read_bytes(), p.name)
            log(f"Plagiarism check: comparing with local file {p.name}")
            sources.append(_analyse(doc, p.name,
                                    {"title": p.name, "year": "", "authors": "",
                                     "doi": "", "url": p.resolve().as_uri(),
                                     "source": "local file", "phrases": []},
                                    text, "local"))
        except Exception as e:  # noqa: BLE001
            notes.append(f"Could not read local file {f}: {e}")

    # --- literature / Zotero folder ----------------------------------------------
    lib_stats = None
    lib_dir = opts.get("library_dir")
    if lib_dir:
        files = core.list_library(lib_dir) if Path(lib_dir).is_dir() else []
        if not files:
            notes.append(f"Library folder empty or not found: {lib_dir}")
        else:
            log(f"Plagiarism check: scanning {len(files)} library files in "
                f"{lib_dir} ...")
            lib_stats = {"files": len(files), "unreadable": 0, "matched": 0,
                         "dir": str(lib_dir)}
            done = 0

            def scan(p):
                try:
                    text, ttl, d = core.read_library_file(p)
                except Exception:  # noqa: BLE001
                    return p, None
                if len(text) < 500:
                    return p, None
                return p, _analyse(
                    doc, p.name,
                    {"title": ttl, "year": "", "authors": "", "doi": d,
                     "url": p.resolve().as_uri(),
                     "source": "library: " + str(p.parent.name),
                     "phrases": []}, text, "library")

            with ThreadPoolExecutor(max_workers=4) as ex:
                for p, res in ex.map(scan, files):
                    done += 1
                    if done % 25 == 0:
                        log(f"Plagiarism check: library {done}/{len(files)}")
                    if res is None:
                        lib_stats["unreadable"] += 1
                    elif res["n_runs"] > 0:
                        lib_stats["matched"] += 1
                        sources.append(res)

    # --- phrase selection (seeded; optionally skipping earlier runs) -----------
    import random
    import time
    eligible = core.eligible_phrases(doc)
    log_path = _phrase_log_path(doc)
    plog = _load_phrase_log(log_path)
    earlier = set()
    for run in plog.get("runs", []):
        earlier.update(run.get("phrases", []))
    seed = opts.get("seed")
    if seed in (None, ""):
        seed = random.randrange(1, 10**6)
    seed = int(seed)
    n_phrases = 0
    phrases = []
    skipped_used = 0
    log(f"Plagiarism check: {len(eligible)} searchable phrases in this "
        f"manuscript ({len(earlier)} already used in earlier runs).")
    if opts["online"]:
        phrases, skipped_used = core.select_phrases(
            eligible, int(opts["max_passages"]), seed,
            earlier if opts["skip_used"] else None)
        n_phrases = len(phrases)
        if opts["skip_used"] and n_phrases < int(opts["max_passages"]):
            notes.append(f"Only {n_phrases} unused phrases were left "
                         f"(requested {opts['max_passages']}).")
        log(f"Plagiarism check: searching {n_phrases} phrases (seed {seed}) in "
            "Europe PMC and OpenAlex...")
        cands = core.retrieve_candidates(phrases, on_log=on_log,
                                         mailto=opts.get("mailto") or None)
        log(f"Plagiarism check: {len(cands)} candidate sources found.")
        top = cands[:int(opts["max_sources"])]
        session = requests.Session()
        session.headers["User-Agent"] = core.UA + (
            f" mailto:{opts['mailto']}" if opts.get("mailto") else "")

        def fetch(w):
            return w, core.fetch_source_text(session, w)

        with ThreadPoolExecutor(max_workers=3) as ex:
            for w, text in ex.map(fetch, top):
                if len(text) < 500:
                    unverified.append(w)
                    continue
                log(f"Plagiarism check: compared with {w['title'][:60]}")
                sources.append(_analyse(doc, w["title"], w, text, "online"))
        unverified.extend(cands[int(opts["max_sources"]):])

    # --- flags -----------------------------------------------------------------
    for s in sources:
        s["same_work"] = False
        s["cited"] = False
        if s["kind"] in ("online", "library"):
            sim = core.title_similarity(s["title"], title)
            s["same_work"] = (bool(doi) and s.get("doi") == doi) or sim >= 0.7
            norm = " ".join(core.tokenize_words(s["title"]))[:80]
            s["cited"] = (s.get("doi") in ref_dois) or (
                len(norm) > 20 and norm in ref_blob)
    sources.sort(key=lambda s: -s["coverage"])

    counted = [s for s in sources if not s["same_work"]]
    n = len(doc.words)
    union = [False] * n
    union_uncited = [False] * n
    for s in counted:
        for i, c in enumerate(s["covered"]):
            if c:
                union[i] = True
                if not s["cited"]:
                    union_uncited[i] = True
    score = sum(union) / doc.n_scored if doc.n_scored else 0.0
    score_uncited = sum(union_uncited) / doc.n_scored if doc.n_scored else 0.0
    top_single = max((s["coverage"] for s in counted), default=0.0)

    if score >= 0.15 or top_single >= 0.15:
        tl = "red"
    elif score >= 0.05 or top_single >= 0.08:
        tl = "yellow"
    else:
        tl = "green"
    if not opts["online"] and not opts["extra_files"] and not lib_stats:
        tl = "na"
    summary_text = (f"Text overlap {score:.1%} across {len(counted)} source(s); "
                    f"{score_uncited:.1%} from sources not in the reference list.")

    # phrase bookkeeping / documentation
    by_text = {c["phrase"]: c for c in eligible}
    current_idx = set()
    for c in phrases:
        current_idx.update(range(c["gstart"], c["gstart"] + core.PHRASE_WORDS))
    earlier_idx = set()
    for ph in earlier:
        c = by_text.get(ph)
        if c:
            earlier_idx.update(range(c["gstart"], c["gstart"] + core.PHRASE_WORDS))
    if opts["online"] and phrases:
        plog.setdefault("runs", []).append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "seed": seed,
            "requested": int(opts["max_passages"]),
            "skip_used": bool(opts["skip_used"]),
            "phrases": [c["phrase"] for c in phrases]})
        plog["title"] = title
        import json
        try:
            log_path.write_text(json.dumps(plog, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        except OSError:
            pass
        (Path(outdir) / "phrase_log.json").write_text(
            json.dumps(plog, ensure_ascii=False, indent=1), encoding="utf-8")
    cumulative = set(earlier) | {c["phrase"] for c in phrases}
    phrase_info = {
        "total": len(eligible), "searched": n_phrases, "seed": seed,
        "skip_used": bool(opts["skip_used"]), "skipped_used": skipped_used,
        "earlier": len(earlier & set(by_text)), "cumulative": len(
            cumulative & set(by_text)),
        "runs": len(plog.get("runs", [])), "current_idx": current_idx,
        "earlier_idx": earlier_idx,
        "words_total": len(doc.words),
        "log_path": str(log_path)}

    result = dict(paper=paper, phrase_info=phrase_info, doc=doc, title=title or stem, sources=sources,
                  unverified=unverified, score=score,
                  score_uncited=score_uncited, traffic_light=tl,
                  summary_text=summary_text, n_phrases=n_phrases, notes=notes,
                  options=opts, union=union, lib_stats=lib_stats)
    html_report = build_report(result)

    slug = "".join(c if c.isalnum() else "-" for c in (title or stem)[:50]).strip("-")
    report_name = f"plagiarism_report_{slug or stem}.html"
    (Path(outdir) / report_name).write_text(html_report, encoding="utf-8")
    meta = {
        "status": "done", "format": "html", "engine": "plagiarism",
        "report_file": report_name, "paper_id": paper.paper_id,
        "title": title, "modules": ["plagiarism"],
        "phrases": {k: phrase_info[k] for k in (
            "total", "searched", "seed", "cumulative", "runs")},
        "summary": [{"module": "plagiarism", "traffic_light": tl,
                     "summary_text": summary_text}],
    }
    import json
    (Path(outdir) / f"{stem}_report.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Plagiarism report written to {report_name}")
    return meta

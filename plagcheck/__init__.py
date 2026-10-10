"""Plagiarism Check engine (third engine next to metacheck and ChetaMeck).

Licence-free verbatim text-overlap detection: exact-phrase retrieval (one
phrase per paragraph) in open full texts (Europe PMC, OpenAlex, Wikipedia)
plus shingle-based verification against the downloaded full texts and any
local comparison files. See ``core`` for the algorithm and its limits.

``check_document`` runs the check on plain rows of text (used by the
benchmark in ``scripts/``); ``run_plagiarism`` wraps it for a GROBID TEI file
and writes the HTML report.
"""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import core

PLAG_APP_VERSION = "0.3.0"
SKIP_SECTIONS = {"references", "figure", "table"}

DEFAULT_OPTIONS = {
    "max_passages": 0,          # cap on searched phrases; 0 = no cap
    "words_per_probe": 60,      # one phrase per N words, at least one per
                                # paragraph (0 = exactly one per paragraph)
    "max_sources": 20,          # candidates whose full text is downloaded
    "online": True, "extra_files": [], "library_dir": None, "seed": None,
    "skip_used": False, "mailto": None, "openalex_key": None,
    "backends": core.BACKENDS,
    "wiki_lang": "en",
    "phrase_log": True,         # False, True (per-user folder) or a folder path
}


def _manuscript_rows(paper):
    """Paragraphs of the manuscript body as ``[{"header", "text"}]``.

    ``paper.table("text")`` holds one row per sentence; the sentences of one
    TEI paragraph (same ``tei_paragraph``) are joined again, so phrase
    selection and the coverage counts work on real paragraphs.
    """
    text = paper.table("text")
    sec = paper.table("section")
    stype, headers = {}, {}
    if not sec.empty:
        stype = dict(zip(sec["section_id"], sec["section_type"]))
        headers = {sid: core._strip_html(str(h or ""))
                   for sid, h in zip(sec["section_id"], sec["header"])}
    rows, last = [], None
    for _, r in text.iterrows():
        sid = r.get("section_id")
        if stype.get(sid) in SKIP_SECTIONS:
            continue
        t = str(r.get("text") or "").strip()
        if not t:
            continue
        para = r.get("tei_paragraph")
        key = (sid, para) if para == para and para is not None else None
        if key is not None and key == last:
            rows[-1]["text"] += " " + t
        else:
            rows.append({"text": t, "header": headers.get(sid, "")})
        last = key
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


def _paper_meta(paper):
    title = doi = ""
    if not paper.info.empty:
        title = str(paper.info.iloc[0].get("title") or "")
        doi = str(paper.info.iloc[0].get("doi") or "").lower()
    authors = []
    au = paper.table("author")
    if not au.empty:
        authors = [core.author_key(str(a.get("family") or ""),
                                   str(a.get("given") or ""))
                   for _, a in au.iterrows()]
    ref_dois, ref_blob = _ref_context(paper)
    return {"title": title, "doi": doi, "author_keys": authors,
            "ref_dois": ref_dois, "ref_blob": ref_blob}


def _analyse(doc, name, meta, text, kind):
    text = core.clean_text(text)
    toks = core.tokenize(text)
    words = [w for w, _, _ in toks]
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


def _phrase_log_path(doc, folder=None):
    import hashlib
    import os
    key = hashlib.sha1(doc.text.encode("utf-8", "ignore")).hexdigest()[:16]
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(folder) if folder else Path(base) / "MuCOS_PlagCheck" / "phrase_logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.json"


def _load_phrase_log(path):
    import json
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"runs": []}


def classify(work, meta):
    """Relation of a source to the manuscript: same work / own work / cited.

    *Same work* (dropped from the report) needs strong evidence, because a
    dropped source is never downloaded: the same DOI, a shared author plus a
    similar title (e.g. the preprint of the manuscript), or a title that is
    the same word for word. A merely similar title is not enough - "X
    increases Y" and "X does not increase Y" are different papers.
    *Own prior work* (labelled, still counted): any shared author.
    """
    if work.get("kind") == "local":
        return {"same_work": False, "own_work": [], "cited": False}
    title = work.get("title") or ""
    shared = core.shared_authors(meta.get("author_keys") or [],
                                 work.get("author_keys") or [])
    same = ((bool(meta["doi"]) and work.get("doi") == meta["doi"])
            or (bool(shared) and core.title_similarity(title, meta["title"]) >= 0.5)
            or core.title_similarity(title, meta["title"], strict=True) >= 0.9)
    norm = " ".join(core.tokenize_words(core.clean_text(title)))[:80]
    cited = bool(work.get("doi") and work["doi"] in meta["ref_dois"]) or (
        len(norm) > 20 and norm in meta["ref_blob"])
    return {"same_work": same, "own_work": shared, "cited": cited}


def _search_warnings(search_stats):
    out = []
    for name, st in search_stats.items():
        lost = st["failed"] + st["quota"]
        if lost:
            why = ("its free daily allowance was used up - add an OpenAlex API "
                   "key or re-run tomorrow" if st["quota"] else
                   "the service did not answer")
            out.append(f"WARNING: {name} left {lost} of {st['ok'] + lost} phrase "
                       f"searches unanswered ({why}). Sources that only {name} "
                       "indexes may have been missed.")
    return out


def check_document(rows, meta, options=None, on_log=None):
    """Run the check on manuscript ``rows`` and return the result dict.

    ``meta``: title, doi, author_keys [(family, initial)], ref_dois (set),
    ref_blob (normalised reference-list text). Online candidates are first
    classified on search metadata, so versions of the manuscript itself are
    neither downloaded nor reported.
    """
    import random
    import time
    opts = dict(DEFAULT_OPTIONS)
    opts.update(options or {})
    meta = dict({"title": "", "doi": "", "author_keys": [], "ref_dois": set(),
                 "ref_blob": ""}, **meta)

    def log(msg):
        if on_log:
            on_log(msg)

    doc = core.Doc(rows)
    log(f"Plagiarism check: {len(doc.words)} words "
        f"({doc.n_scored} scored; {doc.quote_words} quoted words excluded).")
    sources, phrase_only, compared_no_match, same_work, notes = [], [], [], [], []
    search_stats = {}

    # --- local comparison files ------------------------------------------------
    for f in opts["extra_files"]:
        try:
            p = Path(f)
            text = core.bytes_to_text(p.read_bytes(), p.name)
            log(f"Plagiarism check: comparing with local file {p.name}")
            res = _analyse(doc, p.name,
                           {"title": p.name, "year": "", "authors": "",
                            "doi": "", "url": p.resolve().as_uri(),
                            "source": "local file", "phrases": []},
                           text, "local")
            (sources if res["n_runs"] else compared_no_match).append(res)
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
                if len(text) < core.MIN_SOURCE_CHARS:
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

    # --- phrase selection: one per paragraph -------------------------------------
    eligible = core.eligible_phrases(doc)
    searchable = core.searchable_rows(doc)
    rows_with_phrase = {c["row"] for c in eligible}
    plog, log_path = {"runs": []}, None
    if opts["phrase_log"]:
        log_path = _phrase_log_path(
            doc, None if opts["phrase_log"] is True else opts["phrase_log"])
        plog = _load_phrase_log(log_path)
    earlier = set()
    for run in plog.get("runs", []):
        earlier.update(run.get("phrases", []))
    seed = opts.get("seed")
    if seed in (None, ""):
        seed = random.randrange(1, 10**6)
    seed = int(seed)
    phrases, exhausted = [], 0
    log(f"Plagiarism check: {len(searchable)} paragraphs, "
        f"{len(rows_with_phrase)} with a searchable phrase.")
    if opts["online"]:
        phrases, exhausted = core.select_phrases(
            eligible, seed, earlier if opts["skip_used"] else None,
            int(opts["max_passages"] or 0), int(opts["words_per_probe"] or 0))
        if exhausted:
            notes.append(f"{exhausted} paragraph(s) had no phrase left that was "
                         "not searched in an earlier run.")
        log(f"Plagiarism check: searching {len(phrases)} phrases (seed {seed}) in "
            f"{', '.join(opts['backends'])}...")
        client = core.OpenAlexClient(opts.get("openalex_key") or None,
                                     opts.get("mailto") or None)
        cands = core.retrieve_candidates(
            phrases, on_log=on_log, mailto=opts.get("mailto") or None,
            stats=search_stats, client=client,
            backends=opts["backends"], wiki_lang=opts["wiki_lang"])
        for w in cands:
            w.update(classify(w, meta))
        same_work = [w for w in cands if w["same_work"]]
        cands = [w for w in cands if not w["same_work"]]
        log(f"Plagiarism check: {len(cands)} candidate sources found "
            f"({len(same_work)} version(s) of this manuscript ignored).")
        top = cands[:int(opts["max_sources"])]
        session = requests.Session()
        session.headers["User-Agent"] = core.UA + (
            f" mailto:{opts['mailto']}" if opts.get("mailto") else "")

        def fetch(w):
            return w, core.fetch_source_text(session, w)

        with ThreadPoolExecutor(max_workers=3) as ex:
            for w, text in ex.map(fetch, top):
                if len(text) < core.MIN_SOURCE_CHARS:
                    phrase_only.append(w)
                    continue
                log(f"Plagiarism check: compared with {w['title'][:60]}")
                res = _analyse(doc, w["title"], w, text, "online")
                (sources if res["n_runs"] else compared_no_match).append(res)
        phrase_only.extend(cands[int(opts["max_sources"]):])
        # works known only from a combined search: find the matching phrases
        unresolved = [w for w in phrase_only + compared_no_match
                      if not w["phrases"] and w.get("batches")]
        if unresolved:
            log(f"Plagiarism check: identifying the matched phrases of "
                f"{len(unresolved)} unverified source(s)...")
            core.resolve_batch_phrases(unresolved, stats=search_stats,
                                       client=client)
        for msg in _search_warnings(search_stats):
            notes.append(msg)
            log("Plagiarism check: " + msg)

    # --- relation to the manuscript ----------------------------------------------
    kept = []
    for s in sources:
        s.update(classify(s, meta))
        (same_work if s["same_work"] else kept).append(s)
    sources = sorted(kept, key=lambda s: -s["coverage"])
    if same_work:
        notes.append("Ignored as versions of this manuscript: " + "; ".join(
            sorted({(w.get("title") or w.get("name") or "")[:90]
                    for w in same_work})))

    n = len(doc.words)
    union = [False] * n
    union_uncited = [False] * n
    union_own = [False] * n
    for s in sources:
        for i, c in enumerate(s["covered"]):
            if c:
                union[i] = True
                if not s["cited"]:
                    union_uncited[i] = True
                if s["own_work"]:
                    union_own[i] = True
    scored = doc.n_scored or 1
    score = sum(union) / scored
    score_uncited = sum(union_uncited) / scored
    score_own = sum(union_own) / scored
    top_single = max((s["coverage"] for s in sources), default=0.0)

    if score >= 0.15 or top_single >= 0.15:
        tl = "red"
    elif score >= 0.05 or top_single >= 0.08:
        tl = "yellow"
    else:
        tl = "green"
    if not opts["online"] and not opts["extra_files"] and not lib_stats:
        tl = "na"
    summary_text = (f"Verbatim overlap {score:.1%} across {len(sources)} source(s); "
                    f"{score_uncited:.1%} from sources not in the reference list"
                    + (f", {score_own:.1%} from the authors' own prior work"
                       if score_own else "") + ".")

    # --- phrase bookkeeping / documentation --------------------------------------
    by_text = {c["phrase"]: c for c in eligible}
    current_idx = set()
    for c in phrases:
        current_idx.update(range(c["gstart"], c["gstart"] + core.PHRASE_WORDS))
    earlier_idx = set()
    for ph in earlier:
        c = by_text.get(ph)
        if c:
            earlier_idx.update(range(c["gstart"], c["gstart"] + core.PHRASE_WORDS))
    # a phrase counts as searched only if every service answered in this run;
    # otherwise "skip phrases from earlier runs" would never retry it
    complete = not any(st["failed"] or st["quota"] for st in search_stats.values())
    if opts["online"] and phrases and log_path:
        import json
        plog.setdefault("runs", []).append({
            "time": time.strftime("%Y-%m-%d %H:%M:%S"), "seed": seed,
            "skip_used": bool(opts["skip_used"]), "complete": complete,
            "phrases": [c["phrase"] for c in phrases] if complete else []})
        plog["title"] = meta["title"]
        try:
            log_path.write_text(json.dumps(plog, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        except OSError:
            pass
    probed_rows = {c["row"] for c in phrases}
    cumulative = set(earlier) | {c["phrase"] for c in phrases}
    phrase_info = {
        "total": len(eligible), "searched": len(phrases), "seed": seed,
        "skip_used": bool(opts["skip_used"]), "exhausted": exhausted,
        "paragraphs": len(searchable), "paragraphs_probeable": len(rows_with_phrase),
        "paragraphs_probed": len(probed_rows),
        "earlier": len(earlier & set(by_text)), "cumulative": len(
            cumulative & set(by_text)),
        "runs": len(plog.get("runs", [])), "current_idx": current_idx,
        "earlier_idx": earlier_idx, "words_total": len(doc.words),
        "log_path": str(log_path or ""), "backends": list(opts["backends"])}

    return dict(phrase_info=phrase_info, doc=doc, title=meta["title"],
                sources=sources, phrase_only=phrase_only,
                compared_no_match=compared_no_match, same_work=same_work,
                score=score, score_uncited=score_uncited, score_own=score_own,
                traffic_light=tl, summary_text=summary_text,
                n_phrases=len(phrases), phrases=phrases, notes=notes,
                # never hand credentials on to reports or result files
                options={k: v for k, v in opts.items()
                         if k not in ("openalex_key", "mailto")},
                union=union, lib_stats=lib_stats, plog=plog,
                search_stats=search_stats)


def run_plagiarism(xml_path, outdir, stem, options=None, on_log=None,
                   pdf_path=None):
    """Run the check and write the HTML report. Returns a meta dict."""
    import json
    from chetameck.paper import read_paper
    from .report import build_report

    paper = read_paper(str(xml_path))
    meta = _paper_meta(paper)
    r = check_document(_manuscript_rows(paper), meta, options, on_log)
    r["title"] = meta["title"] or stem
    html_report = build_report(r)

    if r["plog"].get("runs"):
        (Path(outdir) / "phrase_log.json").write_text(
            json.dumps(r["plog"], ensure_ascii=False, indent=1), encoding="utf-8")
    slug = "".join(c if c.isalnum() else "-" for c in r["title"][:50]).strip("-")
    report_name = f"plagiarism_report_{slug or stem}.html"
    (Path(outdir) / report_name).write_text(html_report, encoding="utf-8")
    info = r["phrase_info"]
    tl = r["traffic_light"]
    out = {
        "status": "done", "format": "html", "engine": "plagiarism",
        "report_file": report_name, "paper_id": paper.paper_id,
        "title": meta["title"], "modules": ["plagiarism"],
        "phrases": {k: info[k] for k in (
            "total", "searched", "seed", "cumulative", "runs", "paragraphs",
            "paragraphs_probed")},
        "summary": [{"module": "plagiarism", "traffic_light": tl,
                     "summary_text": r["summary_text"]}],
    }
    (Path(outdir) / f"{stem}_report.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    if on_log:
        on_log(f"Plagiarism report written to {report_name}")
    return out

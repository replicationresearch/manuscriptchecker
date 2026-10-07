"""Licence-free plagiarism / text-overlap detection.

No commercial database is used. The algorithm has two stages:

1. **Candidate retrieval.** Distinctive 9-word phrases are cut from sentences
   spread across the manuscript and searched as *exact phrases* in the full
   text of open scholarly sources (Europe PMC open-access articles and the
   OpenAlex full-text index). A work that contains one of these phrases is a
   candidate source.
2. **Verification.** The open full text of the best candidates (and of any
   local comparison files) is downloaded and compared with the *whole*
   manuscript using word shingles (the approach of WCopyfind: 6-word
   shingles, matches of at least 8 consecutive words). Quoted passages and
   parenthetical citations are excluded.

Limits (stated in every report): only open full texts are searched, so
paywalled publisher content, student theses and most books are invisible, and
paraphrase without shared word runs is not detected. A similarity score is a
pointer for a human to look at, not a verdict.
"""

import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor

import requests

SHINGLE = 6          # words per shingle
MIN_RUN = 8          # shortest reported match, in words
PHRASE_WORDS = 9     # words per search phrase
COMMON_PHRASE_HITS = 25   # a phrase found in more works than this is boilerplate
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
HTTP_TIMEOUT = 25
UA = "MuCOS-PlagiarismCheck/1.0 (non-commercial research tool)"

TOKEN_RE = re.compile(r"[^\W_]+(?:['’][^\W_]+)?", re.U)
_CITE_RE = re.compile(r"\([^()]*\b(?:1[89]|20)\d{2}[a-z]?\b[^()]*\)")
_QUOTE_RE = re.compile(r"[“\"„]([^”\"“]{25,700}?)[”\"]")

STOP = frozenset("""a about above after again all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only
or other our out over own same she should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom why will with would you your
et al fig table""".split())


# ----------------------------------------------------------------- tokenising
def tokenize(text):
    """Return [(lowercased word, start, end)] for ``text``."""
    return [(m.group(0).lower(), m.start(), m.end())
            for m in TOKEN_RE.finditer(text or "")]


def tokenize_words(text):
    return [t[0] for t in tokenize(text)]


def _strip_html(text):
    import html
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text or "")).split())


def _ignored_spans(text):
    """Char spans excluded from matching: long quotations and (Author, year)."""
    spans = []
    for m in _QUOTE_RE.finditer(text):
        if len(TOKEN_RE.findall(m.group(1))) >= 5:
            spans.append((m.start(), m.end(), "quote"))
    for m in _CITE_RE.finditer(text):
        spans.append((m.start(), m.end(), "citation"))
    return spans


class Doc:
    """A manuscript: concatenated text of its rows plus token bookkeeping."""

    def __init__(self, rows):
        # rows: [{"header", "text"}] in reading order
        self.rows = rows
        self.row_offsets = []
        parts, pos = [], 0
        for r in rows:
            self.row_offsets.append(pos)
            parts.append(r["text"])
            pos += len(r["text"]) + 1
        self.text = "\n".join(parts)
        toks = tokenize(self.text)
        self.words = [t[0] for t in toks]
        self.spans = [(t[1], t[2]) for t in toks]
        ign = _ignored_spans(self.text)
        self.ignored = [False] * len(toks)
        self.quote_words = 0
        for i, (s, e) in enumerate(self.spans):
            for a, b, kind in ign:
                if s >= a and e <= b:
                    self.ignored[i] = True
                    if kind == "quote":
                        self.quote_words += 1
                    break
        self.n_scored = sum(1 for x in self.ignored if not x)

    def row_of_char(self, ch):
        lo, hi = 0, len(self.row_offsets) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.row_offsets[mid] <= ch:
                lo = mid
            else:
                hi = mid - 1
        return lo


def _doc_index(doc):
    """hash(shingle) -> [token index] of the manuscript (built once)."""
    idx = getattr(doc, "_shingle_index", None)
    if idx is None:
        idx = {}
        w = doc.words
        for i in range(len(w) - SHINGLE + 1):
            if any(doc.ignored[i:i + SHINGLE]):
                continue
            idx.setdefault(hash(tuple(w[i:i + SHINGLE])), []).append(i)
        doc._shingle_index = idx
    return idx


def match_doc(doc, source_words):
    """Compare a manuscript with one source text.

    Returns ``(covered, runs)``: a per-token bool list (only runs >= MIN_RUN
    words are kept) and ``[(start, end, source_start)]`` token runs. The
    manuscript index is built once, so each source costs one pass over its
    own words (fast enough for hundreds of library PDFs).
    """
    n = len(doc.words)
    idx = _doc_index(doc)
    if n < SHINGLE or not idx:
        return [False] * n, []
    hit = [False] * n
    src_pos = {}
    sw = source_words
    for p in range(len(sw) - SHINGLE + 1):
        locs = idx.get(hash(tuple(sw[p:p + SHINGLE])))
        if locs:
            for i in locs:
                for j in range(i, i + SHINGLE):
                    hit[j] = True
                src_pos.setdefault(i, p)
    covered = [False] * n
    runs = []
    i = 0
    while i < n:
        if hit[i]:
            j = i
            while j < n and hit[j]:
                j += 1
            if j - i >= MIN_RUN:
                for t in range(i, j):
                    covered[t] = True
                first = next((src_pos[t] for t in range(i, j) if t in src_pos), 0)
                runs.append((i, j, first))
            i = j
        else:
            i += 1
    return covered, runs


# ------------------------------------------------------- phrase selection
def _row_token_starts(doc):
    """Global token index of the first token of every row."""
    starts = []
    lo = 0
    for base in doc.row_offsets:
        while lo < len(doc.spans) and doc.spans[lo][0] < base:
            lo += 1
        starts.append(lo)
    return starts


def eligible_phrases(doc, per_row=3):
    """All searchable 9-word phrases of the manuscript.

    Per sentence-like row up to ``per_row`` non-overlapping windows with at
    least 5 content words, no digits and no quoted / citation words. Returns
    dicts ``{row, phrase, gstart, score, rank}``.
    """
    starts = _row_token_starts(doc)
    out = []
    for ridx, row in enumerate(doc.rows):
        text = row["text"]
        if not text or row.get("skip"):
            continue
        toks = tokenize(text)
        n = len(toks)
        if n < 12:
            continue
        g0 = starts[ridx]
        wins = []
        for i in range(0, n - PHRASE_WORDS + 1):
            win = toks[i:i + PHRASE_WORDS]
            if any(g0 + i + k < len(doc.ignored) and doc.ignored[g0 + i + k]
                   for k in range(PHRASE_WORDS)):
                continue
            if any(w[0].isdigit() for w in win):
                continue
            score = sum(1 for w in win if w[0] not in STOP and len(w[0]) > 3)
            if score >= 5:
                wins.append((score, i))
        wins.sort(key=lambda x: (-x[0], x[1]))
        taken = []
        for score, i in wins:
            if len(taken) >= per_row:
                break
            if all(abs(i - j) >= PHRASE_WORDS for _, j in taken):
                taken.append((score, i))
        for rank, (score, i) in enumerate(taken):
            out.append({"row": ridx, "gstart": g0 + i, "score": score,
                        "rank": rank,
                        "phrase": " ".join(w[0] for w in toks[i:i + PHRASE_WORDS])})
    out.sort(key=lambda x: x["gstart"])
    return out


def select_phrases(cands, n, seed, exclude=None):
    """Seeded, evenly spread sample of ``n`` phrases not in ``exclude``."""
    import random
    exclude = exclude or set()
    pool = [c for c in cands if c["phrase"] not in exclude]
    if len(pool) <= n:
        return list(pool), len(cands) - len(pool)
    rng = random.Random(seed)
    chosen = []
    step = len(pool) / float(n)
    for k in range(n):
        lo, hi = int(k * step), max(int((k + 1) * step), int(k * step) + 1)
        chosen.append(pool[rng.randrange(lo, hi)])
    return chosen, len(cands) - len(pool)


# --------------------------------------------------------- online retrieval
def _get(session, url, **kw):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=HTTP_TIMEOUT, **kw)
            if r.status_code == 429:
                import time
                time.sleep(2 + 2 * attempt)
                continue
            return r
        except requests.RequestException:
            if attempt == 2:
                return None
    return None


def search_europepmc(session, phrase):
    """Exact-phrase full-text search over open-access Europe PMC articles."""
    r = _get(session, "https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={
        "query": f'BODY:"{phrase}" AND OPEN_ACCESS:y', "format": "json",
        "pageSize": 6, "resultType": "lite"})
    if r is None or r.status_code != 200:
        return 0, []
    j = r.json()
    out = []
    for x in j.get("resultList", {}).get("result", []):
        if not x.get("pmcid"):
            continue
        out.append({
            "key": "pmc:" + x["pmcid"], "source": "Europe PMC",
            "title": x.get("title", ""), "year": x.get("pubYear"),
            "authors": x.get("authorString", ""),
            "doi": (x.get("doi") or "").lower(),
            "url": f"https://europepmc.org/article/PMC/{x['pmcid'][3:]}",
            "pmcid": x["pmcid"]})
    return int(j.get("hitCount", 0)), out


def search_openalex(session, phrase, mailto=None):
    """Exact-phrase search of the OpenAlex index (includes full text)."""
    params = {
        "search": f'"{phrase}"', "per-page": 6,
        "select": "id,doi,title,publication_year,authorships,best_oa_location,open_access"}
    if mailto:
        params["mailto"] = mailto      # OpenAlex "polite pool"
    r = _get(session, "https://api.openalex.org/works", params=params)
    if r is None or r.status_code != 200:
        return 0, []
    j = r.json()
    out = []
    for w in j.get("results", []):
        loc = w.get("best_oa_location") or {}
        pdf = loc.get("pdf_url") or (w.get("open_access") or {}).get("oa_url")
        names = [a.get("author", {}).get("display_name", "")
                 for a in (w.get("authorships") or [])[:3]]
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        out.append({
            "key": "oa:" + w["id"].rsplit("/", 1)[-1], "source": "OpenAlex",
            "title": w.get("title") or "", "year": w.get("publication_year"),
            "authors": ", ".join(n for n in names if n),
            "doi": doi, "url": w.get("doi") or w["id"], "pdf": pdf})
    return int(j.get("meta", {}).get("count", 0)), out


def retrieve_candidates(phrases, on_log=None, workers=4, mailto=None):
    """Search every phrase; return candidate works ranked by evidence."""
    session = requests.Session()
    session.headers["User-Agent"] = UA + (f" mailto:{mailto}" if mailto else "")

    def one(item):
        ridx, phrase = item["row"], item["phrase"]
        res = []
        for fn in (search_europepmc,
                   lambda se, ph: search_openalex(se, ph, mailto)):
            try:
                count, hits = fn(session, phrase)
            except Exception:  # noqa: BLE001
                continue
            if 0 < count <= COMMON_PHRASE_HITS:
                res.extend((h, phrase, ridx, count) for h in hits)
        return res

    works = {}
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(one, phrases):
            done += 1
            if on_log and done % 20 == 0:
                on_log(f"Plagiarism check: searched {done}/{len(phrases)} phrases...")
            for h, phrase, ridx, count in res:
                w = works.setdefault(h["key"], dict(h, phrases=[], score=0.0))
                if h.get("pdf") and not w.get("pdf"):
                    w["pdf"] = h["pdf"]
                w["phrases"].append({"phrase": phrase, "row": ridx})
                w["score"] += 1.0 / count
    return sorted(works.values(), key=lambda w: -w["score"])


# ----------------------------------------------------- text of sources/files
def pdf_to_text(data):
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    with fitz.open(stream=data, filetype="pdf") as d:
        return "\n".join(page.get_text() for page in d)


def docx_to_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        xml = z.read("word/document.xml").decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<[^>]+>", "", xml)
    import html
    return html.unescape(xml)


def bytes_to_text(data, name):
    low = name.lower()
    if low.endswith(".pdf") or data[:5] == b"%PDF-":
        return pdf_to_text(data)
    if low.endswith(".docx"):
        return docx_to_text(data)
    text = data.decode("utf-8", "ignore")
    if low.endswith((".html", ".htm", ".xml")):
        import html
        text = html.unescape(re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text,
                                    flags=re.S | re.I))
        text = re.sub(r"<[^>]+>", " ", text)
    return text


def fetch_source_text(session, work):
    """Download the open full text of a candidate. Returns text or ''."""
    try:
        if work.get("pmcid"):
            r = _get(session, "https://www.ebi.ac.uk/europepmc/webservices/rest/"
                     f"{work['pmcid']}/fullTextXML")
            if r is None or r.status_code != 200:
                return ""
            from lxml import etree
            root = etree.fromstring(r.content, etree.XMLParser(recover=True))
            body = root.find(".//body") if root is not None else None
            if body is None:
                return ""
            etree.strip_elements(body, "ref-list", "table-wrap", with_tail=False)
            return " ".join("".join(body.itertext()).split())
        url = work.get("pdf")
        if not url:
            return ""
        r = _get(session, url, stream=True)
        if r is None or r.status_code != 200:
            return ""
        data = b""
        for chunk in r.iter_content(1 << 16):
            data += chunk
            if len(data) > MAX_DOWNLOAD_BYTES:
                return ""
        if data[:5] != b"%PDF-":
            return ""
        return pdf_to_text(data)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------- helpers
def title_similarity(a, b):
    ta = {w for w, _, _ in tokenize(a)} - STOP
    tb = {w for w, _, _ in tokenize(b)} - STOP
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


# ------------------------------------------------------- literature library
LIB_EXT = {".pdf", ".docx", ".txt", ".md", ".html", ".htm"}
MAX_LIB_FILE = 60 * 1024 * 1024
_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>]+)", re.I)


def _cache_dir():
    import os
    from pathlib import Path
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / "MuCOS_PlagCheck" / "litcache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_library(folder):
    from pathlib import Path
    out = []
    for p in Path(folder).rglob("*"):
        try:
            if p.is_file() and p.suffix.lower() in LIB_EXT \
                    and p.stat().st_size <= MAX_LIB_FILE:
                out.append(p)
        except OSError:
            continue
    return sorted(out)


def read_library_file(path):
    """Return (text, title, doi) for a library file; cached on disk.

    Text extraction (the slow part) is cached by path + mtime + size, so
    re-checking against a large Zotero folder is fast after the first run.
    """
    import gzip
    import hashlib
    import json
    st = path.stat()
    key = hashlib.sha1(f"{path}|{st.st_mtime_ns}|{st.st_size}".encode(
        "utf-8", "ignore")).hexdigest()
    cf = _cache_dir() / (key + ".json.gz")
    if cf.exists():
        try:
            with gzip.open(cf, "rt", encoding="utf-8") as fh:
                d = json.load(fh)
            return d["text"], d["title"], d["doi"]
        except Exception:  # noqa: BLE001
            pass
    data = path.read_bytes()
    title = ""
    if path.suffix.lower() == ".pdf":
        try:
            import pymupdf
            with pymupdf.open(stream=data, filetype="pdf") as d:
                title = (d.metadata or {}).get("title") or ""
                text = "\n".join(pg.get_text() for pg in d)
        except Exception:  # noqa: BLE001
            text = ""
    else:
        text = bytes_to_text(data, path.name)
    m = _DOI_RE.search(text[:6000])
    doi = m.group(1).rstrip(".,;)").lower() if m else ""
    title = title.strip() or path.stem
    try:
        with gzip.open(cf, "wt", encoding="utf-8") as fh:
            json.dump({"text": text, "title": title, "doi": doi}, fh)
    except Exception:  # noqa: BLE001
        pass
    return text, title, doi

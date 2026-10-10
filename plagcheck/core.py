"""Licence-free plagiarism / text-overlap detection (verbatim overlap only).

No commercial database is used. The algorithm has two stages:

1. **Candidate retrieval.** Distinctive 9-word phrases (one per ~60 words, at
   least one per paragraph) are searched as *exact phrases* in open full texts (Europe PMC
   open-access articles and preprints, the OpenAlex full-text index and
   Wikipedia). A work that contains one of these phrases is a candidate source.
   Nothing is downloaded in bulk: only the search APIs are queried, and only
   the full texts of the best candidates are fetched.
2. **Verification.** The open full text of the best candidates (and of any
   local comparison files) is downloaded and compared with the *whole*
   manuscript using word shingles (the approach of WCopyfind: 6-word
   shingles, matches of at least 8 consecutive words). Quoted passages and
   parenthetical citations are excluded. Both texts are normalised first
   (Unicode ligatures, PDF line-end hyphenation, hyphens/apostrophes, accents,
   British/American spelling), so only formatting differences are forgiven -
   reworded text is deliberately out of scope.

Limits (stated in every report): only open full texts are searched, so
paywalled publisher content, student theses and most books are invisible, and
paraphrase is not detected. A similarity score is a pointer for a human to
look at, not a verdict.
"""

import io
import re
import threading
import unicodedata
import zipfile
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

import requests

SHINGLE = 6          # words per shingle
MIN_RUN = 8          # shortest reported match, in words
PHRASE_WORDS = 9     # words per search phrase
MIN_ROW_WORDS = 12   # shorter paragraphs (headings, captions) are not searched
# A phrase found in more works than this is boilerplate. In the benchmark every
# genuinely copied phrase was in 1-3 works (versions of one source), stock
# wording ("limitations of this study are ...") in 4 to several hundred.
COMMON_PHRASE_HITS = 5
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MIN_SOURCE_CHARS = 500
HTTP_TIMEOUT = 25
UA = "MuCOS-PlagiarismCheck/1.0 (https://github.com/replicationresearch/manuscriptchecker; non-commercial research tool)"

# Shown in every report; update after running scripts/plagbench/run_online.py.
BENCHMARK_NOTE = (
    "Measured detection (10 Oct 2026, scripts/plagbench, corpus v2: 72 passages "
    "copied verbatim from openly licensed sources into 12 manuscripts, one run "
    "each; a small pilot, so treat as rough). A passage counts as detected when "
    "at least half of its words are covered by verified overlap with any "
    "source. Detected: 19 of 24 copied paragraphs, 16 of 24 copied "
    "three-sentence blocks and 4 of 24 single copied sentences inside an "
    "otherwise original paragraph. By source: PubMed Central 13/18, Wikipedia "
    "12/18, open-access articles outside PubMed Central 9/18, PsyArXiv "
    "preprints 5/18. In 22 of the 33 misses no searched phrase fell into the "
    "passage. Only sources with a downloadable, openly licensed full text were "
    "tested, so coverage of the literature at large is lower.")

TOKEN_RE = re.compile(r"[^\W_]+(?:['’\-‐][^\W_]+)*", re.U)
_CITE_RE = re.compile(r"\([^()]*\b(?:1[89]|20)\d{2}[a-z]?\b[^()]*\)")
_QUOTE_RE = re.compile(r"[“\"„]([^”\"“]{25,700}?)[”\"]")

STOP = frozenset("""a about above after again all also am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further had has have having
he her here hers him his how i if in into is it its itself just me more most my no nor not now of off on once only
or other our out over own same she should so some such than that the their them then there these they this those
through to too under until up very was we were what when where which while who whom why will with would you your
et al fig table""".split())


# Words of stock academic prose. A search phrase made of them ("descriptive
# statistics are presented in table") matches unrelated papers, so phrase
# selection prefers windows with other content words.
GENERIC = frozenset("""study studies research researchers paper article present current previous prior
findings finding results result analysis analyses analyzed data dataset sample samples participants
participant respondents subjects group groups method methods methodology procedure procedures measure
measures measured measurement scale scales items item questionnaire survey surveys interview interviews
significant significantly significance difference differences effect effects association associations
associated relationship relationships correlation correlated regression model models variable variables
statistics statistical statistically descriptive mean means standard deviation error errors confidence
interval intervals test tests tested testing hypothesis hypotheses table figure shown presented reported
described based using used conducted performed carried obtained collected included including consisted
first second third finally following follows listed part parts section limitations limitation strengths
future further addition additionally moreover however therefore thus although whereas while among
across within between levels level higher lower high increased decreased compared comparison total
number percent percentage approximately several many most also both either related according regarding
suggest suggests suggested indicate indicates indicated showed show shows found reveal revealed
demonstrated consistent important importance impact role factors factor outcome outcomes
evidence literature review information approach approaches different similar various overall general
software version index square root fit likelihood maximum estimated estimate estimates robust
ethics committee approved approval informed consent written authors author declare conflict interest
funding supported grant university department years year aged months weeks time period baseline
""".split())


# -------------------------------------------------------------- normalising
_LINEBREAK_HYPHEN = re.compile(r"(?<=[^\W\d_])[-‐­]\s*\n\s*(?=[^\W\d_])")


def clean_text(text):
    """Undo formatting artefacts before tokenising (offsets refer to the result).

    NFKC folds ligatures (``ﬁ`` -> ``fi``) and full-width forms; soft hyphens
    go; a word split by a hyphen at a line end is rejoined with a hyphen, which
    the word normaliser then drops (so ``de-\\nsign`` == ``design`` and
    ``self-\\nreport`` == ``self-report``).
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = _LINEBREAK_HYPHEN.sub("-", text)
    return text.replace("­", "")


# British -> American spelling. Applied identically to manuscript and source,
# so an over-eager rule only merges spelling variants, never changes a match.
_SPELLING = [
    (re.compile(r"^(behavi|col|fav|flav|hon|hum|lab|neighb|harb|vig|rig|vap|od|"
                r"arm|savi|ferv|cand|clam|endeav|parl|rum|splend|tum|val|"
                r"demean|sav|ard|ranc)our"), r"\1or"),
    (re.compile(r"(?<=..)is(e|ed|es|ing|ation|ations|ational|er|ers|able)$"),
     r"iz\1"),
    (re.compile(r"(?<=..)ys(e|ed|es|ing)$"), r"yz\1"),
    (re.compile(r"(?<=..)([tb])re(s?)$"), r"\1er\2"),
    (re.compile(r"(?<=...)ogue(s?)$"), r"og\1"),
    (re.compile(r"^(model|label|travel|cancel|counsel|fuel|signal|level|total|"
                r"channel|tunnel|equal|marshal|jewel|dial|rival|tranquil|"
                r"focus|bias)(?:l|s)(ed|ing|er|ers)$"), r"\1\2"),
    (re.compile(r"(?<=[bcdfghklmnprstvz])ae(?=[bcdfghklmnprstvz])"), "e"),
    (re.compile(r"^aet"), "et"),
    (re.compile(r"(oestr|oesoph|foet|diarrhoe|manoeuv|coeliac|amoeb|oedem)"),
     lambda m: m.group(1).replace("oe", "e")),
]
_SPELLING_WORDS = {
    "programme": "program", "programmes": "programs", "ageing": "aging",
    "judgement": "judgment", "judgements": "judgments",
    "acknowledgement": "acknowledgment", "enrolment": "enrollment",
    "fulfil": "fulfill", "fulfilment": "fulfillment", "skilful": "skillful",
    "grey": "gray", "mould": "mold", "sceptical": "skeptical",
    "sceptic": "skeptic", "aluminium": "aluminum", "licence": "license",
    "licences": "licenses", "defence": "defense", "offence": "offense",
    "pretence": "pretense", "practise": "practice", "practised": "practiced",
    "practising": "practicing", "cheque": "check", "tyre": "tire",
    "plough": "plow", "draught": "draft", "storey": "story",
}


@lru_cache(maxsize=200_000)
def norm_word(w):
    """Normalised form of one token (lowercase, no accents/hyphens, US spelling)."""
    w = w.lower()
    if not w.isascii():
        w = "".join(c for c in unicodedata.normalize("NFKD", w)
                    if not unicodedata.combining(c))
    w = re.sub(r"['’\-‐]", "", w)
    if w in _SPELLING_WORDS:
        return _SPELLING_WORDS[w]
    if len(w) > 4 and w.isalpha():
        for rx, rep in _SPELLING:
            w = rx.sub(rep, w)
    return w


# ----------------------------------------------------------------- tokenising
def tokenize(text):
    """Return [(normalised word, start, end)] for (already cleaned) ``text``."""
    return [(norm_word(m.group(0)), m.start(), m.end())
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


# Back-matter sections made of standard wording (funding, ethics approval ...):
# neither searched nor scored, since overlap there is expected boilerplate.
DECLARATION_RE = re.compile(
    r"(funding( information| statement| sources?| details)?|financial support|"
    r"(role of the )?funding source|acknowledge?ments?|"
    r"ethic(s|al) (statement|approval|declarations?|considerations?|standards|"
    r"approval and consent to participate)|ethics|"
    r"institutional review board( statement)?|informed consent( statement)?|"
    r"consent (to|for) (participate|publication)|"
    r"(declaration of )?(conflicts?|competing|conflicting) (of )?interests?( statement)?|"
    r"declarations?|disclosures?( statement)?|"
    r"data( and code| and materials?)? availability( statement)?|"
    r"availability of data( and materials?)?|"
    r"author(s['’]?)? contributions?|credit author(ship)? (contribution )?statement|"
    r"abbreviations|supplementary (materials?|information|data)|"
    r"publisher['’]?s note|open access)", re.I)


def is_declaration(header):
    """True for a back-matter heading such as "Funding" or "5. Data availability"
    (the whole heading, so "Ethical decision making" is ordinary content)."""
    h = re.sub(r"^[\s\dIVXivx.)]+", "", header or "")
    h = re.sub(r"[\s:.]+$", "", h)
    return bool(DECLARATION_RE.fullmatch(h))


class Doc:
    """A manuscript: concatenated text of its rows plus token bookkeeping."""

    def __init__(self, rows):
        # rows: [{"header", "text"}] in reading order
        self.rows = [dict(r, text=clean_text(r["text"])) for r in rows]
        for r in self.rows:
            if is_declaration(r.get("header")):
                r["skip"] = True
        self.row_offsets = []
        parts, pos = [], 0
        for r in self.rows:
            self.row_offsets.append(pos)
            parts.append(r["text"])
            pos += len(r["text"]) + 1
        self.text = "\n".join(parts)
        toks = tokenize(self.text)
        self.words = [t[0] for t in toks]
        self.spans = [(t[1], t[2]) for t in toks]
        ign = _ignored_spans(self.text)
        for r, off in zip(self.rows, self.row_offsets):
            if r.get("skip"):
                ign.append((off, off + len(r["text"]), "declaration"))
        ign.sort()
        self.ignored = [False] * len(toks)
        self.quote_words = 0
        k = 0
        for i, (s, e) in enumerate(self.spans):
            while k < len(ign) and ign[k][1] <= s:
                k += 1
            for a, b, kind in ign[k:]:
                if a > s:
                    break
                if e <= b:
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
    """shingle -> [token index] of the manuscript (built once)."""
    idx = getattr(doc, "_shingle_index", None)
    if idx is None:
        idx = {}
        w = doc.words
        for i in range(len(w) - SHINGLE + 1):
            if any(doc.ignored[i:i + SHINGLE]):
                continue
            idx.setdefault(tuple(w[i:i + SHINGLE]), []).append(i)
        doc._shingle_index = idx
    return idx


def match_doc(doc, source_words):
    """Compare a manuscript with one source text.

    Returns ``(covered, runs)``: a per-token bool list and
    ``[(start, end, source_start)]`` token runs, longest first where they
    overlap. A run is a stretch of at least MIN_RUN words that is identical
    and consecutive in *both* texts: shingle hits are chained along one
    manuscript/source alignment, so words that occur in the source in a
    different order or in separate places never add up to a match. The
    manuscript index is built once, so each source costs one pass over its
    own words (fast enough for hundreds of library PDFs).
    """
    n = len(doc.words)
    idx = _doc_index(doc)
    if n < SHINGLE or not idx:
        return [False] * n, []
    sw = source_words
    open_runs = {}      # alignment (source pos - manuscript pos) -> [first, last]
    segs = []           # (manuscript start, end, source start)

    def close(d, cur):
        if cur[1] - cur[0] + SHINGLE >= MIN_RUN:
            segs.append((cur[0], cur[1] + SHINGLE, cur[0] + d))

    for p in range(len(sw) - SHINGLE + 1):
        locs = idx.get(tuple(sw[p:p + SHINGLE]))
        if not locs:
            continue
        for i in locs:
            d = p - i
            cur = open_runs.get(d)
            if cur is not None and cur[1] == i - 1:
                cur[1] = i
            else:
                if cur is not None:
                    close(d, cur)
                open_runs[d] = [i, i]
    for d, cur in open_runs.items():
        close(d, cur)
    covered = [False] * n
    runs = []
    for a, b, src in sorted(segs, key=lambda x: (x[0], x[0] - x[1])):
        if all(covered[a:b]):
            continue            # the same words matched elsewhere in the source
        for t in range(a, b):
            covered[t] = True
        runs.append((a, b, src))
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


@lru_cache(maxsize=1)
def _generic():
    return frozenset(norm_word(w) for w in GENERIC)


def searchable_rows(doc):
    """Indices of rows long enough to be searched (>= MIN_ROW_WORDS words)."""
    return [i for i, r in enumerate(doc.rows)
            if r["text"] and not r.get("skip")
            and len(TOKEN_RE.findall(r["text"])) >= MIN_ROW_WORDS]


def eligible_phrases(doc):
    """All searchable 9-word phrases of the manuscript.

    Per paragraph every non-overlapping window (most distinctive first) with
    at least 5 content words, no digits and no quoted / citation words. The
    score is the number of content words that are not stock academic words. The phrase is the
    lower-cased *surface* text (what search engines index). Returns dicts
    ``{row, phrase, gstart, score, rank}``.
    """
    starts = _row_token_starts(doc)
    out = []
    for ridx in searchable_rows(doc):
        text = doc.rows[ridx]["text"]
        toks = tokenize(text)
        n = len(toks)
        g0 = starts[ridx]
        wins = []
        for i in range(0, n - PHRASE_WORDS + 1):
            win = toks[i:i + PHRASE_WORDS]
            if any(g0 + i + k < len(doc.ignored) and doc.ignored[g0 + i + k]
                   for k in range(PHRASE_WORDS)):
                continue
            if any(any(ch.isdigit() for ch in w[0]) for w in win):
                continue
            content = [w[0] for w in win if w[0] not in STOP and len(w[0]) > 3]
            if len(content) >= 5:           # distinctive = content minus stock words
                wins.append((len(content) - sum(w in _generic() for w in content), i))
        wins.sort(key=lambda x: (-x[0], x[1]))
        taken = []
        for score, i in wins:
            if all(abs(i - j) >= PHRASE_WORDS for _, j in taken):
                taken.append((score, i))
        for rank, (score, i) in enumerate(taken):
            surface = " ".join(text[s:e].lower().replace("’", "'")
                               for _, s, e in toks[i:i + PHRASE_WORDS])
            out.append({"row": ridx, "gstart": g0 + i, "score": score,
                        "rank": rank, "phrase": surface, "row_words": n})
    out.sort(key=lambda x: x["gstart"])
    return out


def select_phrases(cands, seed, exclude=None, max_n=0, words_per_probe=0):
    """One phrase per paragraph (seeded), skipping phrases in ``exclude``.

    Within a paragraph the phrase is drawn from the most distinctive windows
    (content-word score within 1 of the best), so repeated runs with
    ``exclude`` = earlier phrases walk through the rest of the paragraph.
    ``words_per_probe`` > 0 probes long paragraphs more densely: one phrase
    per that many words, drawn from consecutive stretches of the paragraph.
    ``max_n`` > 0 caps the number of phrases (evenly sampled).
    Returns ``(phrases, n_exhausted)`` where ``n_exhausted`` counts paragraphs
    whose phrases were all used before.
    """
    import random
    rng = random.Random(seed)
    exclude = exclude or set()
    by_row = {}
    for c in cands:
        by_row.setdefault(c["row"], []).append(c)
    chosen, exhausted = [], 0
    seen = set()        # identical wording in two places is searched once
    for row in sorted(by_row):
        pool = sorted((c for c in by_row[row] if c["phrase"] not in exclude),
                      key=lambda c: c["gstart"])
        fresh = [c for c in pool if c["phrase"] not in seen]
        if pool and not fresh:
            continue
        pool = fresh
        if not pool:
            exhausted += 1
            continue
        k = 1
        if words_per_probe:
            k = max(1, min(len(pool), round(pool[0]["row_words"] / words_per_probe)))
        for j in range(k):
            part = [c for c in pool[j * len(pool) // k:(j + 1) * len(pool) // k]
                    if c["phrase"] not in seen]
            if not part:
                continue
            best = max(c["score"] for c in part)
            pick = rng.choice([c for c in part if c["score"] >= best - 1])
            seen.add(pick["phrase"])
            chosen.append(pick)
    if max_n and len(chosen) > max_n:
        step = len(chosen) / float(max_n)
        chosen = [chosen[rng.randrange(int(k * step),
                                       max(int((k + 1) * step), int(k * step) + 1))]
                  for k in range(max_n)]
    return chosen, exhausted


# --------------------------------------------------------- online retrieval
_PACE = {"wikipedia.org": 0.7}      # host suffix -> seconds between requests
_pace_lock = threading.Lock()
_pace_next = {}


def _pace(url):
    """Space out requests to hosts that refuse bursts (Wikipedia)."""
    import time
    for host, gap in _PACE.items():
        if host in url.split("/")[2]:
            with _pace_lock:
                wait = _pace_next.get(host, 0) - time.time()
                _pace_next[host] = max(time.time(), _pace_next.get(host, 0)) + gap
            if wait > 0:
                time.sleep(wait)


def _get(session, url, **kw):
    import time
    for attempt in range(4):
        try:
            _pace(url)
            r = session.get(url, timeout=HTTP_TIMEOUT, **kw)
            if r.status_code == 429:
                if _quota_spent(r):         # daily budget gone: retrying is futile
                    return r
                try:
                    wait = min(float(r.headers.get("retry-after", "")), 60.0)
                except ValueError:
                    wait = 2 + 2 * attempt
                if attempt == 3:
                    return r
                time.sleep(wait)
                continue
            return r
        except requests.RequestException:
            if attempt == 3:
                return None
    return None


def _quota_spent(r):
    """True if a 429 response says the (daily) allowance is used up.

    OpenAlex answers a spent key with the cost of the request, the smaller
    remaining budget and a ``retry-after`` of hours (until midnight UTC).
    """
    h = r.headers

    def num(name):
        try:
            return float(h.get(name, ""))
        except ValueError:
            return None
    left, need, after = (num("x-ratelimit-remaining-usd"),
                         num("x-ratelimit-cost-required-usd"), num("retry-after"))
    if left is not None and need is not None and left < need:
        return True
    return (after is not None and after > 600) or h.get("x-ratelimit-remaining") == "0"


class SearchFailed(Exception):
    """A search backend did not answer.

    ``quota``: the allowance is used up. ``status``: HTTP status, or None when
    there was no response (400 = the query itself was rejected).
    """

    def __init__(self, quota=False, status=None):
        super().__init__("quota" if quota else f"failed ({status})")
        self.quota = quota
        self.status = status


def _json(r):
    if r is None:
        raise SearchFailed()
    if r.status_code != 200:
        raise SearchFailed(quota=r.status_code == 429 and _quota_spent(r),
                           status=r.status_code)
    try:
        return r.json()
    except ValueError:
        raise SearchFailed(status=r.status_code) from None


def _surnames_epmc(author_string):
    """'Smith J, van Dijk AB.' -> [('smith', 'j'), ('van dijk', 'a')]"""
    out = []
    for a in (author_string or "").rstrip(".").split(","):
        parts = a.split()
        if not parts:
            continue
        if len(parts) > 1 and parts[-1].isupper() and len(parts[-1]) <= 4:
            out.append((" ".join(parts[:-1]), parts[-1][0]))
        else:
            out.append((" ".join(parts), ""))
    return [author_key(f, g) for f, g in out]


def author_key(family, given=""):
    """Comparable (family, first initial) key for an author name."""
    fam = " ".join(norm_word(w) for w in TOKEN_RE.findall(family or ""))
    giv = norm_word((TOKEN_RE.findall(given or "") or [""])[0])[:1]
    return fam, giv


def search_europepmc(session, phrase):
    """Exact-phrase full-text search over open-access Europe PMC records."""
    r = _get(session, "https://www.ebi.ac.uk/europepmc/webservices/rest/search", params={
        "query": f'BODY:"{phrase}" AND OPEN_ACCESS:y', "format": "json",
        "pageSize": 6, "resultType": "lite"})
    j = _json(r)
    out = []
    for x in j.get("resultList", {}).get("result", []):
        ftid = x.get("pmcid") or (x.get("id") if x.get("source") == "PPR" else None)
        if not ftid:
            continue
        url = (f"https://europepmc.org/article/PMC/{x['pmcid'][3:]}" if x.get("pmcid")
               else f"https://europepmc.org/article/PPR/{x['id']}")
        out.append({
            "key": "epmc:" + ftid, "source": "Europe PMC",
            "title": x.get("title", ""), "year": x.get("pubYear"),
            "authors": x.get("authorString", ""),
            "author_keys": _surnames_epmc(x.get("authorString", "")),
            "doi": (x.get("doi") or "").lower(), "url": url,
            "fulltext_id": ftid})
    return int(j.get("hitCount", 0)), out


OA_MAX_QUERY = 1400     # OpenAlex rejects search strings over 1,500 characters
OA_MAX_BATCH = 20       # phrases joined with OR in one metered search
OA_LONG = 76            # OpenAlex allows 3 phrases over 80 characters per search
OA_MAX_LONG = 3


def search_openalex(session, phrase, mailto=None, api_key=None, only=None):
    """Exact-phrase search of the OpenAlex index (includes full text).

    ``phrase`` is one phrase or a list of phrases, which are joined with OR:
    OpenAlex meters every search (a small free daily allowance without a key,
    about 1,000 a day with a free key), and one combined search costs the same
    as a single one. A 429 with no allowance left raises
    ``SearchFailed(quota=True)``. ``only`` restricts the search to the given
    OpenAlex work ids.
    """
    phrases = [phrase] if isinstance(phrase, str) else list(phrase)
    params = {
        # .exact: no stemming, so "limitation of studies" is not "limitations of study"
        "search.exact": " OR ".join(f'"{p}"' for p in phrases),
        "per-page": 6 if len(phrases) == 1 else 100,
        "select": "id,doi,title,publication_year,authorships,best_oa_location,"
                  "open_access,locations,ids"}
    if only:
        params["filter"] = "openalex:" + "|".join(only)
    if mailto:
        params["mailto"] = mailto
    # the key goes in a header, not the URL, so it stays out of logs and errors
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    j = _json(_get(session, "https://api.openalex.org/works", params=params,
                   headers=headers))
    out = []
    for w in j.get("results", []):
        urls = []
        for loc in [w.get("best_oa_location") or {}] + (w.get("locations") or []):
            if loc and loc.get("is_oa", True) and loc.get("pdf_url"):
                urls.append(loc["pdf_url"])
        oa_url = (w.get("open_access") or {}).get("oa_url")
        if oa_url:
            urls.append(oa_url)
        authors = [a.get("author", {}).get("display_name", "")
                   for a in (w.get("authorships") or [])]
        keys = []
        for name in authors:
            parts = name.split()
            if parts:
                keys.append(author_key(parts[-1], parts[0] if len(parts) > 1 else ""))
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        pmcid = ((w.get("ids") or {}).get("pmcid") or "").rsplit("/", 1)[-1]
        if pmcid and not pmcid.upper().startswith("PMC"):
            pmcid = "PMC" + pmcid
        out.append({
            "key": "oa:" + w["id"].rsplit("/", 1)[-1], "source": "OpenAlex",
            "openalex_id": w["id"].rsplit("/", 1)[-1],
            "title": w.get("title") or "", "year": w.get("publication_year"),
            "authors": ", ".join(a for a in authors[:3] if a) + (
                " et al." if len(authors) > 3 else ""),
            "author_keys": keys,
            "doi": doi, "url": w.get("doi") or w["id"],
            "urls": list(dict.fromkeys(urls)),
            "fulltext_id": pmcid.upper() if pmcid else None})
    return int(j.get("meta", {}).get("count", 0)), out


WIKI_API = "https://{lang}.wikipedia.org/w/api.php"


def search_wikipedia(session, phrase, lang="en"):
    """Exact-phrase search of Wikipedia article text."""
    r = _get(session, WIKI_API.format(lang=lang), params={
        "action": "query", "list": "search", "srsearch": f'"{phrase}"',
        "srlimit": 6, "srinfo": "totalhits", "srprop": "", "format": "json"})
    j = _json(r).get("query", {})
    out = []
    for x in j.get("search", []):
        out.append({
            "key": f"wiki:{lang}:{x['pageid']}", "source": "Wikipedia",
            "title": x["title"], "year": "", "authors": "Wikipedia",
            "author_keys": [], "doi": "",
            "url": f"https://{lang}.wikipedia.org/wiki/" + x["title"].replace(" ", "_"),
            "wiki": (lang, x["title"])})
    return int(j.get("searchinfo", {}).get("totalhits", 0)), out


BACKENDS = ("europepmc", "openalex", "wikipedia")


def _merge(w, h):
    """Merge a hit for a work already seen via another backend."""
    for k in ("fulltext_id", "wiki", "doi", "year", "title", "openalex_id"):
        if h.get(k) and not w.get(k):
            w[k] = h[k]
    w["urls"] = list(dict.fromkeys((w.get("urls") or []) + (h.get("urls") or [])))
    if len(h.get("author_keys") or []) > len(w.get("author_keys") or []):
        w["author_keys"] = h["author_keys"]
        w["authors"] = h["authors"]
    if h["source"] not in w["source"]:
        w["source"] += " + " + h["source"]


def _new_stats():
    return {"ok": 0, "failed": 0, "quota": 0, "requests": 0}


class OpenAlexClient:
    """OpenAlex searches with several keys: moves to the next key when one's
    daily allowance is spent and remembers when all are (``spent``).

    ``stats["requests"]`` counts every request sent, including the one that
    discovers a spent key.
    """

    def __init__(self, keys=None, mailto=None, stats=None, session=None):
        if not isinstance(keys, (list, tuple)):
            keys = [k.strip() for k in (keys or "").split(",") if k.strip()]
        self.keys = list(keys) or [None]
        self.mailto = mailto
        self.stats = stats if stats is not None else _new_stats()
        self.spent = False
        self.session = session or requests.Session()
        if session is None:
            self.session.headers["User-Agent"] = UA + (
                f" mailto:{mailto}" if mailto else "")

    def search(self, phrases, only=None):
        """``(count, hits)`` or raise ``SearchFailed``."""
        if self.spent:
            raise SearchFailed(quota=True, status=429)
        kw = {"only": only} if only else {}
        while True:
            self.stats["requests"] += 1
            try:
                return search_openalex(self.session, phrases, self.mailto,
                                       self.keys[0], **kw)
            except SearchFailed as e:
                if not e.quota:
                    raise
                if len(self.keys) > 1:
                    self.keys.pop(0)
                    continue
                self.spent = True
                raise


def retrieve_candidates(phrases, on_log=None, workers=4, mailto=None,
                        backends=BACKENDS, wiki_lang="en", openalex_key=None,
                        stats=None, client=None):
    """Search every phrase; return candidate works ranked by evidence.

    Works found by several backends are merged by DOI. Each work records the
    phrases it contains (``phrases``) and an evidence score (sum of
    1 / number of works containing the phrase). ``stats`` (a dict, filled in
    place) counts per backend the phrases answered (``ok``), failed
    (``failed``) and skipped after the allowance ran out (``quota``), plus the
    number of ``requests`` sent, so a silent backend never looks like "nothing
    found".

    OpenAlex is searched in combined requests of up to ``OA_MAX_BATCH``
    phrases (``client``: an ``OpenAlexClient`` to share key state with later
    calls). A combined search does not say which phrase matched, so its works
    carry ``batch_hits`` instead of ``phrases``. It is split in two when
    OpenAlex rejects the query or when it returns more than
    ``COMMON_PHRASE_HITS`` works, until the boilerplate phrase is isolated and
    dropped; a timeout or server error is not retried by splitting.
    """
    session = requests.Session()
    session.headers["User-Agent"] = UA + (f" mailto:{mailto}" if mailto else "")
    fns = {"europepmc": search_europepmc,
           "wikipedia": lambda se, ph: search_wikipedia(se, ph, wiki_lang)}
    stats = stats if stats is not None else {}
    for name in backends:
        stats[name] = _new_stats()
    per_phrase = [b for b in backends if b != "openalex"]

    def one(item):
        """Runs in a worker; all bookkeeping happens in the calling thread."""
        res, outcome = [], {}
        for name in per_phrase:
            try:
                count, hits = fns[name](session, item["phrase"])
                outcome[name] = "ok"
            except SearchFailed as e:
                outcome[name] = "quota" if e.quota else "failed"
                continue
            except Exception:  # noqa: BLE001
                outcome[name] = "failed"
                continue
            if 0 < count <= COMMON_PHRASE_HITS:
                res.extend((h, count) for h in hits)
        return item, res, outcome

    works, by_doi = {}, {}

    def register(h, count, item=None, batch=None):
        key = by_doi.get(h["doi"]) if h.get("doi") else None
        key = key or h["key"]
        if key not in works:
            works[key] = dict(h, phrases=[], score=0.0, batch_hits=0)
            works[key].setdefault("urls", [])
            if h.get("doi"):
                by_doi[h["doi"]] = key
        else:
            _merge(works[key], h)
        w = works[key]
        if item is None:                    # combined search: phrase unknown
            w["batch_hits"] += 1
            w.setdefault("batches", []).append(batch)
        elif any(p["phrase"] == item["phrase"] for p in w["phrases"]):
            return
        else:
            w["phrases"].append({"phrase": item["phrase"], "row": item["row"],
                                 "gstart": item["gstart"]})
        w["score"] += 1.0 / count

    done = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for item, res, outcome in ex.map(one, phrases if per_phrase else []):
            done += 1
            if on_log and done % 20 == 0:
                on_log(f"Plagiarism check: searched {done}/{len(phrases)} phrases...")
            for name, kind in outcome.items():
                stats[name][kind] += 1
                stats[name]["requests"] += 1
            for h, count in res:
                register(h, count, item)

    if "openalex" not in backends:
        return sorted(works.values(), key=lambda w: -w["score"])
    if client is None:
        client = OpenAlexClient(openalex_key, mailto)
    st = client.stats = stats["openalex"]

    def openalex_batch(items):
        try:
            count, hits = client.search([it["phrase"] for it in items])
        except SearchFailed as e:
            if e.status == 400 and len(items) > 1:  # query rejected: try halves
                openalex_batch(items[:len(items) // 2])
                openalex_batch(items[len(items) // 2:])
                return
            st["quota" if e.quota else "failed"] += len(items)
            return
        except Exception:  # noqa: BLE001
            st["failed"] += len(items)
            return
        if count > COMMON_PHRASE_HITS and len(items) > 1:
            openalex_batch(items[:len(items) // 2])
            openalex_batch(items[len(items) // 2:])
            return
        st["ok"] += len(items)
        if 0 < count <= COMMON_PHRASE_HITS:
            for h in hits:
                register(h, count, items[0] if len(items) == 1 else None, items)

    batch, size, n_long = [], 0, 0
    for item in list(phrases) + [None]:
        n = len(item["phrase"]) + 6 if item else 0
        is_long = bool(item) and len(item["phrase"]) > OA_LONG
        if batch and (item is None or len(batch) >= OA_MAX_BATCH
                      or size + n > OA_MAX_QUERY
                      or n_long + is_long > OA_MAX_LONG):
            openalex_batch(batch)
            batch, size, n_long = [], 0, 0
        if item:
            batch.append(item)
            size += n
            n_long += is_long
    return sorted(works.values(), key=lambda w: -w["score"])


def resolve_batch_phrases(works, mailto=None, openalex_key=None, stats=None,
                          client=None):
    """Find out which phrases of a combined OpenAlex search each work contains.

    A combined search only says that a work matches *one of* its phrases. For
    the given works (those that could not be verified against a full text) the
    search is repeated, restricted to these works, on halves of the phrase set
    until single phrases remain. Fills ``phrases`` of the works in place and
    costs a few metered searches per matching phrase. Searches that fail are
    counted in ``stats["openalex"]`` like any other, and the work then keeps
    an empty ``phrases`` list; nothing is raised.
    """
    stats = stats if stats is not None else {}
    st = stats.setdefault("openalex", _new_stats())
    if client is None:
        client = OpenAlexClient(openalex_key, mailto)
    client.stats = st
    groups = {}             # one group per combined search
    for w in works:
        for batch in w.get("batches") or []:
            if w.get("openalex_id"):
                groups.setdefault(id(batch), (batch, []))[1].append(w)

    def narrow(items, ws):
        if not items or not ws or client.spent:
            if items and ws:
                st["quota"] += len(items)
            return
        try:
            _, hits = client.search([it["phrase"] for it in items],
                                    only=[w["openalex_id"] for w in ws])
            found = {h.get("openalex_id") for h in hits}
        except SearchFailed as e:
            st["quota" if e.quota else "failed"] += len(items)
            return
        except Exception:  # noqa: BLE001
            st["failed"] += len(items)
            return
        ws = [w for w in ws if w["openalex_id"] in found]
        if not ws:
            return
        if len(items) == 1:
            for w in ws:
                if not any(p["phrase"] == items[0]["phrase"] for p in w["phrases"]):
                    w["phrases"].append({"phrase": items[0]["phrase"],
                                         "row": items[0]["row"],
                                         "gstart": items[0]["gstart"]})
            return
        narrow(items[:len(items) // 2], ws)
        narrow(items[len(items) // 2:], ws)

    for batch, ws in groups.values():
        # the combined search already matched: start with its halves
        narrow(batch[:len(batch) // 2], ws)
        narrow(batch[len(batch) // 2:], ws)


# ----------------------------------------------------- text of sources/files
MAX_TEXT_CHARS = 3_000_000      # extracted text kept per source
MAX_PDF_PAGES = 600
MAX_XML_BYTES = 60 * 1024 * 1024    # unpacked word/document.xml


def pdf_to_text(data):
    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz
    parts, size = [], 0
    with fitz.open(stream=data, filetype="pdf") as d:
        for k, page in enumerate(d):
            if k >= MAX_PDF_PAGES or size > MAX_TEXT_CHARS:
                break
            parts.append(page.get_text())
            size += len(parts[-1])
    return "\n".join(parts)[:MAX_TEXT_CHARS]


def docx_to_text(data):
    import html
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        info = z.getinfo("word/document.xml")
        if info.file_size > MAX_XML_BYTES:      # declared size: no zip bombs
            return ""
        with z.open(info) as fh:
            xml = fh.read(MAX_XML_BYTES + 1)
    if len(xml) > MAX_XML_BYTES:
        return ""
    xml = xml.decode("utf-8", "ignore")
    xml = re.sub(r"</w:p>|<w:br\b[^>]*>", "\n", xml)
    xml = re.sub(r"</w:tc>|<w:tab\b[^>]*>", " ", xml)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))[:MAX_TEXT_CHARS]


_BLOCK_TAGS = (r"p|div|br|li|ul|ol|h\d|td|th|tr|table|section|article|"
               r"blockquote|figcaption|dt|dd|pre|hr")


def html_to_text(text):
    """Plain text of HTML: block elements end a line, inline tags vanish
    (``pro<b>social</b>`` stays one word)."""
    import html
    text = re.sub(r"<(script|style|nav|header|footer)\b[^>]*>.*?</\1>", " ", text,
                  flags=re.S | re.I)
    text = re.sub(rf"</?(?:{_BLOCK_TAGS})\b[^>]*>", "\n", text, flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text))[:MAX_TEXT_CHARS]


def _kind(data, name=""):
    low = name.lower()
    if data[:5] == b"%PDF-" or low.endswith(".pdf"):
        return "pdf"
    if data[:2] == b"PK" or low.endswith(".docx"):
        return "docx"
    head = data[:1000].decode("utf-8", "ignore").lower()
    if low.endswith((".html", ".htm", ".xml")) or "<html" in head or "<!doctype" in head:
        return "html"
    return "text"


def bytes_to_text(data, name=""):
    """Text of a PDF / DOCX / HTML / plain-text file (detected by content)."""
    kind = _kind(data, name)
    if kind == "pdf":
        return pdf_to_text(data)
    if kind == "docx":
        return docx_to_text(data)
    text = data.decode("utf-8", "ignore")
    return html_to_text(text) if kind == "html" else text[:MAX_TEXT_CHARS]


_OSF_ID = r"([a-z0-9]{5,6}(?:_v\d+)?)"
_OSF_PATH = re.compile(rf"^/(?:preprints/[a-z]+/)?{_OSF_ID}(?:/download)?/?$", re.I)
_OSF_DOI = re.compile(rf"^(?:https?://(?:dx\.)?doi\.org/)?10\.\d{{4,9}}/osf\.io/"
                      rf"{_OSF_ID}$", re.I)


def _osf_id(url):
    """OSF preprint id (with its ``_vN`` version, if any) of a link or DOI."""
    from urllib.parse import urlsplit
    url = (url or "").strip()
    m = _OSF_DOI.match(url)
    if m:
        return m.group(1)
    parts = urlsplit(url)
    if parts.scheme in ("http", "https") and (parts.hostname or "").lower() in (
            "osf.io", "www.osf.io", "psyarxiv.com", "www.psyarxiv.com"):
        m = _OSF_PATH.match(parts.path)
        if m and m.group(1).lower() != "download":
            return m.group(1)
    return None


def _rewrite_url(url):
    """Direct-download URL for hosts whose links point at landing pages."""
    osf = _osf_id(url)
    return f"https://osf.io/download/{osf}/" if osf else url


def _public_url(url):
    """True for an http(s) URL whose host resolves only to public addresses.

    Candidate links come from third-party metadata, so they must not reach
    this machine, the local network or cloud metadata services.
    """
    import ipaddress
    import socket
    from urllib.parse import urlsplit
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443)
    except OSError:
        return False
    return bool(infos) and all(
        ipaddress.ip_address(i[4][0].split("%")[0]).is_global for i in infos)


def _download(session, url):
    """Body of a public URL (at most MAX_DOWNLOAD_BYTES), following up to five
    redirects that are each checked like the first URL. Returns b'' otherwise."""
    from urllib.parse import urljoin
    for _ in range(6):
        if not _public_url(url):
            return b""
        r = _get(session, url, stream=True, allow_redirects=False)
        if r is None:
            return b""
        if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
            url = urljoin(url, r.headers["location"])
            r.close()
            continue
        if r.status_code != 200:
            return b""
        data = b""
        for chunk in r.iter_content(1 << 16):
            data += chunk
            if len(data) > MAX_DOWNLOAD_BYTES:
                return b""
        return data
    return b""


def fetch_europepmc_text(session, ftid):
    r = _get(session, "https://www.ebi.ac.uk/europepmc/webservices/rest/"
             f"{ftid}/fullTextXML")
    if r is None or r.status_code != 200 or len(r.content) > MAX_DOWNLOAD_BYTES:
        return ""
    from lxml import etree
    root = etree.fromstring(r.content, etree.XMLParser(recover=True,
                                                       resolve_entities=False))
    body = root.find(".//body") if root is not None else None
    if body is None:
        return ""
    etree.strip_elements(body, "ref-list", "table-wrap", with_tail=False)
    for el in body.iter("p", "title", "sec", "list-item", "caption", "label"):
        el.tail = "\n" + (el.tail or "")   # block ends: keep words apart
    return " ".join("".join(body.itertext()).split())[:MAX_TEXT_CHARS]


def fetch_wikipedia_text(session, lang, title):
    r = _get(session, WIKI_API.format(lang=lang), params={
        "action": "query", "prop": "extracts", "explaintext": 1,
        "titles": title, "format": "json", "formatversion": 2})
    if r is None or r.status_code != 200:
        return ""
    pages = r.json().get("query", {}).get("pages", [])
    return pages[0].get("extract", "") if pages else ""


_BLOCK_PAGE = re.compile(r"access (denied|blocked)|captcha|enable javascript|"
                         r"just a moment|are you a robot|403 forbidden|"
                         r"verify you are (a )?human|unusual traffic", re.I)
MIN_HTML_CHARS = 3000


def fetch_source_text(session, work):
    """Download the open full text of a candidate. Returns text or ''.

    Tries, in order: Europe PMC full-text XML, Wikipedia plain text, then every
    open-access URL (OSF links rewritten to the file; the DOI too if it is an
    OSF preprint). A PDF or DOCX with at least ``MIN_SOURCE_CHARS`` wins at
    once; a web page is only a fallback (the longest one, and never a block or
    error page), so a landing page cannot hide a later full text.
    """
    def attempt(fn):
        try:
            return fn()
        except Exception:  # noqa: BLE001
            return ""

    if work.get("fulltext_id"):
        text = attempt(lambda: fetch_europepmc_text(session, work["fulltext_id"]))
        if len(text) >= MIN_SOURCE_CHARS:
            return text
    if work.get("wiki"):
        text = attempt(lambda: fetch_wikipedia_text(session, *work["wiki"]))
        if len(text) >= MIN_SOURCE_CHARS:
            return text
    urls = [_rewrite_url(u) for u in work.get("urls") or []]
    if _osf_id(work.get("doi")):
        urls.append(_rewrite_url(work["doi"]))
    page = ""
    for u in dict.fromkeys(urls):
        data = attempt(lambda: _download(session, u)) or b""
        if not data:
            continue
        kind = _kind(data, u)
        text = attempt(lambda: bytes_to_text(data, u))
        if kind in ("pdf", "docx"):
            if len(text) >= MIN_SOURCE_CHARS:
                return text
        elif len(text) >= MIN_HTML_CHARS and len(text) > len(page) \
                and not _BLOCK_PAGE.search(text[:1500]):
            page = text
    return page


# ---------------------------------------------------------------- helpers
def title_similarity(a, b, strict=False):
    """Share of title words two titles have in common (Jaccard).

    ``strict`` keeps function words, so "X increases Y" and "X does not
    increase Y" count as different titles.
    """
    drop = frozenset() if strict else STOP
    ta = {w for w, _, _ in tokenize(clean_text(a))} - drop
    tb = {w for w, _, _ in tokenize(clean_text(b))} - drop
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / float(len(ta | tb))


def shared_authors(keys_a, keys_b):
    """Authors in both lists; family names must match, initials when known."""
    out = []
    for fa, ga in keys_a:
        if not fa:
            continue
        for fb, gb in keys_b:
            if fa == fb and (not ga or not gb or ga == gb):
                out.append(fa)
                break
    return out


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

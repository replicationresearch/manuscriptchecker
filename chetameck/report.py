"""Generate a standalone HTML report for ChetaMeck check results.

The report is clearly labelled as a ChetaMeck report (not metacheck) and
includes a disclaimer that it is not affiliated with the official metacheck
project.

The report is laid out like an A4-width project page: a main content column of
about A4 width with a sticky right-hand sidebar that holds a table of contents
and the traffic-light legend.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests

from . import REPORT_APP_VERSION
from ._log import logger

# Embedded logos (base64 PNG data URIs) so the report is self-contained.
LOGO_MUCOS = ("data:image/png;base64,"
              "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")
LOGO_METACHECK = ("data:image/png;base64,"
                  "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")

LABEL = {"green": "Good", "yellow": "Check", "red": "Issue", "info": "Info",
         "na": "N/A", "fail": "Error"}

# Inline SVG pictograms (no emoji - they render inconsistently across OS/
# browser font stacks, which looks unpolished in a report meant to be shared).
# All strokes use currentColor so a pictogram inherits its wrapper's colour
# and adapts automatically between light and dark mode.
_SVG_ATTRS = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
ICONS = {
    "green": f'<svg {_SVG_ATTRS}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>',
    "yellow": f'<svg {_SVG_ATTRS}><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    "red": f'<svg {_SVG_ATTRS}><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    "info": f'<svg {_SVG_ATTRS}><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
    "na": f'<svg {_SVG_ATTRS}><circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/></svg>',
    "fail": f'<svg {_SVG_ATTRS}><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
    "sun": f'<svg {_SVG_ATTRS}><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>',
    "moon": f'<svg {_SVG_ATTRS}><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
    "top": f'<svg {_SVG_ATTRS}><line x1="12" y1="19" x2="12" y2="5"/><polyline points="5 12 12 5 19 12"/></svg>',
    "chevron": f'<svg {_SVG_ATTRS}><polyline points="6 9 12 15 18 9"/></svg>',
}


def _icon(key, cls=""):
    svg = ICONS.get(key, "")
    extra = f" {cls}" if cls else ""
    return f'<span class="icon icon-{key}{extra}" aria-hidden="true">{svg}</span>'

# Coherent, grouped ordering of the check modules in the report. The R2 editorial
# checks are folded into the general flow (not given their own isolated block).
SECTIONS = [
    ("Statistical reporting",
     ["all_p_values", "stat_p_exact", "stat_p_nonsig", "stat_check",
      "stat_effect_size", "es_check", "marginal", "power"]),
    ("Forensic metascience",
     ["grim_check", "grimmer_check", "sd_range_check", "sd_se_check",
      "debit_check", "stalt_check", "csf_check", "test_recalc"]),
    ("Open science & transparency",
     ["all_urls", "prereg_check", "prereg_statement", "open_practices",
      "repo_check", "code_check", "r2_check"]),
    ("Data & content integrity",
     ["duplicate_check", "image_forensic_check", "df_consistency_check",
      "funding_coi_affiliation_check"]),
    ("Social science methodology",
     ["causal_language_check", "reliability_check", "irb_ethics_check",
      "demographics_check", "multiple_comparisons_check",
      "exclusion_reporting_check", "likert_parametric_check",
      "interrater_reliability_check", "harking_check",
      "response_rate_check", "missing_data_check"]),
    ("Disclosures", ["coi_check", "funding_check"]),
    ("References",
     ["ref_summary", "ref_consistency", "ref_accuracy", "ref_miscitation",
      "ref_replication", "ref_retraction", "ref_pubpeer"]),
]

# Short note describing how each module obtains its data / runs its check.
METHOD_NOTES = {
    "all_p_values": "Scans the main text for APA-style p-value statements and "
                    "parses each p-value and its comparator.",
    "all_urls": "Extracts every URL from the main text and (when online) checks "
                "each URL for a reachable HTTP response.",
    "stat_p_exact": "Flags p-values reported imprecisely (e.g. 'p < .05') or as "
                    "exactly zero.",
    "stat_p_nonsig": "Lists non-significant p-values so they can be checked for "
                     "appropriate interpretation.",
    "stat_check": "Finds APA-style t/F statistics, recomputes the p-value from "
                  "the test statistic, and compares it with the reported p-value.",
    "stat_effect_size": "Pairs t- and F-tests with effect sizes in the same "
                        "sentence and reports which tests have an effect size.",
    "es_check": "Recomputes the effect size implied by a co-reported t/F/chi-square "
                "statistic and checks the reported confidence interval. "
                "Port of the escicheck (EffectCheck) core.",
    "marginal": "Searches for wording like 'marginally significant', 'trend', "
                "'almost significant'.",
    "power": "Finds sentences describing statistical power analyses and "
             "classifies them by type (a priori / sensitivity / post-hoc).",
    "grim_check": "Applies the GRIM test: a mean times n must be a whole number "
                  "for integer-valued data.",
    "grimmer_check": "Applies the GRIMMER test: (n-1)*SD^2 + n*mean^2 must be a "
                     "whole number for integer data.",
    "sd_range_check": "The maximum possible SD for a range is about half the "
                      "range; flags SDs that exceed it.",
    "sd_se_check": "Checks whether a reported SD is actually an SE "
                   "(SD = sqrt(n) * SE).",
    "debit_check": "Applies the DEBIT test for binary (0/1) data: "
                   "SD = sqrt(p(1-p)).",
    "stalt_check": "Finds p-values reported only as an inequality ('p < x') and "
                   "recomputes the exact p to see if it hides a much smaller value.",
    "csf_check": "Combines all reported p-values with the Carlisle-Stouffer-Fisher "
                 "omnibus test to detect homogeneity.",
    "test_recalc": "Recalculates independent-samples t-tests from reported group "
                   "means, SDs and sample sizes.",
    "prereg_check": "Finds preregistration links (AsPredicted, OSF) in the text "
                    "and resolves each OSF link via the OSF API to show what it "
                    "actually is (registration, project, file, preprint).",
    "prereg_statement": "Lists sentences that mention preregistration or that the "
                        "study was registered, with the source section.",
    "open_practices": "Reports whether the data are openly available, available on "
                      "request, or not mentioned.",
    "repo_check": "Lists repositories referenced in the text (OSF, GitHub, Zenodo, "
                  "ResearchBox) and lists the files in GitHub repos.",
    "code_check": "Reviews the code files found by the repository check.",
    "coi_check": "Looks for a conflict-of-interest / competing-interests statement.",
    "funding_check": "Looks for a funding statement.",
    "ref_summary": "Summarises the reference list and the results of the other "
                   "reference checks.",
    "ref_consistency": "Compares in-text citations (short form) with the "
                       "bibliography to find references that are not cited and "
                       "citations without a matching reference.",
    "ref_accuracy": "Queries CrossRef for each reference DOI and compares the "
                    "year / title / authors with the parsed reference.",
    "ref_miscitation": "Looks the references up in the bundled miscitation "
                       "database.",
    "ref_replication": "Looks the references up in the FLoRA replication database "
                       "and reports the outcome, outcome quote and link for any "
                       "replicated or reproduced study.",
    "ref_retraction": "Looks the references up in the RetractionWatch database.",
    "ref_pubpeer": "Queries PubPeer for comments on each cited DOI.",
    "r2_check": "Runs the automatable items of the R2 Initial Editorial "
                "Assessment checklist against the manuscript.",
    "duplicate_check": "Compares every sentence/paragraph in the manuscript "
                       "against every other one for verbatim or near-duplicate "
                       "(5-gram shingle Jaccard) text. Checks the manuscript "
                       "against itself only, not external sources.",
    "image_forensic_check": "Extracts every embedded raster image from the "
                            "PDF, perceptual-hashes it to find reused/duplicate "
                            "images, and runs a lightweight Error Level Analysis "
                            "(JPEG recompression diff) on each one. Requires "
                            "PyMuPDF and the original PDF.",
    "df_consistency_check": "Extracts every t/F test statistic's degrees of "
                            "freedom and checks whether the sample size it "
                            "implies is consistent with the manuscript's own "
                            "largest stated N.",
    "funding_coi_affiliation_check": "Compares each author's affiliation "
                                     "against the detected funding statement, "
                                     "and checks whether any overlap is also "
                                     "reflected in the conflict-of-interest "
                                     "statement.",
    "causal_language_check": "Searches for causal wording ('led to', "
                             "'effect of X on Y', ...) and checks whether an "
                             "experimental-design marker (random assignment, "
                             "manipulation, RCT, ...) appears anywhere in "
                             "the text.",
    "reliability_check": "Searches for scale/questionnaire mentions and "
                         "checks whether a reliability coefficient "
                         "(Cronbach's alpha, McDonald's omega, ICC, "
                         "test-retest, ...) is reported.",
    "irb_ethics_check": "Searches for an ethics approval / IRB / informed "
                        "consent statement.",
    "demographics_check": "Checks whether age, gender/sex composition and "
                          "sample origin are reported.",
    "multiple_comparisons_check": "Counts p-values in the text and checks "
                                  "whether a multiple-comparisons correction "
                                  "method is mentioned when there are many.",
    "exclusion_reporting_check": "Searches for exclusion statements and "
                                 "checks whether a reason/criterion is given "
                                 "in the same sentence.",
    "likert_parametric_check": "Checks whether Likert/ordinal scales used "
                               "with parametric tests (t-test, ANOVA, "
                               "Pearson correlation) are justified as "
                               "continuous, or paired with a non-parametric "
                               "check.",
    "interrater_reliability_check": "Searches for coding/rating-procedure "
                                    "wording and checks whether an "
                                    "inter-rater reliability statistic "
                                    "(kappa, ICC, percent agreement) is "
                                    "reported.",
    "harking_check": "Searches for confirmatory-sounding hypothesis "
                     "language ('as predicted', 'consistent with our "
                     "hypothesis') and checks whether a preregistration was "
                     "detected (heuristic, not proof of HARKing).",
    "response_rate_check": "Checks response-rate reporting for surveys, and "
                           "data-quality-control reporting (attention "
                           "checks, ...) for online-panel studies.",
    "missing_data_check": "When missing data/attrition is mentioned, checks "
                          "whether a handling method (deletion, imputation, "
                          "FIML, ...) is also described.",
}

# URL regex used both for linkifying and for collecting URLs to check.
URL_RE = re.compile(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+")
# colour-marker wrappers for table cells: {r}...{/} etc.
_COLOR = re.compile(r"^\{(r|g|y)\}(.*)\{/\}$", re.S)


def _esc(text):
    return html.escape(str(text if text is not None else ""))


def _strip_trailing_punct(url):
    return re.sub(r"[.,;:)\]}<>]+$", "", url)


def _linkify(text):
    """Convert bare URLs in an already-escaped string into clickable links."""
    def repl(m):
        raw = m.group(0)
        url = _strip_trailing_punct(raw)
        return (f'<a href="{_esc(url)}" target="_blank" rel="noopener">'
                f"{_esc(url)}</a>")
    return URL_RE.sub(repl, text)


def _inline(text):
    text = _esc(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = re.sub(r"\{g\}(.*?)\{/\}", r'<span class="cell g">\1</span>', text)
    text = re.sub(r"\{r\}(.*?)\{/\}", r'<span class="cell r">\1</span>', text)
    text = re.sub(r"\{y\}(.*?)\{/\}", r'<span class="cell y">\1</span>', text)
    text = _linkify(text)
    return text


def _table_row(line):
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    out = []
    for c in cells:
        m = _COLOR.match(c)
        if m:
            cls = m.group(1)
            out.append((_inline(m.group(2).strip()), cls))
        else:
            out.append((_inline(c), None))
    return out


def _build_table(header, body):
    thead = "".join(f"<th>{c}</th>" for c in header)
    rows = []
    for r in body:
        tds = []
        for i, (cell, cls) in enumerate(r):
            if cls:
                tds.append(f'<td class="cell-{cls}">{cell}</td>')
            else:
                tds.append(f"<td>{cell}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")
    return (f'<table class="data"><thead><tr>{thead}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def _md_to_html(md):
    """Convert a limited subset of markdown (tables, bold, italic, details,
    colour markers, links) to HTML."""
    if not md:
        return ""
    lines = md.split("\n")
    out_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # details block: :::details Summary ... :::
        if line.strip().startswith(":::details"):
            summary = line.strip().replace(":::details", "", 1).strip() or "Details"
            j = i + 1
            inner = []
            while j < len(lines) and lines[j].strip() != ":::":
                inner.append(lines[j])
                j += 1
            body = _md_to_html("\n".join(inner))
            out_lines.append(
                f'<details><summary>{_inline(summary)}</summary>'
                f'<div class="details-body">{body}</div></details>')
            i = j + 1
            continue
        # table
        if line.strip().startswith("|") and i + 1 < len(lines) and \
           re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            header = [h for h, _ in _table_row(line)]
            i += 2
            body = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = _table_row(lines[i])
                # truncate extra cells to the header count
                cells = cells[:len(header)]
                body.append(cells)
                i += 1
            out_lines.append(_build_table(header, body))
            continue
        out_lines.append(_inline(line))
        i += 1
    return "\n".join(out_lines)


def _meta_table(paper):
    info = paper.info
    if info.empty:
        return ""
    row = info.iloc[0]
    items = []
    if row.get("title"):
        items.append(("<b>Title</b>", _esc(row["title"])))
    if row.get("doi"):
        items.append(("<b>DOI</b>", _esc(row["doi"])))
    authors = paper.table("author")
    if not authors.empty:
        names = [f"{a.get('given','')} {a.get('family','')}".strip()
                 for _, a in authors.iterrows()]
        items.append(("<b>Authors</b>", _esc(", ".join(names))))
    if row.get("input_format"):
        items.append(("<b>Format</b>", _esc(row["input_format"])))
    cells = "".join(f"<tr><td class='k'>{k}</td><td>{v}</td></tr>"
                    for k, v in items)
    return f"<table class='meta'><tbody>{cells}</tbody></table>"


# ---------------------------------------------------------------------------
# URL link checking
# ---------------------------------------------------------------------------
def _collect_urls(outputs):
    """Collect unique URLs from all output tables and report strings."""
    urls = set()
    for o in outputs:
        table = o.get("table")
        if table is not None and not table.empty:
            for col in table.columns:
                for v in table[col]:
                    if isinstance(v, str) and URL_RE.search(v):
                        for m in URL_RE.finditer(v):
                            urls.add(_strip_trailing_punct(m.group(0)))
        for r in o.get("report", []):
            if isinstance(r, str):
                for m in URL_RE.finditer(r):
                    urls.add(_strip_trailing_punct(m.group(0)))
    return sorted(urls)


def _http_status(code):
    """Classify a non-OK HTTP status code for the link check.

    Returns a dict with ``kind`` ("manual" or "error"), ``status`` (short label)
    and ``explanation`` (what the code means / what to do).
    """
    if code == 404:
        return {"kind": "manual", "status": "HTTP 404",
                "explanation": ("HTTP 404 - Not found. The link could not be "
                                "resolved automatically (common for DOIs whose "
                                "landing page is not directly reachable). "
                                "Check it manually.")}
    if code in (401, 403):
        return {"kind": "manual", "status": f"HTTP {code}",
                "explanation": (f"HTTP {code} - Forbidden. The site blocked "
                                "automated access; this is often just a "
                                "publisher blocking bots, not a broken link. "
                                "Check it manually.")}
    return {"kind": "error", "status": f"HTTP {code}",
            "explanation": (f"The link returned HTTP {code}, which may indicate "
                            "a real problem. Check it manually.")}


def _check_url(url, timeout=6):
    """Return a status dict for a URL, or ``{}`` if it looks OK.

    The dict has ``kind`` ("manual"/"error"/"unreachable"), ``status`` (short
    label) and ``explanation`` (human-readable note for the report).
    """
    headers = {"User-Agent": "ChetaMeck/0.2 (metacheck app)"}
    try:
        # HEAD first (cheap); fall back to a streaming GET if not supported.
        try:
            resp = requests.head(url, timeout=timeout, allow_redirects=True,
                                 headers=headers)
            if resp.status_code in (200, 301, 302, 307, 308):
                return {}
            code = resp.status_code
        except requests.exceptions.RequestException:
            resp = requests.get(url, timeout=timeout, allow_redirects=True,
                                headers=headers, stream=True)
            code = resp.status_code
            resp.close()
        if 200 <= code < 400:
            return {}
        return _http_status(code)
    except requests.exceptions.RequestException as e:
        logger.debug("link check: %s unreachable: %s", url, e)
        return {"kind": "unreachable", "status": "unreachable",
                "explanation": ("The link could not be reached from here "
                                "(network/DNS error). Check it manually.")}
    except Exception as e:  # noqa: BLE001
        logger.debug("link check: %s failed: %s", url, e)
        return {"kind": "unreachable", "status": "unreachable",
                "explanation": ("The link could not be checked because of an "
                                "unexpected error. Check it manually.")}


# Cap the number of URLs checked live so a URL-heavy paper can't stall report
# generation; anything past the cap is reported as skipped, not silently
# dropped.
MAX_URLS_CHECKED = 60


def _check_urls(urls):
    """Check a list of URLs concurrently. Returns (status, n_skipped)."""
    if not urls:
        return {}, 0
    checked, skipped = urls[:MAX_URLS_CHECKED], urls[MAX_URLS_CHECKED:]
    status = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(_check_url, checked))
    for u, s in zip(checked, results):
        if s:
            status[u] = s
    return status, len(skipped)


# ---------------------------------------------------------------------------
# Summary / TOC
# ---------------------------------------------------------------------------
def _summary_items(outputs, order):
    by_mod = {o["module"]: o for o in outputs}
    items = []
    for name in order:
        o = by_mod.get(name)
        if o is None:
            continue
        tl = o["traffic_light"]
        items.append(
            f'<li><span class="tl {tl}">{_icon(tl)}</span> '
            f'<a href="#{_esc(o["module"])}">{_esc(o["summary_text"])}</a></li>')
    return items


def _render_module(o):
    """Render one module's <div class="module ..."> block."""
    tl = o["traffic_light"]
    name = o["module"]
    friendly = _module_friendly(name)
    body = "\n".join(_md_to_html(r) for r in o["report"])
    method = METHOD_NOTES.get(name)
    method_attr = f' data-method="{_esc(method)}"' if method else ""
    return (
        f'<div class="module {tl}" id="{_esc(name)}" data-status="{tl}">'
        f'<h3 class="modtitle"{method_attr}>{_icon(tl)} '
        f'<span class="modname">{_esc(friendly)}</span>'
        f' <span class="badge {tl}">{LABEL.get(tl, tl)}</span></h3>'
        f'<p class="summary">{_inline(o["summary_text"])}</p>'
        f'<div class="detail">{body}</div></div>')


def _render_cat_group(sec_name, modules):
    """Render a collapsible '<h2 class="cat">' + its module divs as one group."""
    slug = re.sub(r"[^a-z0-9]+", "-", sec_name.lower()).strip("-")
    body = "\n".join(_render_module(o) for o in modules)
    return (
        f'<section class="cat-group" id="cat-{_esc(slug)}">'
        f'<h2 class="cat" role="button" tabindex="0" aria-expanded="true">'
        f'<span class="cat-label">{_esc(sec_name)}</span>'
        f'<span class="cat-count">{len(modules)}</span>'
        f'{_icon("chevron", "cat-chevron")}</h2>'
        f'<div class="cat-body">{body}</div></section>')


def _order_modules(outputs):
    """Return outputs in the coherent report order, grouped by section."""
    by_mod = {o["module"]: o for o in outputs}
    ordered = []
    for _sec_name, names in SECTIONS:
        for name in names:
            if name in by_mod:
                ordered.append(by_mod[name])
    # include any outputs not listed (safety) at the end
    listed = {o["module"] for o in ordered}
    ordered += [o for o in outputs if o["module"] not in listed]
    return ordered


def sticker_uri(filename, fallback):
    """Data URI of a logo PNG shipped next to the app (fallback if missing)."""
    try:
        import base64
        import config
        data = (config.BASE_DIR / filename).read_bytes()
        return "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    except Exception:  # noqa: BLE001
        return fallback


def generate_report(paper, outputs, include_online=True, engine="chetameck"):
    """Return the full HTML report as a string."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    title = paper.info.iloc[0].get("title") if not paper.info.empty else ""
    title = title or paper.paper_id

    logo = (LOGO_METACHECK if engine == "metacheck"
            else sticker_uri("chetameck_logo_small.png", LOGO_MUCOS))

    ordered = _order_modules(outputs)
    order_names = [o["module"] for o in ordered]
    by_mod = {o["module"]: o for o in ordered}

    # Link-check URLs found anywhere in the outputs.
    link_status, n_urls_skipped = _check_urls(_collect_urls(outputs))

    # ---- build module sections grouped by section heading --------------------
    sections_html = []
    for sec_name, names in SECTIONS:
        present = [by_mod[n] for n in names if n in by_mod]
        if not present:
            continue
        sections_html.append(_render_cat_group(sec_name, present))

    # any leftover outputs (not in a section) go under a catch-all heading
    listed = {n for _s, ns in SECTIONS for n in ns}
    leftover = [o for o in ordered if o["module"] not in listed]
    if leftover:
        sections_html.append(_render_cat_group("Other checks", leftover))

    # ---- summary / TOC -------------------------------------------------------
    summary_items = _summary_items(outputs, order_names)
    toc_items = []
    for sec_name, names in SECTIONS:
        present = [n for n in names if n in by_mod]
        if not present:
            continue
        toc_items.append(f'<div class="toc-sec">{_esc(sec_name)}</div>')
        for n in present:
            o = by_mod[n]
            tl = o["traffic_light"]
            toc_items.append(
                f'<a class="toc-link" href="#{_esc(n)}" data-target="{_esc(n)}">'
                f'<span class="tl {tl}">{_icon(tl)}</span>'
                f'{_esc(_module_friendly(n))}</a>')

    # Legend doubles as a status filter: clicking a status shows only modules
    # with that traffic light (click again, or "Show all", to reset).
    status_counts = {}
    for o in outputs:
        status_counts[o["traffic_light"]] = status_counts.get(o["traffic_light"], 0) + 1
    legend = "".join(
        f'<button type="button" class="legend-item" data-filter="{k}">'
        f'<span class="tl {k}">{_icon(k)}</span>'
        f'<span class="legend-label">{LABEL.get(k, k)}</span>'
        f'<span class="legend-count">{status_counts.get(k, 0)}</span></button>'
        for k in ("green", "yellow", "red", "info", "na", "fail")
        if status_counts.get(k, 0) > 0)

    online_note = ""
    if not include_online:
        online_note = ("<p class='note'>Online checks (CrossRef, repositories, "
                       "retractions, PubPeer) were not run for this report.</p>")

    # annotate URLs that failed the link check
    link_note = ""
    if link_status:
        rows = "".join(
            f"<tr><td>{_linkify(_esc(u))}</td>"
            f'<td class="cell-r">{_esc(s.get("status", ""))}</td>'
            f'<td>{_esc(s.get("explanation", ""))}</td></tr>'
            for u, s in link_status.items())
        has_error = any(s.get("kind") == "error" for s in link_status.values())
        badge = "red" if has_error else "yellow"
        badge_label = "Issue" if has_error else "Check manually"
        head_icon = _icon(badge)
        summary = ("Some URLs returned an error." if has_error else
                   "Some URLs could not be checked automatically; verify them "
                   "manually.")
        skipped_note = (f"<p class='note'>{n_urls_skipped} additional URL(s) "
                        f"were not checked (only the first {MAX_URLS_CHECKED} "
                        "are checked per report).</p>" if n_urls_skipped else "")
        link_note = (f"<div class='module {badge}' id='linkcheck'>"
                     f"<h3>{head_icon} <span class='modname'>Link check</span> "
                     f"<span class='badge {badge}'>{badge_label}</span></h3>"
                     f"<p class='summary'>{summary}</p>"
                     f"<div class='detail'><table class='data'>"
                     f"<thead><tr><th>URL</th><th>Status</th>"
                     f"<th>What it means</th></tr></thead>"
                     f"<tbody>{rows}</tbody></table>"
                     f"<p class='note'><strong>Status codes:</strong> "
                     f"<strong>HTTP 404</strong> = Not found - the link could "
                     f"not be resolved, so it cannot be verified automatically. "
                     f"<strong>HTTP 403</strong> = Forbidden - the site blocked "
                     f"automated access (e.g. a publisher blocking bots), which "
                     f"is not the same as a broken link. Both mean the link "
                     f"could not be checked automatically and should be "
                     f"verified by hand.</p>"
                     f"{skipped_note}</div></div>")
    elif n_urls_skipped:
        link_note = (f"<p class='note'>{n_urls_skipped} URL(s) were not checked "
                    f"(only the first {MAX_URLS_CHECKED} are checked per report).</p>")

    css = _CSS
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ChetaMeck Report</title>
<style>{css}</style>
</head>
<body>
<header>
  <div class="header-left">
    <img class="logo" src="{logo}" alt="logo">
    <div>
      <h1>ChetaMeck Report</h1>
      <p class="sub">A metacheck-style manuscript review &middot; generated {now}</p>
    </div>
  </div>
  <button id="themeToggle" class="theme-toggle" title="Toggle light/dark theme"
          aria-label="Toggle light/dark theme">
    {_icon("sun", "icon-theme-sun")}{_icon("moon", "icon-theme-moon")}
  </button>
</header>

<div class="banner">
  <strong>This is a ChetaMeck report.</strong> It is generated by an independent
  reimplementation of the metacheck checks (ChetaMeck v{REPORT_APP_VERSION}) and is
  <em>not affiliated with the official metacheck project</em>. It is provided for
  private use only. Always verify findings manually.
</div>

<div class="layout">
  <main class="content">
    <section class="meta">{_meta_table(paper)}</section>
    <section class="summary-block">
      <h2>Summary</h2>
      <ul class="summary-list">{''.join(summary_items)}</ul>
    </section>
    {online_note}
    {link_note}
    <section class="modules">
      {''.join(sections_html)}
    </section>
  </main>

  <aside class="sidebar">
    <div class="side-card legend-card">
      <div class="legend-head">
        <h2>Legend &middot; filter</h2>
        <button type="button" id="filterReset" class="filter-reset" hidden>Show all</button>
      </div>
      <div class="legend">{legend}</div>
    </div>
    <div class="side-card toc-card">
      <h2>Table of contents</h2>
      <input type="search" id="tocSearch" class="toc-search"
             placeholder="Filter checks by name...">
      <nav class="toc">{''.join(toc_items)}</nav>
    </div>
  </aside>
</div>

<footer>
  ChetaMeck v{REPORT_APP_VERSION} &middot; Coded by DeepSeek V4 Flash &middot;
  Prompted by Lukas Röseler &middot; Not affiliated with the official metacheck
  app &middot; For private use only.
</footer>

<button id="backToTop" class="back-to-top" title="Back to top" aria-label="Back to top" hidden>
  {_icon("top")}
</button>

<script>
(function() {{
  // --- theme toggle ---------------------------------------------------
  var root = document.documentElement;
  var saved = null;
  try {{ saved = localStorage.getItem('chetameck-theme'); }} catch(e) {{}}
  if (saved) root.dataset.theme = saved;
  var themeBtn = document.getElementById('themeToggle');
  themeBtn.addEventListener('click', function() {{
    var next = (root.dataset.theme === 'dark') ? 'light' : 'dark';
    root.dataset.theme = next;
    try {{ localStorage.setItem('chetameck-theme', next); }} catch(e) {{}}
  }});

  // --- collapsible category sections -----------------------------------
  document.querySelectorAll('.cat-group > .cat').forEach(function(h) {{
    function toggle() {{
      var group = h.closest('.cat-group');
      var collapsed = group.classList.toggle('collapsed');
      h.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    }}
    h.addEventListener('click', toggle);
    h.addEventListener('keydown', function(e) {{
      if (e.key === 'Enter' || e.key === ' ') {{ e.preventDefault(); toggle(); }}
    }});
  }});

  // --- status filter (legend doubles as a filter) -----------------------
  var modules = Array.prototype.slice.call(document.querySelectorAll('.module[data-status]'));
  var catGroups = Array.prototype.slice.call(document.querySelectorAll('.cat-group'));
  var resetBtn = document.getElementById('filterReset');
  function applyFilter(status) {{
    modules.forEach(function(m) {{
      m.style.display = (!status || m.dataset.status === status) ? '' : 'none';
    }});
    // a category with no visible module left (everything filtered out) is
    // hidden entirely, instead of leaving an empty heading + blank gap.
    catGroups.forEach(function(g) {{
      var anyVisible = !status || g.querySelector('.module[data-status="' + status + '"]');
      g.style.display = anyVisible ? '' : 'none';
    }});
    document.querySelectorAll('.legend-item').forEach(function(b) {{
      b.classList.toggle('active', !!status && b.dataset.filter === status);
    }});
    resetBtn.hidden = !status;
    // auto-expand any collapsed group so a filtered-in module stays visible
    if (status) {{
      document.querySelectorAll('.cat-group.collapsed').forEach(function(g) {{
        g.classList.remove('collapsed');
      }});
    }}
  }}
  document.querySelectorAll('.legend-item').forEach(function(btn) {{
    btn.addEventListener('click', function() {{
      var active = btn.classList.contains('active');
      applyFilter(active ? null : btn.dataset.filter);
    }});
  }});
  resetBtn.addEventListener('click', function() {{ applyFilter(null); }});

  // --- TOC search-as-you-type --------------------------------------------
  var tocSearch = document.getElementById('tocSearch');
  tocSearch.addEventListener('input', function() {{
    var q = tocSearch.value.trim().toLowerCase();
    document.querySelectorAll('.toc-link').forEach(function(a) {{
      a.style.display = a.textContent.toLowerCase().indexOf(q) === -1 ? 'none' : '';
    }});
    document.querySelectorAll('.toc-sec').forEach(function(sec) {{
      var next = sec.nextElementSibling, anyVisible = false;
      while (next && !next.classList.contains('toc-sec')) {{
        if (next.style.display !== 'none') anyVisible = true;
        next = next.nextElementSibling;
      }}
      sec.style.display = (q && !anyVisible) ? 'none' : '';
    }});
  }});

  // --- TOC scrollspy: highlight the section currently in view -----------
  var tocLinks = {{}};
  document.querySelectorAll('.toc-link').forEach(function(a) {{
    tocLinks[a.dataset.target] = a;
  }});
  if ('IntersectionObserver' in window) {{
    var observer = new IntersectionObserver(function(entries) {{
      entries.forEach(function(entry) {{
        var link = tocLinks[entry.target.id];
        if (!link) return;
        link.classList.toggle('active', entry.isIntersecting);
      }});
    }}, {{ rootMargin: '-15% 0px -70% 0px' }});
    modules.forEach(function(m) {{ observer.observe(m); }});
  }}

  // --- back-to-top button -------------------------------------------------
  var topBtn = document.getElementById('backToTop');
  window.addEventListener('scroll', function() {{
    topBtn.hidden = window.scrollY < 400;
  }}, {{ passive: true }});
  topBtn.addEventListener('click', function() {{
    window.scrollTo({{ top: 0, behavior: 'smooth' }});
  }});
}})();
</script>
</body>
</html>"""


def _module_friendly(name):
    from .catalog import module_label
    return module_label(name)


_CSS = """
:root { --bg:#ffffff; --panel:#f6f6f8; --panel2:#eaeaf0; --line:#dcdce4;
        --text:#1a1a22; --muted:#6b6b7b; --accent:#2e7d32; --green:#2e7d32;
        --yellow:#c9a227; --red:#c0392b; --info:#2980b9; --na:#7f8c8d;
        --fail:#8e44ad; --link:#1a56db; }
[data-theme="dark"] { --bg:#1e1e2e; --panel:#27273a; --panel2:#31314a;
        --line:#3b3b58; --text:#e6e6ee; --muted:#9a9ab5; --accent:#2e7d32;
        --green:#2e7d32; --yellow:#c9a227; --red:#c0392b; --info:#2980b9;
        --na:#7f8c8d; --fail:#8e44ad; --link:#7aa2f7; }
* { box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { font-family:'Segoe UI',system-ui,sans-serif; margin:0; padding:0;
       background:var(--bg); color:var(--text); line-height:1.5; }
header { background:var(--panel); padding:20px 32px; border-bottom:1px solid var(--line);
         display:flex; align-items:center; justify-content:space-between; gap:16px; }
.header-left { display:flex; align-items:center; gap:16px; }
.header-left .logo { height:52px; width:auto; }
header h1 { margin:0 0 4px; }
header .sub { color:var(--muted); margin:0; }
.theme-toggle { background:var(--panel2); color:var(--text); border:1px solid var(--line);
                width:40px; height:40px; padding:0; border-radius:8px; cursor:pointer;
                display:inline-flex; align-items:center; justify-content:center; }
.theme-toggle:hover { background:var(--panel); }
.theme-toggle .icon { width:20px; height:20px; }
.theme-toggle .icon-theme-sun { display:none; }
[data-theme="dark"] .theme-toggle .icon-theme-sun { display:inline-flex; }
[data-theme="dark"] .theme-toggle .icon-theme-moon { display:none; }
.banner { background:var(--panel); border-left:4px solid var(--fail); margin:16px 32px;
          padding:12px 16px; border-radius:6px; }

/* icon pictograms (replace emoji so status colours stay consistent across
   OS/browser font stacks in both light and dark mode) */
.icon { display:inline-flex; align-items:center; justify-content:center;
        width:1em; height:1em; vertical-align:-0.15em; }
.icon svg { width:100%; height:100%; display:block; }
.icon-green { color:var(--green); }
.icon-yellow { color:var(--yellow); }
.icon-red { color:var(--red); }
.icon-info { color:var(--info); }
.icon-na { color:var(--na); }
.icon-fail { color:var(--fail); }
.modtitle .icon { width:1.15em; height:1.15em; }

/* A4-ish width layout with a right sidebar */
.layout { display:flex; gap:24px; align-items:flex-start; max-width:1300px;
          margin:0 auto; padding:0 32px; }
.content { flex:1 1 auto; min-width:0; max-width:840px; }
.sidebar { flex:0 0 280px; position:sticky; top:16px; max-height:calc(100vh - 32px);
           display:flex; flex-direction:column; gap:14px; overflow:hidden; }
@media (max-width: 1000px) {
  .layout { flex-direction:column; }
  .sidebar { position:static; max-height:none; width:100%; flex:1 1 auto; overflow:visible; }
}

section { margin:16px 0; }
section.meta table { width:100%; border-collapse:collapse; }

/* collapsible category groups */
.cat-group { margin:0; }
h2.cat { color:var(--muted); font-size:1.05em; margin:26px 0 6px;
         text-transform:uppercase; letter-spacing:0.5px; border-bottom:1px solid var(--line);
         padding-bottom:4px; display:flex; align-items:center; gap:8px;
         cursor:pointer; user-select:none; }
h2.cat:hover { color:var(--text); }
h2.cat:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.cat-count { background:var(--panel2); color:var(--muted); border-radius:10px;
             padding:1px 8px; font-size:0.78em; font-weight:400;
             text-transform:none; letter-spacing:normal; }
.cat-chevron { margin-left:auto; width:16px; height:16px; color:var(--muted);
               transition:transform .15s ease; }
.cat-group.collapsed .cat-chevron { transform:rotate(-90deg); }
.cat-group.collapsed .cat-body { display:none; }
table.meta td { padding:4px 8px; border-bottom:1px solid var(--line); }
table.meta td.k { color:var(--muted); width:90px; }
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }
.module { background:var(--panel); border-radius:8px; padding:16px 20px;
          margin:14px 0; border-left:5px solid var(--na); position:relative; }
.module.green { border-left-color:var(--green); }
.module.yellow { border-left-color:var(--yellow); }
.module.red { border-left-color:var(--red); }
.module.info { border-left-color:var(--info); }
.module.na { border-left-color:var(--na); }
.module.fail { border-left-color:var(--fail); }
.module h3 { margin:0 0 8px; }
.modname { text-transform:capitalize; }
.badge { float:right; font-size:0.75em; padding:2px 10px; border-radius:12px;
         color:#fff; }
.badge.green { background:var(--green); } .badge.yellow { background:var(--yellow); }
.badge.red { background:var(--red); } .badge.info { background:var(--info); }
.badge.na { background:var(--na); } .badge.fail { background:var(--fail); }
p.summary { margin:0 0 10px; color:var(--muted); }
.detail { overflow-x:auto; }

/* hover tooltip for 'how this was checked' */
.modtitle { cursor:help; position:relative; }
.modtitle:hover::after {
  content: attr(data-method);
  position:absolute; left:0; top:100%; margin-top:8px; z-index:60;
  background:var(--panel2); color:var(--text); border:1px solid var(--line);
  padding:10px 12px; border-radius:8px; max-width:420px; width:max-content;
  font-size:0.8em; font-weight:400; line-height:1.45; white-space:normal;
  box-shadow:0 6px 18px rgba(0,0,0,.25); pointer-events:none;
}

/* expandable details blocks (statcheck etc.) */
details { margin:8px 0; }
details summary { cursor:pointer; color:var(--link); font-weight:600; }
.details-body { padding:8px 0; }

table.data { width:100%; border-collapse:collapse; margin:8px 0; }
table.data th, table.data td { border:1px solid var(--line); padding:6px 8px;
                                text-align:left; font-size:0.9em; }
table.data th { background:var(--panel2); }
td.cell-r, span.cell.r { color:var(--red); font-weight:600; }
td.cell-g, span.cell.g { color:var(--green); font-weight:600; }
td.cell-y, span.cell.y { color:var(--yellow); font-weight:600; }

/* sidebar cards: legend fixed on top, TOC scrolls below */
.side-card { background:var(--panel); border-radius:8px; padding:14px 16px; }
.legend-card { flex:0 0 auto; }
.toc-card { flex:1 1 auto; overflow-y:auto; }
.side-card h2 { margin:0 0 10px; font-size:0.85em; color:var(--muted);
                text-transform:uppercase; letter-spacing:0.5px; }
.legend-head { display:flex; align-items:center; justify-content:space-between;
               gap:8px; margin-bottom:10px; }
.legend-head h2 { margin:0; }
.filter-reset { background:none; border:none; color:var(--link); cursor:pointer;
                 font-size:0.78em; padding:0; font-family:inherit; }
.filter-reset:hover { text-decoration:underline; }
.toc-search { width:100%; box-sizing:border-box; margin:0 0 8px; padding:6px 8px;
              border-radius:6px; border:1px solid var(--line); background:var(--bg);
              color:var(--text); font-size:0.85em; font-family:inherit; }
.toc-search:focus { outline:2px solid var(--accent); outline-offset:1px; }
.toc-sec { font-size:0.72em; color:var(--muted); text-transform:uppercase;
           margin:8px 0 2px; letter-spacing:0.4px; }
.toc-link { display:flex; align-items:center; gap:6px; padding:4px 6px;
            border-radius:6px; font-size:0.85em; }
.toc-link:hover { background:var(--panel2); text-decoration:none; }
.toc-link.active { background:var(--panel2); font-weight:600; color:var(--text); }
.legend { display:flex; flex-direction:column; gap:2px; }
.legend-item { display:flex; align-items:center; gap:8px; font-size:0.85em;
               margin:0; width:100%; text-align:left; background:none;
               border:1px solid transparent; border-radius:6px; padding:5px 6px;
               cursor:pointer; color:var(--text); font-family:inherit; }
.legend-item:hover { background:var(--panel2); }
.legend-item.active { background:var(--panel2); border-color:var(--line); font-weight:600; }
.legend-item .tl { width:18px; text-align:center; }
.legend-label { flex:1 1 auto; }
.legend-count { color:var(--muted); font-variant-numeric:tabular-nums; }

/* floating back-to-top button */
.back-to-top { position:fixed; right:24px; bottom:24px; width:44px; height:44px;
               border-radius:50%; background:var(--accent); color:#fff; border:none;
               display:flex; align-items:center; justify-content:center; cursor:pointer;
               box-shadow:0 4px 14px rgba(0,0,0,.25); z-index:80; }
.back-to-top[hidden] { display:none; }
.back-to-top:hover { filter:brightness(1.1); }
.back-to-top .icon { width:20px; height:20px; }

/* summary block at the top of the content */
.summary-block { background:var(--panel); border-radius:8px; padding:14px 18px;
                 margin:16px 0; border-left:4px solid var(--accent); }
.summary-block h2 { margin:0 0 8px; font-size:0.9em; color:var(--muted);
                    text-transform:uppercase; letter-spacing:0.5px; }
.summary-list { list-style:none; margin:0; padding:0; }
.summary-list li { font-size:0.82em; margin:6px 0; }
.summary-list .tl { margin-right:6px; }
.note { color:var(--muted); font-style:italic; }
footer { text-align:center; color:var(--muted); padding:20px; font-size:0.85em;
         border-top:1px solid var(--line); margin-top:24px; }
"""

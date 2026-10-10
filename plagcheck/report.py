"""HTML report for the Plagiarism Check engine (reuses the ChetaMeck look)."""

import html
from datetime import datetime

from chetameck.report import _CSS, LOGO_MUCOS, sticker_uri

from .core import BENCHMARK_NOTE

LABEL = {"green": "No substantial verbatim overlap found in the searched sources",
         "yellow": "Check", "red": "High overlap", "na": "Not run"}
COLORS = ["#ffd54f", "#81d4fa", "#a5d6a7", "#f48fb1", "#ce93d8", "#ffab91",
          "#b0bec5", "#c5e1a5"]

_EXTRA_CSS = """
.cards { display:flex; gap:12px; flex-wrap:wrap; margin:16px 0; }
.card { background:var(--panel); border-radius:8px; padding:12px 18px; min-width:150px; }
.card .big { font-size:1.8em; font-weight:600; }
.card .lbl { color:var(--muted); font-size:.85em; }
.src { background:var(--panel); border-radius:8px; margin:10px 0; padding:12px 16px;
       border-left:5px solid var(--na); }
.src.red { border-left-color:var(--red); } .src.yellow { border-left-color:var(--yellow); }
.src.green { border-left-color:var(--green); }
.src h4 { margin:0 0 4px; } .src .meta { color:var(--muted); font-size:.88em; }
.tag { display:inline-block; font-size:.75em; padding:1px 8px; border-radius:10px;
       background:var(--panel2); color:var(--muted); margin-left:6px; }
.pass { border-top:1px solid var(--line); margin-top:8px; padding-top:6px; font-size:.9em; }
.pass .a, .pass .b { padding:4px 8px; border-radius:4px; margin:2px 0; }
.pass .a { background:var(--panel2); } .pass .b { border:1px dashed var(--line); }
details summary { cursor:pointer; color:var(--link); }
.ms h3 { margin:18px 0 4px; color:var(--muted); font-size:1em; }
.ms mark { color:#111; padding:0 1px; border-radius:3px; }
.ms sup { color:var(--muted); font-size:.7em; }
.ms .ign { color:var(--muted); }
.note { color:var(--muted); font-size:.9em; }
"""


def _e(x):
    return html.escape(str(x if x is not None else ""))


def _src_card(i, s):
    tl = ("green" if s["coverage"] < 0.05 else
          "yellow" if s["coverage"] < 0.15 else "red")
    tags = f'<span class="tag">{_e(s.get("source", ""))}</span>'
    if s.get("own_work"):
        tags += ('<span class="tag">own prior work? shared author(s): '
                 f'{_e(", ".join(n.title() for n in s["own_work"]))}</span>')
    if s["cited"]:
        tags += '<span class="tag">cited in reference list</span>'
    title = _e(s["title"] or s["name"])
    if s.get("url"):
        title = f'<a href="{_e(s["url"])}" target="_blank">{title}</a>'
    meta = " &middot; ".join(x for x in (_e(s.get("authors", "")),
                                         _e(s.get("year") or "")) if x)
    swatch = (f'<span style="background:{COLORS[(i - 1) % len(COLORS)]};'
              'padding:0 8px;border-radius:3px;margin-right:6px">&nbsp;</span>')
    passages = ""
    for p in s["passages"]:
        passages += (f'<div class="pass"><div class="a"><b>Manuscript '
                     f'({p["words"]} words):</b> {_e(p["manuscript"])}</div>'
                     f'<div class="b"><b>Source:</b> {_e(p["source"])}</div></div>')
    if s["n_runs"] > len(s["passages"]):
        passages += (f'<p class="note">{s["n_runs"] - len(s["passages"])} more '
                     'matching passages not shown.</p>')
    body = (f"<details><summary>{s['n_runs']} matching passage(s)</summary>"
            f"{passages}</details>") if s["n_runs"] else \
        '<p class="note">No passage of 8+ identical words.</p>'
    return (f'<div class="src {tl}"><h4>{swatch}[{i}] {title}{tags}</h4>'
            f'<div class="meta">{meta}</div>'
            f'<div><b>{s["coverage"]:.1%}</b> of the manuscript '
            f'({s["matched_words"]} words) matches this source.</div>{body}</div>')


def _render_doc(doc, token_style):
    """Render the manuscript; ``token_style(i)`` -> (key, css, title) or None.

    Consecutive tokens with the same key share one <mark> (spaces included).
    """
    out, last_header = [], None
    ti = 0
    n = len(doc.words)
    for ridx, row in enumerate(doc.rows):
        start = doc.row_offsets[ridx]
        end = start + len(row["text"])
        if row["header"] and row["header"] != last_header:
            out.append(f'<h3>{_e(row["header"])}</h3>')
            last_header = row["header"]
        pos = start
        parts = []
        open_key = None

        def close():
            nonlocal open_key
            if open_key is not None:
                parts.append("</mark>")
                open_key = None

        while ti < n and doc.spans[ti][0] < end:
            s0, e0 = doc.spans[ti]
            st = token_style(ti)
            key = st[0] if st else None
            gap = _e(doc.text[pos:s0])
            if key is not None and key == open_key:
                parts.append(gap)
            else:
                close()
                parts.append(gap)
                if key is not None:
                    parts.append(f'<mark style="{st[1]}" title="{_e(st[2])}">')
                    open_key = key
            word = _e(doc.text[s0:e0])
            if key is None and doc.ignored[ti]:
                parts.append(f'<span class="ign">{word}</span>')
            else:
                parts.append(word)
            pos = e0
            ti += 1
        close()
        parts.append(_e(doc.text[pos:end]))
        out.append("<span>" + "".join(parts) + "</span> ")
    return "".join(out)


def _manuscript_html(doc, sources):
    owner = [None] * len(doc.words)
    for si, s in enumerate(sources, 1):
        for t, c in enumerate(s["covered"]):
            if c and owner[t] is None:
                owner[t] = si

    def style(i):
        o = owner[i]
        if not o:
            return None
        return (o, f"background:{COLORS[(o - 1) % len(COLORS)]}",
                f"Source [{o}]")
    return _render_doc(doc, style)


def _phrases_html(doc, info):
    cur, old = info["current_idx"], info["earlier_idx"]

    def style(i):
        if i in cur:
            return ("c", "background:#ff9800;color:#111", "searched in this run")
        if i in old:
            return ("o", "background:#90a4ae;color:#111",
                    "searched in an earlier run")
        return None
    return _render_doc(doc, style)


def _coverage_html(info):
    words = max(info["words_total"], 1)
    cur_w = len(info["current_idx"])
    all_w = len(info["current_idx"] | info["earlier_idx"])
    para = max(info["paragraphs"], 1)
    rows = [
        ("Paragraphs (12+ words)", f'{info["paragraphs"]}'),
        ("Paragraphs probed online in this run",
         f'{info["paragraphs_probed"]} ({info["paragraphs_probed"] / para:.0%}; '
         f'seed {info["seed"]})'),
        ("Paragraphs without a searchable phrase",
         f'{info["paragraphs"] - info["paragraphs_probeable"]} (mostly numbers, '
         'quotes or citations)'),
        ("Searched in", ", ".join(info["backends"])),
        ("Phrases searched: this run / all runs / available",
         f'{info["searched"]} / {info["cumulative"]} / {info["total"]} '
         f'({info["runs"]} run(s) logged)'),
        ("Words inside searched phrases (this run)",
         f"{cur_w} of {words} ({cur_w / words:.0%})"),
        ("Words inside searched phrases (all runs)",
         f"{all_w} of {words} ({all_w / words:.0%})"),
    ]
    tr = "".join(f"<tr><td class='k'>{_e(k)}</td><td>{_e(v)}</td></tr>"
                 for k, v in rows)
    return (
        "<div class='module info'><h3>Search coverage</h3>"
        "<p>Online sources can only be found through the searched phrases: one "
        "9-word excerpt per ~60 words, searched as an exact word sequence. "
        "Every paragraph with a searchable phrase gets at least one (see the "
        "table for paragraphs that have none, and the notes for searches a "
        "service left unanswered). A copied passage is only found if a phrase "
        "falls into it, so a single copied sentence inside an otherwise "
        "original paragraph is often missed. Re-run with <i>skip phrases from earlier runs</i> to "
        "probe other parts of every paragraph (each run is logged in "
        "phrase_log.json). Once a source is found, its full text is compared "
        "with the <b>whole</b> manuscript; the literature folder and local "
        "files are always compared in full.</p>"
        + (f"<p>{_e(BENCHMARK_NOTE)}</p>" if BENCHMARK_NOTE else "")
        + f"<table class='meta'>{tr}</table></div>")


def _work_li(w):
    ph = w.get("phrases") or []
    if ph:
        hit = f'{len(ph)} phrase hit(s), e.g. "{_e(ph[0]["phrase"])}"'
    else:
        hit = "phrase hit reported by OpenAlex (the phrase could not be identified)"
    return (f'<li><a href="{_e(w.get("url", ""))}" target="_blank">'
            f'{_e(w.get("title") or w.get("name"))}</a> '
            f'({_e(w.get("year") or "")}; {_e(w.get("source"))}) - {hit}</li>')


def build_report(r):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tl = r["traffic_light"]
    doc = r["doc"]
    sources = r["sources"]
    info = r["phrase_info"]
    own = (f'<div class="card"><div class="big">{r["score_own"]:.1%}</div>'
           '<div class="lbl">from the authors\' own prior work</div></div>'
           if r["score_own"] else "")
    cards = (
        f'<div class="card"><div class="big">{r["score"]:.1%}</div>'
        '<div class="lbl">verbatim overlap (all sources)</div></div>'
        f'<div class="card"><div class="big">{r["score_uncited"]:.1%}</div>'
        '<div class="lbl">overlap with sources not in reference list</div></div>'
        f'{own}'
        f'<div class="card"><div class="big">{info["paragraphs_probed"]} / '
        f'{info["paragraphs"]}</div>'
        '<div class="lbl">paragraphs probed online</div></div>'
        f'<div class="card"><div class="big">{len(sources)}</div>'
        '<div class="lbl">sources with verified overlap</div></div>'
        f'<div class="card"><div class="big">{doc.quote_words}</div>'
        '<div class="lbl">quoted words excluded</div></div>')

    src_html = "".join(_src_card(i, s) for i, s in enumerate(sources, 1)) or \
        "<p>No passage of 8+ identical words was found in any compared source.</p>"

    unv = ""
    if r["phrase_only"]:
        unv = ("<h2 class='cat'>Phrase matches only (not verified)</h2>"
               "<p class='note'>The search engines report that these works contain "
               "at least one searched phrase, but their full text could not be "
               "downloaded (paywall, blocked download or the per-run limit), so "
               "the overlap is not verified and not counted in the score. Search "
               "engines may also match loosely (stemming, stop words). Open them "
               "and look manually, or add the PDF via the literature folder.</p>"
               f"<ul>{''.join(_work_li(w) for w in r['phrase_only'][:40])}</ul>")
    if r["compared_no_match"]:
        unv += ("<details><summary>"
                f"{len(r['compared_no_match'])} candidate(s) compared in full "
                "without a match of 8+ identical words</summary>"
                "<p class='note'>A search engine reported a phrase hit, but the "
                "full text does not share a verbatim run with the manuscript "
                "(loose search matching or a different version of the text).</p>"
                f"<ul>{''.join(_work_li(w) for w in r['compared_no_match'])}</ul>"
                "</details>")

    ls = r.get("lib_stats")
    if ls:
        r["notes"] = list(r["notes"]) + [
            f"Library folder {ls['dir']}: {ls['files']} files scanned, "
            f"{ls['matched']} with matching passages, {ls['unreadable']} "
            "without extractable text (e.g. scanned PDFs)."]
    notes = "".join(f"<p class='note'>{_e(n)}</p>" for n in r["notes"])
    method = (
        "<div class='module info'><h3>How this check works</h3>"
        "<p>No commercial database or licence is used. (1) Distinctive "
        "9-word phrases (one per ~60 words, at least one per paragraph) were "
        "searched as exact phrases in open "
        "full texts (Europe PMC open-access articles and preprints, OpenAlex, "
        "Wikipedia). (2) The open full text of the best candidates, plus any "
        "local files you added, was compared with the whole manuscript using "
        "6-word shingles; matches of 8+ consecutive words are reported. Before "
        "comparing, formatting differences are removed (ligatures, line-end "
        "hyphenation, hyphens, accents, British/American spelling). Quoted "
        "passages and (Author, year) citations are excluded; the reference "
        "list is not scored. Versions of this manuscript (same DOI, same "
        "title, or shared authors with a similar title) are ignored; sources "
        "sharing an author are labelled as possible own prior work.</p>"
        + ("<p><b>Privacy:</b> the searched 9-word excerpts of the manuscript "
           "were sent to the search services named above; nothing else left "
           "this computer.</p>" if r["n_phrases"] else
           "<p><b>Privacy:</b> no online search was run; nothing left this "
           "computer.</p>") +
        "<p><b>Limits:</b> only <b>verbatim</b> overlap is detected - reworded "
        "or AI-paraphrased text is out of scope. Paywalled publisher content, "
        "theses, books and most websites are not searched. A green result "
        "therefore means no overlap was found in the searched sources, not "
        "that the text is original. High overlap with a cited source or with "
        "the authors' own earlier work is often legitimate (methods text of a "
        "direct replication, for instance). The score is a pointer for a "
        "human to inspect, not a verdict.</p></div>")

    ms = _manuscript_html(doc, sources)
    coverage = _coverage_html(info)
    phr = _phrases_html(doc, info)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Plagiarism Check - {_e(r['title'])}</title>
<style>{_CSS}{_EXTRA_CSS}</style></head>
<body>
<header><div class="header-left"><img class="logo" src="{sticker_uri('plagcheck_logo_small.png', LOGO_MUCOS)}" alt="">
<div><h1>Plagiarism Check</h1>
<p class="sub">{_e(r['title'])} &middot; {now}</p></div></div></header>
<div class="layout"><div class="content">
<div class="banner">Not affiliated with metacheck or any commercial plagiarism
service. Overall: <b>{LABEL.get(tl, tl)}</b> &mdash; {_e(r['summary_text'])}</div>
<div class="cards">{cards}</div>
{method}{coverage}{notes}
<h2 class="cat">Sources with verified overlap</h2>{src_html}{unv}
<h2 class="cat">Manuscript with matches highlighted</h2>
<div class="ms">{ms}</div>
<h2 class="cat">Manuscript with all searched phrases highlighted</h2>
<p class="note"><mark style="background:#ff9800;color:#111">&nbsp;this run&nbsp;</mark>
&nbsp;<mark style="background:#90a4ae;color:#111">&nbsp;earlier runs&nbsp;</mark>
&nbsp;Everything not highlighted was not searched online.</p>
<div class="ms">{phr}</div>
</div></div>
<script>
(function(){{ var r=document.documentElement;
 if(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches)
   r.dataset.theme='dark'; }})();
</script></body></html>"""

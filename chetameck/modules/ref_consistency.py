"""Check that all references are cited and all citations are referenced.

This reimplements metacheck's ``ref_consistency`` but uses short-form in-text
citations (APA / CSL / Chicago style, e.g. ``Smith et al., 2020``,
``(Jones & Lee, 2018)``) rather than relying only on GROBID's cross-reference
links, which are often missing or unreliable. It also uses GROBID's ``<ref>``
cross-references (type ``bibr``) when available.

The report shows one row per reference with an "In-text citation(s)" column and
a "Reference in reference list" column. A cell is highlighted red when the
corresponding citation or reference is missing.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search


def _surnames(authors):
    """Extract lowercase author surnames from a 'Surname, Given; ...' string."""
    if not authors:
        return []
    out = []
    for part in str(authors).split(";"):
        part = part.strip()
        if not part:
            continue
        surname = part.split(",")[0].strip()
        surname = re.sub(r"\s+[A-Z]\.?$", "", surname).strip()
        surname = re.sub(r"\s+et al\.?$", "", surname, flags=re.I).strip()
        if surname:
            out.append(surname.lower())
    return out


def _ref_pattern(surnames, year):
    """Build a regex matching the short-form citation for a reference."""
    if not surnames or year is None:
        return None
    first = re.escape(surnames[0])
    rest = ""
    if len(surnames) > 1:
        # "et al.", "and Smith", "& Smith"
        rest = r"(?:\s+et\s+al\.?|\s+(?:and|&)\s*[A-Za-z'\-]+)?"
    return re.compile(
        r"\b" + first + rest + r"\s*[,(]?\s*" + str(year) + r"\b",
        re.I)


def _in_text_citations(paper, surnames, year):
    """Return the short-form citation strings found in the main text."""
    pat = _ref_pattern(surnames, year)
    if pat is None:
        return []
    out = []
    for _, r in text_search(paper, ".", include_refs=False).iterrows():
        for m in pat.finditer(str(r["text"])):
            out.append(m.group(0).strip())
    return list(dict.fromkeys(out))


def _ref_table(paper):
    """Join bib + text to get reference text per bib_id."""
    bib = paper.table("bib")
    text = paper.table("text")
    if bib.empty or text.empty:
        return pd.DataFrame(columns=["paper_id", "bib_id", "reference"])
    bib = bib.copy()
    bib["paper_id"] = paper.paper_id
    merged = bib.merge(text[["text_id", "text"]], on="text_id", how="left")
    merged["reference"] = merged["text"]
    return merged[["paper_id", "bib_id", "reference"]]


def _xref_citations(paper):
    """Map bib_id -> list of in-text citation strings from GROBID <ref> xrefs."""
    xrefs = paper.table("xref")
    out = {}
    if xrefs.empty:
        return out
    bx = xrefs[xrefs["xref_type"].isin(["bibr", "bib"])][["xref_id", "contents"]]
    for _, r in bx.iterrows():
        bid = r["xref_id"]
        if bid is None:
            continue
        out.setdefault(bid, []).append(str(r["contents"]).strip())
    return out


def _all_author_year_citations(paper):
    """Collect every author-year citation in the main text, returning
    (surnames_list, year) tuples."""
    cite_pat = re.compile(
        r"(?:(?:\(|^)\s*)?"
        r"((?:[A-Z][A-Za-z'\-]+)(?:\s*(?:,\s*[A-Z][A-Za-z'\-]+)*)?"
        r"(?:\s+et\s+al\.?|\s*(?:and|&)\s*[A-Z][A-Za-z'\-]+)?)"
        r"\s*[,(]?\s*\(?(\d{4})\)?", re.I)
    out = []
    for _, r in text_search(paper, r"\d{4}", include_refs=False).iterrows():
        text = str(r["text"])
        for m in cite_pat.finditer(text):
            names_part = m.group(1)
            year = int(m.group(2))
            names = [n.strip().lower() for n in
                     re.split(r",| and | & | et al\.", names_part) if n.strip()]
            names = [re.sub(r"[^a-z'\-]", "", n) for n in names]
            names = [n for n in names if n]
            if names:
                out.append((names, year))
    return out


@register("ref_consistency")
def ref_consistency(paper, prev_outputs=None):
    bibs = _ref_table(paper)
    if bibs.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="No bibliography entries were detected",
            report=["No bibliography entries were detected."],
            na_replace=0)

    xref_cit = _xref_citations(paper)

    # Build per-reference info: surnames, year, short-form citations, xref citations
    bib_info = []
    for _, r in bibs.iterrows():
        bid = r["bib_id"]
        names = _surnames(_authors_for_bib(paper, bid))
        year = _year_for_bib(paper, bid)
        short = _in_text_citations(paper, names, year) if names else []
        xrefs = xref_cit.get(bid, [])
        combined = list(dict.fromkeys(short + xrefs))
        bib_info.append({
            "bib_id": bid,
            "reference": r["reference"],
            "surnames": names,
            "year": year,
            "in_text": combined,
        })

    # References not cited anywhere.
    uncited = [b for b in bib_info if not b["in_text"]]
    n_bib = len(bib_info)
    n_uncited = len(uncited)
    n_cited = n_bib - n_uncited

    # Orphan in-text citations: author-year citations with no matching reference.
    all_cites = _all_author_year_citations(paper)
    orphans = []
    for names, year in all_cites:
        matched = False
        for b in bib_info:
            if b["year"] == year and set(names) & set(b["surnames"]):
                matched = True
                break
        if not matched:
            cite_str = ", ".join(n.title() for n in names[:2])
            if len(names) > 2:
                cite_str = f"{names[0].title()} et al."
            orphans.append(f"{cite_str} ({year})")
    orphans = list(dict.fromkeys(orphans))
    n_orphan = len(orphans)

    # Build the report table.
    rows = []
    for b in bib_info:
        in_text = ", ".join(b["in_text"]) if b["in_text"] else "{r}Not cited{/}"
        rows.append({
            "reference": b["reference"],
            "in_text": in_text,
        })
    for o in orphans:
        rows.append({
            "reference": "{r}No matching reference{/}",
            "in_text": o,
        })

    table = pd.DataFrame(rows)
    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "n_bib": [n_bib],
        "n_cited": [n_cited],
        "n_uncited": [n_uncited],
        "n_orphan": [n_orphan],
    })

    if n_uncited or n_orphan:
        tl = "red"
        summary_text = (f"{n_bib} reference{'s' if n_bib != 1 else ''}; "
                        f"{n_cited} cited, {n_uncited} not cited"
                        + (f", {n_orphan} orphan citation{'s' if n_orphan != 1 else ''}"
                           if n_orphan else ""))
        report = [
            "There are references in the bibliography that are not cited in the "
            "text, and/or in-text citations without a matching bibliography entry.",
            md_table(table, ["reference", "in_text"],
                     ["Reference in reference list", "In-text citation(s)"]),
        ]
    else:
        tl = "green"
        summary_text = (f"All {n_bib} reference{'s' if n_bib != 1 else ''} "
                        f"are cited in the text.")
        report = [summary_text]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _authors_for_bib(paper, bib_id):
    bib = paper.table("bib")
    if bib.empty:
        return ""
    row = bib[bib["bib_id"] == bib_id]
    if row.empty:
        return ""
    return row.iloc[0].get("authors", "")


def _year_for_bib(paper, bib_id):
    bib = paper.table("bib")
    if bib.empty:
        return None
    row = bib[bib["bib_id"] == bib_id]
    if row.empty:
        return None
    y = row.iloc[0].get("year")
    if y is None or pd.isna(y):
        return None
    return int(y)

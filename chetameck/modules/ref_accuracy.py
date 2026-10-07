"""Check reference metadata accuracy against CrossRef.

This module queries the CrossRef API for each reference DOI and compares the
parsed title/year/authors against the crossref record, flagging mismatches.
"""

import re

import requests

import pandas as pd

from .registry import register, module_output, md_table
from ._refs import refs_with_doi


def _crossref(doi, timeout=20):
    try:
        r = requests.get(f"https://api.crossref.org/works/{doi}",
                         timeout=timeout,
                         headers={"User-Agent": "ChetaMeck/0.2 (metacheck app)"})
        if r.status_code != 200:
            return None
        return r.json().get("message", {})
    except Exception:  # noqa: BLE001
        return None


def _clean(s):
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    s = re.sub(r"[-â€“â€”]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    s = s.rstrip(".")
    return s


@register("ref_accuracy")
def ref_accuracy(paper, prev_outputs=None):
    bib = refs_with_doi(paper)
    if bib.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No references with DOIs found.",
                             report=["No references with DOIs found."], na_replace=0)

    rows = []
    for _, r in bib.iterrows():
        doi = r["doi"]
        rec = _crossref(doi)
        row = {"paper_id": paper.paper_id, "bib_id": r["bib_id"], "doi": doi,
               "text": r.get("text", ""),
               "year_orig": _ref_year(r.get("text", "")),
               "title_orig": "", "doi_mismatch": False, "year_mismatch": False,
               "title_mismatch": False, "author_mismatch": False,
               "no_match": rec is None}
        if rec:
            row["year_match"] = _rec_year(rec)
            row["title_match"] = rec.get("title", [""])[0]
            row["title_mismatch"] = _title_mismatch(
                _clean(_ref_title(r.get("text", ""))), _clean(row["title_match"]))
            row["year_mismatch"] = (row["year_orig"] is not None and
                                    row["year_match"] is not None and
                                    row["year_orig"] != row["year_match"])
            row["author_match"] = _rec_authors(rec)
            row["author_mismatch"] = _author_mismatch(
                _ref_authors(r.get("text", "")), row["author_match"])
        rows.append(row)

    table = pd.DataFrame(rows)
    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "refs_checked": [len(table)],
        "no_match": [int(table["no_match"].sum())],
        "doi_mismatch": [int(table["doi_mismatch"].sum())],
        "year_mismatch": [int(table["year_mismatch"].sum())],
        "title_mismatch": [int(table["title_mismatch"].sum())],
        "author_mismatch": [int(table["author_mismatch"].sum())],
    })
    issues = (table["no_match"].any() or table["doi_mismatch"].any() or
              table["year_mismatch"].any() or table["title_mismatch"].any() or
              table["author_mismatch"].any())
    tl = "yellow" if issues else "green"
    if issues:
        report = ["Some reference metadata did not match the CrossRef record. "
                  "Verify these references."]
        report.append(_accuracy_table(table))
        summary_text = "Some references may contain inaccuracies."
    else:
        report = ["All reference metadata matched the CrossRef records.",
                  _accuracy_table(table)]
        summary_text = "Reference metadata appears accurate."
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _mark(v, ok):
    return (f"{{g}}{v}{{/}}" if ok else f"{{r}}{v}{{/}}")


def _fmt_year(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "?"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def _accuracy_table(table):
    """Build a markdown table with green/red cells for match / mismatch."""
    rows = []
    for _, r in table.iterrows():
        no_match = bool(r.get("no_match"))
        if no_match:
            doi = _mark(str(r.get("doi", "")), False)
            year = _mark("?", False)
            cr_year = _mark("?", False)
            title = _mark("no match", False)
            author = _mark("no match", False)
        else:
            doi = _mark(str(r.get("doi", "")), True)
            yo = r.get("year_orig")
            ym = r.get("year_match")
            yok = not bool(r.get("year_mismatch"))
            year = _mark(_fmt_year(yo), yok)
            cr_year = _mark(_fmt_year(ym), yok)
            tok = not bool(r.get("title_mismatch"))
            title = _mark("✓" if tok else "✗", tok)
            aok = not bool(r.get("author_mismatch"))
            author = _mark("✓" if aok else "✗", aok)
        rows.append({
            "doi": doi, "year": year, "cr_year": cr_year,
            "title": title, "author": author,
        })
    df = pd.DataFrame(rows)
    return md_table(df, ["doi", "year", "cr_year", "title", "author"],
                    ["DOI", "Reference year", "CrossRef year", "Title", "Author"])


def _ref_year(text):
    m = re.search(r"\b(19|20)\d{2}\b", str(text or ""))
    return int(m.group(0)) if m else None


def _rec_year(rec):
    for k in ("published-print", "published-online", "issued", "created"):
        if k in rec and rec[k].get("date-parts"):
            dp = rec[k]["date-parts"][0]
            if dp and dp[0]:
                return int(dp[0])
    return None


def _ref_title(text):
    return str(text or "")


def _title_mismatch(a, b):
    if not a or not b:
        return False
    if a == b:
        return False
    # if one is a prefix of the other (unparsed title), treat as match
    if a.startswith(b) or b.startswith(a):
        return False
    return True


def _rec_authors(rec):
    out = []
    for a in rec.get("author", []):
        fam = a.get("family", "")
        if fam:
            out.append(fam.lower())
    return out


def _ref_authors(text):
    # crude last-name extraction from a reference string
    names = re.findall(r"([A-Z][A-Za-z'\-]+),?\s+[A-Z]\.?", str(text or ""))
    return [n.lower() for n in names]


def _author_mismatch(orig, match):
    if not match:
        return False
    if not orig:
        return False
    return not all(any(m in o for o in orig) for m in match)


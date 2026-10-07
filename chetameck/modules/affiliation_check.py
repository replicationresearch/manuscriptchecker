"""Cross-check funding/COI statements against author affiliations.

A common editorial red flag is an author affiliated with a company, institute
or foundation that also appears as the funder, without that overlap being
called out in the conflict-of-interest statement. This module compares each
author's affiliation string against the text of the detected funding
statement (from ``funding_check``) and conflict-of-interest statement (from
``coi_check``, both run earlier in the pipeline and read here via
``prev_outputs``) and flags affiliations that show up in the funding text but
are not echoed anywhere in the COI text.

Purely textual keyword matching - it will miss paraphrased overlaps and can
false-flag generic institution names, so treat flags as "worth a human look",
not a finding of misconduct.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table

# Words too generic to treat as a meaningful affiliation match on their own.
_STOPWORDS = {
    "university", "of", "the", "department", "institute", "hospital",
    "school", "college", "center", "centre", "faculty", "and", "for",
    "medical", "national", "laboratory", "research", "group", "inc",
    "ltd", "gmbh", "corporation", "company", "science", "sciences",
}


def _keywords(affiliation):
    words = re.findall(r"[A-Za-z]{3,}", str(affiliation or ""))
    return {w.lower() for w in words if w.lower() not in _STOPWORDS}


def _joined_text(output):
    table = output.get("table") if isinstance(output, dict) else None
    if table is None or table.empty or "text" not in table.columns:
        return ""
    return " ".join(str(t) for t in table["text"]).lower()


@register("funding_coi_affiliation_check")
def funding_coi_affiliation_check(paper, prev_outputs=None):
    authors = paper.table("author")
    prev = prev_outputs or {}

    if authors.empty or "affiliation" not in authors.columns:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No author affiliations found.",
            report=["No author affiliation data was extracted from this manuscript."],
            na_replace=0)

    affiliations = [a for a in authors["affiliation"].astype(str) if a.strip()]
    if not affiliations:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No author affiliations found.",
            report=["No author affiliation text was extracted from this manuscript."],
            na_replace=0)

    funding_text = _joined_text(prev.get("funding_check", {}))
    coi_text = _joined_text(prev.get("coi_check", {}))

    if not funding_text:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="No funding statement to cross-check against affiliations.",
            report=["No funding statement was detected (see the Funding check), "
                    "so there is nothing to cross-check against author "
                    "affiliations."], na_replace=0)

    rows = []
    for aff in dict.fromkeys(affiliations):  # de-duplicate, keep first-seen order
        kws = _keywords(aff)
        if not kws or not any(kw in funding_text for kw in kws):
            continue
        in_coi = any(kw in coi_text for kw in kws)
        rows.append({
            "affiliation": aff,
            "mentioned_in_coi": in_coi,
            "flag": "{g}disclosed in COI{/}" if in_coi else "{r}not disclosed in COI{/}",
        })

    table = pd.DataFrame(rows)
    n_flag = int((~table["mentioned_in_coi"]).sum()) if not table.empty else 0
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "affiliation_funding_overlap": [len(table)],
                            "undisclosed_overlap": [n_flag]})

    if table.empty:
        return module_output(
            table=table, summary_table=summary, traffic_light="green",
            summary_text="No author-affiliation/funder overlap detected.",
            report=["No author affiliation appears to overlap with the detected "
                    "funding statement."], na_replace=0)

    tl = "red" if n_flag else "yellow"
    report = [
        "The following author affiliation(s) overlap with the funding statement:",
        md_table(table, ["affiliation", "flag"], ["Affiliation", "COI disclosure"]),
    ]
    if n_flag:
        report.append(f"**{n_flag}** overlapping affiliation(s) are not echoed in "
                      "the conflict-of-interest statement - verify this isn't an "
                      "undisclosed institutional/financial conflict.")
    summary_text = (f"{n_flag} author-affiliation/funder overlap(s) not disclosed "
                    "in COI." if n_flag else
                    f"{len(table)} author-affiliation/funder overlap(s), all "
                    "disclosed in COI.")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

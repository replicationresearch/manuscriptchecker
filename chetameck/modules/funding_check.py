"""Detect funding statements.

This mirrors the metacheck ``funding_check`` over-inclusive strategy: find
sentences that combine a funding/funder word with a study/work word, and prefer
those in likely funding/acknowledgment sections when such sections exist.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

FUND_PATTERN = r"\bfunder|funded|funding|financ\w*|supported by|grant\b|sponsor\w*|acknowledg\w*"
STUDY_PATTERN = (r"\bwork\b|\bstudy\b|\bstudies\b|\bresearch\b|\bmanuscript\b"
                 r"|\bproject\b|\bpaper\b|\barticle\b|\bauthor\b|\bthank\b")


@register("funding_check")
def funding_check(paper, prev_outputs=None):
    # Search the whole text for likely funding sentences.
    hits = text_search(paper, FUND_PATTERN)
    if hits.empty:
        table = hits
        found = False
    else:
        mask = hits["text"].astype(str).map(
            lambda s: bool(re.search(STUDY_PATTERN, s, re.I)))
        hits = hits[mask].copy()
        # exclude explicit "no funding" statements
        neg = hits["text"].astype(str).str.contains(
            r"\b(?:no|without|not)\s+(?:fund|support|grant)", re.I)
        hits = hits[~neg]
        table = hits
        found = len(table) > 0

    summary = (pd.DataFrame({"paper_id": [paper.paper_id],
                             "funding_found": [found]})
               if not found else
               table.groupby("paper_id", dropna=False).size().reset_index(
                   name="funding_found"))
    if found:
        summary["funding_found"] = True

    tl = "green" if found else "red"
    if found:
        report = ["The following funding statement was detected:",
                  md_table(table, ["text", "section_type"], ["Statement", "Section"])]
        summary_text = "A funding statement was detected."
    else:
        report = ["No funding statement was detected. Consider adding one."]
        summary_text = "No funding statement was detected."
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=False)


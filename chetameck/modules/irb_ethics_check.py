"""Detect an ethics approval / IRB statement.

Same pattern as ``coi_check``/``funding_check``: search for an ethics
approval, institutional review board (IRB), ethics committee, or informed
consent statement, and flag when none is found.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

ETHICS_PATTERN = (
    r"\b(?:institutional review board|\bIRB\b|ethics committee|ethics "
    r"approval|ethical approval|approved by the .{0,40} ethics|"
    r"declaration of helsinki|informed consent was obtained|"
    r"written informed consent)"
)


@register("irb_ethics_check")
def irb_ethics_check(paper, prev_outputs=None):
    hits = text_search(paper, ETHICS_PATTERN)
    found = not hits.empty

    summary = pd.DataFrame({"paper_id": [paper.paper_id], "ethics_found": [found]})
    if found:
        table = hits[["text", "section_type"]].copy() if \
            "section_type" in hits.columns else hits[["text"]].copy()
        tl = "green"
        report = ["The following ethics/IRB statement(s) were detected:",
                  md_table(table, list(table.columns),
                          ["Statement", "Section"][:len(table.columns)])]
        summary_text = "An ethics/IRB statement was detected."
    else:
        table = pd.DataFrame()
        tl = "red"
        report = ["No ethics approval / IRB / informed consent statement was "
                  "detected. Consider adding one (or noting that ethics "
                  "approval was not required and why)."]
        summary_text = "No ethics/IRB statement was detected."
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=False)

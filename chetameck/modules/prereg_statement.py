"""Find sentences that mention preregistration / being registered.

This surfaces the exact wording and its source so an editor can judge whether
the study was actually preregistered (and not merely described as such).
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

# Words indicating a preregistration claim. "registered" is broad but included
# on purpose so editors see where the manuscript says the study was registered.
PATTERN = (r"\b(registered|pre-?registered|preregistered|"
           r"pre-?registration|preregistration)\b")


@register("prereg_statement")
def prereg_statement(paper, prev_outputs=None):
    hits = text_search(paper, PATTERN)
    if hits.empty:
        summary = pd.DataFrame({"paper_id": [paper.paper_id],
                                "prereg_mentions": [0]})
        return module_output(table=hits, summary_table=summary,
                             traffic_light="na",
                             summary_text="No preregistration mentions found.",
                             report=["No sentence mentioning 'registered', "
                                     "'pre-registered', 'preregistered' or "
                                     "'preregistration' was found."],
                             na_replace=0)

    # drop duplicate sentences and keep the source
    hits = hits.drop_duplicates(subset=["text"]).reset_index(drop=True)
    cols = [c for c in ("text", "section_type", "header") if c in hits.columns]
    table = hits[cols].copy()
    n = len(table)

    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "prereg_mentions": [n]})
    tl = "info"
    if n == 1:
        summary_text = "1 sentence mentions preregistration."
    else:
        summary_text = f"{n} sentences mention preregistration."
    report = ["Sentences that mention preregistration or that the study was "
              "registered:",
              md_table(table, ["text", "section_type", "header"],
                       ["Sentence", "Source section", "Section header"])]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)

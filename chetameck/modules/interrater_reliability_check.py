"""Check whether coded/rated data reports an inter-rater reliability statistic.

Detects coding/rating-procedure wording ("coded by", "independent raters",
"content analysis") and checks whether an inter-rater reliability statistic
(Cohen's kappa, ICC, percent agreement) is reported anywhere in the text.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

CODING_PATTERN = (
    r"\b(?:coded by|independent(?:ly)? (?:coded|rated)|two raters|"
    r"\bcoders?\b|\braters?\b|content analysis)"
)
RELIABILITY_PATTERN = (
    r"Cohen.{0,3}s?\s*kappa|\bkappa\s*=|κ\s*=|intraclass correlation|"
    r"\bICC\s*=|percent(?:age)? agreement|inter-?rater (?:reliabilit|"
    r"agreement)|inter-?coder (?:reliabilit|agreement)"
)


@register("interrater_reliability_check")
def interrater_reliability_check(paper, prev_outputs=None):
    coding = text_search(paper, CODING_PATTERN)
    if coding.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No coding/rating procedure mentioned.",
            report=["No coding, rating, or content-analysis procedure was "
                    "mentioned in the text."], na_replace=0)

    reliability = text_search(paper, RELIABILITY_PATTERN)
    has_reliability = not reliability.empty
    n_coding = len(coding)
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "coding_mentions": [n_coding],
                            "reliability_reported": [has_reliability]})

    if has_reliability:
        table = reliability[["text", "section_type"]].copy() if \
            "section_type" in reliability.columns else reliability[["text"]].copy()
        tl = "green"
        report = ["An inter-rater/inter-coder reliability statistic was found "
                  "for the coding procedure described:",
                  md_table(table, list(table.columns),
                          ["Statement", "Section"][:len(table.columns)])]
        summary_text = "Coding procedure with a reliability statistic reported."
    else:
        table = coding[["text", "section_type"]].copy() if \
            "section_type" in coding.columns else coding[["text"]].copy()
        tl = "yellow"
        report = [f"{n_coding} coding/rating mention(s) found, but no "
                  "inter-rater reliability statistic (Cohen's kappa, ICC, "
                  "percent agreement, ...) was found anywhere:",
                  md_table(table, list(table.columns),
                          ["Statement", "Section"][:len(table.columns)])]
        summary_text = "Coding procedure mentioned, but no reliability statistic reported."
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

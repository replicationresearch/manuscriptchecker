"""Check whether reported scales/questionnaires have a reliability coefficient.

Searches for scale/questionnaire mentions and for reliability-coefficient
statements (Cronbach's alpha, McDonald's omega, ICC, test-retest reliability).
Flags when scales are used but no reliability coefficient is reported
anywhere in the text - a standard psychometric reporting expectation in
survey-based social-science research.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

SCALE_PATTERN = (
    r"\b(?:scale|questionnaire|inventory|subscale)\b"
)
RELIABILITY_PATTERN = (
    r"Cronbach|McDonald.{0,3}s?\s*(?:omega|ω)|\bω\s*=|\bα\s*=|"
    r"internal consistency|test-retest reliabilit|inter-item|split-half "
    r"reliabilit|\bICC\s*=|intraclass correlation"
)


@register("reliability_check")
def reliability_check(paper, prev_outputs=None):
    scales = text_search(paper, SCALE_PATTERN)
    if scales.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No scales/questionnaires mentioned.",
            report=["No scale, questionnaire, inventory or subscale was "
                    "mentioned in the text."], na_replace=0)

    reliability = text_search(paper, RELIABILITY_PATTERN)
    n_scale_mentions = len(scales)
    n_reliability = len(reliability)

    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "scale_mentions": [n_scale_mentions],
                            "reliability_statements": [n_reliability]})

    if n_reliability:
        table = reliability[["text", "section_type"]].copy() if \
            "section_type" in reliability.columns else reliability[["text"]].copy()
        tl = "green"
        report = [f"{n_reliability} reliability statement(s) found for the "
                  f"scale(s)/questionnaire(s) mentioned ({n_scale_mentions} "
                  "scale mention(s) in total):",
                  md_table(table, list(table.columns),
                          ["Statement", "Section"][:len(table.columns)])]
        summary_text = f"{n_reliability} reliability coefficient(s) reported."
    else:
        table = scales[["text", "section_type"]].copy() if \
            "section_type" in scales.columns else scales[["text"]].copy()
        tl = "yellow"
        report = [f"{n_scale_mentions} scale/questionnaire mention(s) found, "
                  "but no reliability coefficient (Cronbach's alpha, "
                  "McDonald's omega, ICC, test-retest, ...) was found "
                  "anywhere in the text. Consider reporting one:",
                  md_table(table, list(table.columns),
                          ["Statement", "Section"][:len(table.columns)])]
        summary_text = "Scale(s) mentioned, but no reliability coefficient reported."
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

"""Check survey-methodology reporting: response rate and panel quality controls.

For survey-based studies, checks (a) whether a response rate is reported, and
(b) when an online panel service (MTurk, Prolific, CloudResearch, a Qualtrics
panel, ...) is mentioned, whether a data-quality control (attention checks,
bot/duplicate detection) is also mentioned.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

SURVEY_PATTERN = r"\bsurvey\b|\bquestionnaire\b(?! items)"
RESPONSE_RATE_PATTERN = (
    r"response rate|\d{1,3}(?:\.\d+)?\s*%\s*(?:of (?:invitees|those "
    r"invited)|response rate|completed the survey)"
)
PANEL_PATTERN = (
    r"\bMTurk\b|Mechanical Turk|\bProlific\b|CloudResearch|Qualtrics panel|"
    r"online panel|survey panel"
)
QUALITY_CONTROL_PATTERN = (
    r"attention check|catch trial|instructional manipulation check|"
    r"\bIMC\b|bot detection|duplicate (?:IP|response)|CAPTCHA|screening "
    r"question"
)


@register("response_rate_check")
def response_rate_check(paper, prev_outputs=None):
    survey = text_search(paper, SURVEY_PATTERN)
    panel = text_search(paper, PANEL_PATTERN)
    if survey.empty and panel.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="No survey or online panel mentioned.",
            report=["No survey or online-panel data collection was mentioned "
                    "in the text."], na_replace=0)

    rows = []
    if not survey.empty:
        rr = text_search(paper, RESPONSE_RATE_PATTERN)
        rows.append({"check": "Response rate reported",
                     "result": "{g}yes{/}" if not rr.empty else "{y}no{/}"})
    if not panel.empty:
        qc = text_search(paper, QUALITY_CONTROL_PATTERN)
        rows.append({"check": "Panel data-quality control mentioned",
                     "result": "{g}yes{/}" if not qc.empty else "{y}no{/}"})

    table = pd.DataFrame(rows)
    n_missing = int((table["result"] == "{y}no{/}").sum())
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "survey_checks": [len(table)],
                            "survey_checks_missing": [n_missing]})

    tl = "green" if n_missing == 0 else "yellow"
    report = ["Survey-methodology reporting:",
              md_table(table, ["check", "result"], ["Check", "Reported?"])]
    if n_missing:
        report.append(f"**{n_missing}** item(s) above were not found - "
                      "consider reporting them for readers to judge sample "
                      "quality.")
    summary_text = (f"All {len(table)} survey-methodology item(s) reported."
                    if n_missing == 0 else
                    f"{n_missing} of {len(table)} survey-methodology item(s) not found.")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

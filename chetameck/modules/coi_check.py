"""Detect conflict-of-interest (COI) statements.

This is a Python reimplementation of the metacheck ``coi_check`` module, which
itself is adapted from the ``rtransparent`` package. Rather than grabbing the
first mention of "conflict of interest", it searches every sentence for the
relevant phrases and applies the same exclusion heuristics (financial
disclosure, patient/other disclosures, and non-COI mentions of "interest") so
that the actual COI statement(s) are returned.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

# The phrases that can start a COI statement. "disclosure" is only accepted
# when it refers to interests (see _is_coi).
PHRASES = {
    "conflict": r"conflict[s]? of interest",
    "competing": r"competing interest[s]?",
    "fin": r"competing financial interest",
    "declaration": r"declaration of interest",
    "duality": r"duality of interest",
    "disclosure": r"disclosure",
}
CANDIDATE = ("conflict[s]? of interest|competing interest[s]?|"
             "competing financial interest|declaration of interest|"
             "duality of interest|disclosure")

REPORT_VERBS = (r"disclosed|reported|mentioned|declared|communicated|"
                r"revealed|divulged|aired|voiced|expressed")


def _is_coi(sentence):
    s = str(sentence)
    matches = [k for k, p in PHRASES.items() if re.search(p, s, re.I)]
    if not matches:
        return False
    # A bare "financial disclosure" is not a COI statement.
    if matches == ["disclosure"] and re.search(r"financial disclosure", s, re.I):
        return False
    # Explicit COI phrasings are always COI.
    if any(k in matches for k in ("fin", "declaration", "duality")):
        return True
    conflict = [k for k in matches if k in ("conflict", "competing")]
    if conflict:
        capital = bool(re.search(r"Conflict|CONFLICT|Compet|COMPET", s))
        no_conflict = bool(re.search(r"no.{0,20}(conflict|competing)", s, re.I))
        author = bool(re.search(r"author", s, re.I))
        punct = bool(re.search(r"interest[s]?[.:;,]", s, re.I))
        report = bool(re.search(REPORT_VERBS, s, re.I))
        # Keep only if it looks like a real COI statement (matches the
        # rtransparent heuristic).
        if not (capital or no_conflict or punct or report or author):
            return False
        return True
    if "disclosure" in matches:
        capital = bool(re.search(r"Disclos|DISCLOS", s))
        neg = bool(re.search(r"None|Nothing|No|Nil|NONE|NOTHING|NO|NIL", s))
        author = bool(re.search(r"Author.{0,2} [dD]isclo", s))
        # A disclosure is only COI if it is about interests, or is a "Disclosure:"
        # heading, or a negation. This avoids flagging patient/data/information
        # disclosures.
        about_interest = bool(re.search(r"\binterests?\b", s, re.I))
        if not (about_interest or capital or neg or author):
            return False
        return True
    return False


@register("coi_check")
def coi_check(paper, prev_outputs=None):
    cands = text_search(paper, CANDIDATE)
    if cands.empty:
        table = cands
        found = False
    else:
        mask = cands["text"].astype(str).map(_is_coi)
        table = cands[mask].reset_index(drop=True)
        found = len(table) > 0

    if found:
        tl = "green"
        cols = [c for c in ("text", "section_type", "header")
                if c in table.columns]
        report = ["The following conflict-of-interest statement(s) were "
                  "detected:",
                  md_table(table, cols, ["Statement", "Source section",
                                         "Section header"])]
        summary_text = "A conflict-of-interest statement was detected."
    else:
        tl = "red"
        report = ["No conflict-of-interest statement was detected. Consider "
                  "adding one."]
        summary_text = "No conflict-of-interest statement was detected."

    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "coi_found": [found],
    })
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=False)

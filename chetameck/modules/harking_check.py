"""Heuristic HARKing (Hypothesizing After Results are Known) check.

Looks for confirmatory-sounding phrasing in the Results/Discussion ("as
predicted", "as expected", "consistent with our hypothesis") and checks
whether the manuscript has a preregistration (from ``prereg_check``, run
earlier in the pipeline). Confirmatory language with no preregistration is
not proof of HARKing - it's simply not verifiable from the text alone - but
it is worth an editor's attention.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

CONFIRMATORY_PATTERN = (
    r"\bas (?:predicted|expected|hypothesi[sz]ed)\b|consistent with (?:our|"
    r"the) hypothes|confirm(?:ed|s)? (?:our|the) hypothes|support(?:ed|s)? "
    r"(?:our|the) hypothes|in line with (?:our|the) (?:hypothes|prediction)"
)


@register("harking_check")
def harking_check(paper, prev_outputs=None):
    hits = text_search(paper, CONFIRMATORY_PATTERN)
    if hits.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No confirmatory hypothesis language found.",
            report=["No confirmatory-sounding phrasing ('as predicted', "
                    "'consistent with our hypothesis', ...) was found."],
            na_replace=0)

    prev = prev_outputs or {}
    prereg_ran = "prereg_check" in prev
    prereg = prev.get("prereg_check", {})
    prereg_table = prereg.get("table") if isinstance(prereg, dict) else None
    has_prereg = prereg_table is not None and not prereg_table.empty

    n = len(hits)
    cols = [c for c in ("text", "section_type") if c in hits.columns]
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "confirmatory_statements": [n],
                            "preregistration_found": [has_prereg]})

    if has_prereg:
        tl = "green"
        report = [f"{n} confirmatory-sounding statement(s) found, and a "
                  "preregistration was also detected - the hypotheses are "
                  "plausibly a priori."]
        summary_text = f"{n} confirmatory statement(s); a preregistration was found."
    else:
        tl = "yellow"
        not_run_note = (
            " (the preregistration check itself was not run for this report "
            "- e.g. online checks were disabled - so this may simply be "
            "unverified rather than actually missing)" if not prereg_ran else "")
        report = [
            f"{n} confirmatory-sounding statement{'s' if n != 1 else ''} "
            "found (language implying the hypothesis was stated in advance), "
            f"but no preregistration was detected{not_run_note}. This is not "
            "proof of HARKing - just something worth checking, since a "
            "preregistration could not be verified from the text:",
            md_table(hits, cols, ["Statement", "Section"][:len(cols)]),
        ]
        summary_text = f"{n} confirmatory statement(s) found, no preregistration detected."
    return module_output(table=hits[cols], summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

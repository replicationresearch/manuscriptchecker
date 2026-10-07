"""Check whether participant exclusions are justified.

Searches for "excluded"/"exclusion" sentences and flags the ones that give no
apparent reason (no criterion, cause, or comparison word nearby) - unjustified
post-hoc exclusions are a classic researcher-degrees-of-freedom red flag.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

EXCLUSION_PATTERN = r"\bexclu(?:ded|sion|des)\b"
REASON_PATTERN = (
    r"\bbecause|due to|owing to|as a result of|for failing|failed (?:to|an|"
    r"the)|did not (?:complete|pass|meet)|criteri(?:a|on)|outlier|attention "
    r"check|incomplete|missing data|did not finish|technical (?:error|issue)|"
    r"withdrew|ineligible|pre-?registered"
)


@register("exclusion_reporting_check")
def exclusion_reporting_check(paper, prev_outputs=None):
    hits = text_search(paper, EXCLUSION_PATTERN)
    if hits.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No exclusions mentioned.",
            report=["No participant/case exclusions were mentioned in the text."],
            na_replace=0)

    hits = hits.copy()
    hits["has_reason"] = hits["text"].astype(str).str.contains(
        REASON_PATTERN, case=False, regex=True)
    unjustified = hits[~hits["has_reason"]]
    n_total, n_unjustified = len(hits), len(unjustified)

    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "exclusion_statements": [n_total],
                            "unjustified_exclusions": [n_unjustified]})

    cols = [c for c in ("text", "section_type") if c in hits.columns]
    if n_unjustified == 0:
        tl = "green"
        report = [f"{n_total} exclusion statement(s) found, all with an "
                  "apparent reason/criterion mentioned nearby."]
        summary_text = f"{n_total} exclusion statement(s), all justified."
    else:
        tl = "yellow"
        report = [
            f"{n_unjustified} of {n_total} exclusion statement(s) give no "
            "apparent reason/criterion in the same sentence - worth checking "
            "whether the exclusion criterion was specified (ideally "
            "pre-registered) elsewhere:",
            md_table(unjustified, cols, ["Statement", "Section"][:len(cols)]),
        ]
        summary_text = f"{n_unjustified} of {n_total} exclusion statement(s) lack a stated reason."
    return module_output(table=hits[cols], summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)

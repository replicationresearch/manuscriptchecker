"""Check whether missing-data handling is described.

When the text mentions missing data, attrition, or dropout, checks whether a
handling method (listwise/pairwise deletion, multiple imputation, FIML, mean
imputation) is also described. Says nothing if missing data is never
mentioned at all (that's not itself suspicious - the dataset may simply be
complete).
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

MISSING_PATTERN = (
    r"\bmissing (?:data|values?)\b|\battrition\b|\bdropout\b|\bdrop-out\b|"
    r"did not complete|incomplete responses?"
)
HANDLING_PATTERN = (
    r"listwise deletion|pairwise deletion|multiple imputation|\bFIML\b|full "
    r"information maximum likelihood|mean imputation|\bMICE\b|complete[- ]"
    r"case analysis|expectation[- ]maximi[sz]ation"
)


@register("missing_data_check")
def missing_data_check(paper, prev_outputs=None):
    missing = text_search(paper, MISSING_PATTERN)
    if missing.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No missing-data mention found.",
            report=["Missing data, attrition, or dropout was not mentioned in "
                    "the text (this may simply mean the dataset was complete)."],
            na_replace=0)

    handling = text_search(paper, HANDLING_PATTERN)
    has_handling = not handling.empty
    n = len(missing)
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "missing_data_mentions": [n],
                            "handling_method_found": [has_handling]})
    cols = [c for c in ("text", "section_type") if c in missing.columns]

    if has_handling:
        tl = "green"
        report = [f"Missing data/attrition is mentioned ({n} statement(s)), "
                  "and a handling method (deletion, imputation, FIML, ...) "
                  "is also described."]
        summary_text = "Missing data mentioned, with a handling method reported."
    else:
        tl = "yellow"
        report = [
            f"Missing data/attrition is mentioned ({n} statement(s)), but no "
            "handling method (listwise/pairwise deletion, multiple "
            "imputation, FIML, ...) was found:",
            md_table(missing, cols, ["Statement", "Section"][:len(cols)]),
        ]
        summary_text = "Missing data mentioned, but no handling method reported."
    return module_output(table=missing[cols], summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)

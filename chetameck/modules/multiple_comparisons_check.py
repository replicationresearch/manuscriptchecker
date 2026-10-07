"""Flag many p-values reported with no multiple-comparisons correction mentioned.

Counts the p-values found in the text (reusing the same extraction as
``all_p_values``) and searches for a correction-method mention (Bonferroni,
Holm, FDR/Benjamini-Hochberg, adjusted alpha). If there are many p-values and
no correction is mentioned anywhere, flags it - a common "garden of forking
paths" concern when many tests are run informally.
"""

import pandas as pd

from .registry import register, module_output
from ..text import extract_p_values, text_search

# Fewer tests than this rarely need a formal correction; avoid flagging
# manuscripts with just one or two confirmatory tests.
MIN_P_VALUES_TO_FLAG = 5

CORRECTION_PATTERN = (
    r"\bBonferroni|Holm[- ]Bonferroni|\bHolm\b.{0,10}correct|false discovery "
    r"rate|\bFDR\b|Benjamini[- ]Hochberg|šidák|multiple compar\w* "
    r"(?:correction|adjustment|were corrected)|alpha (?:level )?(?:was )?"
    r"adjusted|corrected (?:for multiple|α)"
)


@register("multiple_comparisons_check")
def multiple_comparisons_check(paper, prev_outputs=None):
    pvals = extract_p_values(paper)
    n = len(pvals)
    if n < MIN_P_VALUES_TO_FLAG:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id], "p_value_n": [n]}),
            traffic_light="na",
            summary_text=f"Only {n} p-value(s) found; correction not expected.",
            report=[f"Only {n} p-value(s) were found in the text - a formal "
                    "multiple-comparisons correction is not usually expected "
                    "at this scale."], na_replace=0)

    correction = text_search(paper, CORRECTION_PATTERN)
    has_correction = not correction.empty
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "p_value_n": [n],
                            "correction_mentioned": [has_correction]})

    if has_correction:
        tl = "green"
        report = [f"{n} p-values were found, and a multiple-comparisons "
                  f"correction is mentioned ({str(correction['text'].iloc[0])[:150]})."]
        summary_text = f"{n} p-values; a correction method is mentioned."
    else:
        tl = "yellow"
        report = [f"{n} p-values were found in the text, but no "
                  "multiple-comparisons correction (Bonferroni, Holm, FDR, "
                  "adjusted alpha, ...) is mentioned anywhere. With this many "
                  "tests, consider whether a correction is warranted or "
                  "explain why one was not applied."]
        summary_text = f"{n} p-values found; no correction method mentioned."
    return module_output(table=pd.DataFrame(), summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)

"""Flag parametric tests on Likert/ordinal data without justification.

Detects Likert-/ordinal-scale wording (e.g. "5-point Likert scale") together
with parametric-test wording (t-test, ANOVA, Pearson correlation), and checks
whether the text anywhere justifies treating the ordinal data as continuous
(a robustness argument, "treated as continuous/interval", non-parametric
comparison reported, etc.). Flags when no such justification is found -
common methodological criticism in survey-based research.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

LIKERT_PATTERN = (
    r"\b\d{1,2}[- ]point (?:Likert|ordinal|rating) scale|\bLikert[- ]"
    r"(?:type )?scale|\bordinal (?:scale|data|variable)"
)
PARAMETRIC_PATTERN = (
    r"\b(?:independent|paired|one-sample) (?:samples? )?t-test|\bANOVA\b|"
    r"analysis of variance|Pearson('s)? (?:r|correlation)|linear regression"
)
JUSTIFICATION_PATTERN = (
    r"treated as (?:continuous|interval)|robust(?:ness)? (?:to|of) "
    r"(?:violations?|ordinal)|non-?parametric|Mann-Whitney|Wilcoxon|"
    r"Kruskal-Wallis|Spearman|ordinal (?:logistic|regression)|as if "
    r"(?:continuous|interval)"
)


@register("likert_parametric_check")
def likert_parametric_check(paper, prev_outputs=None):
    likert = text_search(paper, LIKERT_PATTERN)
    if likert.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No Likert/ordinal scale mentioned.",
            report=["No Likert-type or ordinal scale was mentioned in the text."],
            na_replace=0)

    parametric = text_search(paper, PARAMETRIC_PATTERN)
    if parametric.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="Likert scale mentioned, but no parametric test found.",
            report=["A Likert/ordinal scale was mentioned, but no parametric "
                    "test (t-test, ANOVA, Pearson correlation, linear "
                    "regression) was found, so there is nothing to flag."],
            na_replace=0)

    justification = text_search(paper, JUSTIFICATION_PATTERN)
    has_justification = not justification.empty

    n_parametric = len(parametric)
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "parametric_tests_on_ordinal": [n_parametric],
                            "justification_found": [has_justification]})
    cols = [c for c in ("text", "section_type") if c in parametric.columns]

    if has_justification:
        tl = "green"
        report = ["A Likert/ordinal scale is used with parametric tests, but "
                  "the text also discusses treating it as continuous or "
                  "reports a non-parametric comparison - likely addressed."]
        summary_text = "Likert scale + parametric tests, with justification found."
    else:
        tl = "yellow"
        report = [
            f"A Likert/ordinal scale is used together with {n_parametric} "
            "parametric-test mention(s), but no justification for treating "
            "ordinal data as continuous (or a non-parametric robustness "
            "check) was found:",
            md_table(parametric, cols, ["Statement", "Section"][:len(cols)]),
        ]
        summary_text = "Likert scale + parametric tests, no justification found."
    return module_output(table=parametric[cols], summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
